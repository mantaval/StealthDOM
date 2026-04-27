# StealthDOM: Undetectable Browser Automation via Extension

> A Manifest V3 browser extension that provides Playwright-level browser control  
> from within the browser itself — completely invisible to anti-bot systems.

---

## The Problem with External Automation

All current browser automation tools (Playwright, Puppeteer, Selenium) control the browser **from outside** via the Chrome DevTools Protocol (CDP). This creates detection signals:

| Signal | What It Reveals |
|--------|----------------|
| `navigator.webdriver = true` | Automation flag set by CDP |
| `window.cdc_` properties | ChromeDriver artifacts |
| `Runtime.enable` traces | CDP command history |
| Missing `chrome.runtime` | No extension ecosystem |
| TLS fingerprint mismatch | CDP proxy alters TLS |
| No mouse jitter / scroll entropy | Non-human interaction patterns |
| Cloudflare Turnstile failure | Behavioral analysis catches all of the above |

**Result:** Sites with Cloudflare, DataDome, or custom bot detection block automation within seconds.

---

## The Solution: Automate from INSIDE

StealthDOM is a browser extension that runs as a **first-class citizen** inside the browser. It has:

- Full, native DOM access (same as any webpage JavaScript)
- No CDP artifacts (doesn't use DevTools Protocol)
- `navigator.webdriver = false` (naturally)
- Real `chrome.runtime` (because it IS an extension)
- Normal TLS fingerprint (browser handles TLS natively)
- **No detectable difference from the user manually browsing**

```
External tool (Python/MCP/AI Agent)
        │
        ▼
localhost WebSocket (:9878)  ← Just a local network request
        │
        ▼
Bridge Server (bridge_server.py)  ← Relay
        │
        ▼
Background Service Worker (:9877)  ← Bridge connection lives HERE
        │
        ▼
Content Script → DOM (native access)
```

---

## Architecture

### Components

```
StealthDOM/
├── extension/
│   ├── manifest.json          ← Manifest V3, injects on <all_urls>
│   ├── background.js          ← Service worker: WebSocket bridge connection,
│   │                             command routing, tabs, windows, screenshots,
│   │                             cookies, JS execution, network capture
│   └── content_script.js      ← Passive DOM command executor
│                                 Receives commands from background via
│                                 chrome.runtime.onMessage
│
├── bridge_server.py           ← WebSocket relay (two ports):
│                                 Port 9877: extension connects here
│                                 Port 9878: external clients connect here
│
├── stealth_dom_mcp.py         ← MCP server wrapping all commands as tools
│                                 for AI agent integration. Includes
│                                 instructions and capabilities resource.
│
├── tests/
│   └── test_stealth_dom.py    ← Integration test suite (19 tests)
│
└── docs/                      ← This documentation
```

### Communication Flow

```
1. Bridge server starts on ports 9877 (extension) and 9878 (clients)
2. Background service worker connects to ws://127.0.0.1:9877
3. Service worker sends heartbeats every 5 seconds to stay alive
4. Client (Python/MCP) connects to ws://127.0.0.1:9878
5. Client sends command:  { "action": "click", "selector": "#btn", "tabId": 123, "_msg_id": "abc" }
6. Bridge relays to background service worker (echoes _msg_id in response)
7. Background routes command:
   - Tab/window/screenshot/cookie/JS commands → handled directly
   - DOM commands → forwarded to content script via chrome.tabs.sendMessage(tabId)
8. Content script executes: document.querySelector('#btn').click()
9. Result sent back: { "success": true, "data": null, "_msg_id": "abc" }
```

### Extension Internals

**Background Service Worker** (`background.js`):
- **Owns the WebSocket bridge connection** — connects to bridge_server.py on port 9877
- Routes all incoming commands to the appropriate handler
- Handles privileged operations directly: tabs, windows, screenshots, cookies
- Forwards DOM commands to the specified tab's content script via `chrome.tabs.sendMessage(tabId, ...)`
- **All tab-scoped commands require an explicit `tabId`** — there is no "active tab" fallback
- Keeps alive via 20-second keepalive interval (`chrome.runtime.getPlatformInfo`)
- Auto-reconnects to bridge on disconnect (3-second interval)
- Network capture via `chrome.webRequest.onBeforeRequest` listener
- Arbitrary JS execution via `chrome.scripting.executeScript({ world: 'MAIN' })`
- **CSP header stripping** via `chrome.declarativeNetRequest` (see below)
- Window management via `chrome.windows.create/remove/update/getAll`

**Content Script** (`content_script.js`):
- Runs in the **ISOLATED world** (has DOM access but separate JS context from the page)
- **Passive listener** — does NOT connect to the bridge directly
- Receives commands from background service worker via `chrome.runtime.onMessage`
- Handles DOM commands: querySelector, click, type, scroll, etc.
- Forwards `evaluate` commands to background for MAIN world JS execution

### How StealthDOM Bypasses CSP

Modern websites enforce **Content Security Policy (CSP)** through HTTP response headers.
These policies restrict what scripts can run, where network connections can go, and whether
dynamic code execution (`eval()`, `new Function()`) is allowed. This creates two challenges
for browser automation:

**Challenge 1: WebSocket Connectivity**

Many sites include a `connect-src` CSP directive that whitelists allowed network destinations.
A content script trying to open a WebSocket to `127.0.0.1` would be blocked on these sites.

| Site | CSP Restriction | Impact |
|------|----------------|--------|
| **Gmail** | `connect-src` whitelist | WebSocket to `127.0.0.1` refused |
| **ChatGPT** | `connect-src` + Cloudflare | Connection blocked + bot flag |
| **YouTube** | Strict CSP | WebSocket blocked |
| **Facebook** | `connect-src` whitelist | WebSocket refused |
| **GitHub** | `connect-src` whitelist | WebSocket blocked |
| **Banking sites** | Strict CSP + PNA | "Private Network Access" popup |

**Solution:** The bridge connection lives in the **background service worker**, a privileged
extension context that runs outside any page and is exempt from page-level CSP. The content
script becomes a passive executor that only responds to `chrome.runtime.onMessage` — it
never initiates any network connections.

**Challenge 2: JavaScript Execution (Trusted Types)**

A growing number of sites enforce **Trusted Types** — a CSP directive that blocks `eval()`,
`new Function()`, and dynamic `<script>` injection entirely. This means even the privileged
`chrome.scripting.executeScript` API (which uses eval internally) returns null on these sites.
Playwright avoids this because it uses the Chrome DevTools Protocol (CDP), which has kernel-
level access — but CDP is trivially detectable by bot protection.

| Site | Trusted Types? | `evaluate` without fix |
|------|---------------|----------------------|
| **YouTube** | Yes | ❌ Returns null |
| **Google Docs** | Yes | ❌ Returns null |
| **Gmail** | Yes | ❌ Returns null |
| **Most other sites** | No | ✅ Works fine |

**Solution:** On extension startup, StealthDOM registers a `declarativeNetRequest` rule that
**strips the `Content-Security-Policy` header** from all page responses before the browser
processes them. With no CSP header, the page loads without Trusted Types enforcement, and
`eval()` works freely in the MAIN world.

```javascript
// Registered on startup in background.js
chrome.declarativeNetRequest.updateDynamicRules({
    addRules: [{
        id: 9999,
        action: {
            type: 'modifyHeaders',
            responseHeaders: [
                { header: 'content-security-policy', operation: 'remove' },
                { header: 'content-security-policy-report-only', operation: 'remove' }
            ]
        },
        condition: { resourceTypes: ['main_frame', 'sub_frame'] }
    }]
});
```

This is safe for an automation tool because:
- The user has already granted full site access (`<all_urls>` host permission)
- CSP protects against XSS attacks — not relevant when you're intentionally injecting code
- The stripping only affects pages loaded while the extension is active

### Security: Enable/Disable Toggle

StealthDOM includes a **popup toggle** (click the extension icon in the toolbar) that lets
you globally enable or disable the extension. This is important because CSP header stripping
reduces the browser's built-in security protections while active.

| State | Bridge | CSP Stripping | Commands | Security |
|-------|--------|---------------|----------|----------|
| **Enabled** | Connected | Active — headers removed | Accepted | Reduced (no page CSP) |
| **Disabled** | Disconnected | Inactive — headers preserved | Rejected | Full (normal CSP) |

> **Security recommendation:** When you're not actively using StealthDOM for automation,
> **disable it** via the popup toggle. This restores full CSP protection on all sites,
> which guards against cross-site scripting (XSS) and other injection attacks during
> normal browsing. Pages loaded or refreshed after disabling will have their original
> CSP headers intact.

The enabled/disabled state **persists across browser restarts** — if you disable StealthDOM
and close the browser, it stays disabled the next time you open it.

---

## Full Command API (35+ Commands)

### DOM Queries
```json
{ "action": "querySelector", "selector": "#prompt-textarea" }
{ "action": "querySelectorAll", "selector": ".message", "limit": 20 }
{ "action": "getInnerText", "selector": "#content" }
{ "action": "getOuterHTML", "selector": "#form", "maxLength": 5000 }
{ "action": "getAttribute", "selector": "#link", "attribute": "href" }
{ "action": "getPageText" }
{ "action": "getPageHTML", "maxLength": 50000 }
{ "action": "waitForSelector", "selector": ".loaded", "timeout": 10000 }
{ "action": "waitForText", "selector": "#status", "text": "Done", "timeout": 5000 }
```

### DOM Interaction
```json
{ "action": "click", "selector": "button.submit" }
{ "action": "dblclick", "selector": ".item" }
{ "action": "type", "selector": "#input", "text": "hello world" }
{ "action": "fill", "selector": "#input", "value": "hello world" }
{ "action": "focus", "selector": "#input" }
{ "action": "blur", "selector": "#input" }
{ "action": "check", "selector": "#checkbox" }
{ "action": "uncheck", "selector": "#checkbox" }
{ "action": "selectOption", "selector": "#dropdown", "value": "option1" }
{ "action": "scrollIntoView", "selector": ".target" }
{ "action": "scrollTo", "x": 0, "y": 500 }
```

### Keyboard
```json
{ "action": "keyPress", "key": "Enter" }
{ "action": "keyCombo", "keys": ["Control", "Shift", "d"] }
```

### Mouse
```json
{ "action": "mouseClick", "x": 100, "y": 200, "button": "left" }
{ "action": "mouseMove", "x": 100, "y": 200 }
{ "action": "mouseWheel", "deltaX": 0, "deltaY": 500 }
```

### Page Info
```json
{ "action": "getURL" }
{ "action": "getTitle" }
{ "action": "getStatus" }
{ "action": "getPageText" }
```

### Navigation
```json
{ "action": "navigate", "url": "https://example.com", "tabId": 123 }
{ "action": "goBack", "tabId": 123 }
{ "action": "goForward", "tabId": 123 }
```

### Tab Management
```json
{ "action": "listTabs" }
{ "action": "newTab", "url": "https://example.com" }
{ "action": "switchTab", "tabId": 123 }
{ "action": "closeTab", "tabId": 123 }
{ "action": "reloadTab", "tabId": 123 }
```

### Window Management
```json
{ "action": "newWindow", "url": "https://example.com" }
→ { "success": true, "data": { "windowId": 456, "incognito": false, "tabs": [...] } }

{ "action": "newIncognitoWindow", "url": "https://example.com" }
→ { "success": true, "data": { "windowId": 789, "incognito": true, "tabs": [...] } }

{ "action": "listWindows" }
→ { "success": true, "data": [{ "id": 456, "type": "normal", "incognito": false, ... }] }

{ "action": "closeWindow", "windowId": 456 }
{ "action": "resizeWindow", "windowId": 456, "width": 1280, "height": 720 }
```

> **Regular window** opens in the user's profile with all cookies and sessions intact.  
> **Incognito window** opens a clean session with no cookies — useful for testing or isolated browsing.  
> Requires "Allow in Incognito" enabled in extension settings.

### Screenshots
```json
{ "action": "captureScreenshot", "tabId": 123 }
→ { "success": true, "data": { "dataUrl": "data:image/png;base64,...", "tabId": 123 } }
```

> The MCP tool wrapping this command (`browser_screenshot`) accepts an optional  
> `save_path` parameter. When provided, the base64 data is automatically decoded  
> and saved as a PNG file on disk, returning the file path instead of raw base64.

### Cookies
```json
{ "action": "getCookies", "url": "https://example.com" }
{ "action": "setCookie", "details": { "url": "...", "name": "...", "value": "..." } }
{ "action": "deleteCookie", "url": "...", "name": "..." }
```

### JavaScript Execution
```json
{ "action": "evaluate", "code": "document.title" }
{ "action": "evaluate", "code": "return document.querySelectorAll('a').length" }
{ "action": "evaluate", "code": "return [...document.querySelectorAll('a')].map(a => a.href)" }
```

> JavaScript execution uses `chrome.scripting.executeScript({ world: 'MAIN' })`.  
> Works on **all sites**, including YouTube, Gmail, and other Trusted Types-enforced pages.  
> CSP headers are automatically stripped via `declarativeNetRequest` on page load.  
> Supports both expressions (`document.title`) and return statements (`return 2 + 2`).

### DOM Manipulation
```json
{ "action": "removeByText", "selector": "ytd-rich-shelf-renderer", "texts": ["Shorts"] }
→ { "success": true, "data": { "removed": 1, "selector": "...", "texts": [...] } }
```

> `removeByText` is a convenience command for simple text-based element removal.  
> Removes elements matching `selector` whose `innerText` contains any of `texts` (case-insensitive).  
> Runs natively in the content script — no eval needed.

### Network Capture
```json
{ "action": "startNetCapture" }
{ "action": "stopNetCapture" }
{ "action": "getNetCapture" }
→ { "data": [{ "url": "...", "method": "POST", "requestHeaders": {...} }] }
```

### Proxy Fetch (Critical)
```json
{ "action": "proxyFetch", "url": "https://api.example.com/data",
  "method": "POST", "headers": {...}, "body": {...}, "bodyType": "json" }
→ { "data": { "status": 200, "headers": {...}, "body": {...} } }
```

> ProxyFetch routes HTTP requests through the browser's `fetch()` API.  
> This inherits the browser's TLS fingerprint (JA3/JA4), cookies, and session state.  
> Essential for bypassing bot detection on API calls.

### File Upload
```json
{ "action": "setInputFiles", "selector": "input[type=file]", "dataUrl": "data:..." }
```

---

## StealthDOM vs Playwright

| Aspect | Playwright | StealthDOM |
|--------|-----------|-----------| 
| Detection risk | High — CDP, webdriver flag, TLS | **Zero** — native browser citizen |
| Cloudflare | Frequently blocked | **Never blocked** |
| Uses real browser profile | Via `executable_path` (hacky) | **Natively** — user's actual browser |
| Logged-in sessions | Must re-authenticate | **Uses existing sessions** |
| Speed | Fast (direct CDP) | Slightly slower (WebSocket relay) |
| Setup | Install Python + Playwright + browsers | **Load extension** (one click) |
| Human behavior | Must simulate (bezier curves, etc.) | **Already human** — real browser |
| JavaScript execution | Built-in | **Built-in** (arbitrary JS, CSP-safe) |
| Window management | Built-in | **Built-in** (regular + incognito) |
| File uploads | Full support | Supported via `setInputFiles` |
| Network interception | Built-in | Via `startNetCapture` / `getNetCapture` |
| Proxy Fetch (browser TLS) | Not available | **StealthDOM exclusive** |

---

## Setup

1. **Load extension**: Open `chrome://extensions` (or `brave://extensions`, `edge://extensions`) → Enable Developer Mode → "Load unpacked" → Select `StealthDOM/extension/`
2. **Enable in Incognito** (optional): Click extension details → toggle "Allow in Incognito"
3. **Start bridge**: `python bridge_server.py`
4. **Use via MCP**: Configure `stealth_dom_mcp.py` in your MCP client
5. **Or connect directly**: WebSocket on port 9878

### Quick Test (Python)

```python
import asyncio, json, websockets

async def test():
    ws = await websockets.connect('ws://127.0.0.1:9878')
    
    # Always list tabs first to get IDs
    await ws.send(json.dumps({'action': 'listTabs', '_timeout': 5}))
    result = json.loads(await ws.recv())
    tab_id = result['data'][0]['id']
    print(f"Tab {tab_id}: {result['data'][0]['title']}")
    
    # Use explicit tabId for all commands
    await ws.send(json.dumps({'action': 'getTitle', 'tabId': tab_id, '_timeout': 5}))
    print(json.loads(await ws.recv()))
    await ws.close()

asyncio.run(test())
```

---

## MCP Integration

StealthDOM includes a full MCP server (`stealth_dom_mcp.py`) that exposes all 35+ commands as MCP tools. The server includes:

- **Instructions**: Automatically sent to AI agents explaining what StealthDOM is and why to use it over Playwright
- **Capabilities Resource**: A static `stealth://capabilities` resource AI agents can read for full tool reference (string embedded directly inside stealth_dom_mcp.py for agent )
- **35+ Tools**: Every command has a corresponding MCP tool with descriptive docstrings

### MCP Configuration

```json
{
    "mcpServers": {
        "stealth_dom": {
            "command": "python",
            "args": ["C:/path/to/StealthDOM/stealth_dom_mcp.py"]
        }
    }
}
```

---

## Known Issues

### Service Worker Lifecycle

Chromium's Manifest V3 service workers can be terminated after ~30 seconds of inactivity. StealthDOM mitigates this with:
- A 20-second keepalive interval
- A 5-second bridge heartbeat
- Automatic reconnection on service worker restart
- Opening the service worker DevTools (from the browser's extensions page) keeps it alive indefinitely

### Content Script Injection After Extension Reload

After reloading the extension in the browser's extensions page, content scripts on already-loaded pages become stale. **Refresh any tab** you want to interact with after reloading the extension.

### Background Tab Throttling

Chromium throttles background tabs, which can delay interactions. StealthDOM includes an anti-throttle system in the content script that:
- Overrides `document.hidden` and `visibilityState`
- Performs periodic DOM touches to keep the tab alive
- Intercepts `visibilitychange` events

---

## Security Considerations

> [!CAUTION]
> A WebSocket server on localhost that can control the browser is powerful.

1. **Localhost only** ✅ — Both ports bound to `127.0.0.1`, never `0.0.0.0`. Only local processes can connect.
2. **Console logging** ✅ — Bridge prints all commands and connections to the terminal with timestamps for visibility.
3. **Domain whitelist** ✅ — Handled natively by the browser. In extension settings, change "Site Access" from "On all sites" to "On specific sites" to restrict which domains StealthDOM can automate.
