"""Tests for MCP tool invocation via FastMCP protocol layer.

All tests use mcp.call_tool() to verify tools are registered and
invoke SDK methods correctly, without network I/O.
"""
import asyncio
from unittest.mock import patch, MagicMock


def test_analyze_emails_registered():
    """Proof: analyze_emails tool is registered with correct schema."""
    from agentic_consult.mcp.server import mcp

    tools = asyncio.run(mcp.list_tools())
    tool_names = [t.name for t in tools]

    assert "analyze_emails" in tool_names

    analyze_tool = next(t for t in tools if t.name == "analyze_emails")
    schema = analyze_tool.inputSchema

    assert schema["type"] == "object"
    assert "message_ids" in schema["properties"]
    assert schema["properties"]["message_ids"]["type"] == "array"
    assert schema["properties"]["message_ids"]["items"]["type"] == "string"
    assert "message_ids" in schema["required"]


def test_analyze_emails_invokes_process_list():
    """Proof: analyze_emails calls SDK process_list with correct args."""
    from agentic_consult.mcp.server import mcp

    mock_analyzer_instance = MagicMock()
    mock_analyzer_instance.process_list.return_value = [
        {"id": "msg-1", "action": "archive", "reason": "test"},
        {"id": "msg-2", "action": "review", "reason": "test"},
    ]

    with patch('email_archive.EmailStore'), \
         patch('agentic_consult.email.analyzer.EmailAnalyzer') as mock_analyzer_cls:

        mock_analyzer_cls.return_value = mock_analyzer_instance

        message_ids = ["msg-1", "msg-2"]
        _, result = asyncio.run(mcp.call_tool("analyze_emails", {"message_ids": message_ids}))

        mock_analyzer_instance.process_list.assert_called_once_with(message_ids)

        assert "results" in result
        assert len(result["results"]) == 2


def test_analyze_emails_empty_list_error():
    """Proof: analyze_emails returns error for empty message_ids."""
    from agentic_consult.mcp.server import mcp

    _, result = asyncio.run(mcp.call_tool("analyze_emails", {"message_ids": []}))

    assert "error" in result
    assert "at least one" in result["error"].lower()


def test_analyze_emails_single_id():
    """Proof: analyze_emails works with single message ID."""
    from agentic_consult.mcp.server import mcp

    mock_analyzer_instance = MagicMock()
    mock_analyzer_instance.process_list.return_value = [
        {"id": "single-msg", "action": "archive", "reason": "test"},
    ]

    with patch('email_archive.EmailStore'), \
         patch('agentic_consult.email.analyzer.EmailAnalyzer') as mock_analyzer_cls:

        mock_analyzer_cls.return_value = mock_analyzer_instance

        _, result = asyncio.run(mcp.call_tool("analyze_emails", {"message_ids": ["single-msg"]}))

        mock_analyzer_instance.process_list.assert_called_once_with(["single-msg"])
        assert len(result["results"]) == 1
