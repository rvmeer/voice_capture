#!/usr/bin/env python3
"""
Download FFmpeg for Windows (to be used during build process)
This script downloads the latest FFmpeg essentials build from gyan.dev
"""
import urllib.request
import zipfile
import os
import shutil
from pathlib import Path

FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
DOWNLOAD_DIR = Path("ffmpeg_windows")
FFMPEG_EXE = DOWNLOAD_DIR / "ffmpeg.exe"

def download_ffmpeg():
    """Download and extract FFmpeg for Windows"""
    print("=" * 60)
    print("Downloading FFmpeg for Windows")
    print("=" * 60)

    # Create download directory
    DOWNLOAD_DIR.mkdir(exist_ok=True)

    # Check if already downloaded
    if FFMPEG_EXE.exists():
        print(f"✓ FFmpeg already exists at: {FFMPEG_EXE}")
        print(f"  Size: {FFMPEG_EXE.stat().st_size / 1024 / 1024:.1f} MB")
        return str(FFMPEG_EXE)

    # Download
    zip_file = DOWNLOAD_DIR / "ffmpeg.zip"
    print(f"\nDownloading from: {FFMPEG_URL}")
    print("This may take a few minutes (~100 MB)...")

    try:
        urllib.request.urlretrieve(FFMPEG_URL, zip_file)
        print(f"✓ Downloaded to: {zip_file}")
    except Exception as e:
        print(f"✗ Download failed: {e}")
        print("\nManual download instructions:")
        print("1. Visit: https://www.gyan.dev/ffmpeg/builds/")
        print("2. Download: ffmpeg-release-essentials.zip")
        print("3. Extract ffmpeg.exe to: ffmpeg_windows/")
        return None

    # Extract
    print("\nExtracting FFmpeg...")
    try:
        with zipfile.ZipFile(zip_file, 'r') as zip_ref:
            # Find ffmpeg.exe in the zip (it's usually in ffmpeg-xxx/bin/ffmpeg.exe)
            for file_info in zip_ref.filelist:
                if file_info.filename.endswith('bin/ffmpeg.exe'):
                    print(f"  Found: {file_info.filename}")
                    # Extract just ffmpeg.exe
                    with zip_ref.open(file_info) as source:
                        with open(FFMPEG_EXE, 'wb') as target:
                            target.write(source.read())
                    break

        if FFMPEG_EXE.exists():
            print(f"✓ Extracted to: {FFMPEG_EXE}")
            print(f"  Size: {FFMPEG_EXE.stat().st_size / 1024 / 1024:.1f} MB")

            # Clean up zip file
            zip_file.unlink()
            print("✓ Cleaned up zip file")

            return str(FFMPEG_EXE)
        else:
            print("✗ Failed to extract ffmpeg.exe")
            return None

    except Exception as e:
        print(f"✗ Extraction failed: {e}")
        return None

if __name__ == "__main__":
    result = download_ffmpeg()
    if result:
        print("\n" + "=" * 60)
        print("SUCCESS!")
        print("=" * 60)
        print(f"FFmpeg ready at: {result}")
        print("\nYou can now run: build_app.bat")
        print("\nThe spec file will automatically bundle this ffmpeg.exe")
    else:
        print("\n" + "=" * 60)
        print("FAILED")
        print("=" * 60)
        print("Please download FFmpeg manually and place in ffmpeg_windows/")
        exit(1)
