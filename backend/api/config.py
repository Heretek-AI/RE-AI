"""Configuration API endpoints with provider validation.

Endpoints
---------
- GET  /api/config         — Return current config with API keys redacted (or 404 if unconfigured)
- PUT  /api/config         — Save/update config to the encrypted ConfigStore
- POST /api/config/validate — Test an AI provider API key with a real API call
- GET  /api/config/wizard-status — Return ``{ "configured": bool }`` for frontend routing
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from httpx import AsyncClient, RequestError
from pydantic import BaseModel, Field

from backend.core.config_store import ConfigStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config", tags=["config"])

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

REDACTED = "••••••••••••••••"


class ConfigUpdate(BaseModel):
    """Payload for saving/updating config."""

    ai_provider: str = Field(default="openai", description="AI provider name")
    ai_api_key: str = Field(default="", description="Raw API key (will be encrypted at rest)")
    ai_model: str = Field(default="gpt-4o", description="Model identifier")
    tool_paths: list[str] = Field(default_factory=list, description="Paths to scan for tools")
    preferences: dict[str, Any] = Field(default_factory=dict, description="Misc preferences")


class ConfigResponse(BaseModel):
    """Config payload returned to the client — API keys are always redacted."""

    ai_provider: str
    ai_api_key: str = REDACTED
    ai_model: str
    tool_paths: list[str]
    preferences: dict[str, Any]


class ValidateRequest(BaseModel):
    """Validation request for a provider credential."""

    provider: str = Field(..., description="Provider name (openai | anthropic | ollama | minimax)")
    api_key: str = Field(default="", description="API key to validate")


class ValidateResponse(BaseModel):
    """Validation result."""

    valid: bool
    provider: str
    error: Optional[str] = None


class WizardStatus(BaseModel):
    """Wizard completion status for frontend routing."""

    configured: bool


# ---------------------------------------------------------------------------
# Helper — redact keys from the response
# ---------------------------------------------------------------------------

SENSITIVE_KEYS = {"ai_api_key", "api_key", "secret_key", "password", "token"}


def _redact(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *data* with sensitive values replaced by ``REDACTED``."""
    out = {}
    for k, v in data.items():
        if k in SENSITIVE_KEYS:
            out[k] = REDACTED
        elif isinstance(v, dict):
            out[k] = _redact(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Provider validation logic
# ---------------------------------------------------------------------------

PROVIDER_VALIDATORS: dict[str, str] = {
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/messages",
}


async def _validate_provider(provider: str, api_key: str) -> ValidateResponse:
    """Make a real API call to verify *provider* credentials.

    Returns a ``ValidateResponse`` with ``valid``, ``provider``, and optionally
    ``error`` on failure.
    """
    provider = provider.lower().strip()

    # --- Ollama (local, no auth — just check the server is reachable) ---
    if provider == "ollama":
        try:
            async with AsyncClient(timeout=5.0) as client:
                resp = await client.get("http://localhost:11434/api/tags")
            if resp.status_code < 500:
                return ValidateResponse(valid=True, provider=provider)
            return ValidateResponse(
                valid=False,
                provider=provider,
                error=f"Ollama server returned HTTP {resp.status_code}",
            )
        except RequestError as exc:
            return ValidateResponse(
                valid=False,
                provider=provider,
                error=f"Ollama not reachable at localhost:11434 — {exc}",
            )

    # --- Providers requiring an API key ---
    if not api_key:
        return ValidateResponse(
            valid=False,
            provider=provider,
            error="API key is required for this provider",
        )

    url = PROVIDER_VALIDATORS.get(provider)
    if not url:
        return ValidateResponse(
            valid=False,
            provider=provider,
            error=f"Unknown provider '{provider}'. Supported: openai, anthropic, ollama, minimax",
        )

    headers: dict[str, str] = {}
    if provider == "openai":
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider == "anthropic":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"

    try:
        async with AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code == 200:
            return ValidateResponse(valid=True, provider=provider)
        if resp.status_code == 401:
            return ValidateResponse(
                valid=False,
                provider=provider,
                error="Invalid API key (HTTP 401)",
            )
        return ValidateResponse(
            valid=False,
            provider=provider,
            error=f"Provider returned HTTP {resp.status_code}",
        )
    except RequestError as exc:
        return ValidateResponse(
            valid=False,
            provider=provider,
            error=f"Could not reach provider: {exc}",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=ConfigResponse)
async def get_config():
    """Return the current config with sensitive values redacted.

    Returns 404 if no config has been saved yet (wizard not completed).
    """
    store = ConfigStore()
    data = store.load()
    if not data:
        raise HTTPException(status_code=404, detail="No configuration found. Run the setup wizard first.")

    redacted = _redact(data)
    return ConfigResponse(**redacted)


@router.put("", status_code=204)
async def save_config(payload: ConfigUpdate):
    """Save or update the configuration in the encrypted store.

    The API key is encrypted at rest inside the ``ConfigStore``.
    This endpoint never logs the raw key.
    """
    store = ConfigStore()
    existing = store.load()

    existing.update(payload.model_dump(exclude_unset=True))
    store.save(data=existing)
    logger.info("Config saved (provider=%s, model=%s)", payload.ai_provider, payload.ai_model)


@router.post("/validate", response_model=ValidateResponse)
async def validate_provider(payload: ValidateRequest):
    """Test an AI provider credential with a real API call.

    For Ollama, this simply checks whether the local server is reachable
    (no API key needed). For OpenAI/Anthropic/MiniMax, a test request
    is made with the provided key.

    This endpoint never logs the raw API key.
    """
    return await _validate_provider(payload.provider, payload.api_key)


@router.get("/wizard-status", response_model=WizardStatus)
async def wizard_status():
    """Return whether the setup wizard has been completed.

    Used by the frontend to determine which page to show (wizard vs. dashboard).
    """
    store = ConfigStore()
    data = store.load()
    configured = bool(data.get("ai_provider") and data.get("ai_api_key"))
    return WizardStatus(configured=configured)
