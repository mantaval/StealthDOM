# API Reference

> Complete reference for all StealthDOM commands. Each command can be invoked via
> WebSocket (JSON) or through the MCP server (Python tool).

---

## How to Read This Reference

Each command shows:
- **WebSocket JSON** — the raw JSON to send over `ws://127.0.0.1:9878`
- **MCP Tool** — the corresponding Python MCP tool name (if available)
- **Parameters** — required and optional parameters
- **Handled by** — whether it runs in the background service worker or content script

> Commands marked **WebSocket only** have no MCP tool wrapper — use them via direct
> WebSocket connection or via `browser_evaluate()`.

---

## DOM Queries

### querySelector
Query a single DOM element by CSS selector. Returns element details (tag, id, class, text, visibility).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector (e.g., `#my-id`, `.class`, `div > p`) |

```json
{ "action": "querySelector", "selector": "#prompt-textarea" }
```
**MCP Tool:** `browser_query(tab_id, selector, frame_id=None)`  
**Handled by:** Content Script

---

### querySelectorAll
Query all matching DOM elements. Returns count and element details array.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector |
| `limit` | integer | — | 0 (all) | Maximum elements to return (0 = no limit) |

```json
{ "action": "querySelectorAll", "selector": ".message" }
{ "action": "querySelectorAll", "selector": "div", "limit": 20 }
```
**MCP Tool:** `browser_query_all(tab_id, selector, limit=0, frame_id=None)`  
**Handled by:** Content Script

---

### getInnerText
Get the inner text content of a DOM element.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector |

```json
{ "action": "getInnerText", "selector": "#content" }
```
**MCP Tool:** `browser_get_text(tab_id, selector, frame_id=None)`  
**Handled by:** Content Script

---

### getOuterHTML
Get the outer HTML of a DOM element.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector |
| `maxLength` | integer | — | 0 (all) | Maximum characters to return (0 = no limit) |

```json
{ "action": "getOuterHTML", "selector": "#form" }
{ "action": "getOuterHTML", "selector": "body", "maxLength": 5000 }
```
**MCP Tool:** `browser_get_html(tab_id, selector, max_length=0, frame_id=None)`  
**Handled by:** Content Script

---

### getAttribute
Get an HTML attribute value from a DOM element.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector |
| `attribute` | string | ✅ | — | Attribute name (e.g., `href`, `src`, `data-id`) |

```json
{ "action": "getAttribute", "selector": "#link", "attribute": "href" }
```
**MCP Tool:** `browser_get_attribute(tab_id, selector, attribute, frame_id=None)`  
**Handled by:** Content Script

---

### getProperty
Get a JavaScript property value from a DOM element.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector |
| `property` | string | ✅ | — | JS property name (e.g., `value`, `checked`, `scrollTop`) |

```json
{ "action": "getProperty", "selector": "#input", "property": "value" }
```
**MCP Tool:** *WebSocket only*  
**Handled by:** Content Script

---

### getComputedStyle
Get a computed CSS style property value from a DOM element.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector |
| `property` | string | ✅ | — | CSS property name (e.g., `color`, `display`, `font-size`) |

```json
{ "action": "getComputedStyle", "selector": "#box", "property": "display" }
```
**MCP Tool:** *WebSocket only*  
**Handled by:** Content Script

---

### getBoundingRect
Get the bounding rectangle (position and size) of a DOM element.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector |

```json
{ "action": "getBoundingRect", "selector": "#button" }
→ { "data": { "x": 100, "y": 200, "width": 150, "height": 40, "top": 200, "left": 100, "bottom": 240, "right": 250 } }
```
**MCP Tool:** `browser_get_bounding_rect(tab_id, selector, frame_id=None)`  
**Handled by:** Content Script

---

### waitForSelector
Wait for a DOM element to appear. Polls every 200ms.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector to wait for |
| `timeout` | integer | — | 10000 | Maximum wait time in milliseconds |

```json
{ "action": "waitForSelector", "selector": ".loaded", "timeout": 10000 }
```
**MCP Tool:** `browser_wait_for(tab_id, selector, timeout=10000, frame_id=None)`  
**Handled by:** Content Script

---

### waitForText
Wait for an element to contain specific text. Polls every 200ms.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector |
| `text` | string | ✅ | — | Text to wait for (substring match) |
| `timeout` | integer | — | 10000 | Maximum wait time in milliseconds |

