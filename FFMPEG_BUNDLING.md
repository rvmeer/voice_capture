# FFmpeg Bundling Guide

Complete guide for bundling FFmpeg with VoiceCapture on different platforms.

## Overview

VoiceCapture requires FFmpeg for audio processing. This document explains how FFmpeg is bundled on each platform.

---

## macOS

### Current Setup

FFmpeg is bundled automatically from Homebrew installation.

**Location**: `/opt/homebrew/bin/ffmpeg` (Apple Silicon) or `/usr/local/bin/ffmpeg` (Intel)

**Spec file**: `voice_capture.spec` (line 10)

```python
binaries=[
    ('/opt/homebrew/bin/ffmpeg', '.'),
],
```

### How it Works

1. PyInstaller copies ffmpeg from Homebrew installation
2. Bundled in `VoiceCapture.app/Contents/Frameworks/`
3. PATH is updated at runtime to include bundled ffmpeg

### Prerequisites

```bash
brew install ffmpeg
```

---

## Windows

### Current Setup (Automatic)

FFmpeg is **automatically downloaded and bundled** during the build process.

**Download Script**: `download_ffmpeg_windows.py`

**Spec file**: `voice_capture_windows.spec` (auto-detects)

### How it Works

1. Run `build_app.bat`
2. Script checks for `ffmpeg_windows/ffmpeg.exe`
3. If not found, runs `download_ffmpeg_windows.py`
4. Downloads from: https://www.gyan.dev/ffmpeg/builds/
5. Extracts `ffmpeg.exe` to `ffmpeg_windows/`
6. PyInstaller bundles it in the executable

### Manual Download

If automatic download fails:

```cmd
python download_ffmpeg_windows.py
```

Or download manually:
1. Visit: https://www.gyan.dev/ffmpeg/builds/
2. Download: `ffmpeg-release-essentials.zip`
3. Extract `ffmpeg.exe` to `ffmpeg_windows/`

### Verify FFmpeg is Bundled

After building:
```cmd
dir dist\VoiceCapture\ffmpeg.exe
```

Should show: `ffmpeg.exe` (~100 MB)

---

## Linux

### Current Setup

Not yet configured (contributions welcome!)

### Recommended Approach

**Option 1: System FFmpeg (Recommended)**
- Don't bundle FFmpeg
- Require users to install via package manager
- Most Linux users prefer this

**Option 2: Static Binary**
- Download static ffmpeg binary
- Bundle similar to Windows approach
- Increases app size significantly

---

## Testing FFmpeg Bundling

### macOS

```bash
# Build app
./build_app.sh

# Check if ffmpeg is bundled
ls -lh dist/VoiceCapture.app/Contents/Frameworks/ffmpeg

# Test the app
./dist/VoiceCapture.app/Contents/MacOS/VoiceCapture
```

### Windows

```cmd
# Build app
build_app.bat

# Check if ffmpeg is bundled
dir dist\VoiceCapture\ffmpeg.exe

# Test the app
dist\VoiceCapture\VoiceCapture.exe
```

---

## Troubleshooting

### macOS: FFmpeg Not Found During Build

**Error**: `FileNotFoundError: /opt/homebrew/bin/ffmpeg`

**Solution**:
```bash
# Install FFmpeg
brew install ffmpeg

# Or update spec file with correct path
which ffmpeg
```

### Windows: FFmpeg Download Fails

**Error**: `Download failed: [...]`

**Solutions**:

1. **Check internet connection**
2. **Manual download**:
   ```cmd
   python download_ffmpeg_windows.py
   ```
3. **Use existing FFmpeg**:
   Edit `voice_capture_windows.spec` line 24:
   ```python
   ffmpeg_binaries.append(('C:\\path\\to\\ffmpeg.exe', '.'))
   ```

### App Runs But Can't Find FFmpeg

**Symptoms**: Recording fails with "ffmpeg not found"

**Check**:
1. Is ffmpeg bundled?
   - macOS: Check `Contents/Frameworks/`
   - Windows: Check same folder as `.exe`
2. Check app logs for PATH issues

**macOS Fix**:
- Verify `main.py` line 1972-1975 adds Frameworks to PATH

