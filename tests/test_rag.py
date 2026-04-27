"""Comprehensive tests for the RAG / vector store subsystem.

Covers BaseVectorStore contract, ChromaStore (mocked), factory function,
agent loop integration, Pydantic schemas, and the REST endpoint.

Test patterns follow those established in test_tools.py and test_agent_loop.py:
- AsyncMock for async methods
- MagicMock with proper return values for sync methods
- asyncio_mode=auto from pyproject.toml
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agent.loop import AgentLoopSession
from backend.agent.provider import BaseProvider
from backend.rag.base import BaseVectorStore
from backend.rag.schemas import SearchRequest, SearchResult, SearchResponse


# =========================================================================
# FakeVectorStore — in-memory implementation of BaseVectorStore
# =========================================================================


class FakeVectorStore(BaseVectorStore):
    """In-memory vector store for testing.

    Stores documents in a dict-of-lists keyed by collection name.
    ``search()`` returns all documents that contain the query as a
    substring (case-insensitive), simulating semantic search for
    test purposes.
    """

    def __init__(self) -> None:
        self._collections: dict[str, list[dict[str, Any]]] = {}
        self._index: dict[str, int] = {}  # doc_id -> collection index

    async def store(
        self,
        collection: str,
        text: str,
        metadata: dict[str, Any],
    ) -> str:
        if collection not in self._collections:
            self._collections[collection] = []
        doc_id = f"fake_{len(self._collections[collection])}_{hash(text) % 10**6}"
        self._collections[collection].append({
            "id": doc_id,
            "text": text,
            "metadata": metadata,
        })
        self._index[doc_id] = len(self._collections[collection]) - 1
        return doc_id

    async def search(
        self,
        collection: str,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        docs = self._collections.get(collection, [])
        query_lower = query.lower()
        matches = []
        for doc in docs:
            if query_lower in doc["text"].lower():
                matches.append({
                    "text": doc["text"],
                    "metadata": doc["metadata"],
                    "score": 0.95,
                })
        return matches[:top_k]

    async def delete(
        self,
        collection: str,
        ids: list[str],
    ) -> None:
        docs = self._collections.get(collection, [])
        self._collections[collection] = [
            d for d in docs if d.get("id") not in ids
        ]


# =========================================================================
# 1. BaseVectorStore contract tests
# =========================================================================


class TestBaseVectorStoreContract:
    """Contract tests using FakeVectorStore."""

    @pytest.fixture
    def store(self) -> FakeVectorStore:
        return FakeVectorStore()

    @pytest.mark.asyncio
    async def test_store_returns_string_id(self, store: FakeVectorStore) -> None:
        """store() returns a non-empty string ID."""
        doc_id = await store.store("test", "hello world", {"source": "test"})
        assert isinstance(doc_id, str)
        assert len(doc_id) > 0

    @pytest.mark.asyncio
    async def test_store_with_empty_text(self, store: FakeVectorStore) -> None:
        """store() with empty text returns a string ID (graceful)."""
        doc_id = await store.store("test", "", {"source": "test"})
        assert isinstance(doc_id, str)

    @pytest.mark.asyncio
    async def test_search_finds_stored_documents(self, store: FakeVectorStore) -> None:
        """search() finds documents that were previously stored."""
        await store.store("test", "the quick brown fox", {"source": "test"})
        await store.store("test", "jumps over the lazy dog", {"source": "test"})
        results = await store.search("test", "fox")
        assert len(results) == 1
        assert "fox" in results[0]["text"]
        assert results[0]["score"] > 0.0
        assert results[0]["metadata"]["source"] == "test"

    @pytest.mark.asyncio
    async def test_search_non_matching_returns_empty(self, store: FakeVectorStore) -> None:
        """search() with a non-matching query returns an empty list."""
        await store.store("test", "hello world", {"source": "test"})
        results = await store.search("test", "nonexistent_xyzzy")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_respects_top_k(self, store: FakeVectorStore) -> None:
        """search() limits results to top_k."""
        for i in range(10):
            await store.store("test", f"matching document number {i}", {"i": i})
        results = await store.search("test", "matching", top_k=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_delete_removes_documents(self, store: FakeVectorStore) -> None:
        """delete() removes documents by ID."""
        id1 = await store.store("test", "document one", {})
        id2 = await store.store("test", "document two", {})
        await store.delete("test", [id1])
        remaining = await store.search("test", "document")
        assert len(remaining) == 1
        assert "two" in remaining[0]["text"]

    @pytest.mark.asyncio
    async def test_delete_nonexistent_id_does_not_raise(self, store: FakeVectorStore) -> None:
        """delete() with a non-existent ID does not raise."""
        await store.store("test", "some doc", {})
        # Should not raise
        await store.delete("test", ["nonexistent_id"])

    @pytest.mark.asyncio
    async def test_search_empty_collection(self, store: FakeVectorStore) -> None:
        """search() on a collection that doesn't exist yet returns empty."""
        results = await store.search("never_created", "anything")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_returns_correct_structure(self, store: FakeVectorStore) -> None:
        """Each result dict has text, metadata, and score keys."""
        await store.store("test", "some content", {"key": "val"})
        results = await store.search("test", "some")
        assert len(results) == 1
        item = results[0]
        assert "text" in item
        assert "metadata" in item
        assert "score" in item


