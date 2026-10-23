"""Command-line interface for open-moodle."""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path
import sys
from typing import Optional

from rich.console import Console
from rich.table import Table

from open_moodle import __version__
from open_moodle.auth import AuthenticationError, login_sso, request_token, verify_credentials
from open_moodle.client import (
    CapabilityError,
    FileTooLargeError,
    MoodleAPIError,
    MoodleClient,
    calculate_attendance_metrics,
)
from open_moodle.config import get_credentials, load_config, normalize_moodle_url, save_config
from open_moodle.downloader import download_course_materials
from open_moodle.parsers import extract_content, strip_html
from open_moodle.search import index_course_materials, search_index
from open_moodle.server import run_stdio

console = Console()
err_console = Console(stderr=True)


def _resolve_creds(args: argparse.Namespace) -> tuple[str, str]:
    """Helper to resolve URL and token from args or config."""
    return get_credentials(getattr(args, "url", None), getattr(args, "token", None))



def cmd_login(args: argparse.Namespace) -> int:
    """Interactively or via flags authenticate with Moodle and save the token."""
    console.print("[bold]open-moodle authentication setup[/bold]\n")

    url = getattr(args, "url", None)
    if not url:
        saved = load_config()
        default_url = saved.get("url", "")
        prompt = f"Moodle URL [{default_url}]: " if default_url else "Moodle URL: "
        url = input(prompt).strip() or default_url

    if not url:
        err_console.print("[red]Error: Moodle URL is required.[/red]")
        return 1

    clean_url = normalize_moodle_url(url)

    if getattr(args, "token", None):
        token = args.token
    elif getattr(args, "sso", False):
        console.print(f"Initiating browser SSO login for {clean_url}...")
        console.print("Waiting for browser callback (timeout 120s)...")
        try:
            token, launch_url = login_sso(clean_url)
            console.print("[green]Token captured successfully from browser callback.[/green]")
        except Exception as e:
            err_console.print(f"[red]SSO login failed:[/red] {e}")
            err_console.print(
                "You can also provide a manual token with: [bold]open-moodle login --token <YOUR_TOKEN>[/bold]"
            )
            return 1
    else:
        username = args.username or input("Username / Student ID: ").strip()
        if not username:
            err_console.print("[red]Error: Username is required.[/red]")
            return 1

        password = getpass.getpass("Password: ")
        if not password:
            err_console.print("[red]Error: Password is required.[/red]")
            return 1

        console.print("\nRequesting token from Moodle mobile service...")
        try:
            res = request_token(clean_url, username, password)
            token = res["token"]
            console.print("[green]Token acquired successfully.[/green]")
        except AuthenticationError as e:
            err_console.print(f"[red]Authentication failed:[/red] {e}")
            err_console.print(
                "\nIf your college uses SSO (Microsoft/Google) or blocks mobile web services,\n"
                "you can provide an existing token with: [bold]open-moodle login --token <YOUR_TOKEN>[/bold]"
            )
            return 1

    console.print("Verifying credentials with Moodle...")
    try:
        info = verify_credentials(clean_url, token)
        fullname = info.get("fullname", "User")
        sitename = info.get("sitename", "Moodle Site")
        save_config(clean_url, token, {"user": fullname, "site": sitename})
        console.print(f"[green]Authenticated as [bold]{fullname}[/bold] on [bold]{sitename}[/bold].[/green]")
        console.print("Credentials saved to ~/.config/open-moodle/config.json\n")
        return 0
    except AuthenticationError as e:
        err_console.print(f"[red]Verification failed:[/red] {e}")
        return 1


