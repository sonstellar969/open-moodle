# open-moodle

A client and Model Context Protocol (MCP) server for Moodle. It enables AI coding assistants and terminal users to inspect courses, read materials, track deadlines, search lecture slides, analyze attendance thresholds, and view announcements directly through Moodle's REST API.

---

## The Problem

Connecting AI models to university Moodle portals usually fails due to practical design hurdles:

1. **Restricted Token Pages**: Universities routinely disable `/user/managetoken.php`, preventing students from generating API tokens through the web interface.
2. **Missing Document Parsing**: Most existing tools only return raw file URLs. External AI models cannot open links behind authenticated intranets, preventing them from reading syllabi, lecture slides, or assignment briefs.
3. **Context Window Blowups**: Downloading multi-megabyte PDFs and slide decks into conversational contexts stalls requests and burns tokens.
4. **Silent Error Swallowing**: Generic wrappers often catch API exceptions and return empty lists, misleading the assistant into claiming you have no courses, deadlines, or assignments when an API function is merely disabled.
5. **Token Leakage**: Moodle attaches secret tokens to download links in API responses. Without explicit sanitization, those tokens leak into chat transcripts, system logs, and model context windows.

`open-moodle` addresses these issues directly:
- Obtains active tokens via the Moodle mobile authentication endpoint or browser-assisted SSO launch flow.
- Indexes course documents locally into an embedded SQLite FTS5 full-text search engine for sub-second keyword lookups without re-downloading files into model context.
- Streams and extracts text from PDFs (via PyMuPDF), Word documents (`.docx`), and PowerPoint presentations (`.pptx`) with strict size limits and page windowing.
- Strips tokens from all output URLs before returning data to the model.
- Checks whitelisted capabilities and reports informative messages if a university disables a specific endpoint.

---

## Features

- **Model Context Protocol Server**: Compatible with Antigravity (`agy`), Claude Desktop, Cursor, Grok, and Zed over standard input/output (stdio).
- **Attendance & Threshold Analytics**: Calculates per-course attendance percentages, safe bunks remaining while staying above a target cutoff (e.g., 75%), or consecutive classes needed to recover from below the threshold.
- **Zero-Dependency Local Search**: Embedded SQLite FTS5 index allows sub-second keyword search across course PDFs, slides, and docs with BM25 snippet ranking without external vector databases.
- **Bulk Course Downloader**: Downloads course files organized into topic directories, skipping unmodified files automatically.
- **In-Memory Document Extraction**: Converts PDFs, Word `.docx`, and PowerPoint `.pptx` slide decks directly into text without external system dependencies like LibreOffice.
- **Bounded Downloads**: Caps file transfers at 25MB and supports windowed reading (`start_page` and `max_pages`) to protect context windows.
- **Assignment Submission Status**: Checks whether you turned in each assignment (`submitted`, `draft`, `new`) alongside due dates and grading states.
- **Course Announcements & Briefing**: Pulls genuine instructor posts from course news forums, and offers a single-call `moodle_brief` tool summarizing deadlines, attendance alerts, notifications, and active courses.
- **Interactive Browser SSO**: One-command browser login flow for campus SSO portals (Microsoft 365, Google Workspace, SAML).
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

`open-moodle` resolves credentials using the following precedence:
1. Command-line flags (`--url`, `--token`)
2. Environment variables (`MOODLE_URL`, `MOODLE_TOKEN`)
3. Local configuration file (`~/.config/open-moodle/config.json`)

### Interactive Password Login

```bash
open-moodle login
```

Prompts for your Moodle site URL, student username, and password. The tool queries `/login/token.php` for a mobile web service token and stores it locally with user-only permissions (`0600`).

### Campus SSO Login (Microsoft / Google)

If your institution uses Single Sign-On (SSO):

```bash
open-moodle login --sso
```

This launches your default browser to Moodle's mobile launch endpoint, starts a temporary local listener, captures the token redirect, and saves it automatically.

### Direct Token Configuration

If you already have a token:

```bash
open-moodle login --url "https://lms.university.edu" --token "YOUR_TOKEN"
```

For detailed guidance, read the [Authentication Guide](docs/authentication.md).

---

## MCP Server Setup

Configure `open-moodle` in your preferred AI assistant.

### Antigravity CLI (`agy`)