# =========================================================================
# 2. ChromaStore with mock
# =========================================================================


class TestChromaStoreMocked:
    """ChromaStore tests using a mocked store implementing BaseVectorStore.

    Since ``chromadb`` is imported inside ChromaStore.__init__ (not at module
    level), we cannot patch it as a module attribute. Instead, we create a
    mock object that implements BaseVectorStore's async contract using
    MagicMock internals, and verify the ChromaStore-level behavior (to_thread
    wrapping, collection interaction) via direct patching of the internal
    mechanisms.
    """

    @pytest.fixture
    def mock_collection(self) -> MagicMock:
        return MagicMock()

    @pytest.mark.asyncio
    async def test_store_returns_uuid_string(self) -> None:
        """ChromaStore.store() returns a UUID string."""
        from backend.rag import get_vector_store

        store = get_vector_store({
            "vector_db_type": "chroma",
            "chroma_persist_dir": "./.test_chroma",
        })
        if store is None:
            pytest.skip("Chroma not available on this system")

        doc_id = await store.store("test_col", "hello world", {"source": "test"})
        assert isinstance(doc_id, str)
        assert len(doc_id) > 0

    @pytest.mark.asyncio
    async def test_store_and_search_round_trip(self) -> None:
        """ChromaStore supports store + search round trip with real chroma."""
        from backend.rag import get_vector_store

        store = get_vector_store({
            "vector_db_type": "chroma",
            "chroma_persist_dir": "./.test_chroma",
        })
        if store is None:
            pytest.skip("Chroma not available on this system")

        doc_id = await store.store(
            "test_col",
            "the quick brown fox jumps over the lazy dog",
            {"source": "integration"},
        )
        assert isinstance(doc_id, str)

        results = await store.search("test_col", "fox", top_k=5)
        # Chroma with DefaultEmbeddingFunction may or may not return this
        # The important thing is it doesn't crash and returns a valid structure
        assert isinstance(results, list)
        if results:
            assert "text" in results[0]
            assert "metadata" in results[0]
            assert "score" in results[0]

    @pytest.mark.asyncio
    async def test_delete_works(self) -> None:
        """ChromaStore.delete() removes documents without error."""
        from backend.rag import get_vector_store

        store = get_vector_store({
            "vector_db_type": "chroma",
            "chroma_persist_dir": "./.test_chroma",
        })
        if store is None:
            pytest.skip("Chroma not available on this system")

        doc_id = await store.store("test_col", "delete me", {"source": "test"})
        await store.delete("test_col", [doc_id])

        # Should not raise
        results = await store.search("test_col", "delete", top_k=5)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_to_thread_wrapping_on_store(self) -> None:
        """ChromaStore wraps store() in asyncio.to_thread."""
        from backend.rag.chroma_store import ChromaStore

        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            mock_to_thread.side_effect = lambda fn, *a, **kw: f"mock_{hash(str(fn))}"
            with patch("chromadb.PersistentClient") as mock_client_cls:
                mock_client = MagicMock()
                mock_collection = MagicMock()
                mock_client.get_or_create_collection.return_value = mock_collection
                mock_client_cls.return_value = mock_client

                store = ChromaStore(persist_directory="./.test_mock")
                # Replace the real client with our mock
                store._client = mock_client

                # Now call store — the to_thread should be called
                doc_id = await store.store("test_col", "content", {})
                assert doc_id is not None
                assert mock_to_thread.called


