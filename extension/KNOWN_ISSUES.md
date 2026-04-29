# StealthDOM — Known Limitations & Applied Fixes

*Authored: 2026-04-28*

---

## Issue 1: `chrome.scripting.executeScript` Cannot Reach Cross-Frame Content

### Observed Behaviour
When navigating to Gmail's standalone compose URL (`https://mail.google.com/mail/u/0/?view=cm&...`), all DOM queries (`browser_evaluate`, `browser_query`, `browser_fill`, `browser_click`) return `null` or fail silently. Even `document.body` is `null`.

The page title is correctly retrieved via `chrome.tabs.get()`, proving the tab is loaded and the connection is alive — but script execution cannot find any elements.

### Root Cause
Gmail's `?view=cm` compose mode renders as a `<frameset>` document (no `<body>`). The actual UI lives inside nested `<frame>` elements. `chrome.scripting.executeScript` targets **only the top-level document** of the tab. It does not descend into `<frame>` or `<iframe>` elements from other origins.

The same issue affects any page that uses framesets or cross-origin iframes for its primary UI:
- Gmail standalone compose (`<frameset>`)
- Legacy web apps using framesets
- Embedded cross-origin iframes (e.g., payment widgets, OAuth dialogs)

### Fix Applied (v3.0.2)

Implemented a complete cross-frame solution in three layers:

1. **On-demand injection with `allFrames: true`** — Content scripts are injected lazily via `chrome.scripting.executeScript({ allFrames: true })` when the first command targets a tab (not declared in `manifest.json`). This injects into every `<frame>` and `<iframe>`, giving every frame native DOM query capabilities without requiring `eval()`, while saving memory on untouched tabs.

2. **`frameId` routing in `bridgeForwardToContentScript`** — The background script passes an optional `frameId` to `chrome.tabs.sendMessage()`, targeting a specific frame's content script. Without `frameId`, the top-level frame is targeted (backward compatible).

3. **`frame_id` parameter on all MCP DOM tools** — All 24 DOM reading and interaction tools (query, click, type, fill, hover, etc.) accept an optional `frame_id` parameter. Frame IDs are discovered via `browser_list_frames()`.

4. **`browser_list_frames(tab_id)`** — Enumerates every frame in a tab using `chrome.scripting.executeScript` with `allFrames: true`. Returns `{ frameIndex, frameId, url, title, hasBody, isFrameset, elementCount }` per frame.

5. **`browser_evaluate_all_frames(tab_id, code, world)`** — Executes arbitrary JS in ALL frames simultaneously, returning per-frame results with `frameIndex` and `frameId`. Includes Trusted Types fallback via `<script>` tag injection.

**Cross-frame workflow:** `browser_list_frames()` → find target `frameId` → pass `frame_id=N` to any DOM tool.

All tools are exposed as MCP tools and registered in the background script's command routing.


---

## Issue 2: `captureVisibleTab` Quota Errors on Rapid Screenshot Calls

### Observed Behaviour
When `browser_screenshot` or `browser_screenshot_full_page` is called in rapid succession (or retried after a failure), Chrome throws:
```
MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND
```
The quota persists across failed attempts — even failed calls consume the quota bucket, making recovery difficult.

### Root Cause
Chrome's `chrome.tabs.captureVisibleTab` API enforces a hard rate limit of ~2 calls/second per extension. Failed attempts still count against the limit. Parallel tool calls (e.g., attempting two screenshots simultaneously) immediately saturate the quota.

### Fix Applied (v3.0.1)
Added `captureWithRetry()` helper in `background.js` that catches quota errors and retries with exponential backoff (600ms base, 1.5× multiplier, 3s cap, 5 max attempts).

### Fix Applied (v3.0.2)
Added a Promise-based mutex (`_screenshotLock`) wrapping `captureWithRetry()`. The mutex ensures only one `captureVisibleTab` call can be in-flight at a time.

### Fix Applied (v3.2.0) — Eliminated
Switched to CDP-based screenshots via `chrome.debugger` API. CDP's `Page.captureScreenshot` has no rate limit — the `captureVisibleTab` quota is no longer relevant. The mutex and retry logic remain as the fallback path for when CDP is unavailable (e.g., DevTools is open on the target tab).

---

## Issue 3: Full-Page Screenshot Stack Overflow on Tall Pages

### Observed Behaviour
`browser_screenshot_full_page` throws `Maximum call stack size exceeded` on pages taller than ~3–4 viewports.

### Root Cause
The original base64 encoder used `String.fromCharCode.apply(null, largeUint8Array)` which passes the entire array as arguments to `apply()`. V8's call stack overflows at ~125,000 arguments. A 4-viewport-tall PNG easily exceeds this.

### Fix Applied (v3.0.1)
Replaced with a chunk-spread loop using chunks of 8,192 bytes — well under V8's argument limit, and orders of magnitude faster than a byte-by-byte loop. Live in current codebase.

---

## Issue 4: Window Focus Steal During Screenshots

### Observed Behaviour
`browser_screenshot` and `browser_screenshot_full_page` force the browser window to pop to the front of all OS windows. If the window was minimized, it stays maximized after the screenshot.

### Root Cause
Chrome's `captureVisibleTab` requires the target tab to be in an active, focused window. This is a hard browser limitation with no extension-level workaround.

### Fix Applied (v3.0.1)
Both screenshot functions now:
1. Record `targetWindow.state` before stealing focus
2. Re-minimize the window after capture if `wasMinimized === true`

### Fix Applied (v3.2.0) — Eliminated
Switched to CDP-based screenshots via `chrome.debugger` API. CDP's `Page.captureScreenshot` renders directly from the compositor pipeline — no window focus, no tab activation required. The focus-steal only occurs in the fallback path (when DevTools is open on the target tab).

See `docs/06_screenshot_approaches.md` and `docs/07_benefits_of_cdp_addition.md` for the full technical analysis.

---

## Summary Table

| # | Issue | Status | Effort to Fix |
|---|-------|--------|---------------|
| 1 | Cross-frame DOM access (`<frameset>`, iframes) | ✅ Fixed (v3.0.2) | Done — `browser_list_frames` + `browser_evaluate_all_frames` |
| 2 | `captureVisibleTab` quota errors | ✅ Eliminated (v3.2.0) | CDP has no rate limit; mutex/retry remain as fallback |
| 3 | Full-page screenshot stack overflow | ✅ Fixed | Done |
| 4 | Window focus steal during screenshots | ✅ Eliminated (v3.2.0) | CDP renders from compositor; no focus needed |

---

## All Issues Resolved

As of v3.2.0, all known issues are fully resolved. CDP-based screenshots via `chrome.debugger` eliminated the focus-stealing and rate-limiting problems entirely. The `captureVisibleTab` path remains as an automatic fallback.
