# StealthDOM — Known Issues

*Last updated: v3.2.0*

---

## Service Worker Lifecycle

Chromium's Manifest V3 service workers can be terminated after ~30 seconds of inactivity. StealthDOM mitigates this with a 20-second keepalive interval and a 5-second bridge heartbeat, but the service worker may still occasionally restart.

**Workaround:** The bridge auto-reconnects within 3 seconds. Opening the service worker's DevTools (from `chrome://extensions`) keeps it alive indefinitely during development.

---

## Content Script Stale After Extension Reload

After reloading the extension in the browser's extensions page, content scripts on already-open pages become stale — commands will fail with "Content script not ready."

**Workaround:** Refresh any tab you want to interact with after reloading the extension.

---

## Background Tab Throttling

Chromium throttles background tabs, which can delay DOM interactions. StealthDOM includes an anti-throttle system in the content script that overrides `document.hidden`, `visibilityState`, and intercepts `visibilitychange` events, but some throttling may still occur on heavily backgrounded tabs.

---

## Resolved Issues

All previously documented issues have been resolved:

| Issue | Resolution |
|---|---|
| Cross-frame DOM access (framesets, iframes) | Fixed in v3.0.2 — see [Architecture](../docs/01_architecture.md) |
| `captureVisibleTab` quota errors | Eliminated in v3.2.0 — see [Screenshot Approaches](../docs/04_screenshot_approaches.md) |
| Full-page screenshot stack overflow | Fixed in v3.0.1 |
| Window focus steal during screenshots | Eliminated in v3.2.0 — see [Screenshot Approaches](../docs/04_screenshot_approaches.md) |