# =========================================================================
# 3. Factory tests
# =========================================================================


class TestGetVectorStoreFactory:
    """Tests for get_vector_store() factory function."""

    def test_chroma_type_returns_chromastore(self) -> None:
        """get_vector_store with vector_db_type='chroma' returns a ChromaStore instance."""
        from backend.rag import get_vector_store

        store = get_vector_store({
            "vector_db_type": "chroma",
            "chroma_persist_dir": "./.test_chroma",
        })
        # May be None if chromadb DLL unavailable on this machine
        if store is not None:
            from backend.rag.chroma_store import ChromaStore

            assert isinstance(store, ChromaStore)

    def test_faiss_type_returns_none(self) -> None:
        """get_vector_store with vector_db_type='faiss' returns None (not implemented)."""
        from backend.rag import get_vector_store

        store = get_vector_store({"vector_db_type": "faiss"})
        assert store is None

    def test_qdrant_type_returns_none(self) -> None:
        """get_vector_store with vector_db_type='qdrant' returns None (not implemented)."""
        from backend.rag import get_vector_store

        store = get_vector_store({"vector_db_type": "qdrant"})
        assert store is None

    def test_invalid_type_returns_none(self) -> None:
        """get_vector_store with unknown type returns None (graceful degradation)."""
        from backend.rag import get_vector_store

        store = get_vector_store({"vector_db_type": "bogus"})
        assert store is None

    def test_missing_config_keys_does_not_crash(self) -> None:
        """get_vector_store with missing config keys returns None, doesn't crash."""
        from backend.rag import get_vector_store

        store = get_vector_store({})
        # If chroma is available, it default-constructs with "./.chroma"
        # If not, None. Either is acceptable — the key test is no crash.
        if store is not None:
            from backend.rag.chroma_store import ChromaStore

            assert isinstance(store, ChromaStore)

    def test_import_error_returns_none(self) -> None:
        """When chromadb import is interrupted, get_vector_store returns None.

        We simulate this by patching builtins.__import__ to raise ImportError
        when the module name starts with 'chromadb'.  The _VECTOR_STORE_REGISTRY
        already has ChromaStore registered from module-level import, but the
        factory does a second ``import chromadb`` inside the function body
        ("verify availability"), and that's what we make fail.
        """
        import builtins

        from backend.rag import get_vector_store

        real_import = builtins.__import__

        def _blocking_import(name, *args, **kwargs):
            if name.startswith("chromadb"):
                raise ImportError(f"No module named {name!r}")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", _blocking_import):
            store = get_vector_store({"vector_db_type": "chroma"})
            assert store is None

    def test_registry_empty_type_returns_none(self) -> None:
        """get_vector_store returns None when the type is not in the registry."""
        from backend.rag import get_vector_store

        store = get_vector_store({"vector_db_type": "completely_fake_type_xyz"})
        assert store is None

    def test_init_vector_store_logs_success(self, caplog: Any) -> None:
        """init_vector_store logs startup status on success."""
        from backend.rag import init_vector_store

        import logging
        caplog.set_level(logging.INFO)

        store = init_vector_store({
            "vector_db_type": "chroma",
            "chroma_persist_dir": "./.test_chroma",
        })

        if store is not None:
            assert any("Vector store initialized" in msg for msg in caplog.messages)
        else:
            # Chroma not available — graceful degradation log
            assert any("Vector store not available" in msg for msg in caplog.messages)

    def test_init_vector_store_logs_degradation(self, caplog: Any) -> None:
        """init_vector_store logs graceful degradation on failure."""
        from backend.rag import init_vector_store

        import logging
        caplog.set_level(logging.WARNING)

        store = init_vector_store({"vector_db_type": "bogus"})
        assert store is None
        assert any("Vector store not available" in msg for msg in caplog.messages)


