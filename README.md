# open-moodle

A client and Model Context Protocol (MCP) server for Moodle. It allows AI coding assistants and terminal users to inspect courses, read course materials, track deadlines, and view announcements directly through Moodle's REST API.

---

## The Problem

Most tools that connect AI models to Moodle encounter two practical obstacles:

1. **Restricted Token Pages**: Universities often disable `/user/managetoken.php`, preventing students from creating API keys through the web interface.
2. **Missing Document Parsing**: Existing tools return file URLs instead of reading their contents. Because external AI models cannot access authenticated university networks, they cannot read syllabi, lecture slides, or assignment briefs.

`open-moodle` addresses both problems:
- It includes a login helper that obtains active tokens through the standard Moodle mobile authentication endpoint.
- It downloads and converts PDFs, Word documents, PowerPoint presentations, and code files into plain text before passing them to the AI model.

---

## Features

- **Model Context Protocol Server**: Compatible with Antigravity, Claude Desktop, Cursor, and other MCP clients over standard I/O.
- **In-Memory Document Extraction**: Converts PDFs (via PyMuPDF), Word `.docx` files, and `.pptx` slide decks directly into text without external dependencies like LibreOffice.
- **Terminal CLI**: Quick terminal commands to check courses, deadlines, announcements, and download materials without opening a browser.
- **Credential Storage**: Saves credentials locally in `~/.config/open-moodle/config.json` with restricted user-only permissions (`0600`).
- **Flexible Environment Support**: Works with `uvx` for zero-install execution or standard `pip`/`pipx` installations.

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

You will be prompted for your Moodle site URL, student username, and password. The tool queries `/login/token.php` for a mobile web service token and stores it locally.

If you already have a token:

```bash
open-moodle login --url "https://lms.university.edu" --token "YOUR_TOKEN"
```

For detailed troubleshooting on university setups, SSO, or proxying, read the [Authentication Guide](docs/authentication.md).

---

## MCP Server Setup

To connect `open-moodle` to your AI assistant, configure it as an MCP server.

### Antigravity CLI (`agy`)

```bash
agy mcp add \
  --env MOODLE_URL="https://lms.university.edu/webservice/rest/server.php" \
  --env MOODLE_TOKEN="YOUR_MOODLE_TOKEN" \
  moodle uvx open-moodle mcp
```

### Claude Desktop

Add this block to your `claude_desktop_config.json`:

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

Add to your project's `.cursor/mcp.json` or configure in Cursor Settings -> Features -> MCP:

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

For full instructions covering Claude Code, Windsurf, and Zed, see the [Client Setup Guide](docs/client-setup.md).

---

## MCP Tools Provided

| Tool | Purpose |
|------|---------|
| `moodle_whoami` | Checks connection and returns student profile metadata. |
| `moodle_list_courses` | Returns enrolled courses with IDs and names. |
| `moodle_get_course_contents` | Lists sections, modules, and resources for a course ID. |
| `moodle_read_resource` | Downloads and parses a PDF, DOCX, PPTX, or text file into text. |
| `moodle_upcoming_deadlines` | Returns scheduled quizzes, assignments, and calendar events. |
| `moodle_notifications` | Fetches announcements and system alerts. |
| `moodle_get_assignments` | Returns assignment descriptions, submission status, and deadlines. |

---

## CLI Usage

### Check account status

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

### View recent announcements

```bash
open-moodle notifications --limit 10
```

### Read a course file directly in terminal

```bash
open-moodle read "https://lms.university.edu/webservice/pluginfile.php/5639/mod_resource/content/1/syllabus.pdf"
```

---

## Documentation

- [Authentication & Token Guide](docs/authentication.md): How to get a token when `/user/managetoken.php` is disabled.
- [Client Setup Guide](docs/client-setup.md): Config examples for Antigravity, Claude, Cursor, and others.
- [Moodle API Reference](docs/moodle-api.md): Standard REST web service functions used under the hood.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
