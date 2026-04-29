# Screenshot Approaches — Architecture, Trade-offs & Detection Analysis

*CDP screenshots introduced in v3.2.0*

---

## The Problem (v3.0.0–v3.1.0)

Prior to v3.2.0, StealthDOM relied on `chrome.tabs.captureVisibleTab` for screenshots — the only screenshot API available to Chrome extensions. This API has three painful limitations:

1. **Focus stealing.** Every screenshot forces the browser to activate the target tab and bring its window to the front. If the user is working in another window, StealthDOM yanks focus away from them. If the window was minimized, it pops up on screen.

2. **Rate limiting.** Chrome enforces a hard quota of ~2 `captureVisibleTab` calls per second. Exceeding this — easy to do during full-page scroll-stitch captures or parallel tool calls — throws `MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND` errors that are difficult to recover from because even failed calls consume the quota.

3. **Complex full-page logic.** Since `captureVisibleTab` only captures the visible viewport, full-page screenshots require scrolling through the page frame by frame, hiding sticky elements to avoid duplication, stitching frames in an OffscreenCanvas, and handling edge cases like lazy-loaded content. This is 100+ lines of fragile code.

These were documented as Issues 2 and 4 in `KNOWN_ISSUES.md`. Despite mitigations (a mutex for the quota, state-restore for the focus steal), the fundamental limitations of the API could not be worked around.

---

## The Solution (v3.2.0)

v3.2.0 replaces `captureVisibleTab` with **CDP (Chrome DevTools Protocol) via the `chrome.debugger` extension API** as the primary screenshot method. CDP's `Page.captureScreenshot` command renders directly from the compositor pipeline — no window focus, no tab activation, no rate limits, no scroll-stitch.

The old `captureVisibleTab` path is retained as an automatic, transparent fallback for the rare case when CDP is unavailable.

### What changed

| Before (v3.1.0) | After (v3.2.0) |
|---|---|
| Screenshots steal window focus | Screenshots are completely silent — no focus change |
| ~2 captures/sec rate limit | No rate limit |
| Full-page requires scroll-stitch (8+ frames) | Full-page renders in a single shot |
| 150ms visible window flash | Zero visual disruption |
| Minimized windows pop to front | Minimized windows stay minimized |
| Mutex + retry logic needed | No serialization needed |

### How it works

```
MCP/WebSocket → background.js → chrome.debugger.attach(tabId)
                               → Page.captureScreenshot (CDP)
                               → chrome.debugger.detach(tabId)
                               → base64 PNG returned
```

For full-page captures, CDP uses `Page.getLayoutMetrics` to measure the full document, `Emulation.setDeviceMetricsOverride` to expand the virtual viewport, and `Page.captureScreenshot` with `captureBeyondViewport: true` to render everything in a single shot.

### When does the fallback activate?

CDP failure is extremely rare in practice. There are only two scenarios:

- **DevTools is open on the exact tab being captured.** Chrome allows only one debugger per tab. If the user has DevTools open on the specific tab StealthDOM is trying to screenshot, `chrome.debugger.attach()` fails with "Another debugger is already attached." The user would have to be inspecting the exact tab being automated.

- **The tab is a browser-internal page** (`chrome://`, `brave://`, etc.) — Chrome blocks debugger attachment to these pages. But StealthDOM already rejects commands on internal pages, so this isn't a new failure.

In both cases, the fallback to `captureVisibleTab` is silent. The response shape is identical regardless of which path was used — the caller never knows.

---

## Why Not Playwright's CDP?

CDP is the protocol that powers Playwright, Puppeteer, and Chrome DevTools. But there are **two completely different ways** to access it, and one is bot-detectable while the other is not.

### Path 1: `--remote-debugging-port` (What Playwright Uses)

Playwright launches Chrome with a command-line flag that opens a WebSocket debugging port:

```bash
chrome.exe --remote-debugging-port=9222
```

This triggers a cascade of detectable signals:
- Sets `navigator.webdriver = true`
- Opens a **network-accessible WebSocket port** (e.g., `ws://127.0.0.1:9222`)
- Changes process launch flags visible to fingerprinting
- May alter TLS handshake behavior

This is the primary detection vector for all Playwright/Puppeteer automation. Anti-bot systems (Cloudflare, DataDome, PerimeterX) specifically look for these signals.

### Path 2: `chrome.debugger` Extension API (What StealthDOM Uses)

The `chrome.debugger` API is a **built-in Manifest V3 extension API** that gives full CDP access without any of the detection baggage:

