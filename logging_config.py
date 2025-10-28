"""
Centralized Logging Configuration
Sets up logging for the entire application with both console and file output
"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime


def setup_logging(name: str = "voice_capture", enable_console: bool = True) -> logging.Logger:
    """
    Setup logging for the application

    Args:
        name: Name of the logger (default: "voice_capture")
        enable_console: Enable console output (default: True). Set to False for MCP servers.

    Returns:
        Configured logger instance
    """
    # Create logger
    logger = logging.getLogger(name)

    # Only configure if not already configured
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Create logs directory next to recordings directory
    base_dir = Path.home() / "Documents" / "VoiceCapture"
    logs_dir = base_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Create formatters
    detailed_formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    console_formatter = logging.Formatter(
        fmt='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    # Console handler - INFO level and above (only if enabled)
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    # File handler - all messages (DEBUG and above)
    # Create a new log file for each day
    log_filename = logs_dir / f"voice_capture_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = RotatingFileHandler(
        log_filename,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)
    logger.addHandler(file_handler)

    # Prevent propagation to root logger
    logger.propagate = False

    # Only log initialization message if it won't interfere with stdio
    if enable_console:
        logger.info(f"Logging initialized - Log file: {log_filename}")
    else:
        # For MCP servers, write directly to file only
        file_handler.stream.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {name} - INFO - Logging initialized (console disabled for MCP) - Log file: {log_filename}\n")
        file_handler.stream.flush()

    return logger


def get_logger(module_name: str) -> logging.Logger:
    """
    Get a logger for a specific module

    Args:
        module_name: Name of the module requesting the logger

    Returns:
        Logger instance for the module
    """
    # Get or create the main logger
    main_logger = logging.getLogger("voice_capture")

    # If main logger not configured yet, set it up
    if not main_logger.handlers:
        setup_logging()

    # Return a child logger for the module
    return logging.getLogger(f"voice_capture.{module_name}")
