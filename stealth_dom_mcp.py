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

import websockets
from mcp.server.fastmcp import FastMCP

# MCP servers must NOT print to stdout (it's reserved for MCP protocol)
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("stealth_dom")

# ==========================================
# Bridge Connection
# ==========================================

BRIDGE_URL = "ws://127.0.0.1:9878"
_ws = None
_ws_lock = asyncio.Lock()


async def get_bridge():
    """Get or create WebSocket connection to bridge control port."""
    global _ws
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
    """Send a command to the extension via the bridge."""
    ws = await get_bridge()
    
    msg = {"action": action, "_timeout": _timeout, **kwargs}
    await ws.send(json.dumps(msg))
    
    response = await asyncio.wait_for(ws.recv(), _timeout + 5)
    return json.loads(response)


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

CAPABILITIES SUMMARY (35+ tools):
- DOM: query, queryAll, getText, getHTML, getAttribute, waitFor
- Interact: click, type, fill, press, keyCombo, check, select, scrollTo
- Navigate: navigate, back, reload, getURL, getTitle, getPageText
- Tabs: listTabs, newTab, closeTab, switchTab
- Windows: newWindow, newIncognitoWindow, listWindows, closeWindow, resizeWindow
- Screenshots: screenshot (full page PNG)
- Cookies: getCookies
- JavaScript: evaluate (arbitrary JS in page context, works on ALL sites)
- Advanced: proxyFetch (browser-native HTTP with real TLS fingerprint)
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
- `browser_query(selector)` — Query single element by CSS selector
- `browser_query_all(selector, limit)` — Query multiple elements
- `browser_get_text(selector)` — Get inner text of element
- `browser_get_html(selector, max_length)` — Get outer HTML
- `browser_get_attribute(selector, attribute)` — Get element attribute
- `browser_wait_for(selector, timeout)` — Wait for element to appear
- `browser_get_page_text()` — Get full page text (up to 50KB)

### DOM Interaction
- `browser_click(selector)` — Click element (auto-scrolls into view)
- `browser_type(selector, text)` — Type text (appends)
- `browser_fill(selector, value)` — Clear and fill input
- `browser_press(key)` — Press keyboard key
- `browser_key_combo(keys)` — Press key combination
- `browser_check(selector)` — Check checkbox
- `browser_select(selector, value)` — Select dropdown option
- `browser_scroll_to(selector)` — Scroll element into view

### Navigation
- `browser_navigate(url)` — Navigate to URL
- `browser_back()` — Go back in history
- `browser_reload()` — Reload page
- `browser_get_url()` — Get current URL
- `browser_get_title()` — Get page title

### Tab Management
- `browser_list_tabs()` — List all tabs (ID, URL, title, active status)
- `browser_new_tab(url)` — Open new tab
- `browser_close_tab(tab_id)` — Close tab
- `browser_switch_tab(tab_id)` — Switch to tab

### Window Management
- `browser_new_window(url)` — Open new browser window (with user session)
- `browser_new_incognito_window(url)` — Open private window (clean session)
- `browser_list_windows()` — List all windows (ID, type, size, incognito)
- `browser_close_window(window_id)` — Close window
- `browser_resize_window(window_id, width, height)` — Resize window

### Screenshots
- `browser_screenshot()` — Capture visible tab as base64 PNG

### Cookies
- `browser_get_cookies(url)` — Get all cookies for a URL

### JavaScript Execution
- `browser_evaluate(code)` — Run arbitrary JS in the page's MAIN world.
  Works on ALL sites, including YouTube, Gmail, and Trusted Types-enforced pages.
  CSP headers are automatically stripped to enable eval everywhere.
  Supports expressions (`document.title`) and return statements (`return 2 + 2`).

