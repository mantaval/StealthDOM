# Benefits of CDP Addition (Implemented v3.2.0)

## The Problem

Prior to v3.2.0, StealthDOM relied on `chrome.tabs.captureVisibleTab` for screenshots — the only screenshot API available to Chrome extensions. This API has three painful limitations:

1. **Focus stealing.** Every screenshot forces the browser to activate the target tab and bring its window to the front. If the user is working in another window, StealthDOM yanks focus away from them. If the window was minimized, it pops up on screen.

2. **Rate limiting.** Chrome enforces a hard quota of ~2 `captureVisibleTab` calls per second. Exceeding this — easy to do during full-page scroll-stitch captures or parallel tool calls — throws `MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND` errors that are difficult to recover from because even failed calls consume the quota.

3. **Complex full-page logic.** Since `captureVisibleTab` only captures the visible viewport, full-page screenshots require scrolling through the page frame by frame, hiding sticky elements to avoid duplication, stitching frames in an OffscreenCanvas, and handling edge cases like lazy-loaded content. This is 100+ lines of fragile code.

These were documented as Issues 2 and 4 in `KNOWN_ISSUES.md`. Despite mitigations (a mutex for the quota, state-restore for the focus steal), the fundamental limitations of the API could not be worked around.

---

## The Solution

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

### When does the fallback activate?

CDP failure is extremely rare in practice. There are only two scenarios:

- **DevTools is open on the exact tab being captured.** Chrome allows only one debugger per tab. If the user has DevTools open on the specific tab StealthDOM is trying to screenshot, `chrome.debugger.attach()` fails with "Another debugger is already attached." The user would have to be inspecting the exact tab being automated.

- **The tab is a browser-internal page** (`chrome://`, `brave://`, etc.) — Chrome blocks debugger attachment to these pages. But StealthDOM already rejects commands on internal pages, so this isn't a new failure.

In both cases, the fallback to `captureVisibleTab` is silent. The response shape is identical regardless of which path was used — the caller never knows.

---

## Why Not Just Use Playwright's CDP?

CDP is the protocol that powers Playwright, Puppeteer, and Chrome DevTools. But there are **two completely different ways** to access it, and one of them is bot-detectable while the other is not.

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

The `chrome.debugger` API is a **built-in Manifest V3 extension API** that gives full CDP access without any of the detection baggage of `--remote-debugging-port`:

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

## Detection Vectors and Countermeasures

### 1. The Yellow Infobar — Non-Issue ✅

When `chrome.debugger.attach()` is called, Chrome shows a yellow "Extension is debugging this browser" bar. When `chrome.debugger.detach()` is called, it disappears immediately.

**This is irrelevant for StealthDOM's use case:**
- No page script can detect it — it's browser chrome UI, completely outside the DOM
- CDP's `Page.captureScreenshot` captures renderer output, not browser chrome — the infobar never appears in screenshots
- The infobar only appears on the window containing the attached tab — if the user is working in a different window or tab (the typical automation scenario), they never see it
- With on-demand attach/detach (attach → screenshot → detach in <300ms), the bar barely flashes before disappearing
- StealthDOM users care about site-level bot detection, not cosmetic UI elements

> **Optional:** Chrome supports `--silent-debugger-extension-api` as a launch flag to suppress the bar entirely if desired, but it is not necessary for stealth.

### 2. `navigator.webdriver` — Not Applicable ✅

The `chrome.debugger` API does not set `navigator.webdriver` at all. This detection vector is entirely specific to `--remote-debugging-port` and Playwright-style automation.

Even if a future Chrome version added debugger-related properties, the extension can pre-emptively patch them at `document_start` in the MAIN world before any page script runs:

```javascript
// content_script with run_at: "document_start", world: "MAIN"
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true
});
// Patch the prototype to defeat iframe-based cross-origin checks
delete Navigator.prototype.webdriver;
```

### 3. Port Scanning — Not Applicable ✅