```json
{ "action": "waitForText", "selector": "#status", "text": "Done", "timeout": 5000 }
```
**MCP Tool:** *WebSocket only*  
**Handled by:** Content Script

---

### getPageText
Get the full visible text content of the current page.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `maxLength` | integer | — | 0 (all) | Maximum characters to return (0 = no limit) |

```json
{ "action": "getPageText" }
```
**MCP Tool:** `browser_get_page_text(tab_id, max_length=0, frame_id=None)`  
**Handled by:** Content Script

---

### getPageHTML
Get the full HTML of the current page.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `maxLength` | integer | — | 0 (all) | Maximum characters to return (0 = no limit) |

```json
{ "action": "getPageHTML" }
{ "action": "getPageHTML", "maxLength": 50000 }
```
**MCP Tool:** `browser_get_page_html(tab_id, max_length=0, frame_id=None)`  
**Handled by:** Content Script

---

## DOM Interaction

### click
Click a DOM element. Element is scrolled into view first.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector of element to click |

```json
{ "action": "click", "selector": "button.submit" }
```
**MCP Tool:** `browser_click(tab_id, selector, frame_id=None)`  
**Handled by:** Content Script

---

### dblclick
Double-click a DOM element. Element is scrolled into view first.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector |

```json
{ "action": "dblclick", "selector": ".item" }
```
**MCP Tool:** *WebSocket only — use `browser_mouse_click(tab_id, x, y, click_count=2)` for double-click*  
**Handled by:** Content Script

---

### type
Type text into a DOM element (appends to existing content). Works with contenteditable divs.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector of element to type into |
| `text` | string | ✅ | — | Text to type |

```json
{ "action": "type", "selector": "#input", "text": "hello world" }
```
**MCP Tool:** `browser_type(tab_id, selector, text, frame_id=None)`  
**Handled by:** Content Script

---

### fill
Clear and fill a form input or contenteditable element with new text.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector of input/textarea/contenteditable |
| `value` | string | ✅ | — | Value to fill |

```json
{ "action": "fill", "selector": "#input", "value": "hello world" }
```
**MCP Tool:** `browser_fill(tab_id, selector, value, frame_id=None)`  
**Handled by:** Content Script

---

### focus
Focus a DOM element.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector |

```json
{ "action": "focus", "selector": "#input" }
```
**MCP Tool:** *WebSocket only — use `browser_evaluate` for focus*  
**Handled by:** Content Script

---

### blur
Remove focus from a DOM element.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector |

```json
{ "action": "blur", "selector": "#input" }
```
**MCP Tool:** *WebSocket only — use `browser_evaluate` for blur*  
**Handled by:** Content Script

---

### check
Check a checkbox (no-op if already checked).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector of the checkbox |

```json
{ "action": "check", "selector": "#checkbox" }
```
**MCP Tool:** `browser_check(tab_id, selector, frame_id=None)`  
**Handled by:** Content Script

---

### uncheck
Uncheck a checkbox (no-op if already unchecked).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector of the checkbox |

```json
{ "action": "uncheck", "selector": "#checkbox" }
```
**MCP Tool:** `browser_uncheck(tab_id, selector, frame_id=None)`  
**Handled by:** Content Script

---

### selectOption
Select an option in a dropdown/select element.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector of the select element |
| `value` | string | ✅ | — | Value of the option to select |

```json
{ "action": "selectOption", "selector": "#dropdown", "value": "option1" }
```
**MCP Tool:** `browser_select(tab_id, selector, value, frame_id=None)`  
**Handled by:** Content Script

---

### scrollIntoView
Scroll an element smoothly into view (centered in viewport).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector |

```json
{ "action": "scrollIntoView", "selector": ".target" }
```
**MCP Tool:** `browser_scroll_into_view(tab_id, selector, frame_id=None)`  
**Handled by:** Content Script

---

### scrollTo
Scroll the page to specific coordinates.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `x` | integer | — | 0 | Horizontal scroll position |
| `y` | integer | — | 0 | Vertical scroll position |

```json
{ "action": "scrollTo", "x": 0, "y": 500 }
```
**MCP Tool:** `browser_scroll_to(tab_id, x=0, y=0, frame_id=None)`  
**Handled by:** Content Script

---

