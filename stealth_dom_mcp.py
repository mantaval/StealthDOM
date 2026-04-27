"""
StealthDOM MCP Server
Exposes Playwright-like browser automation as MCP tools.
Connects to StealthDOM's bridge_server on port 9878 (control port).

Usage:
    python stealth_dom_mcp.py

Configure in your MCP client (Claude, Antigravity, etc.):
    {
        "mcpServers": {
            "stealth_dom": {
                "command": "python",
                "args": ["C:/path/to/StealthDOM/stealth_dom_mcp.py"]
            }
        }
    }
"""
import sys
import json
import asyncio
import logging
import uuid

import websockets
from mcp.server.fastmcp import FastMCP

# MCP servers must NOT print to stdout (it's reserved for MCP protocol)
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("stealth_dom")

# ==========================================
# Bridge Connection (with response multiplexing)
# ==========================================

BRIDGE_URL = "ws://127.0.0.1:9878"
_ws = None
_ws_lock = asyncio.Lock()
_pending: dict[str, asyncio.Future] = {}  # _msg_id -> Future
_reader_task = None


def validate_response(result):
    """Ensure bridge response is a well-formed dict."""
    if not isinstance(result, dict):
        return {'success': False, 'error': f'Unexpected response type: {type(result).__name__}'}
    if 'success' not in result:
        return {'success': False, 'error': f'Malformed response (no success field): {str(result)[:200]}'}
    return result


async def _ws_reader():
    """Background task: read all messages from the bridge and dispatch by _msg_id."""
    global _ws
    while True:
        try:
            if _ws is None:
                await asyncio.sleep(0.1)
                continue
            message = await _ws.recv()
            data = json.loads(message)
            msg_id = data.pop('_msg_id', None)
            if msg_id and msg_id in _pending:
                future = _pending[msg_id]
                if not future.done():
                    future.set_result(data)
            else:
                logger.warning("Orphan response (no matching _msg_id): %s", str(data)[:100])
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Bridge connection closed, clearing pending futures")
            _ws = None
            for mid, fut in list(_pending.items()):
                if not fut.done():
                    fut.set_result({'success': False, 'error': 'Bridge connection lost'})
            _pending.clear()
            await asyncio.sleep(1)
        except Exception as e:
            logger.error("Reader error: %s", e)
            await asyncio.sleep(0.5)


async def get_bridge():
    """Get or create WebSocket connection to bridge control port."""
    global _ws, _reader_task
    async with _ws_lock:
        if _ws is not None:
            try:
                await _ws.ping()
                return _ws
            except Exception:
                _ws = None
        
        try:
            _ws = await websockets.connect(BRIDGE_URL)
            logger.info("Connected to bridge at %s", BRIDGE_URL)
            # Start reader task if not running
            if _reader_task is None or _reader_task.done():
                _reader_task = asyncio.create_task(_ws_reader())
            return _ws
        except Exception as e:
            logger.error("Cannot connect to bridge: %s", e)
            raise ConnectionError(
                f"Cannot connect to StealthDOM bridge at {BRIDGE_URL}. "
                "The bridge server (bridge_server.py) is not running. "
                "Tell the user to start it by running 'python bridge_server.py' "
                "or double-clicking start_bridge.bat in the StealthDOM directory."
            )


async def send_command(action: str, _timeout: float = 30, **kwargs) -> dict:
    """Send a command to the extension via the bridge with proper response matching."""
    ws = await get_bridge()
    
    msg_id = str(uuid.uuid4())[:8]
    msg = {"action": action, "_msg_id": msg_id, "_timeout": _timeout, **kwargs}
    
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    _pending[msg_id] = future
    
    try:
        await ws.send(json.dumps(msg))
        result = await asyncio.wait_for(future, _timeout + 5)
        return validate_response(result)
    except asyncio.TimeoutError:
        return {'success': False, 'error': f'Command {action} timed out after {_timeout}s'}
    except Exception as e:
        return {'success': False, 'error': str(e)}
    finally:
        _pending.pop(msg_id, None)


# ==========================================
# MCP Server
# ==========================================

