#!/usr/bin/env python3
"""
Speaker Diarization Tool
Uses pyannote.audio to perform speaker diarization on recordings
"""

import sys
import argparse
import os
from pathlib import Path
from datetime import timedelta
import torch
from dotenv import load_dotenv

from recording_manager import RecordingManager
from logging_config import setup_logging, get_logger

# Load environment variables from .env file
load_dotenv()

# Setup logging
setup_logging()
logger = get_logger(__name__)


def format_timestamp(seconds):
    """Format seconds to HH:MM:SS format"""
    td = timedelta(seconds=seconds)
    hours = int(td.total_seconds() // 3600)
    minutes = int((td.total_seconds() % 3600) // 60)
    secs = int(td.total_seconds() % 60)
    millis = int((td.total_seconds() % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def diarize_recording(args):
    """Perform speaker diarization on a recording"""
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

    logger.info(f"Recording: {recording.get('name', recording_id)}")
    logger.info(f"Audio file: {audio_file}")
    logger.info("")

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

    # Get HuggingFace token from args, environment variable, or .env file
    hf_token = args.hf_token if hasattr(args, 'hf_token') and args.hf_token else os.getenv('HF_TOKEN')

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
        logger.error("Then provide your HuggingFace token with --hf-token option,")
        logger.error("set the HF_TOKEN environment variable, or add it to your .env file.")
        sys.exit(1)

    logger.info(f"Performing speaker diarization...")

    try:
        # Perform diarization
        output = pipeline(str(audio_file))

        # Prepare output
        output_lines = []

        # Process each segment using the correct API
        for turn, speaker in output.speaker_diarization:
            timestamp = format_timestamp(turn.start)
            output_lines.append(f"{timestamp} {speaker}")

        if not output_lines:
            logger.warning("No speakers detected in audio.")
            output_lines.append("No speakers detected")

        # Save to diarization.txt
        output_file = rec_dir / "diarization.txt"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(output_lines))

        logger.info(f"")
        logger.info(f"Diarization complete!")
        logger.info(f"Found {len(set(line.split()[1] for line in output_lines if ' ' in line))} unique speakers")
        logger.info(f"Saved to: {output_file}")
        logger.info(f"")

        # Show preview of first few lines
        logger.info("Preview (first 10 lines):")
        for line in output_lines[:10]:
            logger.info(f"  {line}")

        if len(output_lines) > 10:
            logger.info(f"  ... and {len(output_lines) - 10} more lines")

    except Exception as e:
        logger.error(f"Error during diarization: {e}")
        logger.error(f"Error processing {recording_id}: {e}", exc_info=True)
        sys.exit(1)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Speaker diarization tool for voice recordings',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  diarization.py <recording_id>                      Perform speaker diarization
  diarization.py <recording_id> --hf-token TOKEN     Use HuggingFace token for authentication

Note: This tool requires pyannote.audio and a HuggingFace account.
You must accept the model license at:
  https://huggingface.co/pyannote/speaker-diarization-3.1
  https://huggingface.co/pyannote/segmentation-3.0

The HF_TOKEN will be automatically loaded from the .env file if present.
        """
    )

    parser.add_argument('id', help='Recording ID (e.g., 20251024_101413)')
    parser.add_argument(
        '--hf-token',
        help='HuggingFace authentication token (or set HF_TOKEN env var)',
        default=None
    )

    args = parser.parse_args()

    # Execute diarization
    diarize_recording(args)


if __name__ == "__main__":
    main()
