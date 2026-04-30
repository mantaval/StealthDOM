# StealthDOM — Known Issues

*Last updated: v3.2.0*

---

## Service Worker Lifecycle (For Developers Modifying StealthDOM)

Chromium's Manifest V3 service workers (`background.js`) are aggressively put to sleep after ~30 seconds of inactivity to save memory. StealthDOM mitigates this with a 20-second keepalive ping, but the service worker may still occasionally restart. This is totally normal, and the Python bridge handles these restarts automatically by silently reconnecting within 3 seconds.

**Developer Tip:** If you are actively modifying the StealthDOM extension code and are annoyed by the background script going to sleep while you debug it, there is a handy trick: go to `chrome://extensions` and click the "service worker" link to manually open the F12 DevTools window for the extension. As long as that specific DevTools window remains open, Chrome assumes a human is debugging it and will permanently keep the background script awake.

---

## Content Script Stale After Extension Reload

After reloading the extension in the browser's extensions page, content scripts on already-open pages become stale. Commands will fail with "Content script error..." or "No response from content script...". 

AI agents will automatically receive this helpful hint in their error payload:
*(If the extension was recently reloaded or the tab is unresponsive, use browser_reload to refresh the tab and re-inject the script)*

**Workaround:** You can programmatically execute `browser_reload`, or manually refresh the tab yourself (e.g., hit F5), to re-inject the content script before interacting with the page again.

---

## Background Tab Throttling & The Anti-Throttle System

Chromium throttles background tabs, which can delay DOM interactions. StealthDOM includes an anti-throttle system in `content_script.js` that mutates the DOM every 15 seconds and overrides `document.hidden` / `visibilityState`. 

**What this protects against:**
This system successfully tricks the *website's JavaScript environment* (e.g., React apps, YouTube, web games). It prevents sites from pausing video playback, halting internal timers, or stopping data fetching when the tab loses focus.

**What this DOES NOT protect against:**
The anti-throttle offers zero protection against Chromium's OS/Renderer-level resource managers, which aggressively optimize system resources and completely ignore JavaScript execution states:

1. **Memory Saver (Sleeping Tabs)**: This operates at the OS/Renderer level. When Chrome needs RAM, it acts like a grim reaper and completely kills the renderer process. The DOM is destroyed, the JavaScript engine is halted, and our anti-throttle `setInterval` is wiped from memory entirely. Chrome leaves a "tombstone" tab in the UI. If an agent tries to execute commands on a discarded tab, it will fail with "Cannot access a discarded tab." 
   * **Workaround:** The agent must use `browser_reload` or `browser_switch_tab` to wake the tab up before interacting with it.

2. **Suspended Graphics (Occlusion Tracking / Minimized Windows)**: This operates at the GPU/Compositor level. Even if our anti-throttle is mutating the DOM every 15 seconds, if the window is completely minimized or 100% occluded by an Always-on-Top application, Chromium's compositor refuses to paint new frames to save GPU cycles. Because visual screenshots (`captureVisibleTab`) wait for the *next painted frame*, they will hang and timeout waiting for a paint that will never happen.
   * **Workaround:** If screenshots are required but you want the browser hidden, use `browser_resize_window` to position the window completely off-screen (e.g., `left: -10000`, `top: -10000`) instead of minimizing it.

---

## Resolved Issues

All previously documented issues have been resolved:

| Issue | Resolution |
|---|---|
| Cross-frame DOM access (framesets, iframes) | Fixed in v3.0.2 — see [Architecture](../docs/01_architecture.md) |
| `captureVisibleTab` quota errors | Eliminated in v3.2.0 — see [Screenshot Approaches](../docs/04_screenshot_approaches.md) |
| Full-page screenshot stack overflow | Fixed in v3.0.1 |
| Window focus steal during screenshots | Eliminated in v3.2.0 — see [Screenshot Approaches](../docs/04_screenshot_approaches.md) |