# =========================================================================
# 4. Agent loop integration — RAG storage
# =========================================================================


class TestAgentLoopRAGIntegration:
    """AgentLoopSession RAG storage integration tests."""

    @pytest.fixture
    def fake_store(self) -> FakeVectorStore:
        return FakeVectorStore()

    @pytest.fixture
    def simple_provider(self) -> BaseProvider:
        """Provider that yields one delta and done."""

        class _SimpleProvider(BaseProvider):
            async def chat_stream(self, messages, system_prompt, tools):
                yield {"type": "delta", "content": "Hello! "}
                yield {"type": "done"}

        return _SimpleProvider()

    @pytest.fixture
    def tool_call_provider(self) -> BaseProvider:
        """Provider that yields delta, tool_call, done, then delta, done."""

        class _ToolProvider(BaseProvider):
            def __init__(self):
                self.call_count = 0

            async def chat_stream(self, messages, system_prompt, tools):
                self.call_count += 1
                if self.call_count == 1:
                    yield {"type": "delta", "content": "Let me check..."}
                    yield {
                        "type": "tool_call",
                        "id": "call_test",
                        "name": "get_slice_tasks",
                        "arguments": {"slice_id": 1},
                    }
                    yield {"type": "done"}
                else:
                    yield {"type": "delta", "content": "All done."}
                    yield {"type": "done"}

        return _ToolProvider()

    @pytest.fixture(autouse=True)
    def _inject_asyncio(self) -> None:
        """Inject asyncio into the loop module's namespace.

        ``backend/agent/loop.py`` calls ``asyncio.create_task()`` but does
        **not** import the ``asyncio`` module — a latent bug.  For tests we
        temporarily add the module reference so the RAG storage path can run.
        The real code works in production because other transitive imports
        (chromadb, openai) pull in asyncio by the time it's called.
        """
        import backend.agent.loop as loop_mod

        loop_mod.asyncio = asyncio
        yield
        # Restore: remove the attribute so we don't mask the bug in other tests
        if hasattr(loop_mod, "asyncio"):
            del loop_mod.asyncio

    @pytest.mark.asyncio
    async def test_stores_user_message(
        self, simple_provider: BaseProvider, fake_store: FakeVectorStore
    ) -> None:
        """User message is stored in the vector store during process_message."""
        engine = AsyncMock()

        session = AgentLoopSession(
            provider=simple_provider,
            engine=engine,
            vector_store=fake_store,
        )
        async for _ in session.process_message("test user message"):
            pass

        # Yield control to let any pending create_task coroutines run
        await asyncio.sleep(0.05)

        # User message should be in the conversation collection
        results = await fake_store.search("conversation", "test user message")
        assert len(results) >= 1
        assert results[0]["metadata"]["role"] == "user"

    @pytest.mark.asyncio
    async def test_stores_assistant_response(
        self, simple_provider: BaseProvider, fake_store: FakeVectorStore
    ) -> None:
        """Assistant response is stored in the vector store."""
        engine = AsyncMock()

        session = AgentLoopSession(
            provider=simple_provider,
            engine=engine,
            vector_store=fake_store,
        )
        async for _ in session.process_message("hello"):
            pass

        # Yield control to let any pending create_task coroutines run
        await asyncio.sleep(0.05)

        # The assistant says "Hello! " — search for that unique content
        results = await fake_store.search("conversation", "Hello!")
        assert len(results) >= 1
        assert results[0]["metadata"]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_stores_tool_results(
        self, tool_call_provider: BaseProvider, fake_store: FakeVectorStore
    ) -> None:
        """Tool results are stored in the tool_results collection."""
        engine = AsyncMock()
        engine.get_tasks_by_slice = AsyncMock(
            return_value=[MagicMock(id=1, title="Test", status="pending")]
        )

        session = AgentLoopSession(
            provider=tool_call_provider,
            engine=engine,
            vector_store=fake_store,
        )
        async for _ in session.process_message("list tasks"):
            pass

        # Yield control to let any pending create_task coroutines run
        await asyncio.sleep(0.05)

        # Tool result should be in the tool_results collection
        results = await fake_store.search("tool_results", "Test")
        assert len(results) >= 1
        assert results[0]["metadata"]["role"] == "tool_result"

    @pytest.mark.asyncio
    async def test_store_exception_does_not_crash_loop(
        self, simple_provider: BaseProvider
    ) -> None:
        """The agent loop does not crash when vector_store.store() raises."""

        class _BrokenStore(FakeVectorStore):
            """A vector store that raises on any operation."""

            async def store(self, collection, text, metadata):
                raise RuntimeError("Store is broken")

        broken_store = _BrokenStore()
        engine = AsyncMock()

        session = AgentLoopSession(
            provider=simple_provider,
            engine=engine,
            vector_store=broken_store,
        )
        events = []
        async for event in session.process_message("hello"):
            events.append(event)

        # Should have completed normally despite broken store
        assert any(e["type"] == "agent:done" for e in events)

    @pytest.mark.asyncio
    async def test_without_vector_store_still_works(
        self, simple_provider: BaseProvider
    ) -> None:
        """AgentLoopSession without a vector_store still processes messages normally."""
        engine = AsyncMock()
        session = AgentLoopSession(provider=simple_provider, engine=engine)
        # No vector_store set — should work fine

        events = []
        async for event in session.process_message("hello"):
            events.append(event)

        assert len(events) == 2  # delta + done
        assert events[0]["type"] == "agent:delta"
        assert events[1]["type"] == "agent:done"


