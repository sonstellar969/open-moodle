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
- Strips `token` and `wstoken` from course, calendar, notification, and search URLs, and from error text, before returning data to the model. File downloads are limited to this site's `pluginfile.php`.
- Checks whitelisted capabilities and reports informative messages if a university disables a specific endpoint.

---

## Features

- **Model Context Protocol Server**: Compatible with Antigravity (`agy`), Claude Desktop, Cursor, Grok, and Zed over standard input/output (stdio).
- **Attendance from the gradebook**: Reads grade items named attendance and compares them with your cutoff. Safe-bunk and recovery math runs only when real session counts are present. Student tokens cannot read the attendance plugin's session register.
- **Local full-text search**: Embedded SQLite FTS5 index gives sub-second BM25 keyword search across course PDFs, slides, and docs. No separate search server. Indexing stores every page, not a 20-page window.
- **Bulk Course Downloader**: Downloads course files organized into topic directories, skipping unmodified files automatically.
- **In-Memory Document Extraction**: Converts PDFs, Word `.docx`, and PowerPoint `.pptx` slide decks directly into text without external system dependencies like LibreOffice.
- **Bounded Downloads**: Caps file transfers at 25MB and supports windowed reading (`start_page` and `max_pages`) to protect context windows.
- **Assignment Submission Status**: Checks whether you turned in each assignment (`submitted`, `draft`, `new`) alongside due dates and grading states.
- **Course Announcements & Briefing**: Pulls genuine instructor posts from course news forums, and offers a single-call `moodle_brief` tool summarizing deadlines, attendance alerts, notifications, and active courses.
- **Interactive Browser SSO**: Opens Moodle's mobile launch page and captures `openmoodle://token=...` after checking the passport. A temporary URL handler is registered on macOS, Linux, and Windows; you can also paste the link.
- **Terminal CLI**: Run commands like `open-moodle attendance`, `open-moodle search`, `open-moodle download`, or `open-moodle brief` directly in your shell.
- **Zero-Install Execution**: Works instantly with `uvx open-moodle` or via standard `pip`/`pipx`.

---

## Installation

### From GitHub (Recommended)

Run or install directly from the repository using `uv` or `pip`:

```bash
# Run directly without installing (via uvx)
uvx --from git+https://github.com/sonstellar969/open-moodle.git open-moodle --help

# Or install globally into your PATH
uv tool install git+https://github.com/sonstellar969/open-moodle.git

# Or via pip
pip install git+https://github.com/sonstellar969/open-moodle.git
```

### Local Development / From Source

```bash
git clone https://github.com/sonstellar969/open-moodle.git
cd open-moodle
uv tool install --editable .
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

If installed globally via `uv tool install`:

```bash
agy mcp add moodle open-moodle mcp
```

Or directly from GitHub without installing:

```bash
agy mcp add moodle uvx --from git+https://github.com/sonstellar969/open-moodle.git open-moodle mcp
```

*(If credentials are saved via `open-moodle login`, they are loaded automatically. Otherwise, pass `--env MOODLE_URL=... --env MOODLE_TOKEN=...`.)*

### Claude Desktop

Add this block to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "moodle": {
      "command": "open-moodle",
      "args": ["mcp"],
      "env": {
        "MOODLE_URL": "https://lms.university.edu/webservice/rest/server.php",
        "MOODLE_TOKEN": "YOUR_MOODLE_TOKEN"
      }
    }
  }
}
```

*(Or use `"command": "uvx"` with `"args": ["--from", "git+https://github.com/sonstellar969/open-moodle.git", "open-moodle", "mcp"]`)*

### Grok

Grok Build reads `~/.grok/config.toml`, not Claude's config file. If you already ran `open-moodle login`, the server picks up the saved token and you can omit the environment variables.

```bash
grok mcp add moodle -- open-moodle mcp
```

Or, in `~/.grok/config.toml`:

```toml
[mcp_servers.moodle]
command = "open-moodle"
args = ["mcp"]
```

### Cursor

Add to your project's `.cursor/mcp.json` or configure under **Cursor Settings -> Features -> MCP**:

```json
{
  "mcpServers": {
    "moodle": {
      "command": "open-moodle",
      "args": ["mcp"],
      "env": {
        "MOODLE_URL": "https://lms.university.edu/webservice/rest/server.php",
        "MOODLE_TOKEN": "YOUR_MOODLE_TOKEN"
      }
    }
  }
}
```

### Local & Open-Source Models (LM Studio, Continue.dev, Ollama, LibreChat)

You can run `open-moodle` with 100% local, open-source models (such as Qwen 2.5, Llama 3.1/3.3, and Mistral) to ensure your campus lecture notes, assignments, attendance, and grades remain strictly on your machine without cloud subscriptions.

#### Recommended Local Models for Tool Calling
- **Qwen 2.5** (`qwen2.5:7b` / `14b`): Best-in-class precision for function calling on consumer hardware.
- **Llama 3.1 / 3.3** (`llama3.1:8b` / `70b`): Strong general-purpose reasoning with native tool output.
- **Mistral Nemo** (`mistral-nemo:12b`): Robust function calling with large context support.

