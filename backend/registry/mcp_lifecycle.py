"""MCP server subprocess lifecycle management.

Provides :class:`MCPServerProcess` for spawning, calling, and shutting down
MCP servers as subprocesses.  Each server communicates via line-delimited
JSON-RPC 2.0 over stdin/stdout.

Usage::

    proc = MCPServerProcess(
        name="my_server",
        command="python",
        args=["-m", "some_mcp_server"],
    )
    await proc.ensure_running()
    result = await proc.call("read_file", {"path": "/tmp/test.txt"})
    await proc.shutdown()
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Windows: prevent a console window from appearing for the child process.
if sys.platform == "win32":
    _CREATE_NO_WINDOW = 0x08000000
else:
    _CREATE_NO_WINDOW = 0


class MCPServerProcess:
    """Manages the lifecycle of a single MCP server subprocess.

    Attributes
    ----------
    name:
        Unique server name (matches :attr:`MCPToolDef.name`).
    status:
        Current lifecycle status: ``"stopped"``, ``"starting"``,
        ``"running"``, ``"errored"``, or ``"shutdown"``.
    """

    def __init__(
        self,
        name: str,
        command: str,
        args: Optional[list[str]] = None,
        env_vars: Optional[dict[str, str]] = None,
    ) -> None:
        self.name = name
        self._command = command
        self._args = args or []
        self._env_vars = env_vars or {}

        self._process: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._request_id = 0

        self.status: str = "stopped"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ensure_running(self) -> None:
        """Spawn the subprocess and perform the JSON-RPC ``initialize`` handshake.

        If the subprocess is already running this is a no-op.  On failure
        the status is set to ``"errored"`` and the exception is propagated.
        """
        async with self._lock:
            if self.status == "running" and self._is_process_alive():
                return
            await self._ensure_running_unlocked()

    async def call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a ``tools/call`` JSON-RPC request and return the result dict.

        Raises
        ------
        RuntimeError
            If the process is not running.
        ConnectionError
            If the subprocess has exited (broken pipe / closed stdout).
        """
        async with self._lock:
            if self.status != "running" or not self._is_process_alive():
                self.status = "errored"
                raise RuntimeError(
                    f"MCP server '{self.name}' is not running "
                    f"(status={self.status})"
                )

            return await self._send_request(
                "tools/call",
                {"name": tool_name, "arguments": arguments},
            )

    async def shutdown(self, timeout: float = 5.0) -> None:
        """Shut down the MCP server subprocess.

        Terminates the process (SIGTERM on POSIX, ``TerminateProcess`` on
        Windows) and waits up to *timeout* seconds for it to exit.  If the
        grace period expires the process is killed.
        """
        async with self._lock:
            if self._process is None:
                self.status = "shutdown"
                return
            if self._process.returncode is not None:
                self.status = "shutdown"
                self._process = None
                return

            self.status = "shutdown"
            try:
                self._process.terminate()

                try:
                    await asyncio.wait_for(self._process.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    logger.warning(
                        "MCP server '%s' did not exit within %.1fs — killing",
                        self.name,
                        timeout,
                    )
                    self._process.kill()
                    await self._process.wait()

                logger.info("MCP server '%s' shut down", self.name)
            except Exception:
                logger.exception("Error shutting down MCP server '%s'", self.name)
            finally:
                self._process = None

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def _is_process_alive(self) -> bool:
        """Check whether the subprocess is still running."""
        if self._process is None:
            return False
        return self._process.returncode is None

    async def _ensure_running_unlocked(self) -> None:
        """Spawn the subprocess and perform the initialize handshake.

        Caller **must** hold ``_lock``.
        """
        self.status = "starting"
        logger.info(
            "Starting MCP server '%s' (%s %s)",
            self.name,
            self._command,
            self._args,
        )

        try:
            env = None
            if self._env_vars:
                env = dict(self._env_vars)

            self._process = await asyncio.create_subprocess_exec(
                self._command,
                *self._args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                creationflags=_CREATE_NO_WINDOW,
            )

            # Perform JSON-RPC initialize handshake
            result = await self._send_request(
                "initialize",
                {
                    "protocolVersion": "0.1.0",
                    "capabilities": {},
                    "clientInfo": {"name": "re-ai", "version": "0.1.0"},
                },
            )

            logger.info(
                "MCP server '%s' initialized (protocol=%s, server=%s)",
                self.name,
                result.get("protocolVersion", "unknown"),
                result.get("serverInfo", {}).get("name", "unknown"),
            )

            # Fire-and-forget initialized notification
            await self._send_notification("notifications/initialized")

            self.status = "running"

        except Exception:
            self.status = "errored"
            logger.exception("Failed to start MCP server '%s'", self.name)
            raise

    # ------------------------------------------------------------------
    # JSON-RPC message helpers
    # ------------------------------------------------------------------

    async def _send_request(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a JSON-RPC 2.0 request and return the ``result`` dict.

        Caller **must** hold ``_lock``.
        """
        self._request_id += 1
        request_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        payload = json.dumps(request, default=str) + "\n"
        assert self._process is not None
        assert self._process.stdin is not None
        assert self._process.stdout is not None

        try:
            self._process.stdin.write(payload.encode("utf-8"))
            await self._process.stdin.drain()
        except BrokenPipeError:
            self.status = "errored"
            raise ConnectionError(
                f"MCP server '{self.name}' process exited unexpectedly "
                f"(broken pipe)"
            )

        line = await self._process.stdout.readline()
        if not line:
            # Stdout closed without a response — the process probably crashed
            self.status = "errored"
            raise ConnectionError(
                f"MCP server '{self.name}' closed stdout without responding"
            )

        response = json.loads(line.decode("utf-8"))

        if "error" in response:
            err = response["error"]
            raise RuntimeError(
                f"MCP server '{self.name}' returned error: "
                f"[{err.get('code', '?')}] {err.get('message', '?')}"
            )

        return response.get("result", {})

    async def _send_notification(
        self, method: str, params: Optional[dict[str, Any]] = None
    ) -> None:
        """Send a JSON-RPC 2.0 notification (no ``id``, fire-and-forget).

        Caller **must** hold ``_lock``.
        """
        notification: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            notification["params"] = params

        payload = json.dumps(notification, default=str) + "\n"
        assert self._process is not None
        assert self._process.stdin is not None

        try:
            self._process.stdin.write(payload.encode("utf-8"))
            await self._process.stdin.drain()
        except BrokenPipeError:
            self.status = "errored"
            logger.warning(
                "Broken pipe sending notification to '%s'", self.name
            )
