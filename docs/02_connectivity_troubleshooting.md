# Extension Connectivity Troubleshooting

> **Last Updated:** 2026-04-26  
> This documents known issues with StealthDOM's extension ↔ bridge connectivity.

## How Connection Works

```
bridge_server.py (port 9877)  ←──WebSocket──→  Background Service Worker
         ↑                                            ↑
    Accepts connections                    Runs in the extension's
    from extension                         privileged context
                                                      │
                                              chrome.tabs.sendMessage
                                                      │
                                              Content Script → DOM
                                           (injected into every page)
```

1. `bridge_server.py` starts and listens on port 9877 (extension) and 9878 (clients)
2. Background service worker connects to `ws://127.0.0.1:9877`
3. On connect, sends handshake with extension details
4. Bridge heartbeats sent every 5 seconds to keep the connection alive
5. DOM commands are forwarded to the specified tab's content script via `chrome.tabs.sendMessage(tabId, ...)`

## Troubleshooting

### Bridge says "Waiting for extension..."

The extension's background service worker hasn't connected yet. This usually means:
- The extension isn't loaded — load it from the extensions page
- The extension is **disabled** — click the StealthDOM icon in the toolbar and toggle it on
- No page is open — open or refresh any tab (the service worker starts when a page loads)

### "Content script not ready on this tab"

After reloading the extension, content scripts on already-open pages become stale. 
**Fix:** Refresh the tab you want to interact with. This injects a fresh content script.

### Extension toggle shows "Enabled — bridge not connected"

The bridge server (`bridge_server.py`) isn't running. Start it:
```bash
python bridge_server.py
```
The extension auto-reconnects every 3 seconds, so it will connect within moments.

### Commands work on some tabs but not others

Content scripts are injected per-tab. If a tab was opened before the extension was loaded
(or before it was re-enabled), it won't have a content script. **Fix:** Refresh that tab.

## Bridge Logging

The bridge server includes timestamped logging. Example output:

```
[16:23:11.042] Extension port listening on ws://127.0.0.1:9877
[16:23:11.043] Control port listening on ws://127.0.0.1:9878
[16:23:11.043] Waiting for extension... (open any page in your browser)
[16:24:44.735] Extension connected from ('127.0.0.1', 58860)
[16:24:44.742] Handshake received from: https://example.com
```

## Content Script Anti-Throttle

The content script includes an anti-throttle system that prevents Chromium from throttling background tabs:
- Overrides `document.hidden` and `visibilityState`
- Performs periodic DOM touches to keep the tab alive
- Intercepts `visibilitychange` events
- Uses `configurable: true` on property definitions to prevent "Cannot redefine property" errors on repeated injections