### Architecture
Bridge connection runs in the extension's background service worker.
Commands flow: MCP → Bridge (port 9878) → Extension Background → Content Script → DOM.
The background script handles tabs, windows, screenshots, cookies, and JS execution.
The content script handles DOM queries and interactions in the page's DOM.
"""


# ==========================================
# DOM Reading Tools
# ==========================================

@mcp.tool()
async def browser_query(selector: str) -> str:
    """Query a single DOM element by CSS selector. Returns element details (tag, id, class, text, visibility).
    
    Args:
        selector: CSS selector (e.g., '#my-id', '.my-class', 'div.container > p')
    """
    result = await send_command("querySelector", selector=selector)
    if not result.get("success"):
        return f"Error: {result.get('error', 'Unknown error')}"
    data = result.get("data")
    if data is None:
        return f"No element found matching: {selector}"
    return json.dumps(data, indent=2)


@mcp.tool()
async def browser_query_all(selector: str, limit: int = 0) -> str:
    """Query all DOM elements matching a CSS selector. Returns list of element details.
    
    Args:
        selector: CSS selector
        limit: Maximum number of elements to return (default 0 = all)
    """
    result = await send_command("querySelectorAll", selector=selector, limit=limit)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


@mcp.tool()
async def browser_get_text(selector: str) -> str:
    """Get the inner text content of a DOM element.
    
    Args:
        selector: CSS selector
    """
    result = await send_command("getInnerText", selector=selector)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return result.get("data", {}).get("text", "")


@mcp.tool()
async def browser_get_html(selector: str, max_length: int = 0) -> str:
    """Get the outer HTML of a DOM element.
    
    Args:
        selector: CSS selector
        max_length: Maximum characters to return (default 0 = no limit)
    """
    result = await send_command("getOuterHTML", selector=selector, maxLength=max_length)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return result.get("data") or "Element not found"


@mcp.tool()
async def browser_get_attribute(selector: str, attribute: str) -> str:
    """Get an HTML attribute value from a DOM element.
    
    Args:
        selector: CSS selector
        attribute: Attribute name (e.g., 'href', 'src', 'data-id')
    """
    result = await send_command("getAttribute", selector=selector, attribute=attribute)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return str(result.get("data"))


@mcp.tool()
async def browser_wait_for(selector: str, timeout: int = 10000) -> str:
    """Wait for a DOM element to appear. Polls every 200ms until found or timeout.
    
    Args:
        selector: CSS selector to wait for
        timeout: Maximum wait time in milliseconds (default 10000)
    """
    result = await send_command("waitForSelector", selector=selector, timeout=timeout, _timeout=timeout/1000 + 5)
    if not result.get("success"):
        return f"Timeout: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


# ==========================================
# DOM Interaction Tools
# ==========================================

@mcp.tool()
async def browser_click(selector: str) -> str:
    """Click a DOM element. Element is scrolled into view first.
    
    Args:
        selector: CSS selector of element to click
    """
    result = await send_command("click", selector=selector)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Clicked successfully"


@mcp.tool()
async def browser_type(selector: str, text: str) -> str:
    """Type text into a DOM element (appends to existing content). Works with contenteditable divs.
    
    Args:
        selector: CSS selector of element to type into
        text: Text to type
    """
    result = await send_command("type", selector=selector, text=text)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Typed successfully"


@mcp.tool()
async def browser_fill(selector: str, value: str) -> str:
    """Clear and fill a form input or contenteditable element with new text.
    
    Args:
        selector: CSS selector of input/textarea/contenteditable
        value: Value to fill
    """
    result = await send_command("fill", selector=selector, value=value)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Filled successfully"


@mcp.tool()
async def browser_press(key: str) -> str:
    """Press a single keyboard key.
    
    Args:
        key: Key to press (e.g., 'Enter', 'Tab', 'Escape', 'a')
    """
    result = await send_command("keyPress", key=key)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return f"Pressed {key}"


@mcp.tool()
async def browser_key_combo(keys: str) -> str:
    """Press a keyboard shortcut (key combination).
    
    Args:
        keys: Comma-separated keys (e.g., 'Control,Shift,d' or 'Alt,Tab')
    """
    key_list = [k.strip() for k in keys.split(",")]
    result = await send_command("keyCombo", keys=key_list)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return f"Pressed {'+'.join(key_list)}"


@mcp.tool()
async def browser_scroll_to(selector: str) -> str:
    """Scroll an element smoothly into view (centered in viewport).
    
    Args:
        selector: CSS selector of element to scroll to
    """
    result = await send_command("scrollIntoView", selector=selector)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Scrolled into view"


@mcp.tool()
async def browser_select(selector: str, value: str) -> str:
    """Select an option in a dropdown/select element.
    
    Args:
        selector: CSS selector of the select element
        value: Value of the option to select
    """
    result = await send_command("selectOption", selector=selector, value=value)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Option selected"


@mcp.tool()
async def browser_check(selector: str) -> str:
    """Check a checkbox (no-op if already checked).
    
    Args:
        selector: CSS selector of the checkbox
    """
    result = await send_command("check", selector=selector)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Checked"


# ==========================================
# Navigation Tools
# ==========================================

@mcp.tool()
async def browser_navigate(url: str) -> str:
    """Navigate the active tab to a URL.
    
    Args:
        url: Full URL to navigate to (e.g., 'https://example.com')
    """
    result = await send_command("navigate", url=url)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return f"Navigating to {url}"


@mcp.tool()
async def browser_reload() -> str:
    """Reload the current page."""
    result = await send_command("reloadTab")
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Page reloaded"


@mcp.tool()
async def browser_back() -> str:
    """Go back in browser history."""
    result = await send_command("goBack")
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Navigated back"


@mcp.tool()
async def browser_get_url() -> str:
    """Get the current page URL."""
    result = await send_command("getURL")
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return result.get("data", "")


@mcp.tool()
async def browser_get_title() -> str:
    """Get the current page title."""
    result = await send_command("getTitle")
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return result.get("data", "")


@mcp.tool()
async def browser_get_page_text() -> str:
    """Get the full visible text content of the current page (up to 50KB)."""
    result = await send_command("getPageText")
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return result.get("data", "")


@mcp.tool()
async def browser_screenshot(save_path: str = None) -> str:
    """Take a screenshot of the current visible tab. Returns base64 PNG data URL.
    
    Args:
        save_path: Optional file path to save the screenshot as PNG (e.g., 'C:/screenshots/page.png').
                   If provided, saves to disk and returns the file path instead of base64 data.
                   Parent directories will be created automatically.
    """
    result = await send_command("captureScreenshot")
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
async def browser_evaluate(code: str) -> str:
    """Execute arbitrary JavaScript code in the current page's MAIN world context.
    Bypasses page CSP via chrome.scripting.executeScript. Works on ALL sites,
    including YouTube, Gmail, and other Trusted Types-enforced pages (CSP headers
    are automatically stripped by the extension).
    
    Supports both expressions and return statements.
    
    Args:
        code: JavaScript code to evaluate (e.g., 'document.title', '2 + 2',
              'return document.querySelectorAll("a").length',
              'return [...document.querySelectorAll("a")].map(a => a.href)')
    """
    result = await send_command("evaluate", code=code)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    data = result.get("data")
    return json.dumps(data) if isinstance(data, (dict, list)) else str(data)


# ==========================================
# Tab Management Tools
# ==========================================

@mcp.tool()
async def browser_list_tabs() -> str:
    """List all open browser tabs with their IDs, URLs, titles, and active status."""
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
