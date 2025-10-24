#!/bin/bash

# VoiceCapture Installatie Script voor macOS

set -e

echo "=========================================="
echo "VoiceCapture Installatie"
echo "=========================================="
echo ""

# Check of de app bestaat
if [ ! -d "dist/VoiceCapture.app" ]; then
    echo "❌ Fout: VoiceCapture.app niet gevonden in dist/"
    echo "   Bouw eerst de app met: pyinstaller voice_capture.spec --clean"
    exit 1
fi

echo "✅ VoiceCapture.app gevonden"
echo ""

# Vraag om bevestiging
echo "Deze script zal VoiceCapture.app installeren naar /Applications/"
read -p "Wil je doorgaan? (j/n): " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[JjYy]$ ]]; then
    echo "Installatie geannuleerd."
    exit 0
fi

# Verwijder oude versie indien aanwezig
if [ -d "/Applications/VoiceCapture.app" ]; then
    echo "🗑️  Oude versie verwijderen..."
    rm -rf "/Applications/VoiceCapture.app"
fi

# Kopieer nieuwe versie
echo "📦 VoiceCapture.app kopiëren naar /Applications/..."
cp -r "dist/VoiceCapture.app" "/Applications/"

echo ""
echo "=========================================="
echo "✅ Installatie succesvol!"
echo "=========================================="
echo ""
echo "Je kunt VoiceCapture nu starten via:"
echo "  • Spotlight: ⌘+Space en typ 'VoiceCapture'"
echo "  • Finder: Ga naar Applications en dubbelklik op VoiceCapture"
echo ""
echo "De app verschijnt als icoon in je menu bar."
echo ""