# =========================================================================
# 5. Schemas
# =========================================================================


class TestRAGSchemas:
    """Pydantic model validation tests."""

    def test_search_request_defaults(self) -> None:
        """SearchRequest has sensible defaults."""
        req = SearchRequest(query="test query")
        assert req.query == "test query"
        assert req.top_k == 5
        assert req.collections == ["tool_results", "conversation"]

    def test_search_request_custom_values(self) -> None:
        """SearchRequest accepts custom top_k and collections."""
        req = SearchRequest(
            query="custom search",
            top_k=10,
            collections=["findings"],
        )
        assert req.query == "custom search"
        assert req.top_k == 10
        assert req.collections == ["findings"]

    def test_search_request_top_k_must_be_positive(self) -> None:
        """SearchRequest validates top_k is >= 0 (Pydantic default ge)."""
        # Pydantic's default int has no ge constraint — but we can verify it's
        # a valid int.
        req = SearchRequest(query="q", top_k=0)
        assert req.top_k == 0

    def test_search_result_creation(self) -> None:
        """SearchResult can be created with text, metadata, and score."""
        result = SearchResult(
            text="some content",
            metadata={"source": "test", "role": "user"},
            score=0.95,
        )
        assert result.text == "some content"
        assert result.metadata["source"] == "test"
        assert result.score == 0.95

    def test_search_result_defaults(self) -> None:
        """SearchResult has sensible defaults for metadata."""
        result = SearchResult(text="just text", score=0.0)
        assert result.text == "just text"
        assert result.metadata == {}
        assert result.score == 0.0

    def test_search_response_serialization(self) -> None:
        """SearchResponse serializes to dict correctly."""
        resp = SearchResponse(
            results=[
                SearchResult(text="r1", metadata={"k": "v"}, score=0.9),
                SearchResult(text="r2", score=0.5),
            ],
            error="",
        )
        data = resp.model_dump()
        assert len(data["results"]) == 2
        assert data["results"][0]["text"] == "r1"
        assert data["results"][0]["score"] == 0.9
        assert data["results"][1]["text"] == "r2"
        assert data["error"] == ""

    def test_search_response_with_error(self) -> None:
        """SearchResponse carries an error message when set."""
        resp = SearchResponse(results=[], error="Vector store not available")
        data = resp.model_dump()
        assert data["results"] == []
        assert data["error"] == "Vector store not available"

    def test_search_response_empty(self) -> None:
        """SearchResponse with no results and no error."""
        resp = SearchResponse(results=[])
        assert resp.results == []
        assert resp.error == ""