```javascript
// Attach CDP to a tab from the extension's background script
await chrome.debugger.attach({ tabId: 12345 }, '1.3');

// Full CDP command access — same protocol, zero detection surface
const screenshot = await chrome.debugger.sendCommand(
    { tabId: 12345 },
    'Page.captureScreenshot',
    { format: 'png', quality: 100 }
);

// Detach immediately — sub-second attach window
await chrome.debugger.detach({ tabId: 12345 });
```

What `chrome.debugger` does **NOT** do:
- ❌ Does NOT set `navigator.webdriver = true`
- ❌ Does NOT open a network port (no port scanning possible)
- ❌ Does NOT change TLS fingerprint
- ❌ Does NOT modify process launch flags

What it **does** do:
- ✅ Shows a brief yellow infobar during the attach window (see below)
- ✅ Requires the `debugger` permission in `manifest.json`
- ✅ Gives full CDP domain access (Page, Network, Fetch, Runtime, etc.)

---

## Detection Analysis

### 1. The Yellow Infobar — Non-Issue ✅

When `chrome.debugger.attach()` is called, Chrome shows a yellow "Extension is debugging this browser" bar. When `chrome.debugger.detach()` is called, it disappears immediately.

**This is irrelevant for StealthDOM's use case:**
- No page script can detect it — it's browser chrome UI, completely outside the DOM
- CDP's `Page.captureScreenshot` captures renderer output, not browser chrome — the infobar never appears in screenshots
- The infobar only appears on the window containing the attached tab — if the user is working in a different window or tab (the typical automation scenario), they never see it
- With on-demand attach/detach (attach → screenshot → detach in <300ms), the bar barely flashes before disappearing

> **Optional:** Chrome supports `--silent-debugger-extension-api` as a launch flag to suppress the bar entirely if desired, but it is not necessary for stealth.

### 2. `navigator.webdriver` — Not Applicable ✅

The `chrome.debugger` API does not set `navigator.webdriver`. This detection vector is entirely specific to `--remote-debugging-port`. Even if a future Chrome version added debugger-related properties, the extension can pre-emptively patch them at `document_start` in the MAIN world before any page script runs:

```javascript
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true
});
delete Navigator.prototype.webdriver;
```

### 3. Port Scanning — Not Applicable ✅

With `chrome.debugger`, there is no open WebSocket port. Anti-bot scripts that probe `ws://127.0.0.1:9222/json` will find nothing. This is the single biggest advantage over `--remote-debugging-port`.

### 4. Timing Side Channels — Very Low Risk ⚠️

When `chrome.debugger` is attached, CDP event listeners fire for every script parsed by V8. In theory, this adds microsecond-level overhead detectable via timing analysis. In practice, `performance.now()` is clamped to 5μs resolution in cross-origin contexts, and no known anti-bot system fingerprints debugger attachment latency.

### 5. `debugger;` Statement Pauses — Blockable ✅

Anti-bot scripts use inline `debugger;` statements to detect open DevTools. **Countermeasure:** never enable the Debugger domain. StealthDOM only uses `Page.captureScreenshot`, `Page.getLayoutMetrics`, and `Emulation.setDeviceMetricsOverride` — the `Debugger` domain remains inactive and `debugger;` statements execute as no-ops.

---

## Alternative: `html2canvas` / `dom-to-image`

JavaScript libraries that re-render the DOM onto a Canvas element. No focus required, completely silent, but ~90% visual fidelity — CSS animations, WebGL, and cross-origin iframes are lost. This remains a viable third option if both CDP and `captureVisibleTab` are unsuitable for a specific use case.

---

## Comparison Table

|  | CDP (`chrome.debugger`) | `captureVisibleTab` | `html2canvas` |
|---|---|---|---|
| **Status in StealthDOM** | **Primary (v3.2.0)** | Fallback | Not implemented |
| Focus required | ❌ No (silent) | ✅ Yes (disruptive) | ❌ No (silent) |
| Rate limit | None | ~2 calls/sec | None |
| Visual fidelity | 100% — GPU composite | 100% — GPU composite | ~90% — DOM re-render |
| WebGL / Canvas | ✅ Captured | ✅ Captured | ❌ Often blank |
| Cross-origin iframes | ✅ Captured | ✅ Captured | ❌ Blocked by CORS |
| CSS animations | ✅ Current frame | ✅ Current frame | ❌ Static snapshot |
| Full-page (single shot) | ✅ `captureBeyondViewport` | ❌ Scroll-stitch | ❌ Manual scroll |
| Bot detection risk | Zero | Zero | Zero |

