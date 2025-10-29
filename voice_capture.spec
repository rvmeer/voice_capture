# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[
        # Include ffmpeg for audio processing
        ('/opt/homebrew/bin/ffmpeg', '.'),
    ],
    datas=[
        # Include custom modules
        ('audio_recorder.py', '.'),
        ('recording_manager.py', '.'),
        ('openapi_server.py', '.'),
        ('logging_config.py', '.'),
        ('mcp_server.py', '.'),
        # Include Whisper assets (mel_filters, tokenizers, etc.)
        ('env/lib/python3.13/site-packages/whisper/assets', 'whisper/assets'),
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
    console=False,  # No console window on macOS
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
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

app = BUNDLE(
    coll,
    name='VoiceCapture.app',
    icon='icon.icns',
    bundle_identifier='com.voicecapture.app',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': 'True',
        'LSUIElement': '0',  # Set to '1' for menu bar only app (no dock icon)
        'NSMicrophoneUsageDescription': 'VoiceCapture heeft toegang tot de microfoon nodig om audio op te nemen.',
        'CFBundleName': 'VoiceCapture',
        'CFBundleDisplayName': 'VoiceCapture',
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1.0.0',
        'NSRequiresAquaSystemAppearance': 'False',
    },
)