def cmd_whoami(args: argparse.Namespace) -> int:
    """Show details of the currently authenticated account."""
    try:
        url, token = _resolve_creds(args)
        with MoodleClient(url, token) as client:
            info = client.get_site_info()
            funcs = client.get_available_functions()
            table = Table(title="Moodle Account Info", show_header=False)
            table.add_column("Field", style="bold")
            table.add_column("Value")

            table.add_row("Full Name", info.get("fullname", ""))
            table.add_row("Username", info.get("username", ""))
            table.add_row("User ID", str(info.get("userid", "")))
            table.add_row("Site Name", info.get("sitename", ""))
            table.add_row("Site URL", info.get("siteurl", ""))
            table.add_row("Moodle Version", info.get("release", ""))
            table.add_row("Available Functions", f"{len(funcs)} functions whitelisted")

            console.print(table)
            return 0
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        return 1


def cmd_courses(args: argparse.Namespace) -> int:
    """List enrolled courses."""
    try:
        url, token = _resolve_creds(args)
        with MoodleClient(url, token) as client:
            courses = client.get_enrolled_courses()
            if not courses:
                console.print("No enrolled courses found.")
                return 0

            table = Table(title="Enrolled Courses")
            table.add_column("ID", justify="right", style="cyan")
            table.add_column("Course Name", style="bold")
            table.add_column("Short Code", style="dim")

            for c in courses:
                cid = str(c.get("id", ""))
                cname = c.get("fullname", c.get("displayname", ""))
                cshort = c.get("shortname", "")
                table.add_row(cid, cname, cshort)

            console.print(table)
            return 0
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        return 1


def cmd_deadlines(args: argparse.Namespace) -> int:
    """List upcoming deadlines and calendar events."""
    try:
        url, token = _resolve_creds(args)
        with MoodleClient(url, token) as client:
            events = client.get_upcoming_events(days_ahead=args.days)
            if not events:
                console.print(f"No upcoming deadlines in the next {args.days} days.")
                return 0

            table = Table(title=f"Upcoming Deadlines (Next {args.days} Days)")
            table.add_column("Event / Task", style="bold")
            table.add_column("Course", style="dim")
            table.add_column("When", style="yellow")

            for ev in events:
                name = ev.get("name", "Event")
                time_str = ev.get("formattedtime", "")
                c_data = ev.get("course", {})
                c_name = c_data.get("fullname", "") if isinstance(c_data, dict) else ""
                table.add_row(name, c_name, time_str)

            console.print(table)
            return 0
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        return 1


def cmd_announcements(args: argparse.Namespace) -> int:
    """List real teacher announcements from the course Announcements forum."""
    try:
        url, token = _resolve_creds(args)
        with MoodleClient(url, token) as client:
            posts = client.get_course_announcements(course_id=args.course, limit=args.limit)
            if not posts:
                console.print(f"No forum announcements found for Course ID {args.course}.")
                return 0

            console.print(f"\n[bold]Course Announcements (Course ID: {args.course})[/bold]\n")
            for p in posts:
                title = p.get("name", "Announcement")
                author = p.get("userfullname", "Instructor")
                msg = p.get("message", "")
                console.print(f"[bold cyan]{title}[/bold cyan] — by {author}")
                if msg:
                    console.print(f"{strip_html(msg)}\n")
            return 0
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        return 1


def cmd_notifications(args: argparse.Namespace) -> int:
    """List recent announcements and notifications."""
    try:
        url, token = _resolve_creds(args)
        with MoodleClient(url, token) as client:
            notifs = client.get_notifications(limit=args.limit)
            if not notifs:
                console.print("No notifications found.")
                return 0

            for n in notifs:
                subj = n.get("subject", "Notification")
                text = n.get("text", n.get("smallmessage", ""))
                when = n.get("timecreatedpretty", "")
                status = "[green]Read[/green]" if n.get("read") else "[bold red]Unread[/bold red]"
                console.print(f"\n[bold]{subj}[/bold] ({status} - {when})")
                if text:
                    console.print(f"  {text}")
            return 0
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        return 1