## Keyboard

### keyPress
Press a single keyboard key (dispatches keydown + keyup).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `key` | string | ✅ | — | Key to press (e.g., `Enter`, `Tab`, `Escape`, `a`) |

```json
{ "action": "keyPress", "key": "Enter" }
```
**MCP Tool:** `browser_press(tab_id, key, frame_id=None)`  
**Handled by:** Content Script

---

### keyCombo
Press a keyboard shortcut (key combination).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `keys` | array | ✅ | — | Array of keys (e.g., `["Control", "Shift", "d"]`) |

```json
{ "action": "keyCombo", "keys": ["Control", "Shift", "d"] }
```
**MCP Tool:** `browser_key_combo(tab_id, keys, frame_id=None)` — pass keys as comma-separated string: `"Control,Shift,d"`  
**Handled by:** Content Script

---

## Mouse (CDP)

These commands use `chrome.debugger` + `Input.dispatchMouseEvent` to produce **native system-level
mouse events**. All events have `isTrusted: true`, making them indistinguishable from real user input.
Use `getBoundingRect` to get coordinates for a target element.

> **Handled by:** Background (CDP — `chrome.debugger` + `Input.dispatchMouseEvent`)

### mouseMoveCDP
Move the mouse to specific coordinates with interpolated trajectory and random jitter.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tabId` | integer or string | ✅ | — | Tab ID (numeric or virtualId) |
| `x` | integer | ✅ | — | Target X coordinate (viewport pixels) |
| `y` | integer | ✅ | — | Target Y coordinate (viewport pixels) |
| `steps` | integer | — | 10 | Number of intermediate points in the trajectory |
| `duration` | integer | — | 300 | Total movement time in milliseconds |

```json
{ "action": "mouseMoveCDP", "tabId": 123, "x": 500, "y": 300 }
{ "action": "mouseMoveCDP", "tabId": 123, "x": 500, "y": 300, "steps": 20, "duration": 500 }
```
**MCP Tool:** `browser_mouse_move(tab_id, x, y, steps=10, duration=300)`  
**Handled by:** Background (CDP)

---

### mouseClickCDP
Click at specific coordinates. Dispatches mouseMoved → mousePressed → mouseReleased.
Supports left/right/middle buttons and double-click via clickCount.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tabId` | integer or string | ✅ | — | Tab ID (numeric or virtualId) |
| `x` | integer | ✅ | — | Click X coordinate |
| `y` | integer | ✅ | — | Click Y coordinate |
| `button` | string | — | `left` | `left`, `right`, or `middle` |
| `clickCount` | integer | — | 1 | 1 for single click, 2 for double-click |

```json
{ "action": "mouseClickCDP", "tabId": 123, "x": 100, "y": 200 }
{ "action": "mouseClickCDP", "tabId": 123, "x": 100, "y": 200, "button": "right" }
{ "action": "mouseClickCDP", "tabId": 123, "x": 100, "y": 200, "clickCount": 2 }
```
**MCP Tool:** `browser_mouse_click(tab_id, x, y, button='left', click_count=1)`  
**Handled by:** Background (CDP)

---

### mouseDownCDP
Press and hold the mouse button at coordinates. Use with mouseUpCDP for atomic hold/release.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tabId` | integer or string | ✅ | — | Tab ID |
| `x` | integer | ✅ | — | Press X coordinate |
| `y` | integer | ✅ | — | Press Y coordinate |
| `button` | string | — | `left` | `left`, `right`, or `middle` |

```json
{ "action": "mouseDownCDP", "tabId": 123, "x": 100, "y": 200 }
```
**MCP Tool:** `browser_mouse_down(tab_id, x, y, button='left')`  
**Handled by:** Background (CDP)

---

### mouseUpCDP
Release the mouse button at coordinates. Completes a hold started by mouseDownCDP.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tabId` | integer or string | ✅ | — | Tab ID |
| `x` | integer | ✅ | — | Release X coordinate |
| `y` | integer | ✅ | — | Release Y coordinate |
| `button` | string | — | `left` | `left`, `right`, or `middle` |

```json
{ "action": "mouseUpCDP", "tabId": 123, "x": 100, "y": 200 }
```
**MCP Tool:** `browser_mouse_up(tab_id, x, y, button='left')`  
**Handled by:** Background (CDP)

---

