# open-moodle

A client and Model Context Protocol (MCP) server for Moodle. It allows AI coding assistants and terminal users to inspect courses, read course materials, track deadlines, check submission status, and view announcements directly through Moodle's REST API.

---

## The Problem

Connecting AI models to university Moodle portals usually fails due to practical design hurdles:

1. **Restricted Token Pages**: Universities routinely disable `/user/managetoken.php`, preventing students from generating API tokens through the web interface.
2. **Missing Document Parsing**: Most existing tools only return raw file URLs. External AI models cannot open links behind authenticated intranets, so they cannot read syllabi, lecture slides, or assignment briefs.
3. **Silent Error Swallowing**: Generic wrappers often catch API exceptions and return empty lists, misleading the assistant into claiming you have no courses, deadlines, or assignments when an API function is merely disabled.
4. **Token Leakage**: Moodle attaches secret tokens to download links in API responses. Without explicit sanitization, those tokens leak into chat transcripts, system logs, and model context windows.

`open-moodle` addresses these issues directly:
- Obtains active tokens via the Moodle mobile authentication endpoint or browser SSO launch flow.
- Streams and extracts text from PDFs (via PyMuPDF), Word documents (`.docx`), and PowerPoint presentations (`.pptx`) with strict size limits and page windowing.
- Strips tokens from all output URLs before returning data to the model.
- Checks whitelisted capabilities and reports informative messages if a university disables a specific endpoint.

---

## Features

- **Model Context Protocol Server**: Compatible with Antigravity, Claude Desktop, Cursor, and Grok over standard I/O (stdio).
- **Attendance & Threshold Analytics**: Tracks attendance records across courses with automated 75% target threshold calculation (safe bunks allowed vs consecutive sessions needed to recover).
- **Zero-Dependency Local Search**: Embedded SQLite FTS5 index allows sub-second keyword search across course PDFs, slides, and docs with BM25 snippet ranking.
- **Bulk Course Downloader**: Downloads course files organized into topic directories, skipping unmodified files automatically.
- **In-Memory Document Extraction**: Converts PDFs, Word `.docx`, and PowerPoint `.pptx` slide decks directly into text without external system dependencies like LibreOffice.
- **Bounded Downloads**: Caps file transfers at 25MB and supports windowed reading (`start_page` and `max_pages`) to protect context windows.
- **Assignment Submission Status**: Checks whether you turned in each assignment (`submitted`, `draft`, `new`) alongside due dates and grading states.
- **Course Announcements & Briefing**: Pulls genuine instructor posts from course news forums, and offers a single-call `moodle_brief` tool summarizing deadlines, attendance alerts, notifications, and active courses.
- **Terminal CLI**: Run commands like `open-moodle attendance`, `open-moodle search`, `open-moodle download`, or `open-moodle brief` directly in your shell.
- **Zero-Install Execution**: Works instantly with `uvx open-moodle` or via standard `pip`/`pipx`.

---

## Installation

### Using uv (Recommended)

Run directly without manual installation:

```bash
uvx open-moodle --help
```

### Using pip

```bash
pip install open-moodle
```

---

## Authentication

Run the interactive login command:

```bash
open-moodle login
```

You will be prompted for your Moodle site URL, student username, and password. The tool queries `/login/token.php` for a mobile web service token and stores it locally in `~/.config/open-moodle/config.json` with user-only permissions (`0600`).

If you already have a token or use campus SSO:

```bash
open-moodle login --url "https://lms.university.edu" --token "YOUR_TOKEN"
```

For detailed guidance on campus SSO (Microsoft 365, Google Workspace) or mobile app token extraction, read the [Authentication Guide](docs/authentication.md).

---

## MCP Server Setup

Configure `open-moodle` in your preferred AI client.

### Antigravity CLI (`agy`)

```bash
agy mcp add \
  --env MOODLE_URL="https://lms.university.edu/webservice/rest/server.php" \
  --env MOODLE_TOKEN="YOUR_MOODLE_TOKEN" \
  moodle uvx open-moodle mcp
```

