# StealthDOM Future Work & Ideas

This document tracks upcoming features, architectural ideas, and improvements for the StealthDOM ecosystem.

## Pending Implementation
- [ ] **Tab Discarding (`browser_discard_tab`)**
  - **Description**: Add a new background command `chrome.tabs.discard(tabId)` to forcefully put a tab into Memory Saver (sleeping) mode.
  - **Purpose**: Allows developers to write test cases that explicitly test an agent's ability to handle and recover from discarded tabs.

- [x] **CDP-based Native Mouse Interactions (`browser_mouse_*`)** ✅ Implemented
  - **Description**: Exposed a suite of 6 MCP tools using `chrome.debugger` + `Input.dispatchMouseEvent` for native, system-level mouse interactions with `isTrusted: true` events:
    - `browser_mouse_move(tab_id, x, y, steps, duration)`: Move mouse with interpolated trajectory and random jitter.
    - `browser_mouse_click(tab_id, x, y, button, click_count)`: Native click, double-click, or right-click via CDP.
    - `browser_mouse_down(tab_id, x, y, button)` & `browser_mouse_up(tab_id, x, y, button)`: Atomic hold/release via CDP.
    - `browser_mouse_drag(tab_id, start_x, start_y, end_x, end_y, steps, duration)`: Full drag sequence in a single debugger session via CDP.
    - `browser_mouse_wheel(tab_id, x, y, delta_x, delta_y)`: Native scroll wheel events via CDP.
  - **Implementation**: Background script handlers (`withDebugger` helper + 6 command functions), MCP server wrappers, and full API documentation.

## Architectural Ideas
- [ ] **JavaScript Render Composition Fallback (html2canvas)**
  - **Description**: If CDP `captureScreenshot` fails (e.g., because the browser is fully occluded or minimized), automatically inject a library like `html2canvas` into the content script to manually read the DOM tree and paint it onto an HTML5 `<canvas>`.
  - **Purpose**: Provides a highly resilient visual fallback for Vision-Language Models that works completely independently of the Chromium graphics compositor.

- [ ] **Built-in Proxy Support and Management**
  - **Description**: Add the ability to proxy requests through the StealthDOM node. Furthermore, implement an automated pipeline to fetch proxy lists from the internet, test/verify their connectivity, and maintain a never-ending, rotating pool of healthy proxies for the extension to use.
  - **Purpose**: Greatly enhances stealth capabilities by rotating IPs and prevents rate-limiting across large-scale automation tasks.
