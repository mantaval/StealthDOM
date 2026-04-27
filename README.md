# StealthDOM

**Undetectable browser automation via a Manifest V3 extension.**

StealthDOM replaces Playwright/Puppeteer by controlling the browser **from inside** — as a native extension, not through CDP. Zero detection signals. Works on Cloudflare, DataDome, Facebook, Instagram, Gmail, and any site that blocks traditional automation.

## How It Works

StealthDOM can be used in two ways:

**AI Agents** connect via the MCP protocol — most commands exposed as tools with descriptions, so the agent knows what's available and how to use it.(see **05_api_reference.md** for complete api reference)

**Scripts & applications** connect directly via WebSocket on port 9878, sending JSON commands and receiving JSON responses.(see **05_api_reference.md** for complete api reference)

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

The **content script** is injected into every page and provides direct DOM access — clicking elements, reading text, filling inputs, scrolling, etc. It receives commands from the background worker via `chrome.tabs.sendMessage` and never initiates any network connections itself, bypassing all page-level CSP restrictions.

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

- **35+ automation commands**: DOM queries, clicks, typing, scrolling, keyboard, mouse, navigation
- **Window management**: Open regular or incognito windows, resize, close
- **Tab management**: List, open, close, switch tabs
- **Screenshots**: Full-page PNG capture (with optional file save)
- **Cookies**: Get, set, delete
- **JavaScript execution**: Arbitrary JS in page context — works on ALL sites including YouTube/Gmail (CSP headers auto-stripped)
- **Network capture**: Record HTTP requests and responses
- **Proxy Fetch**: Route HTTP requests through the browser's real TLS fingerprint
- **MCP integration**: Full MCP server with 35+ tools, instructions, and capabilities resource
- **Enable/Disable toggle**: Click the extension icon to globally enable/disable (restores site security when not in use)

## Quick Start

1. **Load extension** in any Chromium browser (Chrome, Brave, Edge, etc.):  
   Open the extensions page (`chrome://extensions` or `brave://extensions`) → Developer Mode → Load Unpacked → select `extension/`

2. **Install dependencies**:
   ```bash
   pip install websockets mcp
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
   import asyncio, json, websockets

   async def main():
       ws = await websockets.connect("ws://127.0.0.1:9878")
       await ws.send(json.dumps({"action": "listTabs", "_timeout": 5}))
       print(json.loads(await ws.recv()))
       await ws.close()

   asyncio.run(main())
   ```

## Documentation

- [**Installation & Setup Guide**](docs/04_installation_guide.md) — Step-by-step setup, MCP configuration for popular IDEs, auto-start on Windows
- [**Full API Reference**](docs/05_api_reference.md) — Every command with parameters, WebSocket JSON, and MCP tool names
- [Extension Architecture](docs/01_stealth_dom_extension.md)
- [Connectivity Troubleshooting](docs/02_connectivity_troubleshooting.md)
- [Bot Detection Test Results](docs/03_test_results.md)

## Requirements

- Python 3.10+
- `websockets` (`pip install websockets`)
- `mcp` (`pip install mcp`)
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
