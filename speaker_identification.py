"""
Speaker identification pipeline.
Uses pyannote/speaker-diarization-3.1 (DiarizeOutput) which already provides
speaker_embeddings (k-means centroids), so no separate embedding model is needed.
"""

import os
import types as _types
import wave
from pathlib import Path as _Path
from dataclasses import dataclass
from typing import Optional, Tuple
import numpy as np
from dotenv import load_dotenv

from logging_config import get_logger
from voiceprint_store import VoiceprintStore

load_dotenv(dotenv_path=_Path(__file__).parent / ".env", override=False)
logger = get_logger(__name__)

SIMILARITY_THRESHOLD = 0.80

_hint_pipeline = None


def _get_hint_pipeline():
    """Return a cached diarization pipeline (loads once, reused across segments)."""
    global _hint_pipeline
    if _hint_pipeline is None:
        from pyannote.audio import Pipeline
        token = _get_hf_token()
        device = _get_device()
        logger.info("Loading diarization pipeline for segment speaker hints…")
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", token=token
        )
        _hint_pipeline = pipeline.to(device)
        logger.info("Diarization pipeline ready for segment hints.")
    return _hint_pipeline


def get_segment_speaker_hint(audio_file, store, threshold=SIMILARITY_THRESHOLD):
    """
    Quick speaker hint for a single audio segment WAV.
    Runs the (cached) diarization pipeline on the file and matches each detected
    speaker embedding against known voiceprints.

    Returns (name, score) where name is None when no match meets the threshold.
    Raises ImportError if pyannote/torch not installed.
    """
    pipeline = _get_hint_pipeline()

    raw = pipeline(str(audio_file))
    if isinstance(raw, _types.GeneratorType):
        try:
            next(raw)
            raise RuntimeError("Pipeline generator did not stop as expected")
        except StopIteration as _e:
            diarize_output = _e.value
    else:
        diarize_output = raw

    annotation = diarize_output.speaker_diarization
    raw_embeddings = diarize_output.speaker_embeddings
    labels = annotation.labels()

    if not labels or raw_embeddings is None or len(raw_embeddings) == 0:
        return None, 0.0

    best_name, best_score = None, 0.0
    for i, label in enumerate(labels):
        if i >= len(raw_embeddings):
            continue
        name, score = store.best_match(raw_embeddings[i])
        if name and score > best_score:
            best_name, best_score = name, score

    if best_name and best_score >= threshold:
        return best_name, best_score
    return None, best_score


@dataclass
class SpeakerResult:
    label: str
    status: str                                  # "matched" or "unknown"
    name: Optional[str]                          # identified name, or None
    rep_fragment: Optional[Tuple[float, float]]  # (start, end) of longest segment
    embedding: Optional[np.ndarray]


def _get_device():
    import torch
    if torch.cuda.is_available():
        return torch.device("cuda")
    elif torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _get_hf_token():
    return os.getenv('HF_TOKEN', '').strip() or None


