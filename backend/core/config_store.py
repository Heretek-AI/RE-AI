"""Encrypted JSON config store using Fernet symmetric encryption.

Config is persisted as an encrypted JSON blob at ``~/.re-ai/config.enc``.
The encryption key is derived from a machine-stable seed
(``COMPUTERNAME`` + ``USERNAME`` + a salt constant) via PBKDF2HMAC,
so the same config file is transparently readable across restarts
on the same machine.

A key fingerprint (SHA-256 of the derived key) is stored alongside
the ciphertext to detect environment changes (e.g. the config was
copied to a different machine) or corruption.

Config shape::

    {
        "ai_provider": "openai",
        "ai_api_key": "sk-...",
        "ai_model": "gpt-4o",
        "tool_paths": ["/path/to/tool"],
        "preferences": {"theme": "dark"},
    }
"""

import base64
import hashlib
import json
import os
import platform
from pathlib import Path
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIG_DIR_NAME = ".re-ai"
CONFIG_FILE_NAME = "config.enc"
SALT = b"re-ai-v1-salt-2024"  # fixed salt — stable across restarts
KEY_DERIVATION_ITERATIONS = 600_000  # OWASP recommended minimum for PBKDF2-HMAC-SHA256
FINGERPRINT_KEY = "_key_fingerprint"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _machine_seed() -> str:
    """Return a machine-stable seed string.

    On Windows this uses ``COMPUTERNAME`` + ``USERNAME``. On other platforms
    it falls back to the hostname + login name.
    """
    host = os.environ.get("COMPUTERNAME") or platform.node() or "unknown-host"
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown-user"
    return f"{host}::{user}"


def _derive_key(seed: str) -> bytes:
    """Derive a 32-byte Fernet-compatible key from *seed* using PBKDF2HMAC."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SALT,
        iterations=KEY_DERIVATION_ITERATIONS,
    )
    return kdf.derive(seed.encode("utf-8"))


def _to_fernet_key(raw_key: bytes) -> bytes:
    """Encode a 32-byte raw key as a URL-safe base64 Fernet key."""
    return base64.urlsafe_b64encode(raw_key)


def _fingerprint(key: bytes) -> str:
    """Return a hex fingerprint of *key* for mismatch detection."""
    return hashlib.sha256(key).hexdigest()


# ---------------------------------------------------------------------------
# ConfigStore
# ---------------------------------------------------------------------------


class ConfigStore:
    """Encrypted, file-backed configuration store.

    Usage::

        cs = ConfigStore()
        cs.set("ai_api_key", "sk-test-123")
        cs.save()
        loaded = ConfigStore().load()
        assert loaded["ai_api_key"] == "sk-test-123"
    """

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        self._config_dir = Path(config_dir or Path.home() / CONFIG_DIR_NAME)
        self._config_path = self._config_dir / CONFIG_FILE_NAME
        self._seed = _machine_seed()
        self._raw_key = _derive_key(self._seed)
        self._fernet_key = _to_fernet_key(self._raw_key)
        self._cipher = Fernet(self._fernet_key)
        self._data: dict[str, Any] = {}

    # -- Public API -----------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """Load and decrypt config from disk. Returns the config dict."""
        if not self._config_path.exists():
            return {}

        raw = self._config_path.read_bytes()
        try:
            payload = json.loads(self._cipher.decrypt(raw).decode("utf-8"))
        except InvalidToken:
            # Key changed or file corrupted — return empty so caller can
            # re-initialise rather than crash.
            return {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

        # Fingerprint check — does the stored fingerprint match the current key?
        stored_fingerprint = payload.pop(FINGERPRINT_KEY, None)
        current_fingerprint = _fingerprint(self._raw_key)
        if stored_fingerprint is not None and stored_fingerprint != current_fingerprint:
            # Environment changed (e.g. config copied to another machine).
            # Return empty rather than silently returning stale credentials.
            return {}

        self._data = payload
        return self._data

    def save(self, data: Optional[dict[str, Any]] = None) -> None:
        """Encrypt *data* (or current in-memory state) and write to disk."""
        if data is not None:
            self._data = data

        payload = dict(self._data)
        payload[FINGERPRINT_KEY] = _fingerprint(self._raw_key)

        self._config_dir.mkdir(parents=True, exist_ok=True)
        ciphertext = self._cipher.encrypt(
            json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        )
        self._config_path.write_bytes(ciphertext)

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for *key* from the in-memory config, or *default*."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set *key* to *value* in the in-memory config (does **not** persist)."""
        self._data[key] = value

    # -- Helpers for introspection -------------------------------------------

    @property
    def config_path(self) -> Path:
        """Path to the encrypted config file on disk."""
        return self._config_path

    @property
    def fingerprint(self) -> str:
        """Return the SHA-256 fingerprint of the current encryption key."""
        return _fingerprint(self._raw_key)

    def fingerprint_matches(self, other_fingerprint: str) -> bool:
        """Return ``True`` if *other_fingerprint* matches the current key."""
        return self.fingerprint == other_fingerprint

    @property
    def seed(self) -> str:
        """Return the machine-stable seed used for key derivation (read-only)."""
        return self._seed
