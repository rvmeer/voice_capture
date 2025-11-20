#!/bin/bash
#
# Run script for Voice Capture Docker container
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
IMAGE_NAME="voice-capture-cli"
IMAGE_TAG="latest"
RECORDINGS_DIR="$HOME/Documents/VoiceCapture"
CONTAINER_RECORDINGS_DIR="/data/VoiceCapture"

# Function to show usage
show_usage() {
    echo -e "${GREEN}Voice Capture Docker Runner${NC}"
    echo "================================================"
    echo ""
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  test                  Test architecture and CUDA availability"
    echo "  list [--reverse]      List all recordings"
    echo "  show <id>             Show recording details"
    echo "  retranscribe <id> -m <model>  Retranscribe with specified model"
    echo "  shell                 Start interactive shell"
    echo "  help                  Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 test"
    echo "  $0 list"
    echo "  $0 list --reverse"
    echo "  $0 show 20251117_195656"
    echo "  $0 retranscribe 20251117_195656 -m large"
    echo "  $0 shell"
    echo ""
    echo "Recordings directory: ${RECORDINGS_DIR}"
    echo ""
}

# Check if Docker is running
check_docker() {
    if ! docker info > /dev/null 2>&1; then
        echo -e "${RED}Error: Docker is not running${NC}"
        echo "Please start Docker and try again"
        exit 1
    fi
}

# Detect if GPU support is available
detect_gpu_support() {
    # Try to detect NVIDIA GPU support
    if command -v nvidia-smi &> /dev/null; then
        # nvidia-smi exists, check if it works
        if nvidia-smi &> /dev/null; then
            echo "gpu"
            return
        fi
    fi

    # No GPU support
    echo "nogpu"
}

# Check if image exists
check_image() {
    if ! docker image inspect "${IMAGE_NAME}:${IMAGE_TAG}" > /dev/null 2>&1; then
        echo -e "${RED}Error: Docker image '${IMAGE_NAME}:${IMAGE_TAG}' not found${NC}"
        echo ""
        echo "Please build the image first:"
        echo "  ./build_docker.sh"
        echo ""
        exit 1
    fi
}

# Check if recordings directory exists
check_recordings_dir() {
    if [ ! -d "$RECORDINGS_DIR" ]; then
        echo -e "${YELLOW}Warning: Recordings directory not found: ${RECORDINGS_DIR}${NC}"
        echo ""
        read -p "Create directory? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            mkdir -p "$RECORDINGS_DIR"
            echo -e "${GREEN}Created directory: ${RECORDINGS_DIR}${NC}"
        else
            echo -e "${RED}Aborted${NC}"
            exit 1
        fi
    fi
}

# Run docker with GPU support (if available)
run_docker() {
    local cmd="$@"
    local gpu_support=$(detect_gpu_support)

    if [ "$gpu_support" = "gpu" ]; then
        echo -e "${GREEN}GPU support detected - using CUDA${NC}"
        echo -e "${BLUE}Running: ${cmd}${NC}"
        echo ""

        docker run --rm --runtime=nvidia --gpus all \
            -v "${RECORDINGS_DIR}:${CONTAINER_RECORDINGS_DIR}" \
            "${IMAGE_NAME}:${IMAGE_TAG}" \
            ${cmd}
    else
        echo -e "${YELLOW}No GPU support detected - using CPU${NC}"
        echo -e "${YELLOW}Note: This will be slower. For GPU support, run on a system with NVIDIA GPU.${NC}"
        echo -e "${BLUE}Running: ${cmd}${NC}"
        echo ""

        docker run --rm \
            -v "${RECORDINGS_DIR}:${CONTAINER_RECORDINGS_DIR}" \
            "${IMAGE_NAME}:${IMAGE_TAG}" \
            ${cmd}
    fi
}

# Run docker in interactive mode
run_docker_interactive() {
    local gpu_support=$(detect_gpu_support)

    echo -e "${BLUE}Starting interactive shell...${NC}"
    echo -e "${YELLOW}Recordings directory mounted at: ${CONTAINER_RECORDINGS_DIR}${NC}"

    if [ "$gpu_support" = "gpu" ]; then
        echo -e "${GREEN}GPU support enabled${NC}"
        echo ""

        docker run --rm -it --gpus all \
            -v "${RECORDINGS_DIR}:${CONTAINER_RECORDINGS_DIR}" \
            "${IMAGE_NAME}:${IMAGE_TAG}" \
            /bin/bash
    else
        echo -e "${YELLOW}No GPU support - running on CPU${NC}"
        echo ""

        docker run --rm -it \
            -v "${RECORDINGS_DIR}:${CONTAINER_RECORDINGS_DIR}" \
            "${IMAGE_NAME}:${IMAGE_TAG}" \
            /bin/bash
    fi
}

# Main logic
main() {
    # Check prerequisites
    check_docker
    check_image
    check_recordings_dir

    # Parse command
    if [ $# -eq 0 ]; then
        show_usage
        exit 1
    fi

    COMMAND="$1"
    shift

    case "$COMMAND" in
        test)
            run_docker python test_architecture.py
            ;;
        list)
            run_docker python recordings.py list "$@"
            ;;
        show)
            if [ $# -eq 0 ]; then
                echo -e "${RED}Error: Recording ID required${NC}"
                echo "Usage: $0 show <recording_id>"
                exit 1
            fi
            run_docker python recordings.py show "$@"
            ;;
        retranscribe)
            if [ $# -eq 0 ]; then
                echo -e "${RED}Error: Recording ID required${NC}"
                echo "Usage: $0 retranscribe <recording_id> [-m model]"
                exit 1
            fi
            run_docker python recordings.py retranscribe "$@"
            ;;
        shell)
            run_docker_interactive
            ;;
        help|--help|-h)
            show_usage
            ;;
        *)
            echo -e "${RED}Error: Unknown command '${COMMAND}'${NC}"
            echo ""
            show_usage
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