---

## Architecture: Hybrid Stealth Model

```
┌──────────────────────────────────────────────────────────────┐
│  StealthDOM Extension (Hybrid Mode — v3.2.0)                 │
│                                                              │
│  Content Scripts (unchanged — zero detection)                │
│  ├── DOM queries: querySelector, getText, getHTML, etc.       │
│  ├── DOM interaction: click, type, fill, hover, drag, etc.   │
│  ├── Keyboard/mouse: keyPress, keyCombo, scroll, etc.        │
│  └── Proxy fetch: browser-native fetch() with real TLS       │
│                                                              │
│  chrome.debugger CDP (v3.2.0 — near-zero detection)          │
│  ├── Screenshots: Page.captureScreenshot (no focus needed)    │
│  ├── Network bodies: Fetch.requestPaused (full interception) │
│  ├── Console capture: Runtime.consoleAPICalled               │
│  └── DOM snapshots: DOMSnapshot.captureSnapshot              │
│                                                              │
│  Anti-Detection Layer (MAIN world, document_start)           │
│  ├── navigator.webdriver override                            │
│  ├── Navigator.prototype cleanup                             │
│  └── Future-proof property patching                          │
└──────────────────────────────────────────────────────────────┘
```

The key principle: **use CDP only for what the extension API can't do well**, while keeping all DOM interaction through content scripts where it's truly invisible.

---

## Implementation Details

The `debugger` permission is declared in `manifest.json`. No browser launch flags are required.

### Attach/Detach Strategy

The debugger is attached **on-demand** and detached immediately after each screenshot, limiting the timing side-channel window to ~100-300ms:

```javascript
await chrome.debugger.attach({ tabId }, '1.3');   // ~50ms
const result = await chrome.debugger.sendCommand(  // ~100ms
    target, 'Page.captureScreenshot', opts
);
await chrome.debugger.detach({ tabId });            // ~50ms
```

### Graceful Fallback

```javascript
// Actual implementation in background.js
async function cmdCaptureScreenshot(tabId) {
    // Primary: CDP (no focus, no quota, no rate limit)
    try {
        return await cmdCaptureScreenshotCDP(tabId);
    } catch (cdpError) {
        // DevTools open on this tab? Fall back silently.
        console.log('[StealthDOM] CDP unavailable, falling back:', cdpError.message);
    }
    // Fallback: captureVisibleTab (focus-steal + mutex + retry)
    // ... unchanged legacy code ...
}
```

---

## Risk Assessment

| Detection Vector | Risk Level | Notes |
|---|---|---|
| `navigator.webdriver` | ✅ None | `chrome.debugger` doesn't set it |
| Network port scanning | ✅ None | No port opened |
| TLS fingerprint | ✅ None | Same browser, same TLS stack |
| Yellow infobar | ✅ None | Browser chrome UI, invisible to page scripts |
| Process launch flags | ✅ None | No launch flags required |
| Timing side channels | ⚠️ Negligible | No known anti-bot system uses this |
| `debugger;` pauses | ✅ None | Debugger domain never enabled |
| Future Chrome changes | ⚠️ Low | Unchanged for 15+ years; breaking it affects legitimate extensions |

**Overall detection risk: Near-zero** — comparable to the content-script-only approach, with significant capability gains.

---

## Future CDP Capabilities

Now that the `chrome.debugger` pipeline is established, these become trivial to add:

| Capability | CDP Domain | Current Limitation |
|---|---|---|
| Read HTTP response bodies | `Fetch.requestPaused` | Network capture only gets headers |
| Modify responses in-flight | `Fetch.fulfillRequest` | Only header-level `declarativeNetRequest` |
| Stream console output | `Runtime.consoleAPICalled` | Must use `browser_evaluate` workarounds |

---

## References

- [Chrome Extension API — `captureVisibleTab`](https://developer.chrome.com/docs/extensions/reference/api/tabs#method-captureVisibleTab)
- [Chrome Extension API — `chrome.debugger`](https://developer.chrome.com/docs/extensions/reference/api/debugger)
- [Chrome DevTools Protocol — `Page.captureScreenshot`](https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-captureScreenshot)
- [Chrome DevTools Protocol — `Page.getLayoutMetrics`](https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-getLayoutMetrics)
- [html2canvas](https://html2canvas.hertzen.com/)
- [dom-to-image-more](https://github.com/1904labs/dom-to-image-more)
