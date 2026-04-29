# Screenshot Approaches — Trade-offs & Implementation

*Last updated: 2026-04-29*

---

## Current Implementation (v3.2.0)

StealthDOM uses **CDP via `chrome.debugger`** as the primary screenshot method, with
`captureVisibleTab` as an automatic fallback. This hybrid approach eliminates the
focus-stealing and rate-limiting problems of the previous implementation while maintaining
zero bot-detection risk.

### How It Works

```
MCP/WebSocket → background.js → chrome.debugger.attach(tabId)
                               → Page.captureScreenshot (CDP)
                               → chrome.debugger.detach(tabId)
                               → base64 PNG returned
```

The `chrome.debugger` extension API provides full CDP access without:
- Setting `navigator.webdriver` (only `--remote-debugging-port` does that)
- Opening a network port (no port scanning possible)
- Changing the TLS fingerprint
- Requiring any browser launch flags

The only visible side effect is a brief yellow infobar ("Extension is debugging this
browser") that appears during the attach/detach window (~100-300ms). This is a browser
chrome UI element — no page script can detect it. In the typical automation scenario,
the automated tab is in a different window or not in focus, so the user never sees it.

### Fallback Behavior

If CDP is unavailable — which only happens when another debugger is already attached
to the target tab (e.g., DevTools is open on it) — StealthDOM falls back to the
`captureVisibleTab` approach automatically. This fallback:
- Activates the tab and focuses its window
- Captures via `chrome.tabs.captureVisibleTab`
- Re-minimizes the window if it was minimized before

The fallback is transparent to the caller — the response shape is identical.

### Full-Page Screenshots

For full-page captures, CDP uses `Page.getLayoutMetrics` to measure the full document,
`Emulation.setDeviceMetricsOverride` to expand the virtual viewport, and
`Page.captureScreenshot` with `captureBeyondViewport: true` to render everything in
a single shot. No scrolling, no stitching, no sticky-element hiding needed.

If CDP fails, the fallback uses the v3.0.x scroll-and-stitch approach:
1. Measures scrollHeight and viewport dimensions
2. Detects and hides sticky/fixed elements during middle frames
3. Scrolls through the page, capturing each viewport chunk
4. Stitches all frames into a single PNG using OffscreenCanvas

---

## Previous Approaches

### `captureVisibleTab` (v3.0.0–v3.1.0, now fallback)

`chrome.tabs.captureVisibleTab` — the only Chrome extension API for taking screenshots —
requires the target tab's window to be **focused and visible** on screen. Every screenshot
forces the browser window to pop to the front.

StealthDOM mitigated this by:
- Recording `targetWindow.state` before stealing focus
- Re-minimizing the window after capture if `wasMinimized === true`
- Adding a Promise-based mutex to prevent quota saturation
- Adding `captureWithRetry()` with exponential backoff for rate-limit errors

The flash was still visible (~150ms) and rate-limited to ~2 calls/second.

### Playwright / Puppeteer — CDP `Page.captureScreenshot` via `--remote-debugging-port`

Playwright uses CDP via a remote debugging port, which renders and captures entirely
off-screen. However, launching Chrome with `--remote-debugging-port` sets
`navigator.webdriver = true`, adds a detectable DevTools socket, changes the TLS
fingerprint, and causes Cloudflare/DataDome to score the session as a bot.

**StealthDOM's `chrome.debugger` approach achieves the same CDP benefits without any
of these detection vectors** — it's the extension-native path to CDP.

### `html2canvas` / `dom-to-image`

JavaScript libraries that re-render the DOM onto a Canvas element. No focus required,
completely silent, but ~90% visual fidelity (CSS animations, WebGL, and cross-origin
iframes are lost). This remains a viable third option if both CDP and captureVisibleTab
are unsuitable.

---

## Comparison Table

|  | CDP (`chrome.debugger`) | `captureVisibleTab` | `html2canvas` |
|---|---|---|---|
| Focus required | ❌ No (silent) | ✅ Yes (disruptive) | ❌ No (silent) |
| Rate limit | None | ~2 calls/sec | None |
| Visual fidelity | 100% — GPU composite | 100% — GPU composite | ~90% — DOM re-render |
| WebGL / Canvas | ✅ Captured | ✅ Captured | ❌ Often blank |
| Cross-origin iframes | ✅ Captured | ✅ Captured | ❌ Blocked by CORS |
| CSS animations | ✅ Current frame | ✅ Current frame | ❌ Static snapshot |
| Full-page (single shot) | ✅ captureBeyondViewport | ❌ Scroll-stitch | ❌ Manual scroll |
| Bot detection risk | Zero | Zero | Zero |
| Extension required | ✅ Yes (`debugger` perm) | ✅ Yes | ❌ No (pure JS) |

---

## References

- [Chrome Extension API — `captureVisibleTab`](https://developer.chrome.com/docs/extensions/reference/api/tabs#method-captureVisibleTab)
- [Chrome Extension API — `chrome.debugger`](https://developer.chrome.com/docs/extensions/reference/api/debugger)
- [Chrome DevTools Protocol — `Page.captureScreenshot`](https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-captureScreenshot)
- [Chrome DevTools Protocol — `Page.getLayoutMetrics`](https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-getLayoutMetrics)
- [html2canvas](https://html2canvas.hertzen.com/)
- [dom-to-image-more](https://github.com/1904labs/dom-to-image-more) — modern fork, better CSS support
