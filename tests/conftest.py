"""Test configuration to import modules from the MCP implementation."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_DIR = REPO_ROOT / "narrator-mcp"

# Ensure modules like `chunker` and `events` are importable from tests
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))