### Claude Desktop & Grok

Add this block to your MCP configuration file:

```json
{
  "mcpServers": {
    "moodle": {
      "command": "uvx",
      "args": ["open-moodle", "mcp"],
      "env": {
        "MOODLE_URL": "https://lms.university.edu/webservice/rest/server.php",
        "MOODLE_TOKEN": "YOUR_MOODLE_TOKEN"
      }
    }
  }
}
```

### Cursor

Add to your project's `.cursor/mcp.json` or configure under Cursor Settings -> Features -> MCP:

```json
{
  "mcpServers": {
    "moodle": {
      "command": "uvx",
      "args": ["open-moodle", "mcp"],
      "env": {
        "MOODLE_URL": "https://lms.university.edu/webservice/rest/server.php",
        "MOODLE_TOKEN": "YOUR_MOODLE_TOKEN"
      }
    }
  }
}
```

See the [Client Setup Guide](docs/client-setup.md) for full instructions covering Claude Code, Windsurf, and Zed.

---

## MCP Tools Provided

| Tool | Purpose |
|------|---------|
| `moodle_brief` | Consolidated student briefing: enrolled courses, attendance alerts, deadlines, and notifications. |
| `moodle_get_attendance` | Fetches course attendance with percentage and safe bunks / recovery targets for target thresholds. |
| `moodle_search` | Sub-second full-text BM25 search across indexed course slides, PDFs, and notes. |
| `moodle_sync_course` | Indexes all text materials for a course into local SQLite FTS5 database. |
| `moodle_whoami` | Checks connection and returns student profile metadata and allowed API count. |
| `moodle_list_courses` | Returns enrolled courses with numeric IDs, full titles, and short codes. |
| `moodle_get_course_contents` | Outlines syllabus sections, modules, and resources (with sanitized URLs). |
| `moodle_read_resource` | Downloads and parses a PDF, DOCX, PPTX, or text file with page range support. |
| `moodle_upcoming_deadlines` | Returns scheduled quizzes, assignments, and calendar events. |
| `moodle_get_assignments` | Lists assignments, due dates, submission states (`Submitted`, `Draft`), and grading status. |
| `moodle_get_announcements` | Fetches instructor announcements and posts from the course Announcements forum. |
| `moodle_get_grades` | Pulls grade items, marks, percentages, and teacher feedback. |
| `moodle_notifications` | Fetches recent system bell alerts and personal notices. |

---

## CLI Usage

### Check attendance and safe bunks (75% threshold)

```bash
open-moodle attendance --threshold 75.0
```

### Search course notes and slides locally

```bash
# Index course materials first
open-moodle sync 201

# Fast BM25 keyword search across all indexed documents
open-moodle search "virtual memory" --course 201
```

### Bulk download course materials

```bash
open-moodle download 201 --dest ./OS-Materials
```

### Get a quick student briefing

```bash
open-moodle brief --days 7
```

### Check account status and whitelisted APIs

```bash
open-moodle whoami
```

### List enrolled courses

```bash
open-moodle courses
```

### View upcoming deadlines

```bash
open-moodle deadlines --days 14
```

### View instructor announcements for a course

```bash
open-moodle announcements 201 --limit 5
```

### Check grades

```bash
open-moodle grades --course 201
```

### Read a course file directly in terminal

```bash
open-moodle read "https://lms.university.edu/webservice/pluginfile.php/5639/mod_resource/content/1/syllabus.pdf" --start 1 --pages 10
```

---

## Documentation

- [Authentication & Token Guide](docs/authentication.md): Mobile token acquisition, SSO launch flow, and troubleshooting.
- [Client Setup Guide](docs/client-setup.md): Config examples for Antigravity, Claude, Cursor, Grok, and others.
- [Moodle API Reference](docs/moodle-api.md): Standard REST web service functions used under the hood.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
