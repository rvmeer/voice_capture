#!/usr/bin/env python3
"""
CLI tool for managing voice recordings
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta
import os
import torch
import whisper
from dotenv import load_dotenv

from recording_manager import RecordingManager, iso_duration_to_seconds
from logging_config import setup_logging, get_logger

# Load environment variables
load_dotenv()

# Setup logging
setup_logging()
logger = get_logger(__name__)


def format_duration(duration_iso):
    """Format ISO duration to human readable format"""
    if not duration_iso:
        return "N/A"

    seconds = iso_duration_to_seconds(duration_iso)
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}m {secs}s"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours}h {minutes}m {secs}s"


def parse_timestamp(timestamp_str):
    """Parse timestamp string (HH:MM:SS.mmm) to seconds"""
    try:
        parts = timestamp_str.split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        secs_parts = parts[2].split('.')
        seconds = int(secs_parts[0])
        millis = int(secs_parts[1]) if len(secs_parts) > 1 else 0

        total_seconds = hours * 3600 + minutes * 60 + seconds + millis / 1000.0
        return total_seconds
    except Exception as e:
        logger.error(f"Error parsing timestamp '{timestamp_str}': {e}")
        return 0.0


def load_diarization(diarization_file):
    """Load diarization data from file

    Returns a list of tuples: [(start_time, end_time, speaker), ...]
    where times are in seconds
    """
    if not diarization_file.exists():
        return []

    segments = []
    with open(diarization_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

        for i, line in enumerate(lines):
            line = line.strip()
            if not line or line == "No speakers detected":
                continue

            parts = line.split()
            if len(parts) < 2:
                continue

            timestamp_str = parts[0]
            speaker = parts[1]

            start_time = parse_timestamp(timestamp_str)

            # End time is the start of the next segment, or infinity for the last segment
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and next_line != "No speakers detected":
                    next_parts = next_line.split()
                    if len(next_parts) >= 1:
                        end_time = parse_timestamp(next_parts[0])
                    else:
                        end_time = float('inf')
                else:
                    end_time = float('inf')
            else:
                end_time = float('inf')

            segments.append((start_time, end_time, speaker))

    return segments


def find_speaker_for_timestamp(timestamp, diarization_segments):
    """Find which speaker is talking at a given timestamp

    Args:
        timestamp: Time in seconds
        diarization_segments: List of (start_time, end_time, speaker) tuples

    Returns:
        Speaker name or None if no speaker found
    """
    for start, end, speaker in diarization_segments:
        if start <= timestamp < end:
            return speaker
    return None


def format_transcription_with_speakers(segments, diarization_segments):
    """Format transcription segments with speaker labels

    Args:
        segments: Whisper transcription segments with timestamps
        diarization_segments: List of (start_time, end_time, speaker) tuples

    Returns:
        Formatted transcription string with speaker labels
    """
    output_lines = []
    current_speaker = None
    current_text = []

    for segment in segments:
        # Get the start timestamp of this segment
        segment_start = segment.get('start', 0)
        segment_text = segment.get('text', '').strip()

        if not segment_text:
            continue

        # Find which speaker is talking
        speaker = find_speaker_for_timestamp(segment_start, diarization_segments)

        # If speaker changed, output the previous speaker's text and start new
        if speaker != current_speaker:
            if current_text:
                # Output previous speaker's text
                output_lines.append(' '.join(current_text))
                current_text = []

            # Start new speaker line
            if speaker:
                current_speaker = speaker
                output_lines.append(f"\n{speaker}:")
            else:
                current_speaker = None

        # Add this segment's text
        current_text.append(segment_text)

    # Output any remaining text
    if current_text:
        output_lines.append(' '.join(current_text))

    return '\n'.join(output_lines).strip()


def perform_diarization(audio_file, rec_dir, hf_token=None, num_speakers=None, min_speakers=None, max_speakers=None):
    """Perform speaker diarization on an audio file

    Args:
        audio_file: Path to the audio file
        rec_dir: Recording directory where diarization.txt will be saved
        hf_token: Optional HuggingFace token
        num_speakers: Exact number of speakers (if known)
        min_speakers: Minimum number of speakers
        max_speakers: Maximum number of speakers

    Returns:
        Path to diarization.txt file
    """
    # Import pyannote.audio
    try:
        from pyannote.audio import Pipeline
    except ImportError:
        logger.error("pyannote.audio is not installed. Please install it with:")
        logger.error("  pip install pyannote.audio")
        sys.exit(1)

    # Detect best available device
    if torch.cuda.is_available():
        device = torch.device("cuda")
    elif torch.backends.mps.is_available():
        device = torch.device("mps")
    else:
        device = torch.device("cpu")

    logger.info(f"Loading speaker-diarization-3.1 model on {device}...")

    # Get HuggingFace token from parameter or environment
    if not hf_token:
        hf_token = os.getenv('HF_TOKEN')

    if not hf_token:
        logger.warning("No HuggingFace token found. Trying without authentication...")

    try:
        # Load the pipeline
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            token=hf_token
        )

        # Send pipeline to device
        pipeline = pipeline.to(device)

    except Exception as e:
        logger.error(f"Error loading pipeline: {e}")
        logger.error("")
        logger.error("Note: This model requires authentication with Hugging Face.")
        logger.error("Please accept the user agreement at:")
        logger.error("  https://huggingface.co/pyannote/speaker-diarization-3.1")
        logger.error("  https://huggingface.co/pyannote/segmentation-3.0")
        logger.error("")
        logger.error("Then set the HF_TOKEN environment variable or add it to your .env file.")
        sys.exit(1)

    logger.info(f"Performing speaker diarization...")

    try:
        # Prepare diarization parameters
        diarization_params = {}
        if num_speakers is not None:
            diarization_params['num_speakers'] = num_speakers
            logger.info(f"  Using exact number of speakers: {num_speakers}")
        else:
            if min_speakers is not None:
                diarization_params['min_speakers'] = min_speakers
                logger.info(f"  Minimum speakers: {min_speakers}")
            if max_speakers is not None:
                diarization_params['max_speakers'] = max_speakers
                logger.info(f"  Maximum speakers: {max_speakers}")

        # Perform diarization
        output = pipeline(str(audio_file), **diarization_params)

        # Format output
        output_lines = []

        # Process each segment using the correct API
        for turn, speaker in output.speaker_diarization:
            # Format timestamp
            td = timedelta(seconds=turn.start)
            hours = int(td.total_seconds() // 3600)
            minutes = int((td.total_seconds() % 3600) // 60)
            secs = int(td.total_seconds() % 60)
            millis = int((td.total_seconds() % 1) * 1000)
            timestamp = f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"

            output_lines.append(f"{timestamp} {speaker}")

        if not output_lines:
            logger.warning("No speakers detected in audio.")
            output_lines.append("No speakers detected")

        # Save to diarization.txt
        output_file = rec_dir / "diarization.txt"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(output_lines))

        logger.info(f"Diarization complete!")
        logger.info(f"Found {len(set(line.split()[1] for line in output_lines if ' ' in line))} unique speakers")
        logger.info(f"Saved to: {output_file}")

        return output_file

    except Exception as e:
        logger.error(f"Error during diarization: {e}", exc_info=True)
        sys.exit(1)


def list_recordings(args):
    """List all recordings"""
    manager = RecordingManager()
    manager.load_recordings()

    recordings = manager.recordings

    if not recordings:
        logger.info("No recordings found.")
        return

    # Sort by date (oldest first by default, newest first if --reverse)
    recordings_sorted = sorted(
        recordings,
        key=lambda r: r.get('id', ''),
        reverse=args.reverse if hasattr(args, 'reverse') else False
    )

    # Print header
    logger.info(f"{'ID':<17} {'Name':<40} {'Duration':<12} {'Model':<10}")
    logger.info("-" * 85)

    # Print recordings
    for rec in recordings_sorted:
        rec_id = rec.get('id', 'N/A')
        name = rec.get('name', 'N/A')
        duration = format_duration(rec.get('duration', ''))
        model = rec.get('model', 'N/A')

        # Truncate name if too long
        if len(name) > 40:
            name = name[:37] + "..."

        logger.info(f"{rec_id:<17} {name:<40} {duration:<12} {model:<10}")

    logger.info(f"\nTotal: {len(recordings)} recording(s)")


def show_recording(args):
    """Show details of a specific recording"""
    manager = RecordingManager()
    manager.load_recordings()

    recording = manager.get_recording(args.id)

    if not recording:
        logger.error(f"Recording '{args.id}' not found.")
        sys.exit(1)

    # Print all details
    logger.info(f"Recording Details:")
    logger.info(f"  ID:               {recording.get('id', 'N/A')}")
    logger.info(f"  Name:             {recording.get('name', 'N/A')}")
    logger.info(f"  Date:             {recording.get('date', 'N/A')}")
    logger.info(f"  Duration:         {format_duration(recording.get('duration', ''))}")
    logger.info(f"  Model:            {recording.get('model', 'N/A')}")
    logger.info(f"  Segment Duration: {recording.get('segment_duration', 'N/A')}s")
    logger.info(f"  Overlap Duration: {recording.get('overlap_duration', 'N/A')}s")
    logger.info(f"  Audio File:       {recording.get('audio_file', 'N/A')}")

    # Show transcription (truncated)
    transcription = recording.get('transcription', '')
    if transcription:
        if len(transcription) > 200:
            logger.info(f"  Transcription:    {transcription[:200]}...")
        else:
            logger.info(f"  Transcription:    {transcription}")
    else:
        logger.info(f"  Transcription:    (empty)")


def retranscribe_recording(args):
    """Retranscribe a recording with a different model"""
    manager = RecordingManager()
    manager.load_recordings()

    # Get the recording
    recording = manager.get_recording(args.id)
    if not recording:
        logger.error(f"Recording '{args.id}' not found.")
        sys.exit(1)

    recording_id = recording.get('id')
    rec_dir = manager.recordings_dir / f"recording_{recording_id}"
    audio_file = rec_dir / f"recording_{recording_id}.wav"

    # Check if audio file exists
    if not audio_file.exists():
        logger.error(f"Audio file not found: {audio_file}")
        sys.exit(1)

    model_name = args.model
    current_model = recording.get('model', 'N/A')
    use_diarization = args.diarization if hasattr(args, 'diarization') else False
    num_speakers = args.num_speakers if hasattr(args, 'num_speakers') else None
    min_speakers = args.min_speakers if hasattr(args, 'min_speakers') else None
    max_speakers = args.max_speakers if hasattr(args, 'max_speakers') else None

    logger.info(f"Recording: {recording.get('name', recording_id)}")
    logger.info(f"Current model: {current_model}")
    logger.info(f"New model: {model_name}")
    logger.info(f"Audio file: {audio_file}")
    if use_diarization:
        logger.info(f"Diarization: enabled")
    logger.info("")

    # Perform diarization if requested
    diarization_segments = []
    if use_diarization:
        diarization_file = rec_dir / "diarization.txt"

        # Check if diarization already exists
        if diarization_file.exists():
            logger.info(f"Using existing diarization file: {diarization_file}")
        else:
            # Perform diarization
            hf_token = os.getenv('HF_TOKEN')
            perform_diarization(audio_file, rec_dir, hf_token, num_speakers, min_speakers, max_speakers)

        # Load diarization data
        diarization_segments = load_diarization(diarization_file)
        logger.info(f"Loaded {len(diarization_segments)} diarization segments")
        logger.info("")

    # Detect best available device
    if torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"

    logger.info(f"Loading {model_name} model on {device}...")
    try:
        model = whisper.load_model(model_name, device=device)
    except Exception as e:
        logger.error(f"Error loading model: {e}")
        sys.exit(1)

    logger.info(f"Transcribing with {model_name} model...")
    try:
        # Transcribe the full audio file
        # If using diarization, we need word-level timestamps
        # Note: word_timestamps with MPS can cause issues, so we force CPU for that case
        if use_diarization and device == "mps":
            logger.info("Word timestamps requested - temporarily using CPU for compatibility...")
            # Reload model on CPU for word timestamp support
            model_cpu = whisper.load_model(model_name, device="cpu")
            result = model_cpu.transcribe(
                str(audio_file),
                language="nl",
                task="transcribe",
                fp16=False,
                verbose=False,
                word_timestamps=True
            )
        else:
            result = model.transcribe(
                str(audio_file),
                language="nl",
                task="transcribe",
                fp16=False,  # Avoid NaN on MPS
                verbose=False,
                word_timestamps=use_diarization  # Enable word timestamps for diarization
            )

        # Format transcription based on diarization
        if use_diarization and diarization_segments:
            # Use segments from transcription result
            segments = result.get("segments", [])
            logger.info(f"Processing {len(segments)} transcription segments with speaker diarization...")
            transcription_text = format_transcription_with_speakers(segments, diarization_segments)
        else:
            # Use plain text
            transcription_text = result["text"].strip()

        if not transcription_text:
            logger.warning("Transcription is empty.")
        else:
            logger.info(f"Transcription complete: {len(transcription_text)} characters")

        # Save new transcription
        transcription_file = rec_dir / f"transcription_{recording_id}.txt"
        with open(transcription_file, 'w', encoding='utf-8') as f:
            f.write(transcription_text)

        logger.info(f"Saved transcription to: {transcription_file}")

        # Update recording metadata with new transcription and model
        manager.update_recording(
            recording_id,
            transcription=transcription_text,
            model=model_name
        )

        logger.info(f"Updated recording metadata with new model: {model_name}")
        logger.info("")
        logger.info("Retranscription complete!")

    except Exception as e:
        logger.error(f"Error during transcription: {e}")
        logger.error(f"Error retranscribing {recording_id}: {e}", exc_info=True)
        sys.exit(1)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='CLI tool for managing voice recordings',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  recordings.py list                                    List all recordings (oldest first)
  recordings.py list --reverse                          List all recordings (newest first)
  recordings.py show <id>                               Show details of a specific recording
  recordings.py retranscribe <id>                       Retranscribe with medium model
  recordings.py retranscribe <id> --model large         Retranscribe with large model
  recordings.py retranscribe <id> --diarization         Retranscribe with speaker diarization
  recordings.py retranscribe <id> -d -m large           Retranscribe with diarization and large model
  recordings.py retranscribe <id> -d --num-speakers 2   Retranscribe with exactly 2 speakers
  recordings.py retranscribe <id> -d --max-speakers 3   Retranscribe with max 3 speakers
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # List command
    list_parser = subparsers.add_parser('list', help='List all recordings')
    list_parser.add_argument(
        '--reverse', '-r',
        action='store_true',
        help='Show newest recordings first'
    )
    list_parser.set_defaults(func=list_recordings)

    # Show command
    show_parser = subparsers.add_parser('show', help='Show recording details')
    show_parser.add_argument('id', help='Recording ID')
    show_parser.set_defaults(func=show_recording)

    # Retranscribe command
    retranscribe_parser = subparsers.add_parser('retranscribe', help='Retranscribe a recording with a different model')
    retranscribe_parser.add_argument('id', help='Recording ID')
    retranscribe_parser.add_argument(
        '--model', '-m',
        default='medium',
        choices=['tiny', 'small', 'medium', 'large'],
        help='Whisper model to use (default: medium)'
    )
    retranscribe_parser.add_argument(
        '--diarization', '-d',
        action='store_true',
        help='Perform speaker diarization and include speaker labels in transcription'
    )
    retranscribe_parser.add_argument(
        '--num-speakers',
        type=int,
        help='Exact number of speakers (if known)'
    )
    retranscribe_parser.add_argument(
        '--min-speakers',
        type=int,
        help='Minimum number of speakers'
    )
    retranscribe_parser.add_argument(
        '--max-speakers',
        type=int,
        help='Maximum number of speakers'
    )
    retranscribe_parser.set_defaults(func=retranscribe_recording)

    # Parse arguments
    args = parser.parse_args()

    # Show help if no command specified
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Execute command
    args.func(args)


if __name__ == "__main__":
    main()