def _fmt_timestamp(seconds):
    from datetime import timedelta
    td = timedelta(seconds=seconds)
    h = int(td.total_seconds() // 3600)
    m = int((td.total_seconds() % 3600) // 60)
    s = int(td.total_seconds() % 60)
    ms = int((td.total_seconds() % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _get_audio_duration(audio_file):
    try:
        with wave.open(str(audio_file), 'r') as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return 0.0


def _run_diarization(audio_file, hf_token, device, rec_dir):
    """
    Run pyannote/speaker-diarization-3.1 and return:
      segments      : list of (start, end, speaker_label)
      embeddings    : dict of speaker_label -> np.ndarray (k-means centroid)
      rep_fragments : dict of speaker_label -> (start, end) of longest segment
    Also writes/updates diarization.txt as a side-effect.
    """
    from pyannote.audio import Pipeline

    logger.info(f"Loading speaker-diarization-3.1 on {device}… (file: {audio_file.name})")
    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", token=hf_token
        )
        pipeline = pipeline.to(device)
    except Exception as e:
        raise RuntimeError(
            f"Could not load pyannote/speaker-diarization-3.1: {e}\n"
            "Accept model agreement at https://huggingface.co/pyannote/speaker-diarization-3.1\n"
            "and ensure HF_TOKEN is set in .env."
        ) from e

    logger.info(f"Running diarization on {audio_file}…")
    raw = pipeline(str(audio_file))

    # pyannote 4.x: Pipeline.__call__ is a generator function (has `yield` for the
    # batch path), so even a single-file call returns a generator object.
    if isinstance(raw, _types.GeneratorType):
        try:
            next(raw)
            raise RuntimeError("Pipeline generator did not stop as expected for single file")
        except StopIteration as _e:
            diarize_output = _e.value
    else:
        diarize_output = raw

    # DiarizeOutput has:
    #   .speaker_diarization : Annotation  (itertracks yields (Segment, track, label))
    #   .speaker_embeddings  : np.ndarray (num_speakers, dim), sorted by .labels() order
    annotation = diarize_output.speaker_diarization
    raw_embeddings = diarize_output.speaker_embeddings  # may be None

    labels = annotation.labels()  # ordered list of speaker labels

    # Build embedding dict: speaker_label -> centroid vector
    emb_dict = {}
    if raw_embeddings is not None and len(raw_embeddings) == len(labels):
        for i, label in enumerate(labels):
            emb_dict[label] = raw_embeddings[i]

    # Build segment list + rep_fragment dict
    segments = []
    seg_by_speaker = {}
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        segments.append((turn.start, turn.end, speaker))
        seg_by_speaker.setdefault(speaker, []).append((turn.start, turn.end))

    rep_fragments = {
        spk: max(segs, key=lambda s: s[1] - s[0])
        for spk, segs in seg_by_speaker.items()
    }

    # Write diarization.txt (same format as diarization.py)
    output_lines = [f"{_fmt_timestamp(s)} {sp}" for s, _, sp in segments]
    (rec_dir / "diarization.txt").write_text('\n'.join(output_lines), encoding='utf-8')
    logger.info(f"Diarization done: {len(labels)} speaker(s), {len(segments)} segment(s)")

    return segments, emb_dict, rep_fragments


def identify_speakers(recording_id, recording_manager, voiceprint_store,
                      threshold=SIMILARITY_THRESHOLD):
    """
    Full pipeline for one recording: diarization → voiceprint matching.
    Returns list of SpeakerResult.
    Raises ImportError if pyannote.audio is not installed.
    """
    try:
        import torch  # noqa: F401
    except ImportError:
        raise ImportError("torch is required for speaker identification")

    try:
        import pyannote.audio  # noqa: F401
    except ImportError:
        raise ImportError(
            "pyannote.audio is niet geïnstalleerd.\n"
            "Installeer met: pip install pyannote.audio"
        )

    rec = recording_manager.get_recording(recording_id)
    if not rec:
        raise ValueError(f"Recording {recording_id} not found")

    rec_dir = recording_manager.recordings_dir / f"recording_{recording_id}"
    audio_file = rec_dir / f"recording_{recording_id}.wav"
    if not audio_file.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_file}")

    hf_token = _get_hf_token()
    if not hf_token:
        logger.warning("No HF_TOKEN found — pyannote models may fail to load")

    device = _get_device()

    recording_name = rec.get('name') or rec.get('title') or recording_id
    logger.info(f"Speaker identification: '{recording_name}' ({recording_id})")
    logger.info(f"  Audio: {audio_file}")

    # Always run the pipeline: DiarizeOutput contains speaker_embeddings (centroids)
    # which are needed for matching and are not stored in diarization.txt.
    segments, emb_dict, rep_fragments = _run_diarization(
        audio_file, hf_token, device, rec_dir
    )

    if not segments:
        logger.warning(f"No speaker segments for {recording_id}")
        return []

    # Collect unique speakers
    speakers = list(dict.fromkeys(sp for _, _, sp in segments))

    results = []
    for speaker in speakers:
        embedding = emb_dict.get(speaker)
        rep = rep_fragments.get(speaker)

        if embedding is None:
            results.append(SpeakerResult(
                label=speaker, status="unknown", name=None,
                rep_fragment=rep, embedding=None
            ))
            continue

        best_name, score = voiceprint_store.best_match(embedding)
        if best_name and score >= threshold:
            logger.info(f"{speaker} → '{best_name}' (score={score:.3f})")
            results.append(SpeakerResult(
                label=speaker, status="matched", name=best_name,
                rep_fragment=rep, embedding=embedding
            ))
        else:
            best_info = f"best={score:.3f}" if best_name else "no known speakers"
            logger.info(f"{speaker} unknown ({best_info})")
            results.append(SpeakerResult(
                label=speaker, status="unknown", name=None,
                rep_fragment=rep, embedding=embedding
            ))

    return results
