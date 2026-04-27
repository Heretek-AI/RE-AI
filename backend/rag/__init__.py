"""RAG / Vector store package.

Provides an abstract ``BaseVectorStore`` interface and a factory
function ``get_vector_store(config)`` that instantiates the configured
backend (default: Chroma).

Usage::

    store = get_vector_store({
        "vector_db_type": "chroma",
        "chroma_persist_dir": "./.chroma",
    })
    if store is None:
        # Vector store unavailable — graceful degradation
        ...
    doc_id = await store.store("findings", "some text", {"source": "agent"})
    results = await store.search("findings", "what do we know about X")
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_VECTOR_STORE_REGISTRY: dict[str, type] = {}

# Try to register Chroma — may fail if onnxruntime/DLL is missing
try:
    from backend.rag.chroma_store import ChromaStore  # noqa: F811

    _VECTOR_STORE_REGISTRY["chroma"] = ChromaStore
except ImportError as exc:
    logger.warning(
        "chromadb import failed (%s). Vector store will not be available.",
        exc,
    )

# FAISS and Qdrant stubs — gracefully indicate not-yet-implemented
class _FaissStub:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("FaissStore is not implemented yet. Use 'chroma' instead.")


class _QdrantStub:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("QdrantStore is not implemented yet. Use 'chroma' instead.")


_VECTOR_STORE_REGISTRY.setdefault("faiss", _FaissStub)
_VECTOR_STORE_REGISTRY.setdefault("qdrant", _QdrantStub)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_vector_store(config: dict[str, Any]) -> Optional[Any]:
    """Factory: instantiate a vector store from a config dict.

    Expects keys: ``vector_db_type`` and (for Chroma) ``chroma_persist_dir``.

    Returns ``None`` on any configuration error (unknown type, import
    failure) so the caller can degrade gracefully instead of crashing.
    """
    db_type = (config.get("vector_db_type") or "chroma").lower().strip()
    cls = _VECTOR_STORE_REGISTRY.get(db_type)

    if cls is None:
        valid = ", ".join(_VECTOR_STORE_REGISTRY)
        logger.error(
            "Unknown vector_db_type %r. Valid options: %s",
            db_type,
            valid,
        )
        return None

    if db_type == "chroma":
        # Chroma needs special construction with persist_directory
        persist_dir = config.get("chroma_persist_dir") or "./.chroma"
        try:
            import chromadb  # noqa: F401 — verify availability

            return cls(persist_dir)  # type: ignore[call-arg]
        except ImportError as exc:
            logger.error(
                "Failed to create ChromaStore (import error): %s",
                exc,
            )
            return None
        except Exception as exc:
            logger.error(
                "Failed to create ChromaStore: %s",
                exc,
            )
            return None

    # Stub backends or future full implementations
    try:
        instance = cls()
        return instance
    except NotImplementedError:
        logger.warning("Vector store %r requested but not implemented.", db_type)
        return None
    except Exception as exc:
        logger.error("Failed to create vector store %r: %s", db_type, exc)
        return None


# ---------------------------------------------------------------------------
# Convenience: module-level global
# ---------------------------------------------------------------------------

_vector_store: Optional[Any] = None


def set_rag_store(config: dict[str, Any]) -> None:
    """Initialize and store a global vector store instance.

    Sets ``_vector_store`` to ``None`` on failure, matching the
    graceful-degradation contract.
    """
    global _vector_store
    try:
        _vector_store = get_vector_store(config)
    except Exception as exc:
        logger.error("set_rag_store failed: %s", exc)
        _vector_store = None


def get_rag_store() -> Optional[Any]:
    """Return the global vector store instance (may be ``None``)."""
    return _vector_store
