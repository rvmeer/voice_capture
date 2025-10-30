# -*- mode: python ; coding: utf-8 -*-
# Windows build specification for VoiceCapture

import sys
import os
from pathlib import Path

block_cipher = None

# Auto-detect FFmpeg location
ffmpeg_binaries = []

# Check for downloaded FFmpeg (from download_ffmpeg_windows.py)
ffmpeg_local = Path('ffmpeg_windows/ffmpeg.exe')
if ffmpeg_local.exists():
    print(f"✓ Found FFmpeg at: {ffmpeg_local} (will bundle)")
    ffmpeg_binaries.append((str(ffmpeg_local), '.'))
else:
    print("⚠ FFmpeg not found at ffmpeg_windows/ffmpeg.exe")
    print("  Run: python download_ffmpeg_windows.py")
    print("  Or users will need to install FFmpeg separately")

# You can also manually specify FFmpeg location:
# ffmpeg_binaries.append(('C:\\ffmpeg\\bin\\ffmpeg.exe', '.'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=ffmpeg_binaries,
    datas=[
        # Include custom modules
        ('audio_recorder.py', '.'),
        ('recording_manager.py', '.'),
        ('openapi_server.py', '.'),
        ('logging_config.py', '.'),
        ('mcp_server.py', '.'),
        # Include Whisper assets (mel_filters, tokenizers, etc.)
        # Note: Path will be different on Windows, adjust as needed
        # Example for virtual environment:
        # ('env\\Lib\\site-packages\\whisper\\assets', 'whisper\\assets'),
    ],
    hiddenimports=[
        'whisper',
        'openai',
        'torch',
        'numpy',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'pyaudio',
        'wave',
        'fastapi',
        'uvicorn',
        'pydantic',
        'requests',
        'transformers',
        'pyannote.audio',
        'mcp',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VoiceCapture',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',  # Windows icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VoiceCapture',
)
