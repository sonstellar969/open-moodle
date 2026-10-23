# Client Configuration Guide

This document provides setup instructions for connecting `open-moodle` as an MCP server to various AI tools and coding environments.

---

## 1. Antigravity CLI (`agy`)

Add the server to your Antigravity configuration using `agy mcp add`:

```bash
agy mcp add \
  --env MOODLE_URL="https://lms.university.edu/webservice/rest/server.php" \
  --env MOODLE_TOKEN="YOUR_MOODLE_TOKEN" \
  moodle uvx open-moodle mcp
```

Flags must precede the server name (`moodle`).

To verify registration:

```bash
agy mcp list
```

---

## 2. Claude Desktop

Locate your Claude Desktop configuration file:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

Add `open-moodle` under the `mcpServers` object:

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

Restart Claude Desktop after updating this file.

---

## 3. Cursor

Cursor supports MCP servers through its graphical settings or workspace configuration:

1. Open **Cursor Settings** -> **Features** -> **MCP**.
2. Click **+ Add New MCP Server**.
3. Set the following values:
   - **Name**: `moodle`
   - **Type**: `command`
   - **Command**: `uvx open-moodle mcp`
   - **Environment Variables**:
     - `MOODLE_URL` = `https://lms.university.edu/webservice/rest/server.php`
     - `MOODLE_TOKEN` = `YOUR_MOODLE_TOKEN`

Alternatively, add it to your project's `.cursor/mcp.json`:

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

---

## 4. Claude Code

Run the following command in your terminal:

```bash
claude mcp add moodle -- uvx open-moodle mcp
```

Ensure `MOODLE_URL` and `MOODLE_TOKEN` are exported in your current shell or stored via `open-moodle login`.

---

## 5. Windsurf and Zed

For editors supporting standard stdio MCP servers:

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
