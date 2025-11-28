"""Test configuration to import modules from the MCP implementation."""

from __future__ import annotations

import sys
from pathlib import Path

# Get the narrator-mcp directory (parent of tests)
MCP_DIR = Path(__file__).resolve().parent.parent

# Ensure modules like `chunker` are importable from tests
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))
