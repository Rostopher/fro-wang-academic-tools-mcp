# How to Configure MCP in AI Agents

This guide explains how to connect `fro-wang-academic-tools-mcp` to popular AI coding agents and IDEs that support the Model Context Protocol (MCP).

Since this project uses `FastMCP` and communicates via `stdio`, you need to configure your agent to run the server command.

---

## 1. Cursor

Cursor supports MCP servers natively.

1. Open Cursor Settings (`Ctrl+Shift+J` or `Cmd+Shift+J` -> type "Settings").
2. Navigate to **Features** -> **MCP**.
3. Click **+ Add New MCP Server**.
4. Configure it as follows:
   - **Name**: `academic-tools`
   - **Type**: `command`
   - **Command**: `uv run fro-wang-academic-tools-mcp` (or the absolute path to your python executable running the module, e.g., `/path/to/venv/bin/python -m academic_tools`)
5. Click **Save**. Cursor will start the server and list the available tools.

---

## 2. Claude Desktop

Claude Desktop uses a JSON configuration file to manage MCP servers.

1. Open your Claude Desktop configuration file:
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
2. Add the server to the `mcpServers` object:

```json
{
  "mcpServers": {
    "academic-tools": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/your/mcps/fro-wang-academic-tools-mcp",
        "run",
        "fro-wang-academic-tools-mcp"
      ]
    }
  }
}
```
*(Note: Replace `/absolute/path/to/your/mcps/fro-wang-academic-tools-mcp` with the actual absolute path to the project folder).*

3. Restart Claude Desktop.

---

## 3. GitHub Copilot (VS Code)

GitHub Copilot in VS Code supports MCP via the `github.copilot.chat.mcp.servers` setting.

1. Open VS Code Settings (`Ctrl+,` or `Cmd+,`).
2. Search for `mcp` and find **GitHub > Copilot > Chat > Mcp: Servers**.
3. Click **Edit in settings.json**.
4. Add the configuration:

```json
{
  "github.copilot.chat.mcp.servers": {
    "academic-tools": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/your/mcps/fro-wang-academic-tools-mcp",
        "run",
        "fro-wang-academic-tools-mcp"
      ]
    }
  }
}
```
5. Reload the VS Code window.

---

## 4. Cline

Cline (formerly Claude Dev) supports MCP configuration via its UI or config file.

1. Open the Cline panel in VS Code.
2. Click the **MCP Servers** icon (usually a plug or server icon).
3. Click **Configure MCP Servers** to open `cline_mcp_settings.json`.
4. Add the server:

```json
{
  "mcpServers": {
    "academic-tools": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/your/mcps/fro-wang-academic-tools-mcp",
        "run",
        "fro-wang-academic-tools-mcp"
      ]
    }
  }
}
```
5. Save the file. Cline will automatically detect and connect to the server.

---

## 5. Claude Code (CLI)

Claude Code provides a built-in `claude mcp add` command to register MCP servers without manually editing any config file.

```bash
claude mcp add academic-tools -- uv --directory /absolute/path/to/your/mcps/fro-wang-academic-tools-mcp run fro-wang-academic-tools-mcp
```

*(Replace `/absolute/path/to/your/mcps/fro-wang-academic-tools-mcp` with the actual absolute path to the project folder.)*

To verify the server was registered:

```bash
claude mcp list
```

To remove it later:

```bash
claude mcp remove academic-tools
```

---

## Troubleshooting

- **Command not found**: If the agent complains that `uv` is not found, provide the absolute path to the `uv` executable (e.g., `/usr/local/bin/uv` or `C:\\Users\\Name\\.cargo\\bin\\uv.exe`).
- **Environment Variables**: The MCP server will read the `.env` file in the project directory. Ensure your `.env` is correctly configured in the `fro-wang-academic-tools-mcp` folder.
- **Python Path**: Alternatively, instead of using `uv run`, you can directly use the absolute path to the virtual environment's Python executable:
  - Command: `/path/to/.venv/bin/python`
  - Args: `["-m", "academic_tools"]`