With `chrome.debugger`, there is no open WebSocket port. Anti-bot scripts that probe `ws://127.0.0.1:9222/json` (or common debugging port ranges) will find nothing. This is the single biggest advantage over `--remote-debugging-port`.

### 4. Debugger-Attached Timing Side Channels — Very Low Risk ⚠️

When `chrome.debugger` is attached, CDP event listeners (like `Debugger.scriptParsed`) fire for every script parsed by V8. In theory, this adds microsecond-level overhead that could be detected via high-resolution timing analysis.

In practice:
- `performance.now()` is clamped to 5μs resolution in cross-origin contexts
- No known anti-bot system fingerprints debugger attachment latency
- The overhead occurs in Chrome's C++ IPC layer, not in observable JS execution
- If the `Debugger` domain is never enabled (see below), these events don't fire

**Risk: Negligible with current anti-bot technology.**

### 5. `Error.stack` Behavioral Differences — Negligible ⚠️

Some debugging implementations change how error stack traces are formatted. With `chrome.debugger`, this is not the case — V8 produces identical stack traces whether or not the debugger is attached. The CDP protocol operates at a different layer than the JS engine's error handling.

### 6. `debugger;` Statement / Pause Detection — Blockable ✅

Sophisticated anti-bot scripts use inline `debugger;` statements to detect if DevTools is open. When a debugger is attached and the Debugger domain is enabled, these statements cause the page to pause, creating a detectable timing gap.

**Countermeasure:** Simply never enable the Debugger domain. StealthDOM only uses `Page.captureScreenshot`, `Page.getLayoutMetrics`, and `Emulation.setDeviceMetricsOverride` — the `Debugger` domain remains inactive and `debugger;` statements execute as no-ops:

```javascript
// Only enable the domains you need — never touch Debugger domain
await chrome.debugger.sendCommand(tabId, 'Page.enable');
// Debugger domain is NOT enabled — debugger; statements are harmless
```

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

## What This Release Solves — and What CDP Enables Next

| Pain Point | Before (v3.1.0) | After (v3.2.0) |
|---|---|---|
| Screenshots require focus + window activation | `captureVisibleTab` with focus-steal/restore | `Page.captureScreenshot` — works silently on background tabs |
| `MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND` quota | Mutex + retry with backoff | CDP has no rate limit |
| Window state disruption | Save/restore minimized state | No window state changes needed |
| Full-page screenshots are fragile | 100+ lines of scroll/capture/stitch | Single-shot `captureBeyondViewport: true` |

**Future CDP capabilities** (not yet implemented, but now trivial to add):

| Capability | CDP Domain | Current Limitation |
|---|---|---|
| Read HTTP response bodies | `Fetch.requestPaused` | Network capture only gets headers |
| Modify responses in-flight | `Fetch.fulfillRequest` | Only header-level `declarativeNetRequest` |
| Stream console output | `Runtime.consoleAPICalled` | Must use `browser_evaluate` workarounds |

---

## Implementation Details

The `debugger` permission is declared in `manifest.json`. No browser launch flags are required.

### Attach/Detach Strategy

The debugger is attached **on-demand** and detached immediately after each screenshot. This limits the theoretical timing side-channel window to ~100-300ms per call:

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
    // Primary path: CDP (no focus, no quota, no rate limit)
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
| `debugger;` statement pauses | ✅ None | Don't enable the Debugger domain |
| Future Chrome API changes | ⚠️ Low | Google hasn't changed this in 15+ years; breaking it would affect legitimate devtools extensions |

**Overall detection risk: Near-zero** — comparable to the content-script-only approach, with significant capability gains.

---

## Conclusion

The `chrome.debugger` extension API provides full CDP capabilities without the detection baggage of `--remote-debugging-port`. As of v3.2.0, this is StealthDOM's primary screenshot method — eliminating focus-stealing, rate limits, and scroll-stitch complexity while maintaining zero bot-detection risk.

The key insight is that **`chrome.debugger` is an official, supported extension API** — it's not a hack or an exploit. It's how Chrome's own DevTools extension communicates with the browser, and Google has no incentive to make it detectable by web content.