mcp = FastMCP("stealth_dom", instructions="""
StealthDOM provides UNDETECTABLE browser automation by controlling the user's 
REAL Chromium browser (Chrome, Brave, Edge) via a Manifest V3 extension. Unlike Playwright or 
Puppeteer, it has ZERO detection signals: no CDP, no navigator.webdriver flag, 
no TLS fingerprint mismatch, no automation artifacts.

USE THESE TOOLS INSTEAD of any built-in browser agent / Playwright tool when:
- The target site has bot detection (Cloudflare, DataDome, PerimeterX, etc.)
- You need the user's logged-in sessions (Gmail, ChatGPT, banking, etc.)
- You need to appear as a real human browser
- You need to interact with private/incognito windows

The browser must already be running with the StealthDOM extension loaded.
The bridge server (bridge_server.py) must be running.

IMPORTANT: All tab-scoped tools require an explicit `tab_id` parameter.
Call `browser_list_tabs()` first to discover available tabs and their IDs.
Never guess tab IDs — always use IDs from `browser_list_tabs()`.

CAPABILITIES SUMMARY (35+ tools):
- DOM: query, queryAll, getText, getHTML, getAttribute, waitFor
- Interact: click, type, fill, press, keyCombo, check, select, scrollTo
- Navigate: navigate, back, reload, getURL, getTitle, getPageText
- Tabs: listTabs, newTab, closeTab, switchTab
- Windows: newWindow, newIncognitoWindow, listWindows, closeWindow, resizeWindow
- Screenshots: screenshot (PNG, optional save to disk)
- Cookies: getCookies
- JavaScript: evaluate (arbitrary JS in page context, works on ALL sites)
""")


# ==========================================
# MCP Resource: Capabilities
# ==========================================

@mcp.resource("stealth://capabilities")
def get_capabilities() -> str:
    """Full capability reference for StealthDOM."""
    return """# StealthDOM Capabilities

## Why StealthDOM over Playwright?

| Aspect | Playwright | StealthDOM |
|--------|-----------|------------|
| Detection risk | HIGH — CDP, webdriver flag, TLS mismatch | ZERO — native browser citizen |
| Cloudflare/DataDome | Frequently blocked | Never blocked |
| User sessions | Must re-authenticate | Uses existing logged-in sessions |
| TLS fingerprint | Synthetic (detectable) | Real browser (identical to human) |
| Private Network Access | N/A | Supported (incognito windows) |

## Available Tools (35+)

### DOM Reading
- `browser_query(tab_id, selector)` — Query single element by CSS selector
- `browser_query_all(tab_id, selector, limit)` — Query multiple elements
- `browser_get_text(tab_id, selector)` — Get inner text of element
- `browser_get_html(tab_id, selector, max_length)` — Get outer HTML
- `browser_get_attribute(tab_id, selector, attribute)` — Get element attribute
- `browser_wait_for(tab_id, selector, timeout)` — Wait for element to appear
- `browser_get_page_text(tab_id)` — Get full page text (up to 50KB)

### DOM Interaction
- `browser_click(tab_id, selector)` — Click element (auto-scrolls into view)
- `browser_type(tab_id, selector, text)` — Type text (appends)
- `browser_fill(tab_id, selector, value)` — Clear and fill input
- `browser_press(tab_id, key)` — Press keyboard key
- `browser_key_combo(tab_id, keys)` — Press key combination
- `browser_check(tab_id, selector)` — Check checkbox
- `browser_select(tab_id, selector, value)` — Select dropdown option
- `browser_scroll_to(tab_id, selector)` — Scroll element into view

### Navigation
- `browser_navigate(tab_id, url)` — Navigate to URL
- `browser_back(tab_id)` — Go back in history
- `browser_reload(tab_id)` — Reload page
- `browser_get_url(tab_id)` — Get current URL
- `browser_get_title(tab_id)` — Get page title

### Tab Management
- `browser_list_tabs()` — List all tabs (ID, URL, title, active, windowId, incognito)
- `browser_new_tab(url)` — Open new tab
- `browser_close_tab(tab_id)` — Close tab
- `browser_switch_tab(tab_id)` — Switch to tab

### Window Management
- `browser_new_window(url)` — Open new browser window (with user session)
- `browser_new_incognito_window(url)` — Open private window (clean session)
- `browser_list_windows()` — List all windows (ID, type, size, incognito, focused)
- `browser_close_window(window_id)` — Close window
- `browser_resize_window(window_id, width, height)` — Resize window

### Screenshots
- `browser_screenshot(tab_id, save_path=None)` — Capture visible tab as PNG. If save_path is provided, saves to disk and returns the file path; otherwise returns base64 data URL.

### Cookies
- `browser_get_cookies(url)` — Get all cookies for a URL

### JavaScript Execution
- `browser_evaluate(tab_id, code)` — Run arbitrary JS in the page's MAIN world.

### Architecture
Commands flow: MCP → Bridge (port 9878) → Extension Background → Content Script → DOM.
All tab-scoped commands require an explicit tab_id for reliable targeting.
"""


