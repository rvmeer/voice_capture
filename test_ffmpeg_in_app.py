#!/usr/bin/env python3
"""
Test script to verify ffmpeg is accessible from within the bundled app
"""
import sys
import os
import subprocess
from pathlib import Path

print("Testing ffmpeg accessibility in bundled app")
print("=" * 60)

# Check if we're running in a bundled app
if getattr(sys, 'frozen', False):
    print("✓ Running as bundled app")
    bundle_dir = Path(sys._MEIPASS)
    print(f"  Bundle directory: {bundle_dir}")

    # Check Frameworks location
    frameworks_dir = bundle_dir.parent / 'Frameworks'
    print(f"  Frameworks directory: {frameworks_dir}")

    ffmpeg_path = frameworks_dir / 'ffmpeg'
    if ffmpeg_path.exists():
        print(f"✓ ffmpeg found at: {ffmpeg_path}")
        print(f"  File size: {ffmpeg_path.stat().st_size / 1024:.1f} KB")
        print(f"  Executable: {os.access(ffmpeg_path, os.X_OK)}")
    else:
        print(f"✗ ffmpeg NOT found at: {ffmpeg_path}")
else:
    print("✗ Not running as bundled app (running from source)")

print()
print("Current PATH:")
print("-" * 60)
for p in os.environ.get('PATH', '').split(':'):
    print(f"  {p}")

print()
print("Trying to execute ffmpeg:")
print("-" * 60)
try:
    result = subprocess.run(['ffmpeg', '-version'],
                          capture_output=True,
                          text=True,
                          timeout=5)
    if result.returncode == 0:
        print("✓ ffmpeg is accessible!")
        # Print first line only
        first_line = result.stdout.split('\n')[0]
        print(f"  {first_line}")
    else:
        print(f"✗ ffmpeg returned error code: {result.returncode}")
        print(f"  stderr: {result.stderr}")
except FileNotFoundError:
    print("✗ ffmpeg NOT found in PATH")
except Exception as e:
    print(f"✗ Error running ffmpeg: {e}")

print("=" * 60)
