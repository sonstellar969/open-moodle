"""Model Context Protocol (MCP) server for Moodle."""

from __future__ import annotations

import os
from typing import Any, Optional

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

from open_moodle.client import MoodleClient
from open_moodle.config import get_credentials
from open_moodle.parsers import extract_content


def create_server(
    url_override: Optional[str] = None,
    token_override: Optional[str] = None,
) -> MCPServer:
    """Instantiate and configure the Moodle MCP server with all tools."""
    server = MCPServer("open-moodle")

    def _get_client() -> MoodleClient:
        url, token = get_credentials(url_override, token_override)
        return MoodleClient(url, token)

    @server.tool()
    def moodle_whoami() -> str:
        """Get profile information about the authenticated student and institution."""
        with _get_client() as client:
            info = client.get_site_info()
            lines = [
                f"Full Name: {info.get('fullname', '')}",
                f"Username: {info.get('username', '')}",
                f"User ID: {info.get('userid', '')}",
                f"Institution / Site: {info.get('sitename', '')}",
                f"Moodle URL: {info.get('siteurl', '')}",
                f"Moodle Release: {info.get('release', '')}",
            ]
            return "\n".join(lines)

    @server.tool()
    def moodle_list_courses() -> str:
        """List all courses the student is currently enrolled in, including Course IDs."""
        with _get_client() as client:
            courses = client.get_enrolled_courses()
            if not courses:
                return "No enrolled courses found."

            output = ["# Enrolled Courses\n"]
            for c in courses:
                cid = c.get("id")
                cname = c.get("fullname", c.get("displayname", "Untitled"))
                cshort = c.get("shortname", "")
                output.append(f"- **ID {cid}**: {cname} (`{cshort}`)")
            return "\n".join(output)

    @server.tool()
    def moodle_get_course_contents(course_id: int) -> str:
        """Get the full syllabus, sections, modules, and resources for a given course ID."""
        with _get_client() as client:
            sections = client.get_course_contents(course_id)
            if not sections:
                return f"No contents found for Course ID {course_id}."

            output = [f"# Course Contents (ID: {course_id})\n"]
            for sec in sections:
                sec_name = sec.get("name", "Section")
                modules = sec.get("modules", [])
                output.append(f"## {sec_name}")

                if not modules:
                    output.append("_No items in this section._\n")
                    continue

                for mod in modules:
                    mod_name = mod.get("name", "Unnamed module")
                    mod_type = mod.get("modname", "")
                    mod_url = mod.get("url", "")
                    contents = mod.get("contents", [])

                    output.append(f"### {mod_name} ({mod_type})")
                    if mod_url:
                        output.append(f"- URL: {mod_url}")

                    for item in contents:
                        fname = item.get("filename", "")
                        furl = item.get("fileurl", "")
                        fsize = item.get("filesize", 0)
                        size_kb = round(fsize / 1024, 1)
                        output.append(f"- File: `{fname}` ({size_kb} KB)")
                        output.append(f"  Download URL: {furl}")

                    output.append("")

            return "\n".join(output)

    @server.tool()
    def moodle_read_resource(
        file_url: str,
        filename: str = "",
        max_pages: int = 40,
    ) -> str:
        """Download and read the full text content of a PDF, Word document, slide deck, or text file."""
        with _get_client() as client:
            data = client.download_file(file_url)
            text = extract_content(data, filename=filename, max_pages=max_pages)
            return text

    @server.tool()
    def moodle_upcoming_deadlines(days_ahead: int = 30) -> str:
        """Check for upcoming assignment submissions, quizzes, and calendar events."""
        with _get_client() as client:
            events = client.get_upcoming_events(days_ahead=days_ahead)
            if not events:
                return f"No upcoming deadlines or events in the next {days_ahead} days."

            output = [f"# Upcoming Deadlines (Next {days_ahead} Days)\n"]
            for ev in events:
                name = ev.get("name", "Event")
                time_str = ev.get("formattedtime", "")
                c_data = ev.get("course", {})
                c_name = c_data.get("fullname", "") if isinstance(c_data, dict) else ""
                url = ev.get("url", "")

                output.append(f"- **{name}**")
                if c_name:
                    output.append(f"  Course: {c_name}")
                if time_str:
                    output.append(f"  When: {time_str}")
                if url:
                    output.append(f"  Link: {url}")
                output.append("")

            return "\n".join(output)

    @server.tool()
    def moodle_notifications(limit: int = 15) -> str:
        """Fetch recent announcements, teacher messages, and grade notifications."""
        with _get_client() as client:
            notifs = client.get_notifications(limit=limit)
            if notifs:
                output = ["# Recent Notifications\n"]
                for n in notifs:
                    subj = n.get("subject", "Notification")
                    text = n.get("text", n.get("smallmessage", ""))
                    when = n.get("timecreatedpretty", "")
                    read_status = "Read" if n.get("read") else "Unread"
                    url = n.get("contexturl", "")

                    output.append(f"### {subj} [{read_status}]")
                    if when:
                        output.append(f"_Received: {when}_")
                    if text:
                        output.append(text)
                    if url:
                        output.append(f"Link: {url}")
                    output.append("")
                return "\n".join(output)
            return "No notifications found."

    @server.tool()
    def moodle_get_assignments(course_id: int = 0) -> str:
        """List assignments, descriptions, and submission deadlines for a course (or all courses if 0)."""
        with _get_client() as client:
            cids = [course_id] if course_id > 0 else None
            assigns = client.get_assignments(cids)
            if not assigns:
                return "No assignments found."

            output = ["# Assignments\n"]
            for a in assigns:
                title = a.get("name", "Assignment")
                course = a.get("course_title", "")
                intro = a.get("intro", "")
                due = a.get("duedate", 0)

                output.append(f"## {title}")
                if course:
                    output.append(f"- Course: {course}")
                if due:
                    import datetime
                    dt = datetime.datetime.fromtimestamp(due)
                    output.append(f"- Due Date: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                if intro:
                    from open_moodle.parsers import strip_html
                    output.append(f"\n{strip_html(intro)}\n")

            return "\n".join(output)

    return server


def run_stdio() -> None:
    """Run the MCP server over standard input/output."""
    server = create_server()
    server.run(transport="stdio")