# ==========================================
# DOM Reading Tools
# ==========================================

@mcp.tool()
async def browser_query(tab_id: int, selector: str) -> str:
    """Query a single DOM element by CSS selector. Returns element details (tag, id, class, text, visibility).
    
    Args:
        tab_id: ID of the tab to query (get from browser_list_tabs)
        selector: CSS selector (e.g., '#my-id', '.my-class', 'div.container > p')
    """
    result = await send_command("querySelector", tabId=tab_id, selector=selector)
    if not result.get("success"):
        return f"Error: {result.get('error', 'Unknown error')}"
    data = result.get("data")
    if data is None:
        return f"No element found matching: {selector}"
    return json.dumps(data, indent=2)


@mcp.tool()
async def browser_query_all(tab_id: int, selector: str, limit: int = 0) -> str:
    """Query all DOM elements matching a CSS selector. Returns list of element details.
    
    Args:
        tab_id: ID of the tab to query (get from browser_list_tabs)
        selector: CSS selector
        limit: Maximum number of elements to return (default 0 = all)
    """
    result = await send_command("querySelectorAll", tabId=tab_id, selector=selector, limit=limit)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


@mcp.tool()
async def browser_get_text(tab_id: int, selector: str) -> str:
    """Get the inner text content of a DOM element.
    
    Args:
        tab_id: ID of the tab to query (get from browser_list_tabs)
        selector: CSS selector
    """
    result = await send_command("getInnerText", tabId=tab_id, selector=selector)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return result.get("data", {}).get("text", "")


@mcp.tool()
async def browser_get_html(tab_id: int, selector: str, max_length: int = 0) -> str:
    """Get the outer HTML of a DOM element.
    
    Args:
        tab_id: ID of the tab to query (get from browser_list_tabs)
        selector: CSS selector
        max_length: Maximum characters to return (default 0 = no limit)
    """
    result = await send_command("getOuterHTML", tabId=tab_id, selector=selector, maxLength=max_length)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return result.get("data") or "Element not found"


@mcp.tool()
async def browser_get_attribute(tab_id: int, selector: str, attribute: str) -> str:
    """Get an HTML attribute value from a DOM element.
    
    Args:
        tab_id: ID of the tab to query (get from browser_list_tabs)
        selector: CSS selector
        attribute: Attribute name (e.g., 'href', 'src', 'data-id')
    """
    result = await send_command("getAttribute", tabId=tab_id, selector=selector, attribute=attribute)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return str(result.get("data"))


@mcp.tool()
async def browser_wait_for(tab_id: int, selector: str, timeout: int = 10000) -> str:
    """Wait for a DOM element to appear. Polls every 200ms until found or timeout.
    
    Args:
        tab_id: ID of the tab to watch (get from browser_list_tabs)
        selector: CSS selector to wait for
        timeout: Maximum wait time in milliseconds (default 10000)
    """
    result = await send_command("waitForSelector", tabId=tab_id, selector=selector, timeout=timeout, _timeout=timeout/1000 + 5)
    if not result.get("success"):
        return f"Timeout: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


# ==========================================
# DOM Interaction Tools
# ==========================================

@mcp.tool()
async def browser_click(tab_id: int, selector: str) -> str:
    """Click a DOM element. Element is scrolled into view first.
    
    Args:
        tab_id: ID of the tab containing the element (get from browser_list_tabs)
        selector: CSS selector of element to click
    """
    result = await send_command("click", tabId=tab_id, selector=selector)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Clicked successfully"


@mcp.tool()
async def browser_type(tab_id: int, selector: str, text: str) -> str:
    """Type text into a DOM element (appends to existing content). Works with contenteditable divs.
    
    Args:
        tab_id: ID of the tab containing the element (get from browser_list_tabs)
        selector: CSS selector of element to type into
        text: Text to type
    """
    result = await send_command("type", tabId=tab_id, selector=selector, text=text)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Typed successfully"


@mcp.tool()
async def browser_fill(tab_id: int, selector: str, value: str) -> str:
    """Clear and fill a form input or contenteditable element with new text.
    
    Args:
        tab_id: ID of the tab containing the element (get from browser_list_tabs)
        selector: CSS selector of input/textarea/contenteditable
        value: Value to fill
    """
    result = await send_command("fill", tabId=tab_id, selector=selector, value=value)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Filled successfully"


