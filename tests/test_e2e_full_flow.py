"""End-to-end test proving the full M001 foundation works.

Launches a real uvicorn subprocess on port 8765 with an isolated temp
database, then exercises the entire REST API surface via httpx and
verifies the SPA renders correctly in Chromium via Playwright.

Constraints
----------
- Port 8765 (avoids conflicts with any running dev server on 8000)
- ``tmp_path``-isolated SQLite database and Chroma persist directory
- No real AI provider key needed — the ``AI_API_KEY`` env var is set to
  a dummy value so the app starts without errors
- Server fixture is session-scoped (one subprocess for the whole module)
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page

# Project root (parent of tests/)
ROOT = Path(__file__).resolve().parent.parent


# ── Helpers ──────────────────────────────────────────────────────────────────


def _dump_logs(proc: subprocess.Popen[bytes]) -> None:
    """Print subprocess stdout/stderr for debugging startup failures."""
    try:
        out, err = proc.communicate(timeout=5)
        print("=== server stdout (startup failure) ===")
        print(out.decode("utf-8", errors="replace")[-2000:])
        print("=== server stderr (startup failure) ===")
        print(err.decode("utf-8", errors="replace")[-2000:])
    except Exception:
        pass


# ── Session-scoped server fixture ────────────────────────────────────────────


@pytest.fixture(scope="session")
def server(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Start a uvicorn subprocess with an isolated temp database.

    Yields ``"http://127.0.0.1:8765"`` after the health endpoint responds.
    Tears down the subprocess unconditionally in the ``finally`` block.
    """
    tmp = tmp_path_factory.mktemp("e2e")
    db_url = f"sqlite+aiosqlite:///{tmp / 'test.db'}"
    chroma_dir = str(tmp / "chroma")

    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    env["CHROMA_PERSIST_DIR"] = chroma_dir
    env["AI_API_KEY"] = "test-e2e-key"
    env["HOST"] = "127.0.0.1"
    env["PORT"] = "8765"
    env["DEBUG"] = "false"

    base_url = "http://127.0.0.1:8765"

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--port",
            "8765",
            "--host",
            "127.0.0.1",
        ],
        env=env,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )

    try:
        # Poll /health until ready (30 s timeout, 1 s retry)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                resp = httpx.get(f"{base_url}/health", timeout=1.0)
                if resp.status_code == 200:
                    break
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError):
                pass
            time.sleep(1)
        else:
            _dump_logs(proc)
            raise RuntimeError(
                "Server did not become ready within 30 s on port 8765"
            )

        yield base_url
    finally:
        proc.kill()
        proc.wait(timeout=10)
        # Flush remaining output (best-effort)
        try:
            proc.stdout.read() if proc.stdout else None
        except Exception:
            pass


# ── Test class ───────────────────────────────────────────────────────────────


class TestE2EFullFlow:
    """End-to-end test proving the full M001 foundation works."""

    # ------------------------------------------------------------------
    # REST API checks (httpx — no browser needed)
    # ------------------------------------------------------------------

    def test_rest_api_full_crud(self, server: str) -> None:
        """Exercise the full CRUD + status + persistence + favicon surface.

        Maps to checks a, c, d, e, f, g, h, i, j from the task plan.
        """
        base = server

        # ── a. GET /health ────────────────────────────────────────────
        resp = httpx.get(f"{base}/health", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "re-ai"

        # ── c. GET /api/config/wizard-status ─────────────────────────
        resp = httpx.get(f"{base}/api/config/wizard-status", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["configured"], bool)

        # ── d. GET /api/milestones (empty initial state) ──────────────
        resp = httpx.get(f"{base}/api/milestones", timeout=5)
        assert resp.status_code == 200
        assert resp.json() == []

        # ── e. POST /api/milestones → 201 ────────────────────────────
        resp = httpx.post(
            f"{base}/api/milestones",
            json={"title": "E2E Milestone", "description": "Created by E2E test"},
            timeout=5,
        )
        assert resp.status_code == 201
        ms = resp.json()
        assert ms["title"] == "E2E Milestone"
        assert ms["status"] == "active"
        assert isinstance(ms["id"], int)
        milestone_id = ms["id"]

        # ── f. POST /api/milestones/{id}/slices → 201 ────────────────
        resp = httpx.post(
            f"{base}/api/milestones/{milestone_id}/slices",
            json={"title": "E2E Slice"},
            timeout=5,
        )
        assert resp.status_code == 201
        sl = resp.json()
        assert sl["title"] == "E2E Slice"
        assert sl["milestone_id"] == milestone_id
        assert sl["status"] == "pending"
        slice_id = sl["id"]

        # ── g. POST /api/slices/{id}/tasks → 201 ─────────────────────
        resp = httpx.post(
            f"{base}/api/slices/{slice_id}/tasks",
            json={"title": "E2E Task", "description": "Do the thing"},
            timeout=5,
        )
        assert resp.status_code == 201
        tk = resp.json()
        assert tk["title"] == "E2E Task"
        assert tk["slice_id"] == slice_id
        assert tk["status"] == "pending"
        task_id = tk["id"]

        # ── h. PATCH /api/tasks/{id}/status → 200 (pending→in_progress) ─
        resp = httpx.patch(
            f"{base}/api/tasks/{task_id}/status",
            json={"status": "in_progress"},
            timeout=5,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"

        # Also transition to complete (validates full state machine)
        resp = httpx.patch(
            f"{base}/api/tasks/{task_id}/status",
            json={"status": "complete"},
            timeout=5,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "complete"

        # ── i. GET /api/milestones includes created milestone ─────────
        resp = httpx.get(f"{base}/api/milestones", timeout=5)
        assert resp.status_code == 200
        milestones = resp.json()
        ids = [m["id"] for m in milestones]
        assert milestone_id in ids, f"Milestone {milestone_id} not in list {ids}"

        # ── j. GET /favicon.svg → 200, image/svg+xml ─────────────────
        resp = httpx.get(f"{base}/favicon.svg", timeout=5)
        assert resp.status_code == 200
        ctype = resp.headers.get("content-type", "")
        assert "image/svg+xml" in ctype, f"Expected SVG content-type, got {ctype}"
        assert len(resp.content) > 0

    # ------------------------------------------------------------------
    # Frontend SPA check (Playwright browser)
    # ------------------------------------------------------------------

    def test_frontend_renders(self, server: str, page: "Page") -> None:  # noqa: F821
        """SPA loads in Chromium with the correct title and non-empty body."""
        page.goto(server, wait_until="networkidle")

        # Verify page title
        title = page.title()
        assert "RE-AI" in title, f"Expected 'RE-AI' in title, got '{title}'"

        # Verify visible body content exists (SPA rendered, not just a blank page)
        body = page.locator("body")
        body_text = body.text_content() or ""
        assert len(body_text.strip()) > 0, "Body content is empty — SPA may not have loaded"

        # Verify the page actually loaded something meaningful by checking
        # that the root mount point exists and contains rendered children
        root_el = page.locator("#root")
        assert root_el.is_visible(), "#root element is not visible"
        root_children = root_el.locator("> *")
        child_count = root_children.count()
        assert child_count > 0, (
            f"#root has {child_count} visible children — SPA likely did not mount"
        )
