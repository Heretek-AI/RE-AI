"""RAG search REST API endpoint.

``POST /api/rag/search`` — queries the vector database for semantically
similar past findings, tool results, and conversation context.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

from backend.rag.schemas import SearchRequest, SearchResult, SearchResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rag", tags=["rag"])


@router.post("/search", response_model=SearchResponse)
async def search_rag(request: Request, body: SearchRequest) -> SearchResponse:
    """Search the vector database for semantically similar documents.

    Accepts a natural-language query and returns relevant results from
    the specified collections (default: tool_results and conversation).
    Returns an empty results list with an error message when the vector
    store is unavailable.
    """
    # Lazy-fetch the vector store from app.state
    vector_store: Any | None = getattr(request.app.state, "vector_store", None)

    if vector_store is None:
        logger.warning("RAG search called but vector store is not available")
        return SearchResponse(results=[], error="Vector store not available")

    all_results: list[dict[str, Any]] = []
    seen_texts: set[str] = set()

    for collection in body.collections:
        try:
            results = await vector_store.search(collection, body.query, body.top_k)
        except Exception:
            logger.exception(
                "RAG search error on collection %r for query %r",
                collection,
                body.query,
            )
            continue

        for item in results:
            text = item.get("text", "")
            if text not in seen_texts:
                seen_texts.add(text)
                all_results.append(item)

    # Sort by score descending and limit to top_k
    all_results.sort(key=lambda r: r.get("score", 0.0), reverse=True)
    all_results = all_results[: body.top_k]

    response_results = [
        SearchResult(
            text=item.get("text", ""),
            metadata=item.get("metadata", {}),
            score=item.get("score", 0.0),
        )
        for item in all_results
    ]

    return SearchResponse(results=response_results)