### mouseDragCDP
Full drag sequence: move to start, press, interpolated move to end, release — all in a single
debugger session (single attach/detach to minimize infobar flash).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tabId` | integer or string | ✅ | — | Tab ID |
| `startX` | integer | ✅ | — | Drag start X coordinate |
| `startY` | integer | ✅ | — | Drag start Y coordinate |
| `endX` | integer | ✅ | — | Drag end X coordinate |
| `endY` | integer | ✅ | — | Drag end Y coordinate |
| `steps` | integer | — | 20 | Number of intermediate movement points |
| `duration` | integer | — | 500 | Total drag time in milliseconds |

```json
{ "action": "mouseDragCDP", "tabId": 123, "startX": 100, "startY": 200, "endX": 400, "endY": 200 }
{ "action": "mouseDragCDP", "tabId": 123, "startX": 100, "startY": 200, "endX": 400, "endY": 200, "steps": 30, "duration": 800 }
```
**MCP Tool:** `browser_mouse_drag(tab_id, start_x, start_y, end_x, end_y, steps=20, duration=500)`  
**Handled by:** Background (CDP)

---

### mouseWheelCDP
Dispatch a native scroll wheel event at specific coordinates.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tabId` | integer or string | ✅ | — | Tab ID |
| `x` | integer | ✅ | — | Wheel event X coordinate |
| `y` | integer | ✅ | — | Wheel event Y coordinate |
| `deltaX` | integer | — | 0 | Horizontal scroll amount in pixels |
| `deltaY` | integer | — | 0 | Vertical scroll amount (positive = down) |

```json
{ "action": "mouseWheelCDP", "tabId": 123, "x": 500, "y": 300, "deltaY": 300 }
```
**MCP Tool:** `browser_mouse_wheel(tab_id, x, y, delta_x=0, delta_y=0)`  
**Handled by:** Background (CDP)

---

## Page Info

### getURL
Get the current page URL.

```json
{ "action": "getURL" }
```
**MCP Tool:** `browser_get_url(tab_id)`  
**Handled by:** Content Script

---

### getTitle
Get the current page title.

```json
{ "action": "getTitle" }
```
**MCP Tool:** `browser_get_title(tab_id)`  
**Handled by:** Content Script

---

### getStatus
Get page status (URL and title).

```json
{ "action": "getStatus" }
```
**MCP Tool:** *WebSocket only*  
**Handled by:** Content Script

---

## Navigation

### navigate
Navigate a tab to a URL.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | ✅ | — | Full URL (e.g., `https://example.com`) |

```json
{ "action": "navigate", "url": "https://example.com" }
```
**MCP Tool:** `browser_navigate(tab_id, url)`  
**Handled by:** Background

---

### goBack
Go back in browser history.

```json
{ "action": "goBack" }
```
**MCP Tool:** `browser_back(tab_id)`  
**Handled by:** Background

---

### goForward
Go forward in browser history.

```json
{ "action": "goForward" }
```
**MCP Tool:** `browser_forward(tab_id)`  
**Handled by:** Background

---

### reloadTab
Reload a tab.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tabId` | integer or string | ✅ | — | Tab ID (numeric or virtualId like `"chrome:12345"`) |

```json
{ "action": "reloadTab", "tabId": 123 }
```
**MCP Tool:** `browser_reload(tab_id)`  
**Handled by:** Background

---

## Tab Management

### listTabs
List all open browser tabs with their IDs, URLs, titles, active status, windowId, and incognito status.

```json
{ "action": "listTabs" }
```
**MCP Tool:** `browser_list_tabs()`  
**Handled by:** Background

---

### newTab
Open a new browser tab.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | — | `about:blank` | URL to open |

```json
{ "action": "newTab", "url": "https://example.com" }
```
**MCP Tool:** `browser_new_tab(url="about:blank")`  
**Handled by:** Background

---

### closeTab
Close a browser tab.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tabId` | integer or string | ✅ | — | Tab ID (numeric or virtualId like `"chrome:12345"`) |

```json
{ "action": "closeTab", "tabId": 123 }
```
**MCP Tool:** `browser_close_tab(tab_id)`  
**Handled by:** Background

---

