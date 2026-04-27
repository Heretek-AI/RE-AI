"""Pydantic models for the RAG / vector-search API.

Used by the REST endpoint at ``POST /api/rag/search`` and internally
by the agent loop to format query results.
"""

from __future__ import annotations

from pydantic import BaseModel


class SearchRequest(BaseModel):
    """Request body for a vector search.

    By default searches both ``tool_results`` and ``conversation``
    collections.  Use ``collections`` to restrict to a subset or provide
    custom collection names.
    """

    query: str
    top_k: int = 5
    collections: list[str] = ["tool_results", "conversation"]


class SearchResult(BaseModel):
    """A single document returned from a vector search."""

    text: str
    metadata: dict = {}
    score: float


class SearchResponse(BaseModel):
    """Response envelope for a vector search."""

    results: list[SearchResult]
    error: str = ""
