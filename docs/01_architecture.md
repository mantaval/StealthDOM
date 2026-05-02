# Architecture & Design Decisions

This document explains how StealthDOM works internally and the engineering decisions behind its design. For a high-level overview of why StealthDOM exists, see [Why StealthDOM?](00_why_stealthdom.md).

---

## System Architecture

```
StealthDOM/
├── extension/
│   ├── manifest.json          ← Manifest V3 (on-demand injection, debugger permission)
│   ├── background.js          ← Service worker: WebSocket bridge, command routing,
│   │                             tabs, windows, CDP screenshots, cookies, JS execution,
│   │                             network capture
│   └── content_script.js      ← Passive DOM command executor (injected lazily)
│
├── bridge_server.py           ← WebSocket relay (port 9877: extension, port 9878: clients)
├── stealth_dom_mcp.py         ← MCP server wrapping all commands as AI agent tools
├── install.bat                ← Backend installer (Python & Auto-start)
├── uninstall.bat              ← Backend uninstaller
├── scripts/                   ← Internal scripts (bridge startup, installer logic)
├── tests/test_stealth_dom.py  ← Integration test suite
└── docs/                      ← This documentation
```

### Communication Flow

```
1. Bridge server starts on ports 9877 (extension) and 9878 (clients)
2. Background service worker connects to ws://127.0.0.1:9877
3. Service worker sends keepalive pings every 20 seconds to prevent Chromium from killing it
4. Client (Python/MCP) connects to ws://127.0.0.1:9878
5. Client sends command:
   { "action": "click", "selector": "#btn", "tabId": 123, "_msg_id": "abc" }
6. Bridge relays to background service worker (echoes _msg_id in response)
7. Background routes command:
   - Tab/window/screenshot/cookie/JS commands → handled directly
   - DOM commands → forwarded to content script via chrome.tabs.sendMessage(tabId)
8. Content script executes: document.querySelector('#btn').click()
9. Result sent back: { "success": true, "data": null, "_msg_id": "abc" }
```

---

## Design Decision: Why Content Scripts Don't Connect to the Bridge

Modern websites enforce **Content Security Policy (CSP)** that restricts network connections. A content script trying to open a WebSocket to `127.0.0.1` would be blocked on Gmail, ChatGPT, YouTube, and most other major sites.

**Solution:** The bridge connection lives in the **background service worker**, which runs in a privileged extension context exempt from page-level CSP. The content script is a passive executor that only responds to `chrome.runtime.onMessage` — it never initiates network connections.

| Site | CSP Restriction | Would Block Content Script WebSocket? |
|------|----------------|------|
| Gmail | `connect-src` whitelist | ✅ Yes |
| ChatGPT | `connect-src` + Cloudflare | ✅ Yes |
| YouTube | Strict CSP | ✅ Yes |
| Banking sites | Strict CSP + PNA | ✅ Yes |

---

## Design Decision: On-Demand Content Script Injection

Content scripts are **NOT** declared in `manifest.json`. Instead, the background worker injects them lazily via `chrome.scripting.executeScript({ allFrames: true })` when the first command targets a tab.

**Why:**
- Saves memory — scripts aren't loaded on tabs you never interact with
- Works across all frames — `allFrames: true` injects into every `<frame>` and `<iframe>`, giving native DOM access to framesets (like Gmail's compose view) and embedded content
- Includes a double-injection guard using a non-enumerable `Symbol`-keyed property — invisible to `Object.keys`, `for...in`, and `JSON.stringify`, even within the isolated world

**Cross-frame workflow:** When you need to interact with content inside an iframe:
1. `browser_list_frames(tab_id)` → discover all frames and their IDs
2. Pass `frame_id=N` to any DOM tool → targets that specific frame's content script

---

## Design Decision: CSP Header Stripping

Some sites enforce **Trusted Types** — a CSP directive that blocks `eval()`, `new Function()`, and dynamic script injection. This means even `chrome.scripting.executeScript` (which uses eval internally) returns null on YouTube, Gmail, and Google Docs.

**Solution:** On startup, StealthDOM registers a `declarativeNetRequest` rule that strips the `Content-Security-Policy` header from all page responses before the browser processes them:

```javascript
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

**Why this is safe for an automation tool:**
- The user has already granted full site access (`<all_urls>` host permission)
- CSP protects against XSS — not relevant when you're intentionally injecting code
- The stripping only affects pages loaded while the extension is active

### Enable/Disable Toggle

StealthDOM includes a **popup toggle** (click the extension icon) to globally enable or disable the extension. When disabled, CSP headers are preserved and the bridge disconnects — restoring full browser security for normal browsing.

| State | Bridge | CSP Stripping | Commands | Security |
|-------|--------|---------------|----------|----------|
| **Enabled** | Connected | Active | Accepted | Reduced (no page CSP) |
| **Disabled** | Disconnected | Inactive | Rejected | Full (normal CSP) |

---

## Design Decision: CDP Screenshots (v3.2.0)

Chrome's `captureVisibleTab` API — the only extension API for screenshots — requires window focus and has a 2-call/sec rate limit. StealthDOM v3.2.0 replaced this with CDP-based screenshots via `chrome.debugger`, which renders directly from the compositor pipeline without any focus stealing or rate limits.

The `captureVisibleTab` path is retained as an automatic fallback for the rare case when DevTools is already open on the target tab.

For the full technical deep-dive, detection analysis, and comparison with alternative approaches, see [Screenshot Approaches](04_screenshot_approaches.md).

---

## Design Decision: Explicit Tab Targeting

All tab-scoped commands require an explicit `tabId`. There is no "active tab" inference or heuristic fallback. This prevents accidental command misrouting and makes the API deterministic when multiple tabs are open.

```python
# Always list tabs first to get IDs
tabs = await send(ws, "listTabs")
tab_id = tabs["data"][0]["id"]

# All subsequent commands use the explicit tab ID
await send(ws, "click", selector="#btn", tabId=tab_id)
```

---

## Background Service Worker Lifecycle

Chromium's Manifest V3 service workers can be terminated after ~30 seconds of inactivity. StealthDOM mitigates this with:
- A 20-second keepalive interval (`chrome.runtime.getPlatformInfo`)
- Automatic reconnection on service worker restart

> **Tip:** Opening the service worker's DevTools (from `chrome://extensions`) keeps it alive indefinitely during development.

---

## Security Considerations

> [!CAUTION]
> A WebSocket server on localhost that can control the browser is powerful.

1. **Localhost only** ✅ — Both ports bound to `127.0.0.1`, never `0.0.0.0`. Only local processes can connect.
2. **Console logging** ✅ — Bridge prints all commands and connections to the terminal with timestamps.
3. **Domain whitelist** ✅ — In extension settings, change "Site Access" from "On all sites" to "On specific sites" to restrict which domains StealthDOM can automate.
4. **Enable/disable toggle** ✅ — Disable the extension when not in use to restore full CSP protection.

---

## Further Reading

- [Why StealthDOM?](00_why_stealthdom.md) — The case for inside-the-browser automation
- [Installation Guide](02_installation_guide.md) — Setup, MCP configuration, troubleshooting
- [API Reference](03_api_reference.md) — Complete reference for all 57 MCP tools and WebSocket commands
- [Screenshot Approaches](04_screenshot_approaches.md) — CDP screenshot architecture and detection analysis
