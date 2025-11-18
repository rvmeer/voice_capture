#!/usr/bin/env python3
"""
Test script to display system architecture and GPU information
"""

import platform
import sys
import torch
from logging_config import setup_logging, get_logger

# Setup logging
setup_logging()
logger = get_logger(__name__)


def test_architecture():
    """Test and display architecture information"""

    logger.info("=" * 80)
    logger.info("SYSTEM ARCHITECTURE TEST")
    logger.info("=" * 80)

    # Python information
    logger.info("")
    logger.info("Python Information:")
    logger.info(f"  Python version: {sys.version}")
    logger.info(f"  Python executable: {sys.executable}")

    # Platform information
    logger.info("")
    logger.info("Platform Information:")
    logger.info(f"  System: {platform.system()}")
    logger.info(f"  Release: {platform.release()}")
    logger.info(f"  Version: {platform.version()}")
    logger.info(f"  Machine: {platform.machine()}")
    logger.info(f"  Processor: {platform.processor()}")
    logger.info(f"  Architecture: {platform.architecture()}")

    # PyTorch information
    logger.info("")
    logger.info("PyTorch Information:")
    logger.info(f"  PyTorch version: {torch.__version__}")
    logger.info(f"  PyTorch file location: {torch.__file__}")

    # CUDA information
    logger.info("")
    logger.info("CUDA Information:")
    logger.info(f"  CUDA available: {torch.cuda.is_available()}")
    logger.info(f"  CUDA version (compiled): {torch.version.cuda}")

    if torch.cuda.is_available():
        logger.info(f"  CUDA device count: {torch.cuda.device_count()}")
        logger.info(f"  CUDA current device: {torch.cuda.current_device()}")

        for i in range(torch.cuda.device_count()):
            logger.info(f"  CUDA device {i}:")
            logger.info(f"    Name: {torch.cuda.get_device_name(i)}")
            logger.info(f"    Capability: {torch.cuda.get_device_capability(i)}")

            # Get memory info
            props = torch.cuda.get_device_properties(i)
            logger.info(f"    Total memory: {props.total_memory / 1024**3:.2f} GB")
            logger.info(f"    Multi-processor count: {props.multi_processor_count}")
    else:
        logger.info("  No CUDA devices found")
        logger.info("")
        logger.info("  Possible reasons:")
        logger.info("    - PyTorch installed without CUDA support (CPU-only version)")
        logger.info("    - NVIDIA drivers not installed")
        logger.info("    - CUDA toolkit not installed")
        logger.info("    - PyTorch CUDA version mismatch with system CUDA")

    # MPS (Metal Performance Shaders - Apple Silicon) information
    logger.info("")
    logger.info("MPS (Apple Silicon) Information:")
    logger.info(f"  MPS available: {torch.backends.mps.is_available()}")

    if hasattr(torch.backends.mps, 'is_built'):
        logger.info(f"  MPS built: {torch.backends.mps.is_built()}")

    # cuDNN information
    logger.info("")
    logger.info("cuDNN Information:")
    logger.info(f"  cuDNN available: {torch.backends.cudnn.is_available()}")
    logger.info(f"  cuDNN version: {torch.backends.cudnn.version() if torch.backends.cudnn.is_available() else 'N/A'}")
    logger.info(f"  cuDNN enabled: {torch.backends.cudnn.enabled}")

    # Device selection logic (same as in main.py and recordings.py)
    logger.info("")
    logger.info("Device Selection:")

    if torch.cuda.is_available():
        device = "cuda"
        logger.info(f"  Selected device: {device}")
        logger.info(f"  Reason: CUDA is available (highest priority)")

        # Check for compute capability issues
        if torch.cuda.device_count() > 0:
            capability = torch.cuda.get_device_capability(0)
            capability_str = f"sm_{capability[0]}{capability[1]}"
            logger.info(f"  Note: GPU compute capability is {capability_str}")

            # Warn if capability might not be fully supported
            if capability[0] >= 12:  # Blackwell and newer
                logger.warning(f"  Warning: GPU has very new architecture ({capability_str})")
                logger.warning(f"  Some PyTorch operations might fall back to CPU if not supported")
    elif torch.backends.mps.is_available():
        device = "mps"
        logger.info(f"  Selected device: {device}")
        logger.info(f"  Reason: MPS is available (CUDA not available)")
    else:
        device = "cpu"
        logger.info(f"  Selected device: {device}")
        logger.info(f"  Reason: No GPU acceleration available")

    # Test tensor creation on selected device
    logger.info("")
    logger.info("Device Test:")
    try:
        test_tensor = torch.randn(10, 10, device=device)
        logger.info(f"  Successfully created test tensor on {device}")
        logger.info(f"  Tensor device: {test_tensor.device}")
        logger.info(f"  Tensor shape: {test_tensor.shape}")
    except Exception as e:
        logger.error(f"  Failed to create tensor on {device}: {e}")

    logger.info("")
    logger.info("=" * 80)
    logger.info("TEST COMPLETE")
    logger.info("=" * 80)


if __name__ == "__main__":
    test_architecture()
