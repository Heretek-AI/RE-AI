"""Abstract base class for vector store backends.

Defines a common async interface for storing and searching document
embeddings, compatible with Chroma, FAISS, Qdrant, and future backends.

Documents must be pickle-serializable (a constraint imposed by Chroma's
metadata handling).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseVectorStore(ABC):
    """Abstract base class for vector database backends.

    Subclasses must implement ``store``, ``search``, and ``delete``.
    All methods are async — synchronous backends (e.g. Chroma) should
    use ``asyncio.to_thread()`` to avoid blocking the event loop.
    """

    @abstractmethod
    async def store(
        self,
        collection: str,
        text: str,
        metadata: dict[str, Any],
    ) -> str:
        """Store a document in the vector database.

        Parameters
        ----------
        collection:
            Logical collection / namespace name.
        text:
            Document text content.
        metadata:
            Arbitrary key-value metadata.

        Returns
        -------
        str
            The generated document ID.
        """
        ...  # pragma: no cover

    @abstractmethod
    async def search(
        self,
        collection: str,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Search for documents similar to the query.

        Parameters
        ----------
        collection:
            Collection to search within.
        query:
            Natural-language query string.
        top_k:
            Maximum number of results to return (default 5).

        Returns
        -------
        list[dict]
            Each dict has keys ``text``, ``metadata``, and ``score``.
        """
        ...  # pragma: no cover

    @abstractmethod
    async def delete(
        self,
        collection: str,
        ids: list[str],
    ) -> None:
        """Delete documents by their IDs.

        Parameters
        ----------
        collection:
            Collection containing the documents.
        ids:
            Document IDs to remove.
        """
        ...  # pragma: no cover
