# Running open-moodle with Local & Open-Source Models

This guide explains how to connect `open-moodle` to open-source language models running locally via **Ollama**, **LM Studio**, **Continue.dev**, **Open WebUI**, **LibreChat**, and custom agent scripts.

Running `open-moodle` with local models gives you a completely private, offline-first academic assistant: your university syllabi, lecture slides, assignments, attendance, and grades never leave your machine.

---

## Recommended Local Models for Tool Calling

For reliable MCP tool execution, use models with dedicated function/tool calling support:

| Model | Size | Minimum VRAM / RAM | Recommended Use Case |
|-------|------|--------------------|----------------------|
| **Qwen 2.5** (`qwen2.5:7b` / `14b`) | 7B / 14B | 8 GB / 16 GB | **Best overall**. Exceptional tool-calling precision and concise responses. |
| **Llama 3.1** (`llama3.1:8b`) | 8B | 8 GB | Standard general-purpose model with robust structured output. |
| **Llama 3.3** (`llama3.3:70b`) | 70B | 48 GB (or quantized) | Near-frontier capability for complex reasoning and synthesis. |
| **Mistral Nemo** (`mistral-nemo:12b`) | 12B | 12 GB | Strong function calling with 128k context support. |
| **DeepSeek R1 (Distill Qwen)** | 8B / 14B | 8 GB / 16 GB | High-level reasoning before invoking tools. |

---

## 1. LM Studio

LM Studio supports MCP servers natively.

### Prerequisites
1. Install `open-moodle` globally:
   ```bash
   uv tool install git+https://github.com/sonstellar969/open-moodle.git
   # or from local clone:
   uv tool install --editable /path/to/open-moodle
   ```
2. Log in once to cache your university token:
   ```bash
   open-moodle login
   ```

### Setup in LM Studio
1. Open **LM Studio**.
2. Go to the **Developer / MCP** tab (or open `~/.cache/lm-studio/mcp_servers.json` / LM Studio settings).
3. Add the `open-moodle` server definition:

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

*(If `open-moodle` is not in your global system PATH, provide the absolute path: `/Users/<USERNAME>/.local/bin/open-moodle` or `/home/<USERNAME>/.local/bin/open-moodle`)*.

4. Load a tool-compatible model (e.g., `qwen2.5-7b-instruct` or `meta-llama-3.1-8b-instruct`).
5. Start chatting! You can ask:
   - *"What are my upcoming deadlines?"*
   - *"Check my attendance and tell me how many classes I can safely miss."*
   - *"Search my course notes for virtual memory."*

---

## 2. Continue.dev (VS Code & JetBrains)

