# PyTorch CUDA Support on ARM64 (DGX Spark)

## Het Probleem

De NVIDIA DGX Spark heeft een ARM64 processor en NVIDIA GB10 GPU (Blackwell architectuur). PyTorch CUDA support op ARM64 is helaas **zeer beperkt**:

1. **NVIDIA NGC containers**: Bevatten alleen CPU-only PyTorch voor ARM64
2. **PyTorch wheels**: Geen officiële CUDA wheels voor ARM64 beschikbaar
3. **GB10 GPU**: Te nieuw (compute capability sm_121) voor de meeste PyTorch builds

## Beschikbare Oplossingen

### Optie 1: CPU-only Docker Container (AANBEVOLEN)

**Dockerfile** (standaard)
- Gebruikt CPU-only PyTorch
- Snel te bouwen (5-10 minuten)
- Stabiel en betrouwbaar
- **Nadeel**: Langzamer dan GPU (5-10x)

```bash
./build_docker.sh
./run_docker.sh retranscribe <id> -m large
```

**Performance**:
- **large** model: ~5-15 minuten per opname
- **medium** model: ~3-8 minuten per opname
- **small** model: ~1-3 minuten per opname

### Optie 2: Compile PyTorch from Source (GEAVANCEERD)

**Dockerfile.source**
- Compileert PyTorch met CUDA support
- **Zeer** lang bouwen (2-4 uur!)
- Mogelijk instabiel door GB10 incompatibiliteit
- **Voordeel**: GPU acceleration als het werkt

```bash
# Build (duurt 2-4 uur!)
docker build --platform linux/arm64 -t voice-capture-cli:cuda -f Dockerfile.source .

# Run
docker run --rm --gpus all \
  -v ~/Documents/VoiceCapture:/data/VoiceCapture \
  voice-capture-cli:cuda \
  python test_architecture.py
```

**Waarschuwing**: Zelfs na compilatie kan de GB10 GPU problemen geven door te nieuwe architectuur.

### Optie 3: Gebruik Native Installation (BESTE PERFORMANCE)

In plaats van Docker, installeer direct op de DGX Spark:

```bash
# Op de DGX Spark (niet in Docker)
# 1. Check CUDA versie
nvidia-smi

# 2. Installeer PyTorch met CUDA (probeer verschillende versies)
pip install torch torchvision torchaudio

# Of probeer een specifieke CUDA versie
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

# 3. Test
python test_architecture.py

# 4. Als CUDA werkt, run recordings.py direct
python recordings.py retranscribe -m large <recording_id>
```

**Voordelen**:
- Directe toegang tot CUDA
- Geen Docker overhead
- Beste kans op GPU support

**Nadelen**:
- Vereist admin rechten op DGX
- Dependencies moeten handmatig geïnstalleerd worden
- Minder geïsoleerd dan Docker

## Aanbeveling

Voor de DGX Spark met GB10 GPU:

1. **Eerste keuze**: Native installation (Optie 3)
   - Probeer verschillende PyTorch versies
   - Test met `python test_architecture.py`
   - Gebruik GPU als het werkt, anders CPU

2. **Tweede keuze**: CPU Docker (Optie 1)
   - Werkt altijd
   - Acceptabele performance voor occasioneel gebruik
   - Makkelijk te deployen

3. **Laatste keuze**: Source compilation (Optie 2)
   - Alleen als je veel tijd hebt
   - Geen garantie dat GB10 werkt

## Waarom is dit zo moeilijk?

1. **ARM64 + CUDA**: Weinig vraag, weinig support
2. **Blackwell (GB10)**: Te nieuw (late 2024/2025 release)
3. **PyTorch ARM64**: Focus ligt op x86_64
4. **NVIDIA NGC**: Ondersteunt ARM64 maar vaak CPU-only

## Toekomst

NVIDIA en PyTorch werken aan betere ARM64 + CUDA support. In 2025-2026 zal dit waarschijnlijk verbeteren. Voor nu is native installation de beste optie.

## Questions?

Run `test_architecture.py` om te zien welke devices beschikbaar zijn:
```bash
python test_architecture.py
```

Dit toont:
- CUDA availability
- GPU info
- Compute capability
- Welk device gebruikt zal worden
