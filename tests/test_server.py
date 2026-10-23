"""Tests for MCP server tool registration."""

from __future__ import annotations

from open_moodle.server import create_server


def test_server_tools_registered():
    server = create_server("https://example.com/webservice/rest/server.php", "dummy_token")
    # Verify tool manager has the expected tools
    tools = [t.name for t in server._tool_manager.list_tools()]
    expected_tools = [
        "moodle_whoami",
        "moodle_list_courses",
        "moodle_get_course_contents",
        "moodle_read_resource",
        "moodle_upcoming_deadlines",
        "moodle_notifications",
        "moodle_get_assignments",
    ]
    for tool_name in expected_tools:
        assert tool_name in tools, f"Missing tool: {tool_name}"
