# Benefits of CDP Addition (Implemented v3.2.0)

## Overview

As of v3.2.0, StealthDOM uses CDP (Chrome DevTools Protocol) via the `chrome.debugger`
extension API as the **primary screenshot method**. The previous approach — `captureVisibleTab` —
remains as an automatic fallback. This hybrid eliminates window focus stealing, rate-limit
quota errors, and the complex scroll-stitch logic for full-page screenshots, while maintaining
zero bot-detection risk.

---

## Two Paths to CDP

### Path 1: `--remote-debugging-port` (What Playwright Uses)

Chrome is launched with a flag that:
- Sets `navigator.webdriver = true`
- Opens a **network-accessible WebSocket port** (e.g., `ws://127.0.0.1:9222`)
- Changes process launch flags visible to fingerprinting
- May alter TLS handshake behavior

This is the primary detection vector for Playwright, Puppeteer, and similar tools.
Anti-bot systems (Cloudflare, DataDome, PerimeterX) specifically look for these signals.

### Path 2: `chrome.debugger` Extension API (The Viable Path)

This is a **built-in Manifest V3 extension API** that gives full CDP access without
any launch-flag baggage:

```javascript
// Attach CDP to a tab from the extension's background script
await chrome.debugger.attach({ tabId: 12345 }, '1.3');

// Full CDP command access
const screenshot = await chrome.debugger.sendCommand(
    { tabId: 12345 },
    'Page.captureScreenshot',
    { format: 'png', quality: 100 }
);
```

What `chrome.debugger` does **NOT** do:
- ❌ Does NOT set `navigator.webdriver = true`
- ❌ Does NOT open a network port (no port scanning possible)
- ❌ Does NOT change TLS fingerprint
- ❌ Does NOT modify process launch flags

What it **does** do:
- ✅ Shows a yellow infobar: *"StealthDOM is debugging this browser"*
- ✅ Requires the `debugger` permission in `manifest.json`
- ✅ Gives full CDP domain access (Page, Network, Fetch, Runtime, etc.)

---

## Detection Vectors and Countermeasures

### 1. The Yellow Infobar — Non-Issue ✅

When `chrome.debugger.attach()` is called, Chrome shows a yellow "Extension is debugging
this browser" bar. When `chrome.debugger.detach()` is called, it disappears immediately.

**This is irrelevant for StealthDOM's use case:**
- No page script can detect it — it's browser chrome UI, completely outside the DOM
- CDP's `Page.captureScreenshot` captures renderer output, not browser chrome — the
  infobar never appears in screenshots
- The infobar only appears on the window containing the attached tab — if the user is
  working in a different window or tab (the typical automation scenario), they never see it
- With on-demand attach/detach (attach → screenshot → detach in <300ms), the bar
  barely flashes before disappearing
- StealthDOM users care about site-level bot detection, not cosmetic UI elements

> **Optional:** Chrome supports `--silent-debugger-extension-api` as a launch flag to
> suppress the bar entirely if desired, but it is not necessary for stealth.

### 2. `navigator.webdriver` — Not Applicable ✅

The `chrome.debugger` API does not set `navigator.webdriver` at all. This detection vector
is entirely specific to `--remote-debugging-port` and Playwright-style automation.

Even if a future Chrome version added debugger-related properties, the extension can
pre-emptively patch them at `document_start` in the MAIN world before any page script runs:

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

With `chrome.debugger`, there is no open WebSocket port. Anti-bot scripts that probe
`ws://127.0.0.1:9222/json` (or common debugging port ranges) will find nothing.

This is the single biggest advantage over `--remote-debugging-port`.

### 4. Debugger-Attached Timing Side Channels — Very Low Risk ⚠️

When `chrome.debugger` is attached, CDP event listeners (like `Debugger.scriptParsed`)
fire for every script parsed by V8. In theory, this adds microsecond-level overhead that
could be detected via high-resolution timing analysis.

In practice:
- `performance.now()` is clamped to 5μs resolution in cross-origin contexts
- No known anti-bot system fingerprints debugger attachment latency
- The overhead occurs in Chrome's C++ IPC layer, not in observable JS execution
- If the `Debugger` domain is never enabled (see below), these events don't fire

**Risk: Negligible with current anti-bot technology.**

### 5. `Error.stack` Behavioral Differences — Negligible ⚠️

Some debugging implementations change how error stack traces are formatted. With
`chrome.debugger`, this is not the case — V8 produces identical stack traces whether
or not the debugger is attached. The CDP protocol operates at a different layer than
the JS engine's error handling.

### 6. `debugger;` Statement / Pause Detection — Blockable ✅

Sophisticated anti-bot scripts use inline `debugger;` statements to detect if DevTools
is open. When a debugger is attached and the Debugger domain is enabled, these statements
cause the page to pause, creating a detectable timing gap.

**Countermeasure:** Simply never enable the Debugger domain. If you only use
`Page.captureScreenshot`, `Fetch.requestPaused`, and similar domains, the `Debugger`
domain remains inactive and `debugger;` statements execute as no-ops:

