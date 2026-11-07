"""MCP wire encoding; independent of storage and reasoning semantics."""
from __future__ import annotations

import json
from typing import Any


def tool_result(payload: Any, *, is_error: bool = False) -> dict:
    """Encode data in a 2024-11-05 CallToolResult text content block.

    Only tools/call responses use this envelope. Handshake and tools/list
    results retain their protocol-specific shapes. Lists, including [], must
    remain visible rather than being replaced by an empty result object.
    """
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": is_error,
    }
