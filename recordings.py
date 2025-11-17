#!/usr/bin/env python3
"""
CLI tool for managing voice recordings
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime
import torch
import whisper

from recording_manager import RecordingManager, iso_duration_to_seconds
from logging_config import setup_logging, get_logger

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

    logger.info(f"Recording: {recording.get('name', recording_id)}")
    logger.info(f"Current model: {current_model}")
    logger.info(f"New model: {model_name}")
    logger.info(f"Audio file: {audio_file}")
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
        result = model.transcribe(
            str(audio_file),
            language="nl",
            task="transcribe",
            fp16=False,  # Avoid NaN on MPS
            verbose=False
        )

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
  recordings.py list                        List all recordings (oldest first)
  recordings.py list --reverse              List all recordings (newest first)
  recordings.py show <id>                   Show details of a specific recording
  recordings.py retranscribe <id>           Retranscribe with medium model
  recordings.py retranscribe <id> --model large  Retranscribe with large model
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