### switchTab
Switch to (activate) a browser tab and focus its window.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tabId` | integer or string | ✅ | — | Tab ID (numeric or virtualId like `"chrome:12345"`) |

```json
{ "action": "switchTab", "tabId": 123 }
```
**MCP Tool:** `browser_switch_tab(tab_id)`  
**Handled by:** Background

---

## Window Management

### newWindow
Open a new browser window in the user's profile (with cookies and sessions).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | — | `about:blank` | URL to open |

```json
{ "action": "newWindow", "url": "https://example.com" }
```
**MCP Tool:** `browser_new_window(url="about:blank")`  
**Handled by:** Background

---

### newIncognitoWindow
Open a new private/incognito browser window (clean session, no cookies).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | — | `about:blank` | URL to open |

```json
{ "action": "newIncognitoWindow", "url": "https://example.com" }
```
**MCP Tool:** `browser_new_incognito_window(url="about:blank")`  
**Handled by:** Background

> Requires "Allow in Incognito" enabled in extension settings.

---

### listWindows
List all open browser windows with their IDs, types, sizes, and incognito status.

```json
{ "action": "listWindows" }
```
**MCP Tool:** `browser_list_windows()`  
**Handled by:** Background

---

### closeWindow
Close a browser window and all its tabs.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `windowId` | integer | ✅ | — | ID of the window to close |

```json
{ "action": "closeWindow", "windowId": 456 }
```
**MCP Tool:** `browser_close_window(window_id)`  
**Handled by:** Background

---

### resizeWindow
Resize a browser window.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `windowId` | integer | ✅ | — | ID of the window to resize |
| `width` | integer | — | unchanged | New width in pixels |
| `height` | integer | — | unchanged | New height in pixels |

```json
{ "action": "resizeWindow", "windowId": 456, "width": 1280, "height": 720 }
```
**MCP Tool:** `browser_resize_window(window_id, width=None, height=None)`  
**Handled by:** Background

---

## Screenshots

### captureScreenshot
Capture a screenshot of a specific tab as PNG. Uses CDP (`chrome.debugger`) for silent capture — no tab activation or window focus required. Falls back to `captureVisibleTab` if CDP is unavailable (e.g., DevTools is open on the target tab).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tabId` | integer or string | ✅ | — | Tab ID (numeric or virtualId like `"chrome:12345"`) |

```json
{ "action": "captureScreenshot", "tabId": 123 }
→ { "data": { "dataUrl": "data:image/png;base64,...", "tabId": 123 } }
```
**MCP Tool:** `browser_screenshot(tab_id, save_path=None)`  
When `save_path` is provided, the MCP tool saves the PNG to disk and returns the file path.  
**Handled by:** Background (CDP primary, captureVisibleTab fallback)

---

### captureFullPageScreenshot
Capture a full-page screenshot. Uses CDP single-shot rendering when available — captures the entire page in one pass without scrolling. Falls back to scroll-and-stitch via `captureVisibleTab` if CDP is unavailable. Sticky/fixed elements are automatically hidden during middle frames in the fallback path.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tabId` | integer or string | ✅ | — | Tab ID (numeric or virtualId like `"chrome:12345"`) |
| `maxHeight` | integer | — | 20000 | Maximum page height to capture in pixels. Prevents memory issues on infinite-scroll pages. |

```json
{ "action": "captureFullPageScreenshot", "tabId": 123 }
{ "action": "captureFullPageScreenshot", "tabId": 123, "maxHeight": 30000 }
→ { "data": { "dataUrl": "data:image/png;base64,...", "fullPage": true, "dimensions": { "width": 2560, "height": 15360, "frames": 1, "actualHeight": 7680 } } }
```
**MCP Tool:** `browser_screenshot_full_page(tab_id, max_height=20000, save_path=None)`  
When `save_path` is provided, saves the PNG to disk and returns the file path with dimensions info.  
**Handled by:** Background (CDP primary, scroll-stitch fallback)

---

## Cookies

### getCookies
Get all cookies for a URL.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | ✅ | — | URL to get cookies for (e.g., `https://example.com`) |

```json
{ "action": "getCookies", "url": "https://example.com" }
```
**MCP Tool:** `browser_get_cookies(url)`  
**Handled by:** Background

---

### setCookie
Set a cookie.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `details` | object | ✅ | — | Cookie details: `{ url, name, value, domain, path, ... }` |

```json
{ "action": "setCookie", "details": { "url": "https://example.com", "name": "token", "value": "abc123" } }
```
**MCP Tool:** `browser_set_cookie(url, name, value, ...)`  
**Handled by:** Background