#### LM Studio Setup
1. Open **LM Studio** -> navigate to the **Developer / MCP** tab.
2. Add the server definition:
   ```json
   {
     "mcpServers": {
       "open-moodle": {
         "command": "open-moodle",
         "args": ["mcp"]
       }
     }
   }
   ```
3. Load a tool-compatible model (e.g., `qwen2.5-7b-instruct`) and ask: *"Check my attendance"* or *"Search my course notes for virtual memory"*.

#### Continue.dev (VS Code / JetBrains) Setup
Add `open-moodle` under `experimental.modelContextProtocolServers` in `~/.continue/config.json`:
```json
{
  "models": [
    {
      "title": "Ollama - Qwen 2.5 7B",
      "provider": "ollama",
      "model": "qwen2.5:7b"
    }
  ],
  "experimental": {
    "modelContextProtocolServers": [
      {
        "transport": {
          "type": "stdio",
          "command": "open-moodle",
          "args": ["mcp"]
        }
      }
    ]
  }
}
```

#### LibreChat Setup
In your `librechat.yaml`:
```yaml
mcpServers:
  open-moodle:
    type: stdio
    command: open-moodle
    args:
      - mcp
```

For advanced usage, Goose CLI agent setup, and custom Python scripts with Ollama, see the [Local Models Guide](docs/local-models.md).

See the [Client Setup Guide](docs/client-setup.md) for instructions covering Claude Code, Windsurf, and Zed.

---

## MCP Tools Provided

The server exposes 14 tools:

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
| `moodle_get_assignments` | `course_id: int = 0` | Lists assignments, due dates, submission states (`Submitted`, `Draft`), and grading status. `0` means every course. |
| `moodle_get_announcements` | `course_id: int, limit: int = 10` | Fetches instructor announcements and posts from the course Announcements forum. |
| `moodle_get_grades` | `course_id: int = 0` | Pulls grade items, marks, percentages, and teacher feedback. |
| `moodle_notifications` | `limit: int = 15` | Fetches recent system bell alerts and personal notices. |
| `moodle_doctor` | None | Lists which web service functions this token can call, and which features those functions unlock. |

---

## CLI Commands Reference

All commands accept global flags `--url <URL>` and `--token <TOKEN>` to override saved credentials or environment variables on the fly.

### Command Overview

| Command | Arguments & Flags | Description |
|---------|-------------------|-------------|
| `login` | `[-u USER] [--sso] [--token TOK]` | Authenticates with Moodle and stores credentials in `~/.config/open-moodle/config.json`. |
| `whoami` | None | Displays authenticated student name, user ID, university site, Moodle version, and whitelisted APIs. |
| `courses` | None | Lists all enrolled courses with numeric course IDs, short codes, and full course names. |
| `attendance` | `[-t, --threshold 75.0]` | Displays per-course attendance records with safe bunks allowed or classes needed to hit target percentage. |
| `brief` | `[-d, --days 7]` | Consolidated student dashboard: active courses, attendance alerts, upcoming deadlines, and unread alerts. |
| `deadlines` | `[-d, --days 30]` | Lists upcoming actionable calendar deadlines, pending assignment submissions, and quizzes. |
| `announcements` | `<course_id> [-n, --limit 10]` | Fetches genuine instructor posts and discussion topics from the course Announcements forum. |
| `notifications` | `[-n, --limit 15]` | Displays recent personal system bell notifications with read/unread statuses. |
| `grades` | `[-c, --course 0]` | Pulls student grade items, marks, display percentages, grade ranges, and instructor feedback. |
| `sync` | `<course_id>` | Downloads and indexes course slides, PDFs, Word docs, and notes into local SQLite FTS5 database. |
| `search` | `<query> [-c COURSE] [-n 5]` | Sub-millisecond BM25 keyword search across locally indexed course slides and notes with excerpts. |
| `download` | `<course_id> [-d, --dest PATH]` | Bulk downloads all course files into topic folders, automatically skipping unmodified files. |
| `read` | `<file_url> [-s 1] [-p 20]` | Downloads and extracts readable text directly from a remote file URL with page windowing. |
| `doctor` | None | Shows which Moodle web services this token can call. |
| `mcp` | None | Runs the Model Context Protocol (MCP) server over standard input/output (stdio) for AI assistants. |

---

### Detailed Command Guide

#### 1. `open-moodle login`
Authenticates with your university's Moodle portal.

- **Password login**: prompts for URL, student ID, and password, acquiring a token from `/login/token.php`:
  ```bash
  open-moodle login
  ```
- **Campus SSO login**: opens Moodle's mobile launch page (`urlscheme=openmoodle`). Moodle redirects to `openmoodle://token=<base64>`. The payload is `md5(wwwroot + passport):::token`, and a mismatch is rejected. Paste the link if the temporary URL handler does not catch it:
  ```bash
  open-moodle login --sso
  ```
- **Manual token**: save an existing token directly:
  ```bash
  open-moodle login --url "https://lms.university.edu" --token "YOUR_TOKEN"
  ```

