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
**MCP Tool:** `browser_query(selector)`  
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
**MCP Tool:** `browser_query_all(selector, limit=0)`  
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
**MCP Tool:** `browser_get_text(selector)`  
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
**MCP Tool:** `browser_get_html(selector, max_length=0)`  
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
**MCP Tool:** `browser_get_attribute(selector, attribute)`  
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
**MCP Tool:** *WebSocket only*  
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
**MCP Tool:** `browser_wait_for(selector, timeout=10000)`  
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
**MCP Tool:** `browser_get_page_text()`  
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
**MCP Tool:** *WebSocket only*  
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
**MCP Tool:** `browser_click(selector)`  
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
**MCP Tool:** *WebSocket only*  
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
**MCP Tool:** `browser_type(selector, text)`  
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
**MCP Tool:** `browser_fill(selector, value)`  
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
**MCP Tool:** *WebSocket only*  
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
**MCP Tool:** *WebSocket only*  
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
**MCP Tool:** `browser_check(selector)`  
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
**MCP Tool:** *WebSocket only*  
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
**MCP Tool:** `browser_select(selector, value)`  
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
**MCP Tool:** `browser_scroll_to(selector)`  
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
**MCP Tool:** *WebSocket only*  
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
**MCP Tool:** `browser_press(key)`  
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
**MCP Tool:** `browser_key_combo(keys)` — pass as comma-separated string: `"Control,Shift,d"`  
**Handled by:** Content Script

---

## Mouse (Coordinate-Based)

### mouseClick
Click at specific screen coordinates.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `x` | integer | ✅ | — | X coordinate |
| `y` | integer | ✅ | — | Y coordinate |
| `button` | string | — | `left` | `left`, `right`, or `middle` |

```json
{ "action": "mouseClick", "x": 100, "y": 200, "button": "left" }
```
**MCP Tool:** *WebSocket only*  
**Handled by:** Content Script

---

### mouseMove
Move the mouse to specific coordinates (dispatches mousemove event).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `x` | integer | ✅ | — | X coordinate |
| `y` | integer | ✅ | — | Y coordinate |

```json
{ "action": "mouseMove", "x": 100, "y": 200 }
```
**MCP Tool:** *WebSocket only*  
**Handled by:** Content Script

---

### mouseWheel
Dispatch a wheel event (scroll).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `deltaX` | integer | — | 0 | Horizontal scroll amount |
| `deltaY` | integer | — | 0 | Vertical scroll amount |

```json
{ "action": "mouseWheel", "deltaX": 0, "deltaY": 500 }
```
**MCP Tool:** *WebSocket only*  
**Handled by:** Content Script

---

## Page Info

### getURL
Get the current page URL.

```json
{ "action": "getURL" }
```
**MCP Tool:** `browser_get_url()`  
**Handled by:** Content Script

---

### getTitle
Get the current page title.

```json
{ "action": "getTitle" }
```
**MCP Tool:** `browser_get_title()`  
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
Navigate the active tab to a URL.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | ✅ | — | Full URL (e.g., `https://example.com`) |

```json
{ "action": "navigate", "url": "https://example.com" }
```
**MCP Tool:** `browser_navigate(url)`  
**Handled by:** Background

---

### goBack
Go back in browser history.

```json
{ "action": "goBack" }
```
**MCP Tool:** `browser_back()`  
**Handled by:** Background

---

### goForward
Go forward in browser history.

```json
{ "action": "goForward" }
```
**MCP Tool:** *WebSocket only*  
**Handled by:** Background

---

### reloadTab
Reload the current (or specified) tab.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `tabId` | integer | — | active tab | ID of tab to reload |

```json
{ "action": "reloadTab" }
```
**MCP Tool:** `browser_reload()`  
**Handled by:** Background

---

## Tab Management

### listTabs
List all open browser tabs with their IDs, URLs, titles, and active status.

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
| `tabId` | integer | ✅ | — | ID of the tab to close |

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
| `tabId` | integer | ✅ | — | ID of the tab to switch to |

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
Capture a screenshot of the current visible tab as PNG.

```json
{ "action": "captureScreenshot" }
→ { "data": { "dataUrl": "data:image/png;base64,..." } }
```
**MCP Tool:** `browser_screenshot(save_path=None)`  
When `save_path` is provided, the MCP tool saves the PNG to disk and returns the file path.  
**Handled by:** Background

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
**MCP Tool:** *WebSocket only*  
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
**MCP Tool:** *WebSocket only*  
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
**MCP Tool:** `browser_evaluate(code)`  
**Handled by:** Background (via `chrome.scripting.executeScript`)

---

## Network Capture

### startNetCapture
Start capturing HTTP requests and responses.

```json
{ "action": "startNetCapture" }
```
**MCP Tool:** *WebSocket only*  
**Handled by:** Background

---

### stopNetCapture
Stop capturing network traffic.

```json
{ "action": "stopNetCapture" }
```
**MCP Tool:** *WebSocket only*  
**Handled by:** Background

---

### getNetCapture
Get captured network traffic (array of request/response objects).

```json
{ "action": "getNetCapture" }
→ { "data": [{ "url": "...", "method": "POST", "requestHeaders": {...}, "responseHeaders": {...}, "statusCode": 200 }] }
```
**MCP Tool:** *WebSocket only*  
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

**MCP Tool:** *WebSocket only*  
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
**MCP Tool:** *WebSocket only*  
**Handled by:** Content Script

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

Every WebSocket command supports these optional parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `_timeout` | integer | 30 | Timeout in seconds for the command |
| `tabId` | integer | active tab | Target a specific tab instead of the active one |

```json
{ "action": "click", "selector": "#btn", "_timeout": 10, "tabId": 456 }
```