---

### deleteCookie
Delete a cookie.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | ✅ | — | URL the cookie belongs to |
| `name` | string | ✅ | — | Cookie name |

```json
{ "action": "deleteCookie", "url": "https://example.com", "name": "token" }
```
**MCP Tool:** `browser_delete_cookie(url, name)`  
**Handled by:** Background

---

## JavaScript Execution

### evaluate
Execute arbitrary JavaScript code in the current page's MAIN world context. Works on **all sites** — CSP headers are automatically stripped.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `code` | string | ✅ | — | JavaScript code to evaluate |

Supports both expressions and return statements:

```json
{ "action": "evaluate", "code": "document.title" }
{ "action": "evaluate", "code": "return document.querySelectorAll('a').length" }
{ "action": "evaluate", "code": "return [...document.querySelectorAll('a')].map(a => a.href)" }
```
**MCP Tool:** `browser_evaluate(tab_id, code)`  
**Handled by:** Background (via `chrome.scripting.executeScript`)

---

## Network Capture

### startNetCapture
Start capturing HTTP requests and responses.

```json
{ "action": "startNetCapture" }
```
**MCP Tool:** `browser_start_net_capture()`  
**Handled by:** Background

---

### stopNetCapture
Stop capturing network traffic.

```json
{ "action": "stopNetCapture" }
```
**MCP Tool:** `browser_stop_net_capture()`  
**Handled by:** Background

---

### getNetCapture
Get captured network traffic (array of request/response objects).

```json
{ "action": "getNetCapture" }
→ { "data": [{ "url": "...", "method": "POST", "requestHeaders": {...}, "responseHeaders": {...}, "statusCode": 200 }] }
```
**MCP Tool:** `browser_get_net_capture()`  
**Handled by:** Background

---

### clearNetCapture
Clear captured network traffic.

```json
{ "action": "clearNetCapture" }
```
**MCP Tool:** *WebSocket only*  
**Handled by:** Background

---

## Proxy Fetch

### proxyFetch
Route HTTP requests through the browser's `fetch()` API. Inherits the browser's TLS fingerprint (JA3/JA4), cookies, and session state.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | ✅ | — | URL to fetch |
| `method` | string | — | `GET` | HTTP method |
| `headers` | object | — | `{}` | Request headers |
| `body` | any | — | `null` | Request body |
| `bodyType` | string | — | `json` | Body encoding: `json`, `text`, `formdata`, `base64file` |

```json
{ "action": "proxyFetch", "url": "https://api.example.com/data",
  "method": "POST", "headers": {"Authorization": "Bearer ..."}, "body": {"key": "value"}, "bodyType": "json" }
→ { "data": { "status": 200, "statusText": "OK", "headers": {...}, "body": {...} } }
```

For file uploads with `bodyType: "base64file"`:
```json
{ "action": "proxyFetch", "url": "...", "method": "POST",
  "body": { "fieldName": "file", "fileName": "image.png", "mimeType": "image/png", "data": "<base64>" },
  "bodyType": "base64file" }
```

**MCP Tool:** `browser_proxy_fetch(tab_id, url, method='GET', headers=None, body=None, body_type='json')`  
**Handled by:** Content Script

---

## File Upload

### setInputFiles
Set files on a file input element using a data URL.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector of `input[type=file]` |
| `dataUrl` | string | ✅ | — | Data URL of the file (e.g., `data:image/png;base64,...`) |

```json
{ "action": "setInputFiles", "selector": "input[type=file]", "dataUrl": "data:image/png;base64,..." }
```
**MCP Tool:** `browser_upload_file(tab_id, selector, data_url)`  
**Handled by:** Content Script

---

### hover
Hover over a DOM element. Triggers mouseenter, mouseover, and mousemove events.
Useful for revealing dropdown menus, tooltips, and hover-activated UI.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | ✅ | — | CSS selector of element to hover over |

```json
{ "action": "hover", "selector": ".dropdown-trigger" }
```
**MCP Tool:** `browser_hover(tab_id, selector, frame_id=None)`  
**Handled by:** Content Script

---

### dragAndDrop
Drag an element and drop it onto another element using the HTML5 Drag API.
Works for drag-enabled libraries (Kanban boards, sortable lists, file drop zones).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `sourceSelector` | string | ✅ | — | CSS selector of the element to drag |
| `targetSelector` | string | ✅ | — | CSS selector of the drop target |

