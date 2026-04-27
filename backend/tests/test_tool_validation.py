"""Tests for tool validation and config integration — config model with tool_configs.

Tests the FastAPI config endpoints (PUT /api/config, GET /api/config) to verify
that ``tool_configs`` is accepted in the PUT payload and returned in the GET
response after save.

Uses httpx AsyncClient with ASGITransport, mocking ConfigStore to avoid
filesystem interaction.
"""

import os
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from backend.api.config import ConfigUpdate, ConfigResponse
from backend.main import app


# ═══════════════════════════════════════════════════════════════════════
# Config model tests — tool_configs in PUT/GET lifecycle
# ═══════════════════════════════════════════════════════════════════════


class TestConfigToolConfigsRoundTrip:
    """Verify tool_configs is accepted in PUT and returned in GET.

    We mock ConfigStore to avoid writing to the actual ~/.re-ai/config.enc.
    """

    @pytest.fixture
    def client(self):
        """Provide a bare httpx AsyncClient with ASGI transport.

        The config endpoints are stateless (everything goes through ConfigStore),
        so we don't need a full lifespan or engine.
        """
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )

    async def test_put_config_accepts_tool_configs(self, client: httpx.AsyncClient):
        """PUT /api/config with tool_configs returns 204 (no crash)."""
        with patch("backend.api.config.ConfigStore") as MockStore:
            instance = MockStore.return_value
            instance.load.return_value = {}

            resp = await client.put("/api/config", json={
                "ai_provider": "openai",
                "ai_api_key": "sk-test-123",
                "ai_model": "gpt-4o",
                "tool_configs": {
                    "ida_pro": "C:\\Program Files\\IDA Pro\\idat64.exe",
                    "ghidra": "C:\\ghidra\\support\\analyzeHeadless.bat",
                },
            })

        assert resp.status_code == 204

    async def test_put_config_stores_tool_configs(self, client: httpx.AsyncClient):
        """PUT /api/config persists tool_configs to the store."""
        with patch("backend.api.config.ConfigStore") as MockStore:
            instance = MockStore.return_value
            instance.load.return_value = {}

            await client.put("/api/config", json={
                "ai_provider": "openai",
                "ai_api_key": "sk-test-123",
                "ai_model": "gpt-4o",
                "tool_configs": {
                    "ida_pro": "/opt/ida/idat64",
                },
            })

            # Verify save was called with tool_configs included
            _args, save_kwargs = instance.save.call_args
            saved_data = save_kwargs["data"]
            assert saved_data.get("tool_configs") == {"ida_pro": "/opt/ida/idat64"}

    async def test_put_config_does_not_require_tool_configs(self, client: httpx.AsyncClient):
        """PUT /api/config without tool_configs defaults to empty dict."""
        with patch("backend.api.config.ConfigStore") as MockStore:
            instance = MockStore.return_value
            instance.load.return_value = {}

            resp = await client.put("/api/config", json={
                "ai_provider": "openai",
                "ai_api_key": "sk-test-123",
                "ai_model": "gpt-4o",
            })

        assert resp.status_code == 204

    async def test_get_config_includes_tool_configs(self, client: httpx.AsyncClient):
        """GET /api/config returns tool_configs when the store has them."""
        with patch("backend.api.config.ConfigStore") as MockStore:
            instance = MockStore.return_value
            instance.load.return_value = {
                "ai_provider": "openai",
                "ai_api_key": "sk-real-key",
                "ai_model": "gpt-4o",
                "tool_configs": {
                    "ida_pro": "C:\\ida\\idat64.exe",
                    "ghidra": "C:\\ghidra\\analyzeHeadless.bat",
                },
            }

            resp = await client.get("/api/config")

        assert resp.status_code == 200
        data = resp.json()
        assert "tool_configs" in data
        assert data["tool_configs"] == {
            "ida_pro": "C:\\ida\\idat64.exe",
            "ghidra": "C:\\ghidra\\analyzeHeadless.bat",
        }

    async def test_get_config_tool_configs_empty_by_default(self, client: httpx.AsyncClient):
        """GET /api/config returns empty tool_configs when store has none."""
        with patch("backend.api.config.ConfigStore") as MockStore:
            instance = MockStore.return_value
            instance.load.return_value = {
                "ai_provider": "openai",
                "ai_api_key": "sk-real-key",
                "ai_model": "gpt-4o",
            }

            resp = await client.get("/api/config")

        assert resp.status_code == 200
        data = resp.json()
        assert "tool_configs" in data
        assert data["tool_configs"] == {}

    async def test_get_config_404_when_not_configured(self, client: httpx.AsyncClient):
        """GET /api/config returns 404 when no config has been saved."""
        with patch("backend.api.config.ConfigStore") as MockStore:
            instance = MockStore.return_value
            instance.load.return_value = {}

            resp = await client.get("/api/config")

        assert resp.status_code == 404

    async def test_config_redacts_api_key(self, client: httpx.AsyncClient):
        """GET /api/config always redacts the API key."""
        with patch("backend.api.config.ConfigStore") as MockStore:
            instance = MockStore.return_value
            instance.load.return_value = {
                "ai_provider": "openai",
                "ai_api_key": "sk-super-secret-key",
                "ai_model": "gpt-4o",
                "tool_configs": {},
            }

            resp = await client.get("/api/config")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ai_api_key"] == "••••••••••••••••"
        assert "sk-super-secret-key" not in str(data)

    async def test_tool_configs_independent_of_tool_paths(self, client: httpx.AsyncClient):
        """tool_configs and tool_paths are separate fields and don't interfere."""
        with patch("backend.api.config.ConfigStore") as MockStore:
            instance = MockStore.return_value
            instance.load.return_value = {}

            await client.put("/api/config", json={
                "ai_provider": "openai",
                "ai_api_key": "sk-test",
                "ai_model": "gpt-4o",
                "tool_paths": ["C:\\tools"],
                "tool_configs": {"ida_pro": "C:\\ida\\idat64.exe"},
            })

            _args, save_kwargs = instance.save.call_args
            saved_data = save_kwargs["data"]
            assert saved_data.get("tool_paths") == ["C:\\tools"]
            assert saved_data.get("tool_configs") == {"ida_pro": "C:\\ida\\idat64.exe"}
            assert saved_data.get("tool_paths") != saved_data.get("tool_configs")


