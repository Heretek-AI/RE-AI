"""pytest conftest — add project root to sys.path so ``backend`` is importable."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path so tests can import backend.* modules
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
