# Use NVIDIA PyTorch base image with CUDA support
FROM nvcr.io/nvidia/pytorch:25.10-py3

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Copy Python requirements (Docker-specific)
COPY requirements-docker.txt .

# Install Python dependencies
# Note: PyTorch is already included in the base image with CUDA support
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
