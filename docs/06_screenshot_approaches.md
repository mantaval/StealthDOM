# Screenshot Approaches — Trade-offs & Future Options

*Discussion notes: 2026-04-28*

---

## The Problem

`chrome.tabs.captureVisibleTab` — the only Chrome extension API for taking screenshots — requires the target tab's window to be **focused and visible** on screen. There is no way around this within the extension model. Every screenshot currently forces the browser window to pop to the front, disrupt the user's workflow, and stay there until the OS focus is restored manually.

StealthDOM partially mitigates this by re-minimizing the window immediately after capture (`chrome.windows.update({ state: 'minimized' })`), but the flash is still visible.

---

## How Other Tools Solve This

### 1. Playwright / Puppeteer — CDP `Page.captureScreenshot`

Playwright does not have this problem. It uses the **Chrome DevTools Protocol (CDP)**, specifically the `Page.captureScreenshot` command, which renders and captures a tab entirely off-screen without touching window focus.

```
Playwright → CDP (port 9222) → Chrome Renderer → PNG
```

The renderer captures directly from the compositing pipeline, not from what's physically on screen. The tab doesn't need to be active, visible, or even in a real window.

**Why StealthDOM can't use this:**  
CDP requires launching Chrome with `--remote-debugging-port`, which sets `navigator.webdriver = true`, adds a detectable DevTools socket, changes the TLS fingerprint, and causes Cloudflare/DataDome to score the session as a bot. This is the *primary detection vector* for Playwright. Using CDP for screenshots only would still expose the debugging port to page-level detection scripts.

---

### 2. Website Error Reporters — `html2canvas` / `dom-to-image`

Services like **Sentry**, **LogRocket**, and **FullStory** take screenshots without any focus manipulation. They inject a JavaScript library (`html2canvas`) that:

1. Walks the entire DOM tree using `document.querySelectorAll` and `getComputedStyle`
2. Re-paints every element onto an `<OffscreenCanvas>` using Canvas 2D API
3. Calls `canvas.toDataURL('image/png')` and uploads the result

This runs entirely in the page's JavaScript context — no privileged APIs, no focus required, completely silent. It is functionally identical to what we already do with `browser_evaluate`.

**Why this works without focus:**  
The Canvas 2D API renders from the DOM layout engine, not from the GPU compositor. It doesn't care what's on screen.

**Trade-offs:**
| | `captureVisibleTab` | `html2canvas` |
|---|---|---|
| Focus required | ✅ Yes (disruptive) | ❌ No (silent) |
| Visual fidelity | 100% — GPU composite | ~90% — DOM re-render |
| WebGL / Canvas elements | ✅ Captured | ❌ Often blank |
| Cross-origin iframes | ✅ Captured | ❌ Blocked by CORS |
| CSS animations | ✅ Current frame | ❌ Static snapshot |
| Extension required | ✅ Yes | ❌ No (pure JS) |
| Detection risk | Zero | Zero |

---

### 3. `chrome.pageCapture` API

Chrome extensions have a `chrome.pageCapture.saveAsMHTML()` API that saves the entire page (HTML + inlined resources) as an MHTML archive. This does **not** produce a visual screenshot — it's an HTML snapshot, not a PNG. Useful for archiving, not for visual capture.

---

## Recommended Future Implementation

If the focus-disruption problem becomes unacceptable, the cleanest path is:

### `browser_screenshot_silent` — html2canvas injection

1. Download `html2canvas.min.js` (~700KB) and place it in `extension/`
2. Add it to `manifest.json` `web_accessible_resources`
3. In `background.js`, create a new `cmdCaptureScreenshotSilent(tabId)` that:
   - Injects `html2canvas.min.js` via `chrome.scripting.executeScript`
   - Calls `html2canvas(document.body).then(c => c.toDataURL())`
   - Returns the data URL

```javascript
async function cmdCaptureScreenshotSilent(tabId) {
    await chrome.scripting.executeScript({
        target: { tabId },
        files: ['html2canvas.min.js'],
    });
    const results = await chrome.scripting.executeScript({
        target: { tabId },
        world: 'MAIN',
        func: () => html2canvas(document.documentElement)
            .then(canvas => canvas.toDataURL('image/png')),
    });
    return { success: true, data: { dataUrl: results[0].result } };
}
```

4. Expose as `browser_screenshot_silent` in `stealth_dom_mcp.py`

No window manipulation. No focus change. Completely invisible to the user.

---

## Current StealthDOM Behavior (as of v3.0.0)

- `browser_screenshot` and `browser_screenshot_full_page` use `captureVisibleTab`
- Both record the window state **before** stealing focus (`wasMinimized`)
- Both re-minimize the window immediately after capture if it was minimized
- The flash is unavoidable but brief (~150–200ms for a single screenshot)
- Full-page screenshots flash for longer (one capture per viewport-height scroll step, each with a 150ms wait for lazy content)

---

## References

- [Chrome Extension API — `captureVisibleTab`](https://developer.chrome.com/docs/extensions/reference/api/tabs#method-captureVisibleTab)
- [Chrome DevTools Protocol — `Page.captureScreenshot`](https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-captureScreenshot)
- [html2canvas](https://html2canvas.hertzen.com/)
- [dom-to-image-more](https://github.com/1904labs/dom-to-image-more) — modern fork, better CSS support
