"""Model Context Protocol (MCP) server for Moodle."""

from __future__ import annotations

import datetime
from typing import Any, Optional

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

from open_moodle.client import CapabilityError, FileTooLargeError, MoodleAPIError, MoodleClient
from open_moodle.config import get_credentials
from open_moodle.parsers import extract_content, strip_html


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
            funcs = client.get_available_functions()
            lines = [
                f"Full Name: {info.get('fullname', '')}",
                f"Username: {info.get('username', '')}",
                f"User ID: {info.get('userid', '')}",
                f"Institution / Site: {info.get('sitename', '')}",
                f"Moodle URL: {info.get('siteurl', '')}",
                f"Moodle Release: {info.get('release', '')}",
                f"Allowed API Functions: {len(funcs)} functions available",
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
        start_page: int = 1,
        max_pages: int = 20,
    ) -> str:
        """Download and read text content from a PDF, Word document, slide deck, or text file."""
        with _get_client() as client:
            try:
                data = client.download_file(file_url)
            except FileTooLargeError as e:
                return f"Download failed: {e}"

            text = extract_content(
                data,
                filename=filename or file_url,
                start_page=start_page,
                max_pages=max_pages,
            )
            return text

    @server.tool()
    def moodle_upcoming_deadlines(days_ahead: int = 30) -> str:
        """Check for upcoming assignment submissions, quizzes, and calendar events."""
        with _get_client() as client:
            try:
                events = client.get_upcoming_events(days_ahead=days_ahead)
            except CapabilityError as e:
                return f"Calendar unavailable: {e}"

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
    def moodle_get_assignments(course_id: int = 0) -> str:
        """List assignments, submission status, due dates, and grading state."""
        with _get_client() as client:
            cids = [course_id] if course_id > 0 else None
            try:
                assigns = client.get_assignments(cids, include_submission_status=True)
            except CapabilityError as e:
                return f"Assignments API unavailable: {e}"

            if not assigns:
                return "No assignments found."

            output = ["# Assignments\n"]
            for a in assigns:
                title = a.get("name", "Assignment")
                course = a.get("course_title", "")
                intro = a.get("intro", "")
                due = a.get("duedate", 0)
                sub = a.get("submission", {})
                status = sub.get("status", "unknown").capitalize()
                graded = "Graded" if sub.get("graded") else "Not graded"

                output.append(f"## {title}")
                if course:
                    output.append(f"- Course: {course}")
                output.append(f"- Submission Status: **{status}** ({graded})")
                if due:
                    dt = datetime.datetime.fromtimestamp(due)
                    output.append(f"- Due Date: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                if intro:
                    output.append(f"\n{strip_html(intro)}\n")

            return "\n".join(output)

    @server.tool()
    def moodle_get_announcements(course_id: int, limit: int = 10) -> str:
        """Fetch actual teacher announcements from the course Announcements forum."""
        with _get_client() as client:
            try:
                posts = client.get_course_announcements(course_id, limit=limit)
            except CapabilityError as e:
                return f"Announcements forum unavailable: {e}"

            if not posts:
                return f"No forum announcements found for Course ID {course_id}."

            output = [f"# Course Announcements (Course ID: {course_id})\n"]
            for p in posts:
                name = p.get("name", "Announcement")
                author = p.get("userfullname", "Instructor")
                modified = p.get("timemodified", 0)
                msg = p.get("message", "")
                date_str = (
                    datetime.datetime.fromtimestamp(modified).strftime("%Y-%m-%d %H:%M")
                    if modified
                    else ""
                )

                output.append(f"### {name}")
                output.append(f"- Author: {author} ({date_str})")
                if msg:
                    output.append(f"\n{strip_html(msg)}\n")
                output.append("")

            return "\n".join(output)

    @server.tool()
    def moodle_notifications(limit: int = 15) -> str:
        """Fetch recent system bell alerts and personal notifications."""
        with _get_client() as client:
            notifs = client.get_notifications(limit=limit)
            if notifs:
                output = ["# Recent System Notifications\n"]
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
    def moodle_get_grades(course_id: int = 0) -> str:
        """Fetch student grades, percentages, and teacher feedback."""
        with _get_client() as client:
            try:
                usergrades = client.get_user_grades(course_id=course_id)
            except CapabilityError as e:
                return f"Grades report unavailable: {e}"

            if not usergrades:
                return "No grade records found."

            output = ["# Student Grade Report\n"]
            for ug in usergrades:
                c_title = ug.get("coursefullname", f"Course {ug.get('courseid')}")
                output.append(f"## {c_title}\n")
                items = ug.get("gradeitems", [])
                for item in items:
                    name = item.get("itemname") or item.get("itemtype", "Grade item")
                    grade_str = item.get("gradeformatted", "-")
                    range_str = item.get("rangeformatted", "")
                    feedback = item.get("feedback", "")

                    output.append(f"- **{name}**: {grade_str} (Range: {range_str})")
                    if feedback:
                        output.append(f"  Feedback: {strip_html(feedback)}")
                output.append("")

            return "\n".join(output)

    @server.tool()
    def moodle_brief(days: int = 7) -> str:
        """Consolidated briefing: enrolled courses, deadlines in the next N days, and pending tasks."""
        with _get_client() as client:
            lines = [f"# Moodle Student Briefing (Next {days} Days)\n"]

            # 1. Enrolled courses count
            try:
                courses = client.get_enrolled_courses()
                lines.append(f"## Active Courses ({len(courses)})\n")
                for c in courses[:6]:
                    lines.append(f"- **{c.get('fullname', '')}** (ID: {c.get('id')})")
                if len(courses) > 6:
                    lines.append(f"- _...and {len(courses) - 6} more courses._")
                lines.append("")
            except Exception as e:
                lines.append(f"_Could not load courses: {e}_\n")

            # 2. Upcoming events & deadlines
            try:
                events = client.get_upcoming_events(days_ahead=days)
                lines.append(f"## Upcoming Deadlines & Events ({len(events)})\n")
                if events:
                    for ev in events:
                        name = ev.get("name", "Event")
                        time_str = ev.get("formattedtime", "")
                        c_data = ev.get("course", {})
                        c_name = c_data.get("fullname", "") if isinstance(c_data, dict) else ""
                        lines.append(f"- **{name}** | {c_name} ({time_str})")
                else:
                    lines.append(f"_No deadlines scheduled in the next {days} days._")
                lines.append("")
            except Exception as e:
                lines.append(f"_Could not check deadlines: {e}_\n")

            # 3. Unread notifications
            try:
                notifs = client.get_notifications(limit=5)
                unread = [n for n in notifs if not n.get("read")]
                lines.append(f"## Recent Notifications ({len(unread)} unread)\n")
                if notifs:
                    for n in notifs[:5]:
                        st = "Unread" if not n.get("read") else "Read"
                        lines.append(f"- [{st}] **{n.get('subject', 'Notice')}**")
                else:
                    lines.append("_No recent notifications._")
                lines.append("")
            except Exception as e:
                lines.append(f"_Could not load notifications: {e}_\n")

            return "\n".join(lines)

    return server


def run_stdio(
    url_override: Optional[str] = None,
    token_override: Optional[str] = None,
) -> None:
    """Run the MCP server over standard input/output with optional URL and token overrides."""
    server = create_server(url_override=url_override, token_override=token_override)
    server.run(transport="stdio")
