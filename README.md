# StealthDOM

**Undetectable browser automation via a Manifest V3 extension.**

StealthDOM replaces Playwright/Puppeteer by controlling the browser **from inside** — as a native extension, not through CDP. Zero detection signals. Works on Cloudflare, DataDome, Facebook, Instagram, Gmail, and any site that blocks traditional automation.

## How It Works

StealthDOM can be used in two ways:

**AI Agents** connect via the MCP protocol — 51 commands exposed as tools with descriptions, so the agent knows what's available and how to use it. (see **[03_api_reference.md](docs/03_api_reference.md)** for complete API reference)

**Scripts & applications** connect directly via WebSocket on port 9878, sending JSON commands and receiving JSON responses. (see **[03_api_reference.md](docs/03_api_reference.md)** for complete API reference)

Both paths flow through the same pipeline:

```
AI Agent (MCP)  ─┐
                  ├─► Bridge Server (bridge_server.py)
Python Script  ──┘    (localhost:9878)
                          │
                     WebSocket relay
                          │
                  Background Service Worker
                  (localhost:9877, inside the extension)
                       │            │
             Privileged ops    DOM commands
            (tabs, windows,    forwarded via
             screenshots,     chrome.tabs.sendMessage
             cookies, JS)          │
                              Content Script
                           (injected into the page,
                            has native DOM access)
```

The **background service worker** owns the bridge connection and handles privileged browser APIs (tabs, windows, screenshots, cookies, JS execution). It runs in the extension's own context, completely separate from any web page.

The **content script** is injected **on-demand** into tabs only when the first command targets them — it is **not** declared in `manifest.json`. This saves memory and CPU across all untouched tabs. When injected, it enters **all frames** (iframes, framesets), providing direct DOM access — clicking elements, reading text, filling inputs, scrolling, hovering, drag-and-drop, etc. It receives commands from the background worker via `chrome.tabs.sendMessage` (with optional `frameId` targeting) and never initiates any network connections itself, bypassing all page-level CSP restrictions.

## Why Not Playwright?

| | Playwright | StealthDOM |
|---|---|---|
| `navigator.webdriver` | `true` (detected) | `false` (natural) |
| TLS fingerprint | Synthetic | Real browser |
| CDP artifacts | Present (detectable) | None |
| Cloudflare/DataDome | Frequently blocked | ✅ Passes |
| User sessions | Must re-login | ✅ Uses existing |
| Bot risk score | Varies | **0/100** |

### Verified Against

StealthDOM has been tested against major bot detection suites:

