# Voice Capture CLI - Docker Guide

Docker image voor het draaien van het `recordings.py` CLI script op NVIDIA GPU's met CUDA support.

## Base Image

- **Image**: `nvcr.io/nvidia/pytorch:24.10-py3`
- **Platform**: Linux ARM64 (NVIDIA DGX Spark compatible)
- **CUDA**: Version 12.x
- **PyTorch**: Pre-installed from NVIDIA NGC container

**Note**: The DGX Spark has an NVIDIA GB10 (Blackwell) GPU with compute capability sm_121. This is very new hardware that may not be fully supported by all PyTorch versions. Some operations might fall back to CPU if the GPU architecture is too new for the PyTorch build. NVIDIA's NGC containers have the best ARM64 + CUDA support available.

## Bouwen

```bash
./build_docker.sh
```

Dit bouwt de image met tag `voice-capture-cli:latest`.

## Gebruik

### 1. Test Architectuur (CUDA check)

Test of CUDA correct werkt:

```bash
docker run --rm --gpus all voice-capture-cli:latest python test_architecture.py
```

Dit toont:
- System architectuur (ARM64)
- CUDA availability en versie
- GPU informatie (naam, geheugen, etc.)
- Geselecteerd device (cuda/mps/cpu)

### 2. Recordings Lijst

```bash
docker run --rm --gpus all \
  -v ~/Documents/VoiceCapture:/data/VoiceCapture \
  voice-capture-cli:latest \
  python recordings.py list
```

### 3. Recording Details

```bash
docker run --rm --gpus all \
  -v ~/Documents/VoiceCapture:/data/VoiceCapture \
  voice-capture-cli:latest \
  python recordings.py show <recording_id>
```

### 4. Hertranscriberen

Met het large model op GPU:

```bash
docker run --rm --gpus all \
  -v ~/Documents/VoiceCapture:/data/VoiceCapture \
  voice-capture-cli:latest \
  python recordings.py retranscribe -m large <recording_id>
```

Models beschikbaar: `tiny`, `small`, `medium`, `large`

### 5. Interactive Shell

Voor debugging:

```bash
docker run --rm -it --gpus all \
  -v ~/Documents/VoiceCapture:/data/VoiceCapture \
  voice-capture-cli:latest \
  /bin/bash
```

Binnen de shell kun je commands uitvoeren:

```bash
python test_architecture.py
python recordings.py list
```

## Volume Mounts

De recordings directory moet gemount worden:

```bash
-v ~/Documents/VoiceCapture:/data/VoiceCapture
```

Dit maakt alle recordings beschikbaar in de container op `/data/VoiceCapture`.

## GPU Support

**Belangrijk**: Gebruik altijd `--gpus all` om GPU support te enablen!

Zonder `--gpus all` draait alles op CPU.

## NVIDIA Container Toolkit

Om Docker met GPU's te gebruiken op de DGX Spark, moet de NVIDIA Container Toolkit geïnstalleerd zijn:

```bash
# Check of nvidia-container-toolkit geïnstalleerd is
dpkg -l | grep nvidia-container-toolkit

# Test GPU toegang
docker run --rm --gpus all nvcr.io/nvidia/pytorch:25.10-py3 nvidia-smi
```

## Troubleshooting

### CUDA niet beschikbaar

Als `test_architecture.py` toont dat CUDA niet beschikbaar is:

1. Check of `--gpus all` flag gebruikt wordt
2. Controleer NVIDIA Container Toolkit installatie
3. Check NVIDIA drivers: `nvidia-smi`
4. Controleer Docker GPU support: `docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi`

### PyTorch versie mismatch

De NVIDIA base image bevat PyTorch met CUDA support. **Installeer GEEN andere PyTorch versie** in de container.

### Recordings niet gevonden

Zorg dat de volume mount correct is:
- Host path: `~/Documents/VoiceCapture`
- Container path: `/data/VoiceCapture`

Check of de directory bestaat op de host:

```bash
ls -la ~/Documents/VoiceCapture
```

## Image Info

Build info bekijken:

```bash
docker images voice-capture-cli
docker inspect voice-capture-cli:latest
```

Image verwijderen:

```bash
docker rmi voice-capture-cli:latest
```

## Performance

Op NVIDIA DGX Spark met CUDA:
- **large** model: ~10-15x sneller dan CPU
- **medium** model: ~8-12x sneller dan CPU
- **small** model: ~5-8x sneller dan CPU
- **tiny** model: ~3-5x sneller dan CPU

Test de performance met `test_architecture.py` en check welk device gebruikt wordt!