```bash
agy mcp add moodle uvx open-moodle mcp
```

*(If credentials are saved via `open-moodle login`, they are loaded automatically. Otherwise, pass `--env MOODLE_URL=... --env MOODLE_TOKEN=...`.)*

### Claude Desktop & Grok

Add this block to your MCP configuration file (`claude_desktop_config.json`):

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

Add to your project's `.cursor/mcp.json` or configure under **Cursor Settings -> Features -> MCP**:

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

The server exposes 13 tools:

| Tool | Parameters | Purpose |
|------|------------|---------|
| `moodle_brief` | `days: int = 7` | Consolidated student briefing: enrolled courses, attendance alerts, deadlines, and notifications. |
| `moodle_get_attendance` | `threshold: float = 75.0` | Fetches course attendance with percentage and safe bunks / recovery targets. |
| `moodle_search` | `query: str, course_id: int?, limit: int = 5` | Sub-second full-text BM25 search across indexed course slides, PDFs, and notes. |
| `moodle_sync_course` | `course_id: int` | Indexes all text materials for a course into local SQLite FTS5 database. |
| `moodle_whoami` | None | Checks connection and returns student profile metadata and allowed API count. |
| `moodle_list_courses` | None | Returns enrolled courses with numeric IDs, full titles, and short codes. |
| `moodle_get_course_contents` | `course_id: int` | Outlines syllabus sections, modules, and resources (with sanitized URLs). |
| `moodle_read_resource` | `file_url: str, start_page: int = 1, max_pages: int = 20` | Downloads and parses a PDF, DOCX, PPTX, or text file with page range support. |
| `moodle_upcoming_deadlines` | `days_ahead: int = 30` | Returns scheduled quizzes, assignments, and calendar events. |
| `moodle_get_assignments` | `course_ids: list[int]?` | Lists assignments, due dates, submission states (`Submitted`, `Draft`), and grading status. |
| `moodle_get_announcements` | `course_id: int, limit: int = 10` | Fetches instructor announcements and posts from the course Announcements forum. |
| `moodle_get_grades` | `course_id: int = 0` | Pulls grade items, marks, percentages, and teacher feedback. |
| `moodle_notifications` | `limit: int = 15` | Fetches recent system bell alerts and personal notices. |

---

## CLI Usage

### Attendance & Safe Bunk Analytics

Calculate safe bunks or sessions needed to reach target percentage:

```bash
open-moodle attendance --threshold 75.0
```

### Search Course Materials Locally

Index files once, then query without burning context window tokens:

```bash
# 1. Index course materials into SQLite FTS5
open-moodle sync 201

# 2. Search for topics across all slides and documents
open-moodle search "virtual memory" --course 201 --limit 5
```

### Bulk Download Course Materials

Download all documents and slides organized by syllabus topic:

```bash
open-moodle download 201 --dest ./OS-Materials
```

### Student Briefing

```bash
open-moodle brief --days 7
```

### Account Metadata

```bash
open-moodle whoami
```

### Course List

```bash
open-moodle courses
```

### Deadlines & Calendar

```bash
open-moodle deadlines --days 14
```

### Course Forum Announcements

```bash
open-moodle announcements 201 --limit 5
```

### Grades & Feedback

```bash
open-moodle grades --course 201
```

### Read a Remote File in Terminal

```bash
open-moodle read "https://lms.university.edu/webservice/pluginfile.php/5639/mod_resource/content/1/syllabus.pdf" --start 1 --pages 10
```

---

## Architecture & Storage

- **Configuration**: Credentials are saved to `~/.config/open-moodle/config.json` with restricted `0600` permissions.
- **Search Index**: Embedded SQLite FTS5 database stored at `~/.cache/open-moodle/search_index.db` (configurable with `OPEN_MOODLE_CACHE_DIR`).
- **Read-Only**: The tool strictly consumes data; it does not submit assignments, modify grades, or alter forum discussions.

---

## Documentation

- [Authentication & Token Guide](docs/authentication.md): Mobile token acquisition, SSO launch flow, and troubleshooting.
- [Client Setup Guide](docs/client-setup.md): Config examples for Antigravity, Claude, Cursor, Grok, and others.
- [Moodle API Reference](docs/moodle-api.md): Standard REST web service functions used under the hood.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
