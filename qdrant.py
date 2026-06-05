#!/usr/bin/env python3
"""
Qdrant indexing/search for Voice Capture transcripts.

Features:
- Build initial vector index from existing recordings
- Live segment indexing during active recordings
- Reindex a single recording after final transcript is available
- Semantic search with optional recording filter

CLI examples:
  python qdrant.py init
  python qdrant.py build
  python qdrant.py reindex --recording-id 20260605_101530
  python qdrant.py search --query "trein naar Parijs" --limit 5
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path
from typing import Any

from logging_config import get_logger

logger = get_logger(__name__)


class QdrantUnavailableError(RuntimeError):
    """Raised when qdrant/sentence-transformers dependencies are unavailable."""


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class QdrantIndexer:
    def __init__(
        self,
        *,
        recordings_dir: str | Path | None = None,
        collection_name: str | None = None,
        qdrant_url: str | None = None,
        qdrant_path: str | Path | None = None,
        embedding_model: str | None = None,
        chunk_words: int | None = None,
        overlap_words: int | None = None,
    ):
        self.recordings_dir = Path(recordings_dir or (Path.home() / "Documents" / "VoiceCapture"))
        self.collection_name = collection_name or os.getenv("QDRANT_COLLECTION", "voice_capture_segments")
        self.embedding_model_name = embedding_model or os.getenv(
            "QDRANT_EMBED_MODEL",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        )
        self.chunk_words = max(20, chunk_words or _safe_int(os.getenv("QDRANT_CHUNK_WORDS"), 140))
        self.overlap_words = max(0, overlap_words or _safe_int(os.getenv("QDRANT_OVERLAP_WORDS"), 30))

        self._client = None
        self._embedder = None
        self._vector_size = None

        self._qdrant_url = qdrant_url if qdrant_url is not None else os.getenv("QDRANT_URL")
        self._qdrant_path = Path(qdrant_path) if qdrant_path else Path(os.getenv("QDRANT_PATH", str(self.recordings_dir / "qdrant_data")))

    # ---------- lazy dependencies ----------

    def _require_qdrant(self):
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import (
                Distance,
                FieldCondition,
                Filter,
                MatchValue,
                PointStruct,
                VectorParams,
            )
        except Exception as e:
            raise QdrantUnavailableError(
                "Qdrant dependencies ontbreken. Installeer: pip install qdrant-client sentence-transformers"
            ) from e

        return QdrantClient, Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue

    def _require_embedder(self):
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as e:
            raise QdrantUnavailableError(
                "Embedding dependency ontbreekt. Installeer: pip install sentence-transformers"
            ) from e
        return SentenceTransformer

    def _client_instance(self):
        if self._client is not None:
            return self._client

        QdrantClient, *_ = self._require_qdrant()
        if self._qdrant_url:
            self._client = QdrantClient(url=self._qdrant_url)
            logger.info(f"Qdrant connected via URL: {self._qdrant_url}")
        else:
            self._qdrant_path.mkdir(parents=True, exist_ok=True)
            self._client = QdrantClient(path=str(self._qdrant_path))
            logger.info(f"Qdrant embedded path: {self._qdrant_path}")
        return self._client

    def _embedder_instance(self):
        if self._embedder is not None:
            return self._embedder

        SentenceTransformer = self._require_embedder()
        logger.info(f"Loading embedding model: {self.embedding_model_name}")
        self._embedder = SentenceTransformer(self.embedding_model_name)
        return self._embedder

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        embedder = self._embedder_instance()
        vectors = embedder.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        if hasattr(vectors, "tolist"):
            vectors = vectors.tolist()
        if self._vector_size is None and vectors:
            self._vector_size = len(vectors[0])
        return vectors

    def _point_id(self, key: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"voice-capture://{key}"))

    # ---------- data loading ----------

    def _recording_dirs(self) -> list[Path]:
        if not self.recordings_dir.exists():
            return []
        return sorted(
            [p for p in self.recordings_dir.iterdir() if p.is_dir() and p.name.startswith("recording_")],
            key=lambda p: p.name,
            reverse=True,
        )

    def _load_recording_json(self, recording_dir: Path) -> dict[str, Any] | None:
        rid = recording_dir.name.replace("recording_", "", 1)
        json_file = recording_dir / f"recording_{rid}.json"
        if not json_file.exists():
            return None
        try:
            return json.loads(json_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Could not parse {json_file}: {e}")
            return None

    def _load_final_transcription(self, recording_dir: Path, recording_id: str, recording_json: dict[str, Any] | None) -> str:
        txt_file = recording_dir / f"transcription_{recording_id}.txt"
        if txt_file.exists():
            try:
                return txt_file.read_text(encoding="utf-8").strip()
            except Exception as e:
                logger.warning(f"Could not read {txt_file}: {e}")

        if recording_json:
            return (recording_json.get("transcription") or "").strip()

        return ""

    def _chunk_text(self, text: str) -> list[dict[str, Any]]:
        words = text.split()
        if not words:
            return []

        chunks: list[dict[str, Any]] = []
        start = 0
        index = 0

        while start < len(words):
            end = min(len(words), start + self.chunk_words)
            chunk_words = words[start:end]
            if not chunk_words:
                break

            chunks.append(
                {
                    "chunk_index": index,
                    "word_start": start,
                    "word_end": end,
                    "text": " ".join(chunk_words).strip(),
                }
            )
            index += 1

            if end >= len(words):
                break

            step = self.chunk_words - self.overlap_words
            if step <= 0:
                step = self.chunk_words
            start += step

        return chunks

    # ---------- collection lifecycle ----------

    def init_collection(self, force_recreate: bool = False) -> dict[str, Any]:
        client = self._client_instance()
        _, Distance, VectorParams, *_ = self._require_qdrant()

        if self._vector_size is None:
            self._vector_size = len(self._embed_texts(["test vector init"])[0])

        exists = client.collection_exists(self.collection_name)
        if exists and force_recreate:
            client.delete_collection(self.collection_name)
            exists = False

        if not exists:
            client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=self._vector_size, distance=Distance.COSINE),
            )
            logger.info(f"Created collection: {self.collection_name}")
            created = True
        else:
            created = False
            logger.info(f"Collection already exists: {self.collection_name}")

        return {
            "collection": self.collection_name,
            "vector_size": self._vector_size,
            "created": created,
        }

    def delete_recording_points(self, recording_id: str) -> None:
        client = self._client_instance()
        *_, Filter, FieldCondition, MatchValue = self._require_qdrant()

        client.delete(
            collection_name=self.collection_name,
            points_selector=Filter(
                must=[FieldCondition(key="recording_id", match=MatchValue(value=recording_id))]
            ),
        )

    # ---------- indexing ----------

    def index_live_segment(
        self,
        *,
        recording_id: str,
        segment_num: int,
        text: str,
        recording_name: str | None = None,
        recording_date: str | None = None,
        prev_segment_text: str | None = None,
    ) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            return {"indexed": 0, "reason": "empty_text"}

        self.init_collection(force_recreate=False)

        client = self._client_instance()
        *_, PointStruct = self._require_qdrant()[:4]

        payload_common = {
            "recording_id": recording_id,
            "recording_name": recording_name,
            "date": recording_date,
            "source": "live",
        }

        points_payloads: list[tuple[str, dict[str, Any], str]] = [
            (
                self._point_id(f"live_raw:{recording_id}:{segment_num}"),
                {
                    **payload_common,
                    "kind": "raw_segment",
                    "segment_num": segment_num,
                    "text": text,
                },
                text,
            )
        ]

        if prev_segment_text and prev_segment_text.strip():
            window_text = f"{prev_segment_text.strip()} {text}".strip()
            points_payloads.append(
                (
                    self._point_id(f"live_window:{recording_id}:{segment_num - 1}:{segment_num}"),
                    {
                        **payload_common,
                        "kind": "window_segment",
                        "segment_num": segment_num,
                        "window_from_segment": segment_num - 1,
                        "window_to_segment": segment_num,
                        "text": window_text,
                    },
                    window_text,
                )
            )

        vectors = self._embed_texts([p[2] for p in points_payloads])
        points = [
            PointStruct(id=pid, vector=vec, payload=payload)
            for (pid, payload, _), vec in zip(points_payloads, vectors)
        ]
        client.upsert(collection_name=self.collection_name, points=points)

        return {"indexed": len(points)}

    def _index_recording_dir(self, recording_dir: Path) -> dict[str, Any]:
        recording_id = recording_dir.name.replace("recording_", "", 1)
        recording_json = self._load_recording_json(recording_dir)

        if recording_json is None:
            return {"recording_id": recording_id, "indexed": 0, "skipped": "missing_json"}

        full_text = self._load_final_transcription(recording_dir, recording_id, recording_json)
        if not full_text:
            return {"recording_id": recording_id, "indexed": 0, "skipped": "empty_transcription"}

        chunks = self._chunk_text(full_text)
        if not chunks:
            return {"recording_id": recording_id, "indexed": 0, "skipped": "no_chunks"}

        self.init_collection(force_recreate=False)
        client = self._client_instance()
        *_, PointStruct = self._require_qdrant()[:4]

        payload_base = {
            "recording_id": recording_id,
            "recording_name": recording_json.get("name"),
            "date": recording_json.get("date"),
            "duration": recording_json.get("duration"),
            "source": "final",
            "audio_file": recording_json.get("audio_file"),
        }

        texts = [chunk["text"] for chunk in chunks]
        vectors = self._embed_texts(texts)

        points = []
        for chunk, vector in zip(chunks, vectors):
            payload = {
                **payload_base,
                "kind": "final_chunk",
                "chunk_index": chunk["chunk_index"],
                "word_start": chunk["word_start"],
                "word_end": chunk["word_end"],
                "text": chunk["text"],
            }
            points.append(
                PointStruct(
                    id=self._point_id(f"final:{recording_id}:{chunk['chunk_index']}"),
                    vector=vector,
                    payload=payload,
                )
            )

        client.upsert(collection_name=self.collection_name, points=points)

        return {
            "recording_id": recording_id,
            "indexed": len(points),
            "chunks": len(chunks),
        }

    def index_recordings(self, recording_id: str | None = None) -> dict[str, Any]:
        self.init_collection(force_recreate=False)

        dirs = self._recording_dirs()
        if recording_id:
            target = self.recordings_dir / f"recording_{recording_id}"
            dirs = [target] if target.exists() else []

        results = []
        total_points = 0

        for recording_dir in dirs:
            if not recording_dir.exists():
                continue
            result = self._index_recording_dir(recording_dir)
            results.append(result)
            total_points += result.get("indexed", 0)

        return {
            "collection": self.collection_name,
            "recordings_scanned": len(dirs),
            "points_indexed": total_points,
            "results": results,
        }

    def reindex_recording(self, recording_id: str) -> dict[str, Any]:
        self.init_collection(force_recreate=False)
        self.delete_recording_points(recording_id)

        target_dir = self.recordings_dir / f"recording_{recording_id}"
        if not target_dir.exists():
            return {
                "recording_id": recording_id,
                "indexed": 0,
                "error": "recording_not_found",
            }

        result = self._index_recording_dir(target_dir)
        result["reindexed"] = True
        return result

    # ---------- search ----------

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        recording_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []

        self.init_collection(force_recreate=False)
        client = self._client_instance()
        *_, Filter, FieldCondition, MatchValue = self._require_qdrant()

        query_vector = self._embed_texts([query])[0]

        query_filter = None
        if recording_id:
            query_filter = Filter(
                must=[FieldCondition(key="recording_id", match=MatchValue(value=recording_id))]
            )

        response = client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=query_filter,
            limit=max(1, limit),
            with_payload=True,
        )

        hits = response.points if hasattr(response, "points") else []

        results: list[dict[str, Any]] = []
        for hit in hits:
            payload = hit.payload or {}
            results.append(
                {
                    "score": float(hit.score),
                    "recording_id": payload.get("recording_id"),
                    "recording_name": payload.get("recording_name"),
                    "date": payload.get("date"),
                    "kind": payload.get("kind"),
                    "segment_num": payload.get("segment_num"),
                    "chunk_index": payload.get("chunk_index"),
                    "text": payload.get("text", ""),
                }
            )

        return results


# ---------------- CLI ----------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Qdrant indexing/search for Voice Capture")
    parser.add_argument("--recordings-dir", default=None, help="Path naar VoiceCapture recordings map")
    parser.add_argument("--collection", default=None, help="Qdrant collection name")
    parser.add_argument("--qdrant-url", default=None, help="Qdrant URL (bijv. http://localhost:6333)")
    parser.add_argument("--qdrant-path", default=None, help="Embedded Qdrant path (default: ~/Documents/VoiceCapture/qdrant_data)")
    parser.add_argument("--embedding-model", default=None, help="SentenceTransformer model name")

    sub = parser.add_subparsers(dest="command", required=True)

    init_cmd = sub.add_parser("init", help="Initialiseer collectie")
    init_cmd.add_argument("--force-recreate", action="store_true", help="Drop en recreate collectie")

    build_cmd = sub.add_parser("build", help="Indexeer bestaande recordings")
    build_cmd.add_argument("--recording-id", default=None, help="Indexeer alleen deze recording")

    reindex_cmd = sub.add_parser("reindex", help="Reindex één recording")
    reindex_cmd.add_argument("--recording-id", required=True)

    search_cmd = sub.add_parser("search", help="Semantic search")
    search_cmd.add_argument("--query", required=True)
    search_cmd.add_argument("--limit", type=int, default=10)
    search_cmd.add_argument("--recording-id", default=None)

    return parser


def _create_indexer_from_args(args) -> QdrantIndexer:
    return QdrantIndexer(
        recordings_dir=args.recordings_dir,
        collection_name=args.collection,
        qdrant_url=args.qdrant_url,
        qdrant_path=args.qdrant_path,
        embedding_model=args.embedding_model,
    )


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        indexer = _create_indexer_from_args(args)

        if args.command == "init":
            result = indexer.init_collection(force_recreate=args.force_recreate)
        elif args.command == "build":
            result = indexer.index_recordings(recording_id=args.recording_id)
        elif args.command == "reindex":
            result = indexer.reindex_recording(args.recording_id)
        elif args.command == "search":
            result = indexer.search(
                args.query,
                limit=args.limit,
                recording_id=args.recording_id,
            )
        else:
            parser.error("Unknown command")
            return

        print(json.dumps(result, indent=2, ensure_ascii=False))

    except QdrantUnavailableError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        raise SystemExit(2)
    except Exception as e:
        logger.error(f"Qdrant CLI failed: {e}", exc_info=True)
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