@mcp.tool()
async def browser_press(tab_id: int, key: str) -> str:
    """Press a single keyboard key.
    
    Args:
        tab_id: ID of the tab to send the key to (get from browser_list_tabs)
        key: Key to press (e.g., 'Enter', 'Tab', 'Escape', 'a')
    """
    result = await send_command("keyPress", tabId=tab_id, key=key)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return f"Pressed {key}"


@mcp.tool()
async def browser_key_combo(tab_id: int, keys: str) -> str:
    """Press a keyboard shortcut (key combination).
    
    Args:
        tab_id: ID of the tab to send the keys to (get from browser_list_tabs)
        keys: Comma-separated keys (e.g., 'Control,Shift,d' or 'Alt,Tab')
    """
    key_list = [k.strip() for k in keys.split(",")]
    result = await send_command("keyCombo", tabId=tab_id, keys=key_list)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return f"Pressed {'+'.join(key_list)}"


@mcp.tool()
async def browser_scroll_to(tab_id: int, selector: str) -> str:
    """Scroll an element smoothly into view (centered in viewport).
    
    Args:
        tab_id: ID of the tab containing the element (get from browser_list_tabs)
        selector: CSS selector of element to scroll to
    """
    result = await send_command("scrollIntoView", tabId=tab_id, selector=selector)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Scrolled into view"


@mcp.tool()
async def browser_select(tab_id: int, selector: str, value: str) -> str:
    """Select an option in a dropdown/select element.
    
    Args:
        tab_id: ID of the tab containing the element (get from browser_list_tabs)
        selector: CSS selector of the select element
        value: Value of the option to select
    """
    result = await send_command("selectOption", tabId=tab_id, selector=selector, value=value)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Option selected"


@mcp.tool()
async def browser_check(tab_id: int, selector: str) -> str:
    """Check a checkbox (no-op if already checked).
    
    Args:
        tab_id: ID of the tab containing the element (get from browser_list_tabs)
        selector: CSS selector of the checkbox
    """
    result = await send_command("check", tabId=tab_id, selector=selector)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Checked"


# ==========================================
# Navigation Tools
# ==========================================

@mcp.tool()
async def browser_navigate(tab_id: int, url: str) -> str:
    """Navigate the active tab to a URL.
    
    Args:
        tab_id: ID of the tab to navigate (get from browser_list_tabs)
        url: Full URL to navigate to (e.g., 'https://example.com')
    """
    result = await send_command("navigate", tabId=tab_id, url=url)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return f"Navigating to {url}"


@mcp.tool()
async def browser_reload(tab_id: int) -> str:
    """Reload the current page.
    
    Args:
        tab_id: ID of the tab to reload (get from browser_list_tabs)
    """
    result = await send_command("reloadTab", tabId=tab_id)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Page reloaded"


@mcp.tool()
async def browser_back(tab_id: int) -> str:
    """Go back in browser history.
    
    Args:
        tab_id: ID of the tab to go back in (get from browser_list_tabs)
    """
    result = await send_command("goBack", tabId=tab_id)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Navigated back"


@mcp.tool()
async def browser_get_url(tab_id: int) -> str:
    """Get the current page URL.
    
    Args:
        tab_id: ID of the tab to get URL from (get from browser_list_tabs)
    """
    result = await send_command("getURL", tabId=tab_id)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return result.get("data", "")


@mcp.tool()
async def browser_get_title(tab_id: int) -> str:
    """Get the current page title.
    
    Args:
        tab_id: ID of the tab to get title from (get from browser_list_tabs)
    """
    result = await send_command("getTitle", tabId=tab_id)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return result.get("data", "")


@mcp.tool()
async def browser_get_page_text(tab_id: int) -> str:
    """Get the full visible text content of the current page (up to 50KB).
    
    Args:
        tab_id: ID of the tab to get text from (get from browser_list_tabs)
    """
    result = await send_command("getPageText", tabId=tab_id)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return result.get("data", "")


@mcp.tool()
async def browser_screenshot(tab_id: int, save_path: str = None) -> str:
    """Take a screenshot of the specified tab. Returns base64 PNG data URL.
    
    Args:
        tab_id: ID of the tab to screenshot (get from browser_list_tabs)
        save_path: Optional file path to save the screenshot as PNG (e.g., 'C:/screenshots/page.png').
                   If provided, saves to disk and returns the file path instead of base64 data.
                   Parent directories will be created automatically.
    """
    result = await send_command("captureScreenshot", tabId=tab_id)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    data = result.get("data", {})
    data_url = data.get("dataUrl", "")
    
    if save_path and data_url:
        import base64, os
        # Strip data URL prefix: "data:image/png;base64,..."
        b64 = data_url.split(",", 1)[-1] if "," in data_url else data_url
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(base64.b64decode(b64))
        return f"Screenshot saved to: {os.path.abspath(save_path)}"
    
    return data_url or "Screenshot failed"


