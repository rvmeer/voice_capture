#!/bin/bash
#
# Build script for Voice Capture Docker image
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
IMAGE_NAME="voice-capture-cli"
IMAGE_TAG="latest"
DOCKERFILE="Dockerfile"

echo -e "${GREEN}Building Voice Capture Docker Image${NC}"
echo "================================================"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running${NC}"
    echo "Please start Docker and try again"
    exit 1
fi

# Check if Dockerfile exists
if [ ! -f "$DOCKERFILE" ]; then
    echo -e "${RED}Error: $DOCKERFILE not found${NC}"
    exit 1
fi

# Check if requirements-docker.txt exists
if [ ! -f "requirements-docker.txt" ]; then
    echo -e "${RED}Error: requirements-docker.txt not found${NC}"
    exit 1
fi

# Build the Docker image
echo -e "${YELLOW}Building Docker image: ${IMAGE_NAME}:${IMAGE_TAG}${NC}"
echo ""

docker build \
    --platform linux/arm64 \
    -t "${IMAGE_NAME}:${IMAGE_TAG}" \
    -f "${DOCKERFILE}" \
    .

# Check build status
if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ Docker image built successfully${NC}"
    echo ""
    echo "Image: ${IMAGE_NAME}:${IMAGE_TAG}"
    echo ""
    echo "Usage examples:"
    echo "================================================"
    echo ""
    echo "1. Test architecture (check CUDA availability):"
    echo "   docker run --rm --gpus all ${IMAGE_NAME}:${IMAGE_TAG} python test_architecture.py"
    echo ""
    echo "2. List recordings:"
    echo "   docker run --rm --gpus all -v ~/Documents/VoiceCapture:/data/VoiceCapture ${IMAGE_NAME}:${IMAGE_TAG} python recordings.py list"
    echo ""
    echo "3. Show recording details:"
    echo "   docker run --rm --gpus all -v ~/Documents/VoiceCapture:/data/VoiceCapture ${IMAGE_NAME}:${IMAGE_TAG} python recordings.py show <recording_id>"
    echo ""
    echo "4. Retranscribe with large model:"
    echo "   docker run --rm --gpus all -v ~/Documents/VoiceCapture:/data/VoiceCapture ${IMAGE_NAME}:${IMAGE_TAG} python recordings.py retranscribe -m large <recording_id>"
    echo ""
    echo "5. Interactive shell:"
    echo "   docker run --rm -it --gpus all -v ~/Documents/VoiceCapture:/data/VoiceCapture ${IMAGE_NAME}:${IMAGE_TAG} /bin/bash"
    echo ""
    echo "Note: Use --gpus all to enable GPU support"
    echo ""
else
    echo -e "${RED}✗ Docker build failed${NC}"
    exit 1
fi