def cmd_grades(args: argparse.Namespace) -> int:
    """View student grades and scores."""
    try:
        url, token = _resolve_creds(args)
        with MoodleClient(url, token) as client:
            usergrades = client.get_user_grades(course_id=args.course or 0)
            if not usergrades:
                console.print("No grade records found.")
                return 0

            for ug in usergrades:
                c_title = ug.get("coursefullname", "Course Grades")
                table = Table(title=c_title)
                table.add_column("Assessment Item", style="bold")
                table.add_column("Grade", style="green")
                table.add_column("Range", style="dim")

                for item in ug.get("gradeitems", []):
                    name = item.get("itemname") or item.get("itemtype", "Item")
                    grade_str = item.get("gradeformatted", "-")
                    range_str = item.get("rangeformatted", "")
                    table.add_row(name, grade_str, range_str)

                console.print(table)
            return 0
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        return 1


def cmd_brief(args: argparse.Namespace) -> int:
    """Print a consolidated student briefing for the next N days."""
    try:
        url, token = _resolve_creds(args)
        from open_moodle.server import create_server
        server = create_server(url_override=url, token_override=token)
        tool = next(t for t in server._tool_manager.list_tools() if t.name == "moodle_brief")
        result = tool.fn(days=args.days)
        console.print(result)
        return 0
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        return 1


def cmd_read(args: argparse.Namespace) -> int:
    """Download and extract readable text from a course file URL."""
    try:
        url, token = _resolve_creds(args)
        with MoodleClient(url, token) as client:
            console.print(f"Downloading {args.file_url} ...")
            data = client.download_file(args.file_url)
            text = extract_content(
                data,
                filename=args.file_url,
                start_page=args.start,
                max_pages=args.pages,
            )
            console.print("\n" + text)
            return 0
    except FileTooLargeError as e:
        err_console.print(f"[red]File size limit exceeded:[/red] {e}")
        return 1
    except Exception as e:
        err_console.print(f"[red]Error reading file:[/red] {e}")
        return 1


def cmd_attendance(args: argparse.Namespace) -> int:
    """Show attendance records and target threshold analysis."""
    try:
        url, token = _resolve_creds(args)
        threshold = float(args.threshold)
        with MoodleClient(url, token) as client:
            records = client.get_attendance()
            if not records:
                console.print("No attendance records found.")
                return 0

            total_sessions = sum(r["total_sessions"] for r in records)
            total_attended = sum(r["attended"] for r in records)
            overall_pct = (
                round((total_attended / total_sessions) * 100.0, 2)
                if total_sessions > 0
                else 0.0
            )

            table = Table(title=f"Attendance Report (Target Threshold: {threshold}%)")
            table.add_column("Course Name", style="bold")
            table.add_column("Attended", justify="right")
            table.add_column("Total", justify="right")
            table.add_column("Percentage", justify="right")
            table.add_column("Status", justify="center")
            table.add_column("Safe Bunks / Recovery Needed", justify="left")

            for r in records:
                m = calculate_attendance_metrics(
                    r["attended"], r["total_sessions"], threshold=threshold
                )
                pct = m["percentage"]
                if m["status"] == "OK":
                    status_str = "[green]OK[/green]"
                    margin_str = (
                        f"[green]+{m['safe_bunks']} safe bunks[/green]"
                        if m["safe_bunks"] > 0
                        else "[dim]On track[/dim]"
                    )
                    pct_style = "green"
                else:
                    status_str = "[bold red]BELOW TARGET[/bold red]"
                    margin_str = f"[bold red]Needs {m['recovery_needed']} classes[/bold red]"
                    pct_style = "bold red"

                table.add_row(
                    r["course_name"],
                    str(r["attended"]),
                    str(r["total_sessions"]),
                    f"[{pct_style}]{pct}%[/{pct_style}]",
                    status_str,
                    margin_str,
                )

            console.print(table)
            console.print(
                f"\n[bold]Overall Aggregate Attendance:[/bold] {total_attended}/{total_sessions} ({overall_pct}%)\n"
            )
            return 0
    except CapabilityError as e:
        err_console.print(f"[red]Attendance unavailable:[/red] {e}")
        return 1
    except Exception as e:
        err_console.print(f"[red]Error fetching attendance:[/red] {e}")
        return 1