#### 2. `open-moodle whoami`
Verifies connection and prints student profile metadata:
```bash
open-moodle whoami
```

`open-moodle doctor` prints the same connection plus a line for each feature (courses, calendar, grades, forums, attendance) and whether the required web service is enabled.

#### 3. `open-moodle courses`
Lists all courses you are enrolled in with their numeric Course IDs (needed for other commands):
```bash
open-moodle courses
```

#### 4. `open-moodle attendance`
Shows course attendance with target threshold analytics (default 75%):
```bash
# Check against standard 75% cutoff
open-moodle attendance

# Check against custom threshold (e.g., 80% or 85%)
open-moodle attendance --threshold 80.0
```
Most student tokens only receive a gradebook percentage. In that case the table shows the percentage and does not invent session counts or safe bunks.

When a record includes real `attended` and `total` session counts:

- For courses at or above the threshold: safe bunks remaining are $\lfloor \frac{\text{attended} - T \times \text{total}}{T} \rfloor$.
- For courses below the threshold: consecutive classes needed are $\lceil \frac{T \times \text{total} - \text{attended}}{1 - T} \rceil$.
- A 100% target cannot be recovered after a session has already been missed.

#### 5. `open-moodle brief`
Single-screen student briefing summarizing everything you need to know for the coming week:
```bash
open-moodle brief --days 7
```
Includes: active course count, attendance danger alerts (<75%), upcoming deadlines, and unread notifications.

#### 6. `open-moodle deadlines`
Lists actionable calendar events and deadlines:
```bash
open-moodle deadlines --days 14
```

#### 7. `open-moodle announcements`
Pulls actual instructor posts from the course Announcements forum (unlike bell notifications, which are generic):
```bash
open-moodle announcements 201 --limit 5
```

#### 8. `open-moodle notifications`
Lists system bell alerts and personal notices:
```bash
open-moodle notifications --limit 10
```

#### 9. `open-moodle grades`
Displays gradebook items, marks, ranges, and teacher feedback:
```bash
# View grades across all enrolled courses
open-moodle grades

# View grades for a specific course ID
open-moodle grades --course 201
```

#### 10. `open-moodle sync`
Downloads and indexes course materials into a local SQLite FTS5 database (`~/.cache/open-moodle/search_index.db`). Once indexed, you can search topics without re-downloading files:
```bash
open-moodle sync 201
```

#### 11. `open-moodle search`
Fast local keyword search across indexed PDFs, slides, and docs. Results include the page or slide and a token-free file URL:
```bash
# Search across all indexed courses
open-moodle search "virtual memory"

# Search within a specific course
open-moodle search "CPU scheduling" --course 201 --limit 5
```

#### 12. `open-moodle download`
Bulk downloads all materials for a course into topic folders (e.g., `01_Syllabus/`, `02_Process_Scheduling/`):
```bash
# Downloads into ./course_201_materials by default
open-moodle download 201

# Downloads into custom directory
open-moodle download 201 --dest ./OS-Notes
```

#### 13. `open-moodle read`
Downloads a remote Moodle file URL and extracts clean readable text in terminal:
```bash
open-moodle read "https://lms.university.edu/webservice/pluginfile.php/123/mod_resource/content/1/notes.pdf" --start 1 --pages 10
```

#### 14. `open-moodle doctor`
Prints which web services this token can call:

```bash
open-moodle doctor
```

#### 15. `open-moodle mcp`
Launches the Model Context Protocol (MCP) stdio server for AI assistants (Antigravity, Claude, Cursor, Grok, Zed):
```bash
open-moodle mcp
```

---

## Architecture & Storage

- **Configuration**: Credentials are saved to `~/.config/open-moodle/config.json`. The file is created with mode `0600`.
- **Search Index**: SQLite FTS5 database at `~/.cache/open-moodle/search_index.db` (or `OPEN_MOODLE_CACHE_DIR`), created with mode `0600`. Sync indexes every page of a PDF or slide deck. `.doc` and `.ppt` files are skipped. Re-sync drops files that disappeared from the course. Search hits include the page label and a URL with the token removed.
- **Downloads**: File fetches are limited to `pluginfile.php` on the configured Moodle host. A URL on any other host is refused, so a tool call cannot send your token elsewhere.
- **Read-only client**: The commands do not submit assignments, change grades, or post to forums. The saved value is still a `moodle_mobile_app` token, and that service can allow writes on some sites. Treat the config file like a password.

---

## Documentation

- [Local & Open-Source Models Guide](docs/local-models.md): Setup for Ollama, LM Studio, Continue.dev, Open WebUI, and LibreChat.
- [Authentication & Token Guide](docs/authentication.md): Mobile token acquisition, SSO launch flow, and troubleshooting.
- [Client Setup Guide](docs/client-setup.md): Config examples for Antigravity, Claude, Cursor, Grok, and others.
- [Moodle API Reference](docs/moodle-api.md): Standard REST web service functions used under the hood.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

Text extraction from PDFs uses PyMuPDF, which is licensed under AGPL-3.0. That license applies to PyMuPDF itself when you install the dependency.