| Test Suite | Result |
|---|---|
| [Sannysoft](https://bot.sannysoft.com) | ✅ Passed — WebDriver missing, Chrome present |
| [Fingerprint-Scan](https://fingerprint-scan.com) | ✅ Passed — Bot Risk Score: **0/100** |
| [BrowserScan](https://browserscan.net) | ✅ Passed — Bot Detection: No, 85% Authenticity |
| [CreepJS](https://abrahamjuliot.github.io/creepjs/) | ✅ Passed — 0% Headless, 0% Stealth |
| [Are You Headless?](https://arh.antoinevastel.com/bots/areyouheadless) | ✅ Passed — "You are not Chrome headless" |

## Features

- **51 MCP tools**: DOM queries, clicks, typing, scrolling, keyboard, hover, drag-and-drop, navigation, cookies, screenshots, JS execution, network capture, proxy fetch, tab/window management
- **Multi-browser support**: Connect Chrome, Brave, and Edge simultaneously — tabs from all browsers shown in one unified list
- **Virtual tab IDs**: Namespaced as `"label:tabId"` (e.g., `"brave:12345"`) for transparent multi-browser routing
- **Window management**: Open regular or incognito windows, resize, close
- **Tab management**: List, open, close, switch tabs across all connected browsers
- **Full-page screenshots**: Scroll-and-stitch PNG capture of entire documents (with optional file save)
- **Cookies**: Get, set, delete
- **JavaScript execution**: Arbitrary JS in page context — works on ALL sites including YouTube/Gmail (CSP headers auto-stripped)
- **Network capture**: Circular buffer (5,000 entries) with overflow detection
- **Proxy Fetch**: Route HTTP requests through the browser's real TLS fingerprint and cookies
- **MCP integration**: Full MCP server with 51 tools, instructions, and capabilities resource
- **Cross-frame DOM access**: Target elements inside iframes and framesets via `frame_id` — works on Gmail, OAuth dialogs, payment widgets
- **Explicit targeting**: All commands target tabs by ID — safe for multi-window, multi-agent use
- **On-demand injection**: Content script only loads in tabs you actually use — zero overhead on untouched tabs
- **Enable/Disable toggle**: Click the extension icon to globally enable/disable (restores site security when not in use)

## Quick Start

1. **Load extension** in any Chromium browser (Chrome, Brave, Edge, etc.):  
   Open the extensions page (`chrome://extensions` or `brave://extensions`) → Developer Mode → Load Unpacked → select `extension/`

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   Or manually:
   ```bash
   pip install websockets mcp psutil
   ```

3. **Start bridge**:
   ```bash
   python bridge_server.py
   ```

4. **Connect via MCP** (for AI agents):
   ```json
   {
     "mcpServers": {
       "stealth_dom": {
         "command": "python",
         "args": ["path/to/stealth_dom_mcp.py"]
       }
     }
   }
   ```

5. **Or connect directly** (Python):
   ```python
   import asyncio, json, uuid, websockets

   async def main():
       ws = await websockets.connect("ws://127.0.0.1:9878")

       # List tabs to get tab IDs (works across all connected browsers)
       msg_id = str(uuid.uuid4())[:8]
       await ws.send(json.dumps({"action": "listTabs", "_msg_id": msg_id, "_timeout": 5}))
       result = json.loads(await ws.recv())
       tabs = result["data"]

       # Use virtualId for reliable multi-browser routing
       tab = tabs[0]
       tab_id = tab.get("virtualId") or tab["id"]
       print(f"Using tab {tab_id}: {tab['title']}")

       # Get the page title
       msg_id = str(uuid.uuid4())[:8]
       await ws.send(json.dumps({"action": "getTitle", "tabId": tab_id, "_msg_id": msg_id, "_timeout": 5}))
       print(json.loads(await ws.recv()))

       await ws.close()

   asyncio.run(main())
   ```

## Multi-Browser Support

Multiple browsers can connect to the bridge simultaneously. Each browser's extension sends its label on connect (`chrome`, `brave`, `edge`, or `default`). The bridge routes commands to the correct browser automatically based on the tab's `virtualId`.

```
# Example: browser_list_tabs() output with two browsers connected
[
  {"id": 123, "virtualId": "brave:123", "browserId": "brave", "title": "...", ...},
  {"id": 456, "virtualId": "chrome:456", "browserId": "chrome", "title": "...", ...}
]
```

Always use `virtualId` as your `tab_id` to ensure commands reach the right browser.

## Documentation

- [**Why StealthDOM?**](docs/00_why_stealthdom.md) — The case for inside-the-browser automation, comparison with Playwright, bot detection test results
- [**Architecture & Design**](docs/01_architecture.md) — How it works, design decisions, CSP bypass, cross-frame support
- [**Installation & Setup Guide**](docs/02_installation_guide.md) — Step-by-step setup, MCP configuration for popular IDEs, troubleshooting
- [**Full API Reference**](docs/03_api_reference.md) — Every command with parameters, WebSocket JSON, and MCP tool names
- [**Screenshot Approaches**](docs/04_screenshot_approaches.md) — CDP screenshot architecture, detection analysis, comparison

## Requirements

- Python 3.10+
- `websockets`, `mcp`, `psutil` (`pip install -r requirements.txt`)
- Any Chromium-based browser (Chrome, Brave, Edge, Opera, Vivaldi, etc.) with the extension loaded

## Disclaimer

StealthDOM is intended for **legitimate automation** use cases:

- Automating your own workflows and accounts
- AI agent integration with your personal browser
- Testing and development
- Accessibility tools

**Do not use** StealthDOM to bypass authentication on accounts you don't own, scrape personal data without consent, violate any website's terms of service, or engage in any illegal activity. The authors are not responsible for misuse.

## License

[MIT](LICENSE)