def cmd_search(args: argparse.Namespace) -> int:
    """Search locally indexed course resources and documents."""
    results = search_index(
        query=args.query,
        course_id=args.course,
        limit=args.limit,
    )
    if not results:
        scope = f" in course {args.course}" if args.course else ""
        console.print(f"No matching documents found for '{args.query}'{scope}.")
        console.print("Tip: Run [bold]open-moodle sync <course_id>[/bold] to index course materials first.")
        return 0

    table = Table(title=f"Search Results: '{args.query}'")
    table.add_column("Course", style="dim")
    table.add_column("File & Location", style="bold")
    table.add_column("Snippet")

    for r in results:
        clean_snippet = strip_html(r["snippet"].replace("<b>", "[bold yellow]").replace("</b>", "[/bold yellow]"))
        table.add_row(
            r["course_name"],
            f"{r['filename']}\n({r['page_or_chunk']})",
            clean_snippet,
        )

    console.print(table)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """Download and build local full-text search index for a course."""
    try:
        url, token = _resolve_creds(args)
        with MoodleClient(url, token) as client:
            console.print(f"Indexing course materials for Course ID {args.course}...")
            res = index_course_materials(client, course_id=args.course)
            console.print(f"[green]Successfully synced {res['course_name']}:[/green]")
            console.print(f"  - Newly indexed: {res['indexed']}")
            console.print(f"  - Already indexed: {res['skipped']}")
            if res["failed"] > 0:
                console.print(f"  - Failed / skipped: {res['failed']}")
            return 0
    except Exception as e:
        err_console.print(f"[red]Sync failed:[/red] {e}")
        return 1


def cmd_download(args: argparse.Namespace) -> int:
    """Bulk download all resource files from a course into structured folders."""
    try:
        url, token = _resolve_creds(args)
        dest = Path(args.dest) if args.dest else Path(f"./course_{args.course}_materials")
        with MoodleClient(url, token) as client:
            console.print(f"Downloading course {args.course} into [bold]{dest}[/bold]...")

            def on_progress(fn: str, cur: int, total: int, status: str):
                if status == "done":
                    console.print(f"  [{cur}/{total}] [green]Downloaded[/green] {fn}")
                elif status == "skipped":
                    console.print(f"  [{cur}/{total}] [dim]Skipped (exists)[/dim] {fn}")
                elif status == "failed":
                    console.print(f"  [{cur}/{total}] [red]Failed[/red] {fn}")

            stats = download_course_materials(
                client,
                course_id=args.course,
                dest_dir=dest,
                progress_callback=on_progress,
            )
            mb = round(stats["total_bytes"] / (1024 * 1024), 2)
            console.print(
                f"\n[green]Download complete:[/green] {stats['downloaded']} downloaded ({mb} MB), "
                f"{stats['skipped']} skipped, {stats['failed']} failed."
            )
            return 0
    except Exception as e:
        err_console.print(f"[red]Download failed:[/red] {e}")
        return 1


