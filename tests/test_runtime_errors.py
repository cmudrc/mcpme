"""Tests for error and notification runtime paths."""

from __future__ import annotations

from pathlib import Path

from mcpme import McpServer, build_manifest


def test_runtime_handles_unknown_methods_and_notifications(tmp_path: Path) -> None:
    """The runtime should produce JSON-RPC errors and ignore notifications."""

    source = tmp_path / "text_tools.py"
    source.write_text(
        """def ping(message: str) -> str:\n"""
        '''    """Ping text.\n\n'''
        """    Args:\n"""
        """        message: Input text.\n\n"""
        """    Returns:\n"""
        """        Same text.\n"""
        '''    """\n'''
        """    return message\n""",
        encoding="utf-8",
    )
    server = McpServer(build_manifest(targets=[source]))

    notification = server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
    error = server.handle_request({"jsonrpc": "2.0", "id": 7, "method": "unknown"})

    assert notification is None
    assert error["error"]["code"] == -32601
