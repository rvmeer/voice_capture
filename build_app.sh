#!/bin/bash
# Build script for VoiceCapture macOS app

set -e  # Exit on error

echo "=========================================="
echo "Building VoiceCapture macOS App"
echo "=========================================="
echo ""

# Check if PyInstaller is installed
if ! command -v pyinstaller &> /dev/null; then
    echo "❌ PyInstaller not found. Installing..."
    pip install pyinstaller
fi

# Check if ffmpeg is available
if ! command -v ffmpeg &> /dev/null; then
    echo "❌ ffmpeg not found. Please install it first:"
    echo "   brew install ffmpeg"
    exit 1
fi

echo "✅ ffmpeg found at: $(which ffmpeg)"
echo ""

# Clean previous builds
echo "🧹 Cleaning previous builds..."
rm -rf build/ dist/
echo ""

# Build the app
echo "🔨 Building app with PyInstaller..."
pyinstaller voice_capture.spec --clean --noconfirm
echo ""

# Check if build was successful
if [ -d "dist/VoiceCapture.app" ]; then
    echo "=========================================="
    echo "✅ Build successful!"
    echo "=========================================="
    echo ""
    echo "App location: dist/VoiceCapture.app"
    echo ""
    echo "To install:"
    echo "  1. Direct run:      open dist/VoiceCapture.app"
    echo "  2. Install to apps: cp -r dist/VoiceCapture.app /Applications/"
    echo ""
    echo "To test from command line:"
    echo "  ./dist/VoiceCapture.app/Contents/MacOS/VoiceCapture"
    echo ""
else
    echo "=========================================="
    echo "❌ Build failed!"
    echo "=========================================="
    exit 1
fi