[Continue](https://continue.dev) is an open-source AI extension that lets you use local models from Ollama or LM Studio inside VS Code or JetBrains with MCP support.

### Setup
1. Open your Continue configuration file:
   - **macOS/Linux**: `~/.continue/config.json`
   - **Windows**: `%USERPROFILE%\.continue\config.json`
2. Add `open-moodle` to the `experimental.modelContextProtocolServers` array:

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

3. Reload VS Code. The assistant can now call `moodle_brief`, `moodle_get_attendance`, and other tools while you code.

---

## 3. Ollama + Open WebUI

[Open WebUI](https://openwebui.com) is a popular local web frontend for Ollama.

### Setup
1. Ensure `open-moodle login` has been executed.
2. In Open WebUI, navigate to **Workspace** -> **Tools** -> **Install Tool / MCP**.
3. Point to the local stdio command:
   ```bash
   open-moodle mcp
   ```
4. Assign the toolset to your preferred Ollama model (such as `qwen2.5:7b` or `llama3.1:8b`).

---

## 4. LibreChat

[LibreChat](https://www.librechat.ai/) is an open-source ChatGPT-like web UI that natively supports local LLMs and MCP servers.

### Setup
In your `librechat.yaml` configuration file, add:

```yaml
mcpServers:
  open-moodle:
    type: stdio
    command: open-moodle
    args:
      - mcp
```

Restart LibreChat. Under the agent or tools menu, enable `open-moodle` to give local models access to Moodle.

---

## 5. Goose CLI Agent (Block / Square)

[Goose](https://block.github.io/goose/) is an open-source, on-machine CLI agent capable of using local Ollama models.

To add `open-moodle` to Goose:

```bash
goose configure
```

Choose **Add Extension**, select **Standard I/O**, and set:
- **Name**: `open-moodle`
- **Command**: `open-moodle`
- **Args**: `mcp`

Now run `goose session` with your local Ollama model to query your courses, grades, and attendance from the terminal.

---

## 6. Python Script (Ollama + open-moodle Direct API)

If you are building custom agents or automation scripts with local models, you can use `open_moodle` as a standard Python library directly with `ollama`:

```python
"""Example: Using local Ollama with open_moodle tools."""

import json
import ollama
from open_moodle.client import MoodleClient, calculate_attendance_metrics
from open_moodle.config import get_credentials

# 1. Resolve stored credentials
url, token = get_credentials()

# 2. Define tools for Ollama
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_attendance",
            "description": "Fetch course attendance and safe bunk / recovery analytics.",
            "parameters": {
                "type": "object",
                "properties": {
                    "threshold": {
                        "type": "number",
                        "description": "Target attendance cutoff percentage (default 75.0)",
                    }
                },
            },
        },
    }
]

# 3. Handle model tool calling
def handle_tool_call(name: str, arguments: dict):
    if name == "get_attendance":
        threshold = arguments.get("threshold", 75.0)
        with MoodleClient(url, token) as client:
            records = client.get_attendance()
            summary = []
            for r in records:
                m = calculate_attendance_metrics(r["attended"], r["total_sessions"], threshold)
                summary.append({
                    "course": r["course_name"],
                    "attended": r["attended"],
                    "total": r["total_sessions"],
                    "percentage": m["percentage"],
                    "status": m["status"],
                    "margin": m["safe_bunks"] if m["status"] == "OK" else -m["recovery_needed"],
                })
            return summary
    return {"error": "Unknown tool"}

# 4. Prompt local model
client = ollama.Client()
messages = [{"role": "user", "content": "How is my attendance doing in my courses?"}]

response = client.chat(
    model="qwen2.5:7b",
    messages=messages,
    tools=tools,
)

# 5. Execute if tool was invoked
if response.message.tool_calls:
    for call in response.message.tool_calls:
        tool_result = handle_tool_call(call.function.name, call.function.arguments)
        messages.append(response.message)
        messages.append({
            "role": "tool",
            "content": json.dumps(tool_result),
        })

    # Generate final answer from tool output
    final_response = client.chat(model="qwen2.5:7b", messages=messages)
    print(final_response.message.content)
else:
    print(response.message.content)
```

---

## Performance & Context Tips for Local Models

Smaller open models (7B–14B parameters) have tighter context limits and lower attention capacity over massive inputs than cloud models. Follow these guidelines for optimal results:

1. **Use `moodle_search` instead of downloading full PDFs**:
   - Do **not** ask local models to read a whole 50-page presentation with `moodle_read_resource`.
   - Instead, index your course once with `open-moodle sync <course_id>`, then let the model use `moodle_search`. The search engine queries local SQLite FTS5 with BM25 ranking and returns only the relevant 200-word paragraph, keeping the prompt compact and fast.

2. **Set adequate context window in Ollama**:
   - Default Ollama context is 2,048 tokens. Increase it to 16,384 or 32,768 in your Modelfile or client config:
     ```
     PARAMETER num_ctx 16384
     ```

3. **Prefer `moodle_brief` for daily summaries**:
   - Calling `moodle_brief` packages courses, attendance warnings, deadlines, and notifications into a single concise Markdown document, preventing multi-turn tool loops.
