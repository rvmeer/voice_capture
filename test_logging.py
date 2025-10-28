#!/usr/bin/env python3
"""
Test script for logging configuration
"""

from logging_config import setup_logging, get_logger
from pathlib import Path

# Setup logging
setup_logging()

# Get loggers for different modules
main_logger = get_logger("main")
audio_logger = get_logger("audio_recorder")
server_logger = get_logger("openapi_server")

# Test different log levels
print("\n" + "=" * 60)
print("Testing logging configuration...")
print("=" * 60 + "\n")

main_logger.debug("This is a DEBUG message from main - should appear in file only")
main_logger.info("This is an INFO message from main - should appear in console and file")
main_logger.warning("This is a WARNING message from main")
main_logger.error("This is an ERROR message from main")

audio_logger.info("Audio recorder initialized successfully")
audio_logger.debug("Detailed audio device information - file only")

server_logger.info("OpenAPI server starting on port 8000")

# Test with exception
try:
    result = 10 / 0
except ZeroDivisionError as e:
    main_logger.error("Caught an error during testing", exc_info=True)

print("\n" + "=" * 60)
print("Logging test complete!")
print("=" * 60)

# Show where logs are saved
logs_dir = Path.home() / "Documents" / "VoiceCapture" / "logs"
print(f"\nLog files are saved in: {logs_dir}")
print(f"Check the latest log file to see all DEBUG messages\n")
