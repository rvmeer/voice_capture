"""
Voiceprint database for speaker identification.
Stores and matches speaker embedding vectors in voiceprints.json.
"""

from pathlib import Path
import json
import numpy as np
from logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_PATH = Path.home() / "Documents" / "VoiceCapture" / "voiceprints.json"


class VoiceprintStore:
    """Manages the voiceprint database (load/save/match)."""

    def __init__(self, path=None):
        self.path = Path(path) if path else DEFAULT_PATH
        self.speakers = []

    def load(self):
        if self.path.exists():
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.speakers = data.get("speakers", [])
                logger.debug(f"Loaded {len(self.speakers)} speakers from voiceprints.json")
            except Exception as e:
                logger.error(f"Error loading voiceprints: {e}", exc_info=True)
                self.speakers = []
        else:
            self.speakers = []

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "speakers": [
                    {
                        "name": s["name"],
                        "embeddings": [
                            e.tolist() if hasattr(e, 'tolist') else list(e)
                            for e in s["embeddings"]
                        ]
                    }
                    for s in self.speakers
                ]
            }
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved voiceprints.json ({len(self.speakers)} speakers)")
        except Exception as e:
            logger.error(f"Error saving voiceprints: {e}", exc_info=True)

    def all_names(self):
        return [s["name"] for s in self.speakers]

    def add_embedding(self, name, vector):
        """Add embedding vector to named speaker profile, creating it if needed."""
        if not name or not name.strip():
            logger.warning("add_embedding called with empty name, skipping")
            return
        name = name.strip()
        vec = vector.tolist() if hasattr(vector, 'tolist') else list(vector)
        for speaker in self.speakers:
            if speaker["name"] == name:
                speaker["embeddings"].append(vec)
                self.save()
                return
        self.speakers.append({"name": name, "embeddings": [vec]})
        self.save()
        logger.info(f"Added voiceprint for speaker '{name}'")

    def best_match(self, vector):
        """
        Find best matching speaker by cosine similarity (max over all stored embeddings).
        Returns (name, score) or (None, 0.0) if no speakers stored.
        """
        if not self.speakers:
            return None, 0.0

        v = np.array(vector, dtype=float)
        norm_v = np.linalg.norm(v)
        if norm_v == 0:
            return None, 0.0

        best_name = None
        best_score = -1.0

        for speaker in self.speakers:
            embeddings = speaker.get("embeddings", [])
            if not embeddings:
                continue
            scores = []
            for emb in embeddings:
                e = np.array(emb, dtype=float)
                norm_e = np.linalg.norm(e)
                if norm_e == 0:
                    continue
                scores.append(float(np.dot(v, e) / (norm_v * norm_e)))
            if scores:
                score = max(scores)
                if score > best_score:
                    best_score = score
                    best_name = speaker["name"]

        return best_name, best_score
