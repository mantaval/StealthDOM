# Installation & Setup Guide

> Complete guide for installing StealthDOM, configuring AI agent integration,  
> and setting up automatic startup.

---

## Prerequisites

- **Python 3.10+** with `pip`
- **A Chromium-based browser**: Chrome, Brave, Edge, Opera, Vivaldi, etc.
- **Git** (optional, for cloning the repo)

---

## Step 1: Download & Install Dependencies

### Clone or download the project

```bash
git clone https://github.com/mantaval/StealthDOM.git
cd StealthDOM
```

### Install Python dependencies

```bash
pip install websockets mcp
```

That's it — only two packages needed.

---

## Step 2: Load the Browser Extension

1. Open your browser's extensions page:
   - **Chrome**: `chrome://extensions`
   - **Brave**: `brave://extensions`
   - **Edge**: `edge://extensions`
   - **Opera**: `opera://extensions`

2. Enable **Developer Mode** (toggle in the top-right corner)

3. Click **"Load unpacked"**

4. Select the `StealthDOM/extension/` folder

5. The StealthDOM extension should appear in your extensions list

### Optional: Enable in Incognito

If you want AI agents to be able to open and control incognito windows:

1. Click the extension's **Details** button
2. Toggle **"Allow in Incognito"** (or "Allow in Private" in some browsers)

> **Note:** The extension needs to run on all sites to function as a general-purpose  
> automation tool. If you want to restrict it to specific domains, change "Site Access"  
> in the extension details to "On specific sites."

---

## Step 3: Start the Bridge Server

The bridge server is the relay between AI agents and the browser extension.

### Option A: Command line (all platforms)

```bash
python bridge_server.py
```

This works on Windows, macOS, and Linux. You'll see:

```
[16:23:11.042] Extension port listening on ws://127.0.0.1:9877
[16:23:11.043] Control port listening on ws://127.0.0.1:9878
[16:23:11.043] Waiting for extension... (open any page in your browser)
```

Press `Ctrl+C` to stop.

### Option B: One-click start (Windows only)

Double-click **`start_bridge.bat`** in the StealthDOM folder. This opens a terminal window with the bridge running. If it crashes, it automatically prompts to restart.

### Option C: Auto-start on login (Windows only)

Right-click **`windows_startup_install.bat`** → **Run as administrator**

This creates a Windows Task Scheduler task that starts the bridge silently on login using `pythonw` (Python's windowless interpreter — no terminal window).

To remove it, right-click **`windows_startup_uninstall.bat`** → **Run as administrator**

> **macOS/Linux:** To auto-start on other platforms, use your system's native  
> mechanism (`launchd` on macOS, `systemd` on Linux) to run  
> `python bridge_server.py` at login.

---

## Step 4: Verify the Connection

Once the bridge is running and you have a browser tab open:

1. The bridge terminal should show:
   ```
   Extension connected from ('127.0.0.1', ...)
   Handshake received from: https://...
   Ready! Bridge is live.
   ```

2. Quick test with Python:
   ```python
   import asyncio, json, websockets

   async def test():
       ws = await websockets.connect('ws://127.0.0.1:9878')
       await ws.send(json.dumps({'action': 'listTabs', '_msg_id': 'test1', '_timeout': 5}))
       result = json.loads(await ws.recv())
       print(result)  # {'success': True, 'data': [{'id': ..., 'url': '...', 'incognito': ..., ...}]}
       await ws.close()

   asyncio.run(test())
   ```

---

## Step 5: Configure MCP for AI Agents

StealthDOM includes a full MCP (Model Context Protocol) server that exposes all 35+ commands as tools for AI agents. Below are setup instructions for popular AI-powered IDEs.

### General MCP Configuration

Every MCP client uses a JSON configuration. The core entry is:

```json
{
  "mcpServers": {
    "stealth_dom": {
      "command": "python",
      "args": ["/absolute/path/to/StealthDOM/stealth_dom_mcp.py"]
    }
  }
}
```

> **Important:** Use the **absolute path** to `stealth_dom_mcp.py`. Relative paths  
> may not resolve correctly depending on the IDE's working directory.

---

### Cursor

1. Open **Settings** → **MCP**
2. Click **"Add new MCP server"**
3. Enter:
   - **Name**: `stealth_dom`
   - **Command**: `python`
   - **Arguments**: `/absolute/path/to/StealthDOM/stealth_dom_mcp.py`
4. Save and restart Cursor

Or edit `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "stealth_dom": {
      "command": "python",
      "args": ["/absolute/path/to/StealthDOM/stealth_dom_mcp.py"]
    }
  }
}
```

---

### Windsurf

1. Open **Settings** → **Cascade** → **MCP**
2. Click **"Add Server"**
3. Enter:
   - **Name**: `stealth_dom`
   - **Command**: `python /absolute/path/to/StealthDOM/stealth_dom_mcp.py`
4. Save and restart

Or edit `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "stealth_dom": {
      "command": "python",
      "args": ["/absolute/path/to/StealthDOM/stealth_dom_mcp.py"]
    }
  }
}
```

---

### Claude Desktop

Edit the Claude Desktop config file:

- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "stealth_dom": {
      "command": "python",
      "args": ["/absolute/path/to/StealthDOM/stealth_dom_mcp.py"]
    }
  }
}
```

Restart Claude Desktop after saving.

---

### Antigravity IDE

Edit the MCP config file at:

- **Windows**: `%USERPROFILE%\.gemini\antigravity\mcp_config.json`

```json
{
  "mcpServers": {
    "stealth_dom": {
      "command": "python",
      "args": ["/absolute/path/to/StealthDOM/stealth_dom_mcp.py"]
    }
  }
}
```

Restart the IDE after saving.

---

### VS Code (with MCP extensions like Cline, Roo Code, etc.)

Most VS Code MCP extensions use a similar config. Create or edit `.vscode/mcp.json` in your workspace:

```json
{
  "mcpServers": {
    "stealth_dom": {
      "command": "python",
      "args": ["/absolute/path/to/StealthDOM/stealth_dom_mcp.py"]
    }
  }
}
```

---

### Custom MCP Client (Python)

If you're building your own MCP client:

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def connect():
    params = StdioServerParameters(
        command="python",
        args=["/absolute/path/to/StealthDOM/stealth_dom_mcp.py"]
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"Available tools: {len(tools.tools)}")
```