@mcp.tool()
async def browser_evaluate(tab_id: int, code: str) -> str:
    """Execute arbitrary JavaScript code in the current page's MAIN world context.
    Bypasses page CSP via chrome.scripting.executeScript. Works on ALL sites,
    including YouTube, Gmail, and other Trusted Types-enforced pages (CSP headers
    are automatically stripped by the extension).
    
    Supports both expressions and return statements.
    
    Args:
        tab_id: ID of the tab to execute JS in (get from browser_list_tabs)
        code: JavaScript code to evaluate (e.g., 'document.title', '2 + 2',
              'return document.querySelectorAll("a").length',
              'return [...document.querySelectorAll("a")].map(a => a.href)')
    """
    result = await send_command("evaluate", tabId=tab_id, code=code)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    data = result.get("data")
    return json.dumps(data) if isinstance(data, (dict, list)) else str(data)


# ==========================================
# Tab Management Tools
# ==========================================

@mcp.tool()
async def browser_list_tabs() -> str:
    """List all open browser tabs with their IDs, URLs, titles, active status, windowId, and incognito status."""
    result = await send_command("listTabs")
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


@mcp.tool()
async def browser_new_tab(url: str = "about:blank") -> str:
    """Open a new browser tab.
    
    Args:
        url: URL to open in the new tab (default: about:blank)
    """
    result = await send_command("newTab", url=url)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"))


@mcp.tool()
async def browser_close_tab(tab_id: int) -> str:
    """Close a browser tab.
    
    Args:
        tab_id: ID of the tab to close (get from browser_list_tabs)
    """
    result = await send_command("closeTab", tabId=tab_id)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return f"Tab {tab_id} closed"


@mcp.tool()
async def browser_switch_tab(tab_id: int) -> str:
    """Switch to (activate) a browser tab and focus its window.
    
    Args:
        tab_id: ID of the tab to switch to (get from browser_list_tabs)
    """
    result = await send_command("switchTab", tabId=tab_id)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return f"Switched to tab {tab_id}"


# ==========================================
# Window Management Tools
# ==========================================

@mcp.tool()
async def browser_new_window(url: str = "about:blank") -> str:
    """Open a new browser window in the user's profile (with cookies and sessions).
    
    Args:
        url: URL to open in the new window (default: about:blank)
    """
    result = await send_command("newWindow", url=url)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


@mcp.tool()
async def browser_new_incognito_window(url: str = "about:blank") -> str:
    """Open a new private/incognito browser window (clean session, no cookies).
    Useful for testing without existing sessions or for isolated browsing.
    
    Args:
        url: URL to open in the new incognito window (default: about:blank)
    """
    result = await send_command("newIncognitoWindow", url=url)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


@mcp.tool()
async def browser_list_windows() -> str:
    """List all open browser windows with their IDs, types, sizes, and incognito status."""
    result = await send_command("listWindows")
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


@mcp.tool()
async def browser_close_window(window_id: int) -> str:
    """Close a browser window and all its tabs.
    
    Args:
        window_id: ID of the window to close (get from browser_list_windows)
    """
    result = await send_command("closeWindow", windowId=window_id)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return f"Window {window_id} closed"


@mcp.tool()
async def browser_resize_window(window_id: int, width: int = None, height: int = None) -> str:
    """Resize a browser window.
    
    Args:
        window_id: ID of the window to resize (get from browser_list_windows)
        width: New width in pixels
        height: New height in pixels
    """
    kwargs = {"windowId": window_id}
    if width is not None:
        kwargs["width"] = width
    if height is not None:
        kwargs["height"] = height
    result = await send_command("resizeWindow", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


# ==========================================
# Cookie Tools
# ==========================================

@mcp.tool()
async def browser_get_cookies(url: str) -> str:
    """Get all cookies for a URL.
    
    Args:
        url: URL to get cookies for (e.g., 'https://example.com')
    """
    result = await send_command("getCookies", url=url)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


# ==========================================
# Entry Point
# ==========================================

def main():
    logger.info("StealthDOM MCP Server starting...")
    logger.info("Connecting to bridge at %s", BRIDGE_URL)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
