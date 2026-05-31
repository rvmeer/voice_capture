#!/usr/bin/env python3
"""
Async transcription server for external audio uploads.

- POST /transcriptions (multipart file upload)
- GET  /transcriptions/{job_id} (status)
- GET  /transcriptions/{job_id}/transcript (result when done)

Auth:
- X-API-Key header, or
- Authorization: Bearer <api_key>
"""

from __future__ import annotations

import json
import threading
import uuid
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException, Depends
from pydantic import BaseModel, Field
import uvicorn

from logging_config import get_logger, setup_logging

logger = get_logger(__name__)

TRANSCRIBE_API_PORT = 5152
TRANSCRIBE_STORAGE_DIR = Path.home() / "Documents" / "VoiceCapture" / "transcribe_jobs"
TRANSCRIBE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# Hardcoded API keys (zoals gevraagd).
# Vervang/uitbreid deze lijst naar wens.
API_KEYS = {
    "vc_local_dev_key_2026",
    "vc_koen_key_2026",
}


class CreateTranscriptionResponse(BaseModel):
    success: bool = True
    transcription_job_id: str
    status: str
    status_url: str
    transcript_url: str


class JobStatusResponse(BaseModel):
    transcription_job_id: str
    status: str
    created_at: str
    updated_at: str
    model: str
    backend: Optional[str] = None
    filename: Optional[str] = None
    error: Optional[str] = None
    completed_at: Optional[str] = None


class TranscriptResponse(BaseModel):
    transcription_job_id: str
    status: str
    model: str
    backend: Optional[str] = None
    transcription: str


@dataclass
class JobRecord:
    transcription_job_id: str
    status: str
    created_at: str
    updated_at: str
    model: str
    backend: Optional[str] = None
    filename: Optional[str] = None
    file_path: Optional[str] = None
    transcription: Optional[str] = None
    transcription_file: Optional[str] = None
    error: Optional[str] = None
    completed_at: Optional[str] = None


class JobStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: Dict[str, JobRecord] = {}

    def create(self, job: JobRecord) -> None:
        with self._lock:
            self._jobs[job.transcription_job_id] = job

    def get(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **kwargs) -> Optional[JobRecord]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            for k, v in kwargs.items():
                setattr(job, k, v)
            job.updated_at = now_iso()
            return job

    def delete(self, job_id: str) -> bool:
        with self._lock:
            return self._jobs.pop(job_id, None) is not None


store = JobStore()

