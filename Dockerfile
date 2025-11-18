# Use NVIDIA CUDA base image for ARM64
FROM nvidia/cuda:12.4.0-base-ubuntu22.04

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

# Install PyTorch with CUDA support for ARM64
# Using pip install with CUDA 12.4 support
RUN pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

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