**Windows Fix**:
- Verify `main.py` line 1976-1979 adds bundle dir to PATH

---

## Size Impact

| Platform | FFmpeg Size | Impact |
|----------|-------------|--------|
| macOS | ~60-80 MB | Moderate |
| Windows | ~90-110 MB | Moderate |
| Linux | Varies | Use system FFmpeg |

**Total app size with FFmpeg**:
- macOS: ~200-300 MB
- Windows: ~250-350 MB

---

## Distribution Strategies

### Strategy 1: Always Bundle (Current)

**Pros**:
- ✅ Works out of the box
- ✅ No user setup needed
- ✅ Consistent behavior

**Cons**:
- ❌ Larger download
- ❌ Duplicate if user has FFmpeg

**Best for**: End-user distribution, installers

### Strategy 2: Optional Bundle

**Pros**:
- ✅ Smaller download
- ✅ User can use system FFmpeg

**Cons**:
- ❌ More complex setup
- ❌ Support burden

**Best for**: Developer distribution, power users

### Strategy 3: System Only (Linux approach)

**Pros**:
- ✅ Smallest download
- ✅ Uses system packages
- ✅ Gets security updates

**Cons**:
- ❌ Requires user installation
- ❌ Version compatibility

**Best for**: Linux, developers, CLI tools

---

## Advanced: Custom FFmpeg Build

For smaller app size, build custom FFmpeg with only needed codecs:

```bash
# Example: Minimal FFmpeg for WAV only
./configure --disable-all --enable-decoder=pcm_s16le --enable-encoder=pcm_s16le
make
```

**Not recommended** unless you need minimal size and understand FFmpeg deeply.

---

## Development vs Production

### Development

Don't bundle FFmpeg:
- Use system FFmpeg
- Faster builds
- Easier debugging

### Production

Always bundle FFmpeg:
- Consistent experience
- No user setup
- Works everywhere

---

## Updating FFmpeg

### macOS

```bash
brew upgrade ffmpeg
# Rebuild app
./build_app.sh
```

### Windows

```bash
# Delete cached FFmpeg
rmdir /s /q ffmpeg_windows

# Download latest
python download_ffmpeg_windows.py

# Rebuild
build_app.bat
```

---

## Security Considerations

### Verify FFmpeg Downloads

**Windows**: Download from trusted source (gyan.dev)

**Check hash** (optional but recommended):
```cmd
certutil -hashfile ffmpeg_windows\ffmpeg.exe SHA256
```

Compare with official release hashes.

### Code Signing

After bundling FFmpeg, code-sign your app:

**macOS**:
```bash
codesign --deep --force --verify --verbose --sign "Developer ID" VoiceCapture.app
```

**Windows**:
```cmd
signtool sign /f cert.pfx /p password VoiceCapture.exe
```

---

## FAQ

**Q: Can users bring their own FFmpeg?**
A: Yes, if it's in PATH, but bundled version takes priority.

**Q: What version of FFmpeg is bundled?**
A: Latest stable at build time from Homebrew (macOS) or gyan.dev (Windows).

**Q: Can I use a different FFmpeg?**
A: Yes, edit the spec file to point to your preferred version.

**Q: Does bundling FFmpeg require license compliance?**
A: FFmpeg is LGPL/GPL. Bundling is allowed. Provide source/notice if GPL.

**Q: Can I bundle FFmpeg with different codecs?**
A: Yes, but be aware of codec licensing (especially H.264, AAC, MP3).

---

## Resources

- **FFmpeg Official**: https://ffmpeg.org/
- **FFmpeg Builds (Windows)**: https://www.gyan.dev/ffmpeg/builds/
- **FFmpeg Licensing**: https://ffmpeg.org/legal.html
- **PyInstaller Bundling**: https://pyinstaller.org/en/stable/usage.html#what-to-bundle-where-to-search

---

## Summary

✅ **macOS**: Auto-bundles from Homebrew
✅ **Windows**: Auto-downloads and bundles
⚠️ **Linux**: Not yet implemented

Both platforms provide a **seamless experience** for end users with no FFmpeg installation required!