---

## Direct WebSocket Usage (No MCP)

If your application doesn't use MCP, you can connect directly to the bridge's control port.
All tab-scoped commands require an explicit `tabId`. Use `listTabs` first to discover IDs.

```python
import asyncio, json, uuid, websockets

async def send(ws, action, **kwargs):
    """Send a command with _msg_id for response matching."""
    msg_id = str(uuid.uuid4())[:8]
    msg = {"action": action, "_msg_id": msg_id, "_timeout": 10, **kwargs}
    await ws.send(json.dumps(msg))
    while True:
        data = json.loads(await ws.recv())
        if data.get("_msg_id") == msg_id:
            data.pop("_msg_id", None)
            return data

async def main():
    ws = await websockets.connect("ws://127.0.0.1:9878")
    
    # Discover tabs
    result = await send(ws, "listTabs")
    tab_id = result["data"][0]["id"]
    print(f"Using tab {tab_id}")
    
    # Navigate
    await send(ws, "navigate", url="https://example.com", tabId=tab_id)
    
    # Click a button
    await send(ws, "click", selector="#my-button", tabId=tab_id)
    
    # Take a screenshot
    result = await send(ws, "captureScreenshot", tabId=tab_id)
    # result["data"]["dataUrl"] contains the base64 PNG
    
    await ws.close()

asyncio.run(main())
```

Commands are JSON objects with an `action` field and optional parameters. See [01_stealth_dom_extension.md](01_stealth_dom_extension.md) for the full command API.

---

## File Reference

| File | Purpose |
|------|---------|
| `bridge_server.py` | WebSocket relay server (ports 9877 + 9878) |
| `stealth_dom_mcp.py` | MCP server wrapping all commands as AI agent tools |
| `extension/` | Browser extension (background.js, content_script.js, manifest.json) |
| `tests/test_stealth_dom.py` | Integration test suite (90 assertions across 31 test functions) |
| `start_bridge.bat` | One-click bridge startup with auto-restart (Windows) |
| `windows_startup_install.bat` | Install bridge as Windows auto-start task (right-click → Run as admin) |
| `windows_startup_uninstall.bat` | Remove the auto-start task (right-click → Run as admin) |
| `docs/` | Full documentation |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Bridge says "Waiting for extension..." | Open or refresh any page in your browser |
| "Extension not connected" errors | Reload the extension, then refresh the target tab |
| MCP server won't start | Check that `websockets` and `mcp` are installed: `pip install websockets mcp` |
| Content script not responding | Refresh the page — content scripts go stale after extension reload |
| Commands fail on `chrome://` or `brave://` pages | Browser internal settings/tabs/pages are protected — the extension cannot access them |
| `browser_evaluate` returns null | The page was loaded before CSP stripping was active — refresh the page |

For detailed troubleshooting, see [02_connectivity_troubleshooting.md](02_connectivity_troubleshooting.md).
