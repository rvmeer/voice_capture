"""
Ollama integration utilities for generating recording titles.
"""

import json
import urllib.request
import urllib.error
from logging_config import get_logger

logger = get_logger(__name__)

OLLAMA_BASE_URL = "http://localhost:11434"


def check_ollama_available(timeout: int = 3) -> bool:
    """Return True if the local Ollama instance is reachable."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def get_ollama_models(timeout: int = 3) -> list:
    """Return a list of model name strings from the local Ollama instance."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            return [m["name"] for m in data.get("models", [])]
    except Exception as e:
        logger.debug(f"Could not fetch Ollama models: {e}")
        return []


def generate_title(transcription: str, model: str, timeout: int = 60) -> str:
    """Generate a short recording title by sending the transcription to Ollama."""
    prompt = (
        "Je krijgt een transcriptie van een gesproken opname. "
        "Geef een korte, beschrijvende titel voor deze opname in dezelfde taal als de transcriptie. "
        "De titel moet maximaal 8 woorden zijn en de kern van het gesprek samenvatten. "
        "Geef alleen de titel, zonder aanhalingstekens of extra uitleg.\n\n"
        f"Transcriptie:\n{transcription}\n\nTitel:"
    )
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
        title = data.get("response", "").strip().strip("\"'")
        return title