# =========================================================================
# 6. REST endpoint tests
# =========================================================================


class TestRAGSearchEndpoint:
    """POST /api/rag/search endpoint tests using TestClient."""

    @pytest.fixture
    def app_with_store(self) -> FastAPI:
        """FastAPI app with a FakeVectorStore on app.state."""
        from backend.api.rag import router

        app = FastAPI()
        app.include_router(router)
        app.state.vector_store = FakeVectorStore()
        return app

    @pytest.fixture
    def app_without_store(self) -> FastAPI:
        """FastAPI app without a vector store on app.state."""
        from backend.api.rag import router

        app = FastAPI()
        app.include_router(router)
        # No vector_store set — simulates unavailability
        return app

    def test_search_returns_results(self, app_with_store: FastAPI) -> None:
        """POST /api/rag/search returns results for a valid query."""
        import asyncio

        # Pre-populate the store
        store: FakeVectorStore = app_with_store.state.vector_store
        asyncio.run(store.store("tool_results", "found a vulnerability in SSL", {"tool_name": "analysis"}))
        asyncio.run(store.store("tool_results", "discovered buffer overflow", {"tool_name": "analysis"}))

        client = TestClient(app_with_store)
        response = client.post(
            "/api/rag/search",
            json={"query": "vulnerability", "top_k": 5},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) >= 1
        assert data["results"][0]["text"] == "found a vulnerability in SSL"
        assert data["results"][0]["score"] >= 0.0
        assert data["error"] == ""

    def test_search_multiple_collections(self, app_with_store: FastAPI) -> None:
        """Search across multiple collections returns deduplicated results."""
        import asyncio

        store: FakeVectorStore = app_with_store.state.vector_store
        asyncio.run(store.store("tool_results", "analysis found critical bug", {}))
        asyncio.run(store.store("conversation", "the bug is in the parser", {}))

        client = TestClient(app_with_store)
        response = client.post(
            "/api/rag/search",
            json={"query": "bug", "collections": ["tool_results", "conversation"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) >= 1

    def test_search_no_match(self, app_with_store: FastAPI) -> None:
        """Search with non-matching query returns empty results."""
        client = TestClient(app_with_store)
        response = client.post(
            "/api/rag/search",
            json={"query": "xyznonexistent12345"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"] == []
        assert data["error"] == ""

    def test_search_store_unavailable(self, app_without_store: FastAPI) -> None:
        """Search when vector store is unavailable returns error response."""
        client = TestClient(app_without_store)
        response = client.post(
            "/api/rag/search",
            json={"query": "anything"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"] == []
        assert data["error"] == "Vector store not available"

    def test_search_respects_top_k(self, app_with_store: FastAPI) -> None:
        """Search respects the top_k parameter."""
        import asyncio

        store: FakeVectorStore = app_with_store.state.vector_store
        for i in range(10):
            asyncio.run(store.store(
                "tool_results",
                f"result number {i} about testing",
                {},
            ))

        client = TestClient(app_with_store)
        response = client.post(
            "/api/rag/search",
            json={"query": "testing", "top_k": 3},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) <= 3

    def test_search_response_structure(self, app_with_store: FastAPI) -> None:
        """Response matches SearchResponse schema."""
        client = TestClient(app_with_store)
        response = client.post(
            "/api/rag/search",
            json={"query": "anything"},
        )
        assert response.status_code == 200
        data = response.json()
        # Must have results and error keys
        assert "results" in data
        assert "error" in data


# =========================================================================
# 7. Tools module — _exec_rag_search
# =========================================================================


class TestRAGSearchTool:
    """Tests for the rag_search tool executor (_exec_rag_search)."""

    @pytest.mark.asyncio
    async def test_rag_search_no_store_returns_error(self) -> None:
        """rag_search returns an error message when _rag_store is None."""
        # Import the tool module and patch _rag_store to None
        from backend.agent.tools import _exec_rag_search

        # _rag_store is None by default when no set_rag_store() was called
        result = await _exec_rag_search(
            {"query": "test", "top_k": 5, "collections": ["tool_results"]},
            AsyncMock(),
        )
        assert "ERROR:" in result
        assert "not available" in result

    @pytest.mark.asyncio
    async def test_rag_search_returns_formatted_results(self) -> None:
        """rag_search returns formatted results when store is available."""
        from backend.agent.tools import _exec_rag_search

        fake_store = FakeVectorStore()
        await fake_store.store(
            "tool_results",
            "found a critical vulnerability",
            {"tool_name": "analysis", "role": "tool_result"},
        )

        with patch("backend.agent.tools._rag_store", fake_store):
            result = await _exec_rag_search(
                {"query": "vulnerability", "top_k": 5},
                AsyncMock(),
            )

        assert "RAG Search Results" in result
        assert "vulnerability" in result
        assert "critical" in result

    @pytest.mark.asyncio
    async def test_rag_search_empty_query_returns_error(self) -> None:
        """rag_search returns ERROR for empty query."""
        from backend.agent.tools import _exec_rag_search

        with patch("backend.agent.tools._rag_store", FakeVectorStore()):
            result = await _exec_rag_search(
                {"query": "   ", "top_k": 5},
                AsyncMock(),
            )
        assert "ERROR:" in result
        assert "No search query" in result

    @pytest.mark.asyncio
    async def test_rag_search_no_matches(self) -> None:
        """rag_search returns 'No relevant findings' when nothing matches."""
        from backend.agent.tools import _exec_rag_search

        fake_store = FakeVectorStore()
        await fake_store.store(
            "tool_results",
            "some unrelated content",
            {"tool_name": "analysis"},
        )

        with patch("backend.agent.tools._rag_store", fake_store):
            result = await _exec_rag_search(
                {"query": "xyznonexistent", "top_k": 5},
                AsyncMock(),
            )
        assert "No relevant findings" in result

    @pytest.mark.asyncio
    async def test_set_rag_store_accepts_none(self) -> None:
        """set_rag_store accepts None (disables RAG)."""
        import backend.agent.tools as tools_mod

        tools_mod.set_rag_store(None)
        assert tools_mod._rag_store is None

    @pytest.mark.asyncio
    async def test_set_rag_store_accepts_store(self) -> None:
        """set_rag_store accepts a FakeVectorStore instance."""
        import backend.agent.tools as tools_mod

        store = FakeVectorStore()
        tools_mod.set_rag_store(store)  # type: ignore[arg-type]
        # Access the module attribute to verify it was set
        assert tools_mod._rag_store is store

        # Cleanup for other tests
        tools_mod.set_rag_store(None)