def cmd_mcp(args: argparse.Namespace) -> int:
    """Run the Model Context Protocol (MCP) server over stdio."""
    run_stdio(url_override=getattr(args, "url", None), token_override=getattr(args, "token", None))
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    """Main CLI entrypoint."""
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("--url", default=argparse.SUPPRESS, help="Moodle server URL or server.php endpoint")
    common_parser.add_argument("--token", default=argparse.SUPPRESS, help="Moodle web service token")

    parser = argparse.ArgumentParser(
        prog="open-moodle",
        description="Moodle client and Model Context Protocol (MCP) server.",
        parents=[common_parser],
    )
    parser.add_argument("--version", action="version", version=f"open-moodle {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    # mcp
    subparsers.add_parser("mcp", help="Run the MCP server over standard input/output", parents=[common_parser])

    # login
    p_login = subparsers.add_parser("login", help="Authenticate with Moodle and save token locally", parents=[common_parser])
    p_login.add_argument("-u", "--username", help="Student ID or username")
    p_login.add_argument("--sso", action="store_true", help="Authenticate interactively via browser SSO flow")

    # whoami
    subparsers.add_parser("whoami", help="Check connection and print student profile", parents=[common_parser])

    # courses
    subparsers.add_parser("courses", help="List enrolled courses", parents=[common_parser])

    # attendance
    p_att = subparsers.add_parser("attendance", help="Show course attendance and safe bunk / recovery analysis", parents=[common_parser])
    p_att.add_argument("-t", "--threshold", type=float, default=75.0, help="Target attendance percentage threshold (default: 75.0)")

    # deadlines
    p_deadlines = subparsers.add_parser("deadlines", help="Show upcoming deadlines and calendar events", parents=[common_parser])
    p_deadlines.add_argument("-d", "--days", type=int, default=30, help="Days to look ahead (default: 30)")

    # announcements
    p_ann = subparsers.add_parser("announcements", help="Show course forum announcements", parents=[common_parser])
    p_ann.add_argument("course", type=int, help="Numeric Course ID")
    p_ann.add_argument("-n", "--limit", type=int, default=10, help="Number of announcements to fetch")

    # notifications
    p_notifs = subparsers.add_parser("notifications", help="Show recent system alerts", parents=[common_parser])
    p_notifs.add_argument("-n", "--limit", type=int, default=15, help="Number of items to fetch (default: 15)")

    # grades
    p_grades = subparsers.add_parser("grades", help="Show grade items and marks", parents=[common_parser])
    p_grades.add_argument("-c", "--course", type=int, default=0, help="Filter by course ID (default: 0 for all)")

    # brief
    p_brief = subparsers.add_parser("brief", help="Get a consolidated student briefing", parents=[common_parser])
    p_brief.add_argument("-d", "--days", type=int, default=7, help="Days to look ahead (default: 7)")

    # read
    p_read = subparsers.add_parser("read", help="Download and extract text from a course resource URL", parents=[common_parser])
    p_read.add_argument("file_url", help="Download URL of the resource")
    p_read.add_argument("-s", "--start", type=int, default=1, help="Starting page or slide (1-indexed)")
    p_read.add_argument("-p", "--pages", type=int, default=20, help="Maximum pages/slides to parse (default: 20)")

    # sync
    p_sync = subparsers.add_parser("sync", help="Index course materials into local text search index", parents=[common_parser])
    p_sync.add_argument("course", type=int, help="Numeric Course ID to sync")

    # search
    p_search = subparsers.add_parser("search", help="Search course documents and slides locally", parents=[common_parser])
    p_search.add_argument("query", help="Search query string")
    p_search.add_argument("-c", "--course", type=int, help="Filter search to specific course ID")
    p_search.add_argument("-n", "--limit", type=int, default=5, help="Maximum snippets to return (default: 5)")

    # download
    p_dl = subparsers.add_parser("download", help="Bulk download course resources into structured folders", parents=[common_parser])
    p_dl.add_argument("course", type=int, help="Numeric Course ID to download")
    p_dl.add_argument("-d", "--dest", help="Destination folder (default: ./course_<ID>_materials)")

    args = parser.parse_args(argv)

    if not args.command:
        # If running in a pipeline or redirected stdin (non-tty), default to MCP server mode
        if not sys.stdin.isatty():
            return cmd_mcp(args)
        parser.print_help()
        return 0

    commands = {
        "mcp": cmd_mcp,
        "login": cmd_login,
        "whoami": cmd_whoami,
        "courses": cmd_courses,
        "deadlines": cmd_deadlines,
        "announcements": cmd_announcements,
        "notifications": cmd_notifications,
        "grades": cmd_grades,
        "brief": cmd_brief,
        "read": cmd_read,
        "attendance": cmd_attendance,
        "sync": cmd_sync,
        "search": cmd_search,
        "download": cmd_download,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