app = FastAPI(
    title="Voice Capture Transcribe API",
    version="1.0.0",
    description="Async upload+transcribe API met API-key auth",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_api_key(x_api_key: Optional[str], authorization: Optional[str]) -> Optional[str]:
    if x_api_key:
        return x_api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def require_api_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    key = _extract_api_key(x_api_key, authorization)
    if key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Unauthorized: invalid API key")
    return True


def _safe_filename(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in {".", "_", "-"} else "_" for c in name).strip("._")
    return cleaned or "audio_upload.bin"


def _detect_device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def _cleanup_job_files(file_path: Path) -> None:
    """Remove uploaded audio + job dir recursively."""
    try:
        job_dir = file_path.parent
        if job_dir.exists() and job_dir.is_dir():
            shutil.rmtree(job_dir, ignore_errors=False)
            logger.info(f"Cleaned up transcribe temp dir: {job_dir}")
    except Exception as cleanup_err:
        logger.warning(f"Failed to cleanup transcribe temp dir {file_path.parent}: {cleanup_err}")


def _run_transcription(job_id: str) -> None:
    job = store.get(job_id)
    if not job:
        return

    store.update(job_id, status="running")
    logger.info(f"Transcribe job started: {job_id} model={job.model} file={job.file_path}")

    file_path = Path(job.file_path or "")

    try:
        if not file_path.exists():
            raise FileNotFoundError(f"Audio file not found: {file_path}")

        text = ""
        backend = None

        # Default route: MLX Whisper
        try:
            import mlx_whisper

            result = mlx_whisper.transcribe(
                str(file_path),
                path_or_hf_repo=f"mlx-community/whisper-{job.model}-mlx",
                verbose=False,
            )
            text = (result.get("text") or "").strip()
            backend = f"mlx-whisper:{job.model}"
            logger.info(f"Transcribe job {job_id}: mlx-whisper success")
        except Exception as mlx_err:
            logger.warning(f"Transcribe job {job_id}: mlx-whisper failed ({mlx_err}), fallback to whisper")

        if not text:
            import whisper

            device = _detect_device()
            model = whisper.load_model(job.model, device=device)
            result = model.transcribe(str(file_path), task="transcribe", fp16=False, verbose=False)
            text = (result.get("text") or "").strip()
            backend = f"whisper:{job.model}@{device}"

        store.update(
            job_id,
            status="completed",
            backend=backend,
            transcription=text,
            transcription_file=None,
            file_path=None,
            completed_at=now_iso(),
            error=None,
        )
        logger.info(f"Transcribe job completed: {job_id} chars={len(text)}")

    except Exception as e:
        logger.error(f"Transcribe job failed: {job_id}: {e}", exc_info=True)
        store.update(job_id, status="failed", error=str(e), file_path=None)

    finally:
        if file_path:
            _cleanup_job_files(file_path)


@app.get("/health")
def health(_: bool = Depends(require_api_key)):
    return {"ok": True, "service": "transcribe_server", "port": TRANSCRIBE_API_PORT}


@app.post("/transcriptions", response_model=CreateTranscriptionResponse)
async def create_transcription_job(
    file: UploadFile = File(..., description="Audio file (wav/mp3/m4a/...)"),
    model: str = Form("large", description="Whisper model: tiny/small/medium/large of compatibele naam"),
    _: bool = Depends(require_api_key),
):
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    job_dir = TRANSCRIBE_STORAGE_DIR / f"job_{job_id}"
    job_dir.mkdir(parents=True, exist_ok=True)

    filename = _safe_filename(file.filename or "audio_upload.bin")
    file_path = job_dir / filename

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Leeg bestand")

    file_path.write_bytes(data)

    now = now_iso()
    job = JobRecord(
        transcription_job_id=job_id,
        status="queued",
        created_at=now,
        updated_at=now,
        model=model,
        filename=filename,
        file_path=str(file_path),
    )
    store.create(job)

    worker = threading.Thread(target=_run_transcription, args=(job_id,), daemon=True)
    worker.start()

    logger.info(f"Queued transcribe job: {job_id} model={model} filename={filename} size={len(data)}")

    return CreateTranscriptionResponse(
        transcription_job_id=job_id,
        status=job.status,
        status_url=f"/transcriptions/{job_id}",
        transcript_url=f"/transcriptions/{job_id}/transcript",
    )


@app.get("/transcriptions/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str, _: bool = Depends(require_api_key)):
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job niet gevonden")

    return JobStatusResponse(
        transcription_job_id=job.transcription_job_id,
        status=job.status,
        created_at=job.created_at,
        updated_at=job.updated_at,
        model=job.model,
        backend=job.backend,
        filename=job.filename,
        error=job.error,
        completed_at=job.completed_at,
    )


@app.get("/transcriptions/{job_id}/transcript", response_model=TranscriptResponse)
def get_transcript(job_id: str, _: bool = Depends(require_api_key)):
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job niet gevonden")

    if job.status != "completed":
        raise HTTPException(status_code=409, detail=f"Job nog niet klaar (status={job.status})")

    response = TranscriptResponse(
        transcription_job_id=job.transcription_job_id,
        status=job.status,
        model=job.model,
        backend=job.backend,
        transcription=job.transcription or "",
    )

    # One-shot behavior: na succesvolle transcript-opvraag direct job vergeten
    store.delete(job_id)
    logger.info(f"Transcript delivered and job purged: {job_id}")

    return response


_server_lock = threading.Lock()
_server_started = False


def start_transcribe_server_in_background(host: str = "127.0.0.1", port: int = TRANSCRIBE_API_PORT) -> None:
    """Start transcribe FastAPI server in daemon thread (for embedding in main.py)."""
    global _server_started
    with _server_lock:
        if _server_started:
            return
        _server_started = True

    def _run():
        try:
            config = uvicorn.Config(app, host=host, port=port, log_level="warning")
            server = uvicorn.Server(config)
            server.run()
        except Exception as e:
            logger.error(f"Transcribe server failed to start on {host}:{port}: {e}", exc_info=True)

    thread = threading.Thread(target=_run, daemon=True, name="transcribe-server")
    thread.start()
    logger.info(f"Transcribe server startup requested on {host}:{port}")


def main():
    setup_logging()
    logger.info(f"Starting standalone transcribe server on 127.0.0.1:{TRANSCRIBE_API_PORT}")
    uvicorn.run(app, host="127.0.0.1", port=TRANSCRIBE_API_PORT, log_level="info")


if __name__ == "__main__":
    main()
