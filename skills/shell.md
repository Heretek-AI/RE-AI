---
name: shell
description: How to use the shell tool effectively — command patterns, timeout management, and output handling
tool_id: shell
command_hint: shell --command "command_string" --cwd "target_dir" --timeout 30
---

## Shell Tool Usage

The `shell` tool executes shell commands on the local filesystem. It returns exit code, stdout, and stderr.

### Key Parameters

- **command** (required): The shell command to execute. Use quotes for commands with spaces or special characters.
- **cwd** (optional): Working directory. Defaults to the project root. Always set this explicitly when working outside the project root.
- **timeout** (optional): Maximum execution time in seconds. Default 30, max 120. Set higher for long-running operations like builds or bulk file processing.

### Best Practices

1. **Always set `cwd`** when operating outside the project root to avoid ambiguity.
2. **Set appropriate timeouts** — a build or `npm install` may need 60–120s; a simple `ls` needs 5s.
3. **Output is truncated to 4000 characters** — for large outputs, pipe to a file and read with a second command (e.g., `dir /s > listing.txt` then `type listing.txt`).
4. **Stderr is appended separately** — the tool reports stdout first, then stderr after a `--- STDERR ---` separator.
5. **Check exit codes** — exit code 0 means success. Non-zero exit codes indicate errors.

### Error Handling

- `FileNotFoundError`: The shell itself wasn't found — usually a PATH issue.
- `TimeoutError`: The command exceeded the timeout. Consider increasing timeout or breaking into smaller steps.
- `PermissionError`: The shell or target file lacks execute permissions.

### Platform Notes

- **Windows (cmd)**: Use `dir` instead of `ls`, `type` instead of `cat`. Paths use backslashes.
- **Unix/POSIX**: Use standard POSIX commands. Paths use forward slashes.
- **PowerShell**: Available on Windows; use for more complex scripting. Use `python3` on Unix, `python` on Windows.