# ═══════════════════════════════════════════════════════════════════════
# ConfigUpdate Pydantic model tests
# ═══════════════════════════════════════════════════════════════════════


class TestConfigUpdateModel:
    """Unit tests for the ConfigUpdate Pydantic model directly."""

    def test_accepts_tool_configs(self):
        """ConfigUpdate can be constructed with tool_configs."""
        model = ConfigUpdate(
            ai_provider="anthropic",
            ai_api_key="sk-ant-test",
            ai_model="claude-3-5-sonnet-20241022",
            tool_configs={"ida_pro": "/usr/bin/idat64"},
        )
        assert model.tool_configs == {"ida_pro": "/usr/bin/idat64"}

    def test_defaults_to_empty_dict(self):
        """ConfigUpdate defaults tool_configs to empty dict."""
        model = ConfigUpdate(
            ai_provider="openai",
            ai_api_key="sk-test",
            ai_model="gpt-4o",
        )
        assert model.tool_configs == {}

    def test_model_dump_includes_tool_configs(self):
        """model_dump() includes tool_configs in the output."""
        model = ConfigUpdate(
            ai_provider="openai",
            ai_api_key="sk-test",
            ai_model="gpt-4o",
            tool_configs={"ghidra": "/opt/ghidra/analyzeHeadless"},
        )
        dumped = model.model_dump(exclude_unset=True)
        assert "tool_configs" in dumped
        assert dumped["tool_configs"] == {"ghidra": "/opt/ghidra/analyzeHeadless"}

    def test_multiple_tool_configs(self):
        """ConfigUpdate accepts multiple tool config entries."""
        model = ConfigUpdate(
            ai_provider="openai",
            ai_api_key="sk-test",
            ai_model="gpt-4o",
            tool_configs={
                "ida_pro": "C:\\IDA Pro\\idat64.exe",
                "ghidra": "C:\\Ghidra\\analyzeHeadless.bat",
            },
        )
        assert len(model.tool_configs) == 2
        assert model.tool_configs["ida_pro"] == "C:\\IDA Pro\\idat64.exe"
        assert model.tool_configs["ghidra"] == "C:\\Ghidra\\analyzeHeadless.bat"

    def test_coexists_with_tool_paths(self):
        """tool_configs and tool_paths are independent and coexist."""
        model = ConfigUpdate(
            ai_provider="openai",
            ai_api_key="sk-test",
            ai_model="gpt-4o",
            tool_paths=["C:\\tools", "D:\\bin"],
            tool_configs={"ida_pro": "C:\\ida\\idat64.exe"},
        )
        assert model.tool_paths == ["C:\\tools", "D:\\bin"]
        assert model.tool_configs == {"ida_pro": "C:\\ida\\idat64.exe"}
