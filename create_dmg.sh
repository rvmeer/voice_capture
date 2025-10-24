#!/bin/bash

# VoiceCapture DMG Creatie Script voor macOS

set -e

APP_NAME="VoiceCapture"
DMG_NAME="VoiceCapture-Installer"
VERSION="1.0.0"
SOURCE_DIR="dist/VoiceCapture.app"
OUTPUT_DMG="${DMG_NAME}-${VERSION}.dmg"

echo "=========================================="
echo "VoiceCapture DMG Creatie"
echo "=========================================="
echo ""

# Check of de app bestaat
if [ ! -d "$SOURCE_DIR" ]; then
    echo "❌ Fout: VoiceCapture.app niet gevonden in dist/"
    echo "   Bouw eerst de app met: pyinstaller voice_capture.spec --clean"
    exit 1
fi

echo "✅ $SOURCE_DIR gevonden"
echo ""

# Verwijder oude DMG indien aanwezig
if [ -f "$OUTPUT_DMG" ]; then
    echo "🗑️  Oude DMG verwijderen..."
    rm -f "$OUTPUT_DMG"
fi

# Maak tijdelijke directory voor DMG inhoud
echo "📦 Voorbereiden DMG inhoud..."
TMP_DMG_DIR="/tmp/${APP_NAME}_dmg"
rm -rf "$TMP_DMG_DIR"
mkdir -p "$TMP_DMG_DIR"

# Kopieer app naar tijdelijke directory
cp -r "$SOURCE_DIR" "$TMP_DMG_DIR/"

# Maak een symlink naar /Applications
ln -s /Applications "$TMP_DMG_DIR/Applications"

# Maak README bestand voor in de DMG
cat > "$TMP_DMG_DIR/README.txt" << EOF
VoiceCapture - Audio Transcriptie App
======================================

Installatie:
1. Sleep VoiceCapture.app naar de Applications folder
2. Open VoiceCapture vanuit je Applications folder
3. De app verschijnt als icoon in je menu bar

Gebruik:
- Klik op het menu bar icoon om een opname te starten/stoppen
- Rechts-klik (of Control+klik) voor meer opties
- Selecteer het gewenste Whisper model voor transcriptie

Eerste keer openen:
macOS kan vragen of je zeker weet dat je deze app wilt openen.
Dit is normaal voor apps die niet via de Mac App Store zijn
gedownload. Bevestig dat je de app wilt openen.

Microfoon toegang:
De app vraagt om toegang tot je microfoon. Dit is nodig om
audio op te kunnen nemen.

Voor meer informatie, zie BUILD_INSTRUCTIONS.md in de repository.

Versie: ${VERSION}
EOF

echo "🔨 DMG aanmaken..."
# Maak de DMG
hdiutil create -volname "$APP_NAME" \
    -srcfolder "$TMP_DMG_DIR" \
    -ov \
    -format UDZO \
    -imagekey zlib-level=9 \
    "$OUTPUT_DMG"

# Opruimen
rm -rf "$TMP_DMG_DIR"

# Toon info over de DMG
DMG_SIZE=$(du -h "$OUTPUT_DMG" | cut -f1)

echo ""
echo "=========================================="
echo "✅ DMG succesvol aangemaakt!"
echo "=========================================="
echo ""
echo "Bestand: $OUTPUT_DMG"
echo "Grootte: $DMG_SIZE"
echo ""
echo "Je kunt deze DMG nu distribueren."
echo "Gebruikers kunnen de app installeren door:"
echo "  1. De DMG te openen"
echo "  2. VoiceCapture.app naar Applications te slepen"
echo ""
echo "Test de DMG door deze te openen:"
echo "  open $OUTPUT_DMG"
echo ""
