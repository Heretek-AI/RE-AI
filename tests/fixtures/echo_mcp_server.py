"""Echo MCP server for testing MCPServerProcess lifecycle.

Reads JSON-RPC 2.0 messages from stdin, one per line, and writes
responses to stdout.

- ``initialize`` → returns a success result with server info.
- ``tools/call`` → echoes the tool name and arguments back in the result.
- ``notifications/initialized`` → ignored (no response expected).
- ``shutdown`` → exits cleanly.
"""

import json
import sys


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method", "")
        msg_id = msg.get("id")

        if method == "initialize":
            # Respond with server capabilities
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "0.1.0",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "echo-server", "version": "1.0.0"},
                },
            }
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

        elif method == "tools/call":
            params = msg.get("params", {})
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "echo_tool": params.get("name", ""),
                                    "echo_args": params.get("arguments", {}),
                                }
                            ),
                        }
                    ],
                    "isError": False,
                },
            }
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

        elif method == "shutdown":
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {},
            }
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
            break

        elif method == "resources/list":
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"resources": []},
            }
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

        # notifications (no id) — no response expected
        # just ignore them


if __name__ == "__main__":
    main()
