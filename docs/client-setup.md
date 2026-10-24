# Client Configuration Guide

This document provides setup instructions for connecting `open-moodle` as an MCP server to various AI tools, editors, and local model environments.

If you have already run `open-moodle login` on your local machine, credentials are saved in `~/.config/open-moodle/config.json`. In that case, you do not need to duplicate `MOODLE_URL` or `MOODLE_TOKEN` in the environment variables block unless running in an isolated container.

---

## 1. Antigravity CLI (`agy`)

If installed globally via `uv tool install`:

```bash
agy mcp add moodle open-moodle mcp
```

Or directly from GitHub:

```bash
agy mcp add \
  --env MOODLE_URL="https://lms.university.edu/webservice/rest/server.php" \
  --env MOODLE_TOKEN="YOUR_MOODLE_TOKEN" \
  moodle uvx --from git+https://github.com/sonstellar969/open-moodle.git open-moodle mcp
```

To verify registration:

```bash
agy mcp list
```

---

## 2. Claude Desktop & Grok

Locate your Claude Desktop configuration file:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

Add `open-moodle` under `mcpServers`:

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

*(If running without local installation, use `"command": "uvx"` with `"args": ["--from", "git+https://github.com/sonstellar969/open-moodle.git", "open-moodle", "mcp"]`)*.

---

## 3. Cursor

Cursor supports MCP servers through its graphical settings or workspace configuration:

1. Open **Cursor Settings** -> **Features** -> **MCP**.
2. Click **+ Add New MCP Server**.
3. Set the following values:
   - **Name**: `moodle`
   - **Type**: `command`
   - **Command**: `open-moodle mcp`

Alternatively, add it to your project's `.cursor/mcp.json`:

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

---

## 4. Claude Code

Run the following command in your terminal:

```bash
claude mcp add moodle -- open-moodle mcp
```

Or from GitHub without installing:

```bash
claude mcp add moodle -- uvx --from git+https://github.com/sonstellar969/open-moodle.git open-moodle mcp
```

---

## 5. Windsurf and Zed

For editors supporting standard stdio MCP servers:

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

---

## 6. Local & Open Models (LM Studio, Continue.dev, Ollama, LibreChat)

`open-moodle` can be run with 100% local, open-source language models (such as Qwen 2.5, Llama 3.1/3.3, and DeepSeek) without sending any campus data or credentials to cloud APIs.

For detailed step-by-step setup guides, recommended models, and configuration files for:
- **LM Studio**
- **Continue.dev (VS Code / JetBrains)**
- **Ollama + Open WebUI**
- **LibreChat**
- **Goose CLI Agent**
- **Custom Python scripts with Ollama**

See the dedicated [Local Models Guide](local-models.md).
