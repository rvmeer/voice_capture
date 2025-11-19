# Use Ubuntu base with Python
# Note: NVIDIA NGC PyTorch containers for ARM64 only have CPU support
# For GPU support on ARM64, PyTorch needs to be compiled from source (very slow)
# This Dockerfile uses CPU-only PyTorch which is stable and works everywhere
FROM ubuntu:22.04

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Create symlink for python
RUN ln -s /usr/bin/python3 /usr/bin/python

# Upgrade pip
RUN pip install --upgrade pip

# Install PyTorch (CPU version - stable and fast to install)
# For ARM64 CUDA support, see Dockerfile.source (requires compilation)
RUN pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# Copy Python requirements (Docker-specific)
COPY requirements-docker.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements-docker.txt

# Copy application files
COPY logging_config.py .
COPY recording_manager.py .
COPY transcription_utils.py .
COPY recordings.py .
COPY test_architecture.py .

# Make scripts executable
RUN chmod +x recordings.py test_architecture.py

# Create volume mount point for recordings
VOLUME ["/data/VoiceCapture"]

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV RECORDINGS_DIR=/data/VoiceCapture

# Default command - show help
CMD ["python", "recordings.py", "--help"]