```json
{ "action": "dragAndDrop", "sourceSelector": ".card", "targetSelector": ".column-done" }
```
**MCP Tool:** `browser_drag_and_drop(tab_id, source_selector, target_selector, frame_id=None)`  
**Handled by:** Content Script

---

### waitForUrl
Wait for the tab's URL to match a pattern. Ideal for SPA navigation.
Pattern can be a substring (e.g., '/dashboard') or a regex (e.g., '/order/[0-9]+/').

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `pattern` | string | ✅ | — | Substring or `/regex/` to match against the URL |
| `timeout` | integer | — | 10000 | Maximum wait time in milliseconds |

```json
{ "action": "waitForUrl", "pattern": "/dashboard", "timeout": 15000 }
```
**MCP Tool:** `browser_wait_for_url(tab_id, pattern, timeout=10000)`  
**Handled by:** Background Script

---

### listConnections
List all browser connections currently active on the bridge.
Useful when multiple browsers (e.g., Brave + Chrome) are connected simultaneously.

```json
{ "action": "listConnections" }
→ { "data": { "connections": [...], "count": 2 } }
```
**MCP Tool:** `browser_list_connections()`  
**Handled by:** Bridge Server

---

### listFrames
List all frames (iframes, framesets) in a tab. Returns URL, title, element count, and body
presence for each frame. Essential for pages where content lives inside iframes (Gmail, OAuth).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tabId` | integer or string | ✅ | — | Tab ID |

```json
{ "action": "listFrames", "tabId": 12345 }
→ { "data": [{ "frameId": 0, "url": "...", "hasBody": true, "elementCount": 150 }, ...] }
```
**MCP Tool:** `browser_list_frames(tab_id)`  
**Handled by:** Background Script

---

### executeScriptAllFrames
Execute JavaScript in ALL frames of a tab and return per-frame results.
Use when target content lives inside an iframe and standard evaluate returns null.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `code` | string | ✅ | — | JavaScript code to evaluate in every frame |
| `world` | string | — | `MAIN` | `MAIN` or `ISOLATED` |

```json
{ "action": "executeScriptAllFrames", "tabId": 12345, "code": "document.title" }
→ { "data": [{ "frameIndex": 0, "frameId": 0, "result": "Page Title" }, ...] }
```
**MCP Tool:** `browser_evaluate_all_frames(tab_id, code, world='MAIN')`  
**Handled by:** Background Script

---

## DOM Manipulation

### removeByText
Remove DOM elements that match a selector and contain specific text.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `selector` | string | — | `*` | CSS selector to match elements |
| `texts` | array | ✅ | — | Array of text strings to match (case-insensitive) |

```json
{ "action": "removeByText", "selector": "ytd-rich-shelf-renderer", "texts": ["Shorts"] }
→ { "data": { "removed": 2, "selector": "ytd-rich-shelf-renderer", "texts": ["Shorts"] } }
```
**MCP Tool:** *WebSocket only*  
**Handled by:** Content Script

---

## Lifecycle

### ping
Test that the content script is responsive.

```json
{ "action": "ping" }
→ { "data": "pong" }
```
**MCP Tool:** *WebSocket only*  
**Handled by:** Content Script

---

## Global Parameters

Every WebSocket command supports these parameters:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `_timeout` | integer | — | 30 | Timeout in seconds for the command |
| `_msg_id` | string | — | — | Correlation ID echoed back in the response (for parallel request matching) |
| `tabId` | integer or string | **✅ Required** | — | Tab ID (numeric or virtualId like `"chrome:12345"`). **Required for all tab-scoped commands.** Use `listTabs` to discover IDs. |
| `frameId` | integer | — | top-level | Target frame ID within the tab. Use `listFrames` to discover frame IDs. Omit for top-level frame. |

> **Important:** `tabId` is **mandatory** for all tab-scoped commands (DOM, navigation, screenshots, evaluate, etc.).
> There is no "active tab" fallback — commands without `tabId` will return an error.
> Only `listTabs`, `listWindows`, `newTab`, `newWindow`, and `newIncognitoWindow` do not require `tabId`.

```json
{ "action": "click", "selector": "#btn", "_timeout": 10, "tabId": 456 }
```