```javascript
// Only enable the domains you need — never touch Debugger domain
await chrome.debugger.sendCommand(tabId, 'Page.enable');
await chrome.debugger.sendCommand(tabId, 'Fetch.enable', {
    patterns: [{ urlPattern: '*', requestStage: 'Response' }]
});
// Debugger domain is NOT enabled — debugger; statements are harmless
```

---

## Proposed Hybrid Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  StealthDOM Extension (Hybrid Mode)                          │
│                                                              │
│  Content Scripts (unchanged — zero detection)                │
│  ├── DOM queries: querySelector, getText, getHTML, etc.       │
│  ├── DOM interaction: click, type, fill, hover, drag, etc.   │
│  ├── Keyboard/mouse: keyPress, keyCombo, scroll, etc.        │
│  └── Proxy fetch: browser-native fetch() with real TLS       │
│                                                              │
│  chrome.debugger CDP (new — near-zero detection)             │
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

The key principle: **use CDP only for what the extension API can't do well**, while
keeping all DOM interaction through content scripts where it's truly invisible.

---

## What CDP Would Solve

| Current Pain Point | Current Workaround | CDP Solution |
|---|---|---|
| Screenshots require tab focus + window activation | `chrome.tabs.captureVisibleTab` with focus-steal/restore | `Page.captureScreenshot` — works on background tabs silently |
| `MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND` quota | Mutex + retry with backoff (captureWithRetry) | CDP has no rate limit for screenshots |
| Window state disruption during screenshots | Save/restore minimized state | No window state changes needed |
| Cannot read HTTP response bodies | Network capture only gets headers | `Fetch.requestPaused` gives full body access |
| Cannot modify response bodies in-flight | Only header-level `declarativeNetRequest` | `Fetch.fulfillRequest` can rewrite response bodies |
| No programmatic console output access | Must use `browser_evaluate` workarounds | `Runtime.consoleAPICalled` streams console output |
| Full-page screenshot is complex scroll-stitch | 50+ lines of scroll/capture/stitch logic | `Page.captureScreenshot` with `captureBeyondViewport: true` |

---

## Implementation Details

The `debugger` permission is declared in `manifest.json`. No browser launch flags are required.

### Graceful Fallback

CDP is the primary path. If `chrome.debugger.attach()` fails, StealthDOM falls back to
`captureVisibleTab` automatically. In practice, CDP failure is extremely rare:

- **Another debugger is already attached to the tab** — Chrome only allows one debugger
  per tab. If the user has DevTools open on the exact tab being screenshotted,
  `chrome.debugger.attach()` throws `"Another debugger is already attached"`. This is the
  only realistic failure mode during normal automation.
- **Tab is a browser-internal page** (`chrome://`, `brave://`, etc.) — Chrome blocks debugger
  attachment to these pages for security. But StealthDOM already blocks commands on these
  pages anyway, so this isn't a new failure.

The `try/catch` exists as defensive programming for these edge cases and any unexpected
Chrome bugs. The fallback is transparent — the response shape is identical regardless
of which path was used.

```javascript
// Actual implementation in background.js
async function cmdCaptureScreenshot(tabId) {
    try {
        return await cmdCaptureScreenshotCDP(tabId);      // CDP: no focus, no quota
    } catch (cdpError) {
        // DevTools open on this tab? Fall back silently.
    }
    // ... captureVisibleTab fallback (focus-steal + mutex + retry) ...
}
```

### Attach/Detach Strategy

The debugger is attached **on-demand** and detached immediately after each screenshot.
This limits the theoretical timing side-channel window to ~100-300ms per call:

```javascript
await chrome.debugger.attach({ tabId }, '1.3');   // ~50ms
const result = await chrome.debugger.sendCommand(  // ~100ms
    target, 'Page.captureScreenshot', opts
);
await chrome.debugger.detach({ tabId });            // ~50ms
```

---

## Risk Assessment

| Detection Vector | Risk Level | Notes |
|---|---|---|
| `navigator.webdriver` | ✅ None | `chrome.debugger` doesn't set it |
| Network port scanning | ✅ None | No port opened |
| TLS fingerprint | ✅ None | Same browser, same TLS stack |
| Yellow infobar | ✅ None | Suppressed by `--silent-debugger-extension-api` |
| Process launch flags | ✅ None | Only `--silent-debugger-extension-api` added (not scanned by anti-bot) |
| Timing side channels | ⚠️ Negligible | No known anti-bot system uses this |
| `debugger;` statement pauses | ✅ None | Don't enable the Debugger domain |
| Future Chrome API changes | ⚠️ Low | Google hasn't changed this in 15+ years; breaking it would affect legitimate devtools extensions |

**Overall detection risk: Near-zero** — comparable to the current extension-only approach,
with significant capability gains.

---

## Conclusion

The `chrome.debugger` extension API provides CDP capabilities without the detection
baggage of `--remote-debugging-port`. As of v3.2.0, this is StealthDOM's primary
screenshot method — eliminating focus-stealing, rate limits, and scroll-stitch complexity
while maintaining zero bot-detection risk.

The key insight is that **`chrome.debugger` is an official, supported extension API** — it's
not a hack or an exploit. It's how Chrome's own DevTools extension communicates with the
browser, and Google has no incentive to make it detectable by web content.
