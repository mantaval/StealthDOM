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

- [ ] **Handle Native JavaScript Dialogs (`browser_handle_dialog`)**
  - **Description**: Add a new tool to natively accept or dismiss `window.alert`, `window.confirm`, or `window.prompt` dialogs from the background service worker using CDP.
  - **Purpose**: Prevents blocked content scripts caused by main thread blocking from native dialogs.
  - **Implementation Steps**: See "Implementation Details" section below.

## Architectural Ideas
- [ ] **JavaScript Render Composition Fallback (html2canvas)**
  - **Description**: If CDP `captureScreenshot` fails (e.g., because the browser is fully occluded or minimized), automatically inject a library like `html2canvas` into the content script to manually read the DOM tree and paint it onto an HTML5 `<canvas>`.
  - **Purpose**: Provides a highly resilient visual fallback for Vision-Language Models that works completely independently of the Chromium graphics compositor.

- [ ] **Built-in Proxy Support and Management**
  - **Description**: Add the ability to proxy requests through the StealthDOM node. Furthermore, implement an automated pipeline to fetch proxy lists from the internet, test/verify their connectivity, and maintain a never-ending, rotating pool of healthy proxies for the extension to use.
  - **Purpose**: Greatly enhances stealth capabilities by rotating IPs and prevents rate-limiting across large-scale automation tasks.

## Implementation Details

### Handle Native JavaScript Dialogs

Currently, StealthDOM cannot dismiss native `window.alert`, `window.confirm`, or `window.prompt` dialogs because they block the main JavaScript thread, which also blocks content scripts.

We need to add a new `browser_handle_dialog` tool that uses the `chrome.debugger` API (CDP) to natively accept or dismiss these dialogs from the extension's background service worker.

#### 1. Modify `extension/background.js`
- Add `handleDialog` to the `bgActions` array.
- Add the following to the `switch(action)` block in `handleBackgroundCommand`:
```javascript
case 'handleDialog':
    return await cmdHandleDialog(msg.tabId, msg.accept, msg.promptText);
```
- Implement `cmdHandleDialog`:
```javascript
async function cmdHandleDialog(tabId, accept, promptText) {
    const target = { tabId };
    try {
        await chrome.debugger.attach(target, '1.3');
        const params = { accept };
        if (promptText !== undefined) {
            params.promptText = promptText;
        }
        await chrome.debugger.sendCommand(target, 'Page.handleJavaScriptDialog', params);
        await chrome.debugger.detach(target);
        return { success: true };
    } catch (e) {
        try { await chrome.debugger.detach(target); } catch (_) {}
        return { success: false, error: e.message };
    }
}
```

#### 2. Modify `stealth_dom_mcp.py`
- Add a new tool to expose this capability to the MCP server:
```python
@mcp.tool()
async def browser_handle_dialog(tab_id: int | str, accept: bool = True, prompt_text: str | None = None) -> str:
    """Accept or dismiss a native JavaScript dialog (alert, confirm, prompt).
    
    Args:
        tab_id: ID of the tab (get from browser_list_tabs)
        accept: True to accept (click OK), False to dismiss (click Cancel)
        prompt_text: Optional text to enter into a prompt dialog
    """
    result = await send_command("handleDialog", tabId=tab_id, accept=accept, promptText=prompt_text)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Dialog handled successfully"
```
- Add `browser_handle_dialog` to the tool list documentation at the top of the file.

#### 3. Deployment
- Reload the extension in `chrome://extensions` to pick up the `background.js` changes.
- Restart the `bridge_server.py`.
