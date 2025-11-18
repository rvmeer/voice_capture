# Use NVIDIA PyTorch NGC container for ARM64 with CUDA support
# This container has PyTorch pre-built for ARM64 with CUDA
FROM nvcr.io/nvidia/pytorch:24.10-py3

# Set working directory
WORKDIR /app

# Install additional system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Note: PyTorch is already installed in the base image with CUDA support
# We'll upgrade to a version that supports GB10 if needed
RUN pip install --upgrade pip

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
