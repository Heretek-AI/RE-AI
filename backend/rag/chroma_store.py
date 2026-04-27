"""ChromaDB-backed vector store implementation.

Uses ``chromadb.PersistentClient`` for on-disk persistence and
``chromadb.utils.embedding_functions.DefaultEmbeddingFunction()``
(ONNX-powered all-MiniLM-L6-v2) for embeddings.

All Chroma operations are synchronous — this module wraps every
call in ``asyncio.to_thread()`` to avoid blocking the FastAPI event
loop.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from backend.rag.base import BaseVectorStore

logger = logging.getLogger(__name__)


def _compute_scores(distances: list[float]) -> list[float]:
    """Convert Chroma L2 distances to relevance scores (0..1).

    Higher output means *more* relevant.

    Uses a simple sigmoid-like transform: ``1 / (1 + distance)``.
    This is monotonic and maps L2 distances in [0, +∞) to (0, 1].
    """
    return [1.0 / (1.0 + d) for d in distances]


# ---------------------------------------------------------------------------
# ChromaStore
# ---------------------------------------------------------------------------


class ChromaStore(BaseVectorStore):
    """Vector store backed by ChromaDB's ``PersistentClient``."""

    def __init__(self, persist_directory: str) -> None:
        # Delayed import so the factory can catch ImportError gracefully.
        import chromadb
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        self._client = chromadb.PersistentClient(path=persist_directory)
        self._ef = DefaultEmbeddingFunction()
        self._persist_directory = persist_directory
        logger.info(
            "Vector store initialized: chroma (persist_dir=%s)",
            persist_directory,
        )

    def _get_or_create_collection(self, name: str) -> Any:
        """Synchronously get or create a Chroma collection."""
        return self._client.get_or_create_collection(
            name=name,
            embedding_function=self._ef,
        )

    async def store(
        self,
        collection: str,
        text: str,
        metadata: dict[str, Any],
    ) -> str:
        doc_id = str(uuid.uuid4())

        def _do_store() -> None:
            coll = self._get_or_create_collection(collection)
            coll.add(
                ids=[doc_id],
                documents=[text],
                metadatas=[metadata],
            )

        await asyncio.to_thread(_do_store)
        return doc_id

    async def search(
        self,
        collection: str,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        def _do_search() -> list[dict[str, Any]]:
            try:
                coll = self._get_or_create_collection(collection)
            except Exception:
                # Collection doesn't exist yet — nothing to search
                return []

            result = coll.query(
                query_texts=[query],
                n_results=top_k,
            )
            if not result.get("documents") or not result["documents"][0]:
                return []

            docs = result["documents"][0]
            metas = result.get("metadatas", [None])[0] or [{}] * len(docs)
            distances = result.get("distances", [None])[0] or [0.0] * len(docs)
            scores = _compute_scores(distances)

            return [
                {
                    "text": docs[i],
                    "metadata": metas[i] if metas and i < len(metas) else {},
                    "score": scores[i] if i < len(scores) else 0.0,
                }
                for i in range(len(docs))
            ]

        return await asyncio.to_thread(_do_search)

    async def delete(
        self,
        collection: str,
        ids: list[str],
    ) -> None:
        def _do_delete() -> None:
            try:
                coll = self._get_or_create_collection(collection)
            except Exception:
                logger.warning(
                    "Attempted to delete from non-existent collection %r",
                    collection,
                )
                return
            coll.delete(ids=ids)

        await asyncio.to_thread(_do_delete)
