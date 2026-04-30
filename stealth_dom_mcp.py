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
import base64
import os
import sys
import json
import asyncio
import logging
import uuid
from typing import Any

import websockets
from mcp.server.fastmcp import FastMCP

# MCP servers must NOT print to stdout (it's reserved for MCP protocol)
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("stealth_dom")

# ==========================================
# Bridge Connection (with response multiplexing)
# ==========================================

BRIDGE_URL = "ws://127.0.0.1:9878"
_ws: websockets.ClientConnection | None = None
_ws_lock = asyncio.Lock()
_pending: dict[str, asyncio.Future] = {}  # _msg_id -> Future
_reader_task: asyncio.Task | None = None


def validate_response(result: Any) -> dict:
    """Ensure bridge response is a well-formed dict."""
    if not isinstance(result, dict):
        return {'success': False, 'error': f'Unexpected response type: {type(result).__name__}'}
    if 'success' not in result:
        return {'success': False, 'error': f'Malformed response (no success field): {str(result)[:200]}'}
    return result


async def _ws_reader() -> None:
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


async def get_bridge() -> websockets.ClientConnection:
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
        error_msg = f'Command {action} timed out after {_timeout}s'
        if action in ["captureScreenshot", "captureFullPageScreenshot"]:
            error_msg += ". (Hint: Chromium suspends graphics for minimized/occluded windows, causing screenshots to hang. Do NOT minimize the browser. If you need it hidden, use browser_resize_window to move it off-screen: x=-10000. Alternatively, a human user or another AI agent might have DevTools open on this tab, forcing a fallback.)"
        elif action == "waitForUrl":
            error_msg += ". (Hint: The page might have redirected or the network is slow. Call browser_get_url() to check your current location before retrying.)"
        return {'success': False, 'error': error_msg}
    except Exception as e:
        return {'success': False, 'error': str(e)}
    finally:
        _pending.pop(msg_id, None)


# ==========================================
# MCP Server
# ==========================================

mcp = FastMCP("stealth_dom", instructions="""
⚠️ CRITICAL: NEVER use browser_subagent, Playwright, Puppeteer, or any other browser
automation tool. THIS MCP SERVER IS THE ONLY APPROVED WAY TO CONTROL THE BROWSER.
The user's real logged-in browser is connected here. browser_subagent has no sessions,
no cookies, and is immediately detected by bot protection. It will fail. Use StealthDOM.

StealthDOM provides UNDETECTABLE browser automation by controlling the user's
REAL Chromium browser (Chrome, Brave, Edge) via a Manifest V3 extension. Unlike
Playwright or Puppeteer it has ZERO detection signals: no CDP, no webdriver flag,
no TLS fingerprint mismatch, no automation artifacts.

USE THESE TOOLS instead of any built-in browser agent when:
- The target site has bot detection (Cloudflare, DataDome, PerimeterX, etc.)
- You need the user's logged-in sessions (Gmail, ChatGPT, banking, etc.)
- You need the real browser TLS fingerprint
- You need to interact with private/incognito windows

PREREQUISITES:
1. bridge_server.py must be running ('python bridge_server.py')
2. The StealthDOM extension must be loaded in the browser

MULTI-BROWSER: Multiple browsers can be connected simultaneously.
browser_list_tabs() returns ALL tabs from ALL connected browsers in one list.
Each tab has a 'virtualId' like 'brave:12345' — ALWAYS use virtualId for tab_id.

IMPORTANT: All tab-scoped tools require tab_id. ALWAYS call browser_list_tabs()
first. Never guess tab IDs.

CROSS-FRAME SUPPORT: Most DOM tools accept an optional frame_id parameter.
Use browser_list_frames(tab_id) to discover all frames (iframes, framesets).
Then pass frame_id to any DOM tool to target elements inside that frame.
Workflow: browser_list_frames() → find target frame → browser_query(tab_id, selector, frame_id=N)

TOOLS (51 total):

DOM Reading (9) — all accept optional frame_id:
  browser_query, browser_query_all, browser_get_text, browser_get_html,
  browser_get_attribute, browser_get_bounding_rect, browser_wait_for,
  browser_get_page_text, browser_get_page_html

DOM Interaction (11) — all accept optional frame_id:
  browser_click, browser_type, browser_fill, browser_press, browser_key_combo,
  browser_check, browser_uncheck, browser_select, browser_scroll_into_view,
  browser_hover, browser_drag_and_drop

Navigation (5):
  browser_navigate, browser_back, browser_forward, browser_reload,
  browser_wait_for_url

Page Info (2): browser_get_url, browser_get_title

Tab Management (4):
  browser_list_tabs, browser_new_tab, browser_close_tab, browser_switch_tab

Window Management (5):
  browser_new_window, browser_new_incognito_window, browser_list_windows,
  browser_close_window, browser_resize_window

Screenshots (2):
  browser_screenshot, browser_screenshot_full_page (scroll-and-stitch)

Cookies (3):
  browser_get_cookies, browser_set_cookie, browser_delete_cookie

Network Capture (3):
  browser_start_net_capture, browser_stop_net_capture, browser_get_net_capture
  Note: get_net_capture returns {requests, overflowCount, bufferSize} —
  check overflowCount > 0 to know if any traffic was missed (circular buffer, 5000 cap)

JavaScript (1): browser_evaluate (MAIN or ISOLATED world)

File Upload (1): browser_upload_file
Proxy Fetch (1): browser_proxy_fetch (real browser TLS fingerprint)
Connections (1): browser_list_connections

Frame Support (2):
  browser_list_frames, browser_evaluate_all_frames
  Note: Use browser_list_frames to discover frame IDs, then pass frame_id to any
  DOM reading/interaction tool. For JS execution across all frames simultaneously,
  use browser_evaluate_all_frames.
""")


# ==========================================
# MCP Resource: Capabilities
# ==========================================

@mcp.resource("stealth://capabilities")
def get_capabilities() -> str:
    """Full capability reference for StealthDOM."""
    return """# StealthDOM Capabilities

## Architecture

MCP tools → Bridge (ws://127.0.0.1:9878) → Extension Background → Content Script → DOM

- Port 9877: Extension connects (multiple browsers supported simultaneously)
- Port 9878: MCP server / control clients connect
- Tab IDs are virtualised as "label:tabId" (e.g. "brave:12345") for multi-browser routing
- browser_list_tabs() aggregates ALL tabs from ALL connected browsers in one flat list
- Content scripts are injected ON-DEMAND via chrome.scripting.executeScript (allFrames: true) when the first command targets a tab — NOT declared in manifest.json (saves memory on untouched tabs)

## Why StealthDOM over Playwright?

| Aspect | Playwright | StealthDOM |
|--------|-----------|------------|
| Detection risk | HIGH — CDP, webdriver flag, TLS mismatch | ZERO — native browser citizen |
| Cloudflare/DataDome | Frequently blocked | Never blocked |
| User sessions | Must re-authenticate | Uses existing logged-in sessions |
| TLS fingerprint | Synthetic (detectable) | Real browser (identical to human) |

## Cross-Frame Support

All DOM reading and interaction tools accept an optional `frame_id` parameter.
This enables targeting elements inside iframes and framesets (Gmail, OAuth dialogs, payment widgets).

**Workflow:**
1. `browser_list_frames(tab_id)` → discover all frames (returns frameId, URL, elementCount per frame)
2. Pass `frame_id=N` to any DOM tool → targets that specific frame
3. Omit `frame_id` → targets top-level frame (default, backward compatible)

## Available Tools (46)

### DOM Reading (9) — all accept optional frame_id
- `browser_query(tab_id, selector, frame_id=None)` — Query single element
- `browser_query_all(tab_id, selector, limit=0, frame_id=None)` — Query multiple elements
- `browser_get_text(tab_id, selector, frame_id=None)` — Inner text
- `browser_get_html(tab_id, selector, max_length=0, frame_id=None)` — Outer HTML
- `browser_get_attribute(tab_id, selector, attribute, frame_id=None)` — Element attribute
- `browser_get_bounding_rect(tab_id, selector, frame_id=None)` — Position and size
- `browser_wait_for(tab_id, selector, timeout=10000, frame_id=None)` — Wait for element
- `browser_get_page_text(tab_id, max_length=0, frame_id=None)` — Full page text (0 = no limit)
- `browser_get_page_html(tab_id, max_length=0, frame_id=None)` — Full page HTML

### DOM Interaction (11) — all accept optional frame_id
- `browser_click(tab_id, selector, frame_id=None)` — Click (auto-scrolls into view)
- `browser_type(tab_id, selector, text, frame_id=None)` — Type/append text
- `browser_fill(tab_id, selector, value, frame_id=None)` — Clear and fill
- `browser_press(tab_id, key, frame_id=None)` — Single key press
- `browser_key_combo(tab_id, keys, frame_id=None)` — Key combo (comma-separated: 'Control,Shift,d')
- `browser_check(tab_id, selector, frame_id=None)` — Check checkbox
- `browser_uncheck(tab_id, selector, frame_id=None)` — Uncheck checkbox
- `browser_select(tab_id, selector, value, frame_id=None)` — Select dropdown option
- `browser_scroll_into_view(tab_id, selector, frame_id=None)` — Scroll element into view
- `browser_hover(tab_id, selector, frame_id=None)` — Hover (mouseenter/mouseover/mousemove)
- `browser_drag_and_drop(tab_id, source_selector, target_selector, frame_id=None)` — HTML5 drag-drop

### Navigation (5)
- `browser_navigate(tab_id, url)` — Navigate to URL
- `browser_back(tab_id)` — Go back
- `browser_forward(tab_id)` — Go forward
- `browser_reload(tab_id)` — Reload page
- `browser_wait_for_url(tab_id, pattern, timeout=10000)` — Wait for URL match

### Page Info (3)
- `browser_get_url(tab_id)` — Current URL
- `browser_get_title(tab_id)` — Page title
- `browser_get_page_text(tab_id)` — Full page visible text

### Tab Management (4)
- `browser_list_tabs()` — All tabs from all browsers (virtualId, url, title, active, browserId)
- `browser_new_tab(url='about:blank')` — Open new tab
- `browser_close_tab(tab_id)` — Close tab
- `browser_switch_tab(tab_id)` — Activate tab

### Window Management (5)
- `browser_new_window(url='about:blank')` — New window (with session)
- `browser_new_incognito_window(url='about:blank')` — New private window
- `browser_list_windows()` — All windows
- `browser_close_window(window_id)` — Close window
- `browser_resize_window(window_id, width, height)` — Resize

### Screenshots (2)
- `browser_screenshot(tab_id, save_path=None)` — Visible area PNG
- `browser_screenshot_full_page(tab_id, max_height=20000, save_path=None)` — Full scroll-stitch PNG

### Cookies (3)
- `browser_get_cookies(url)` — Get all cookies for URL
- `browser_set_cookie(url, name, value, domain=None, path=None, secure=None, http_only=None, expiration_date=None)` — Set cookie
- `browser_delete_cookie(url, name)` — Delete cookie

### Network Capture (3)
- `browser_start_net_capture()` — Start capturing requests/responses (resets buffer)
- `browser_stop_net_capture()` — Stop capture
- `browser_get_net_capture()` — Returns {requests, overflowCount, bufferSize, capturedCount}
  WARNING: If overflowCount > 0, some early requests were overwritten (circular buffer, 5000 cap)

### JavaScript (1)
- `browser_evaluate(tab_id, code, world='MAIN')` — Arbitrary JS. world='ISOLATED' for chrome.runtime access

### File & Fetch (2)
- `browser_upload_file(tab_id, selector, data_url)` — Set file on input[type=file]
- `browser_proxy_fetch(tab_id, url, method='GET', headers=None, body=None, body_type='json')` — Fetch via real browser (real TLS fingerprint + cookies)

### Connections (1)
- `browser_list_connections()` — Show connected browsers and their labels

### Frame Support (2)
- `browser_list_frames(tab_id)` — List all frames in a tab (frameId, URL, elementCount, hasBody per frame)
- `browser_evaluate_all_frames(tab_id, code, world='MAIN')` — Execute JS in ALL frames, returns per-frame results

## Tips
- To focus/blur an element: use browser_evaluate with 'document.querySelector("#id").focus()'
- To double-click: use browser_evaluate with el.dispatchEvent(new MouseEvent('dblclick', {bubbles:true}))
- For JS frameworks (React/Vue): browser_fill uses native value setter to trigger onChange
- For cross-frame access: browser_list_frames → get frameId → pass frame_id to any DOM tool
"""


# ==========================================
# DOM Reading Tools
# ==========================================

@mcp.tool()
async def browser_query(tab_id: int | str, selector: str, frame_id: int | None = None) -> str:
    """Query a single DOM element by CSS selector. Returns element details (tag, id, class, text, visibility).
    
    Args:
        tab_id: ID of the tab to query (get from browser_list_tabs)
        selector: CSS selector (e.g., '#my-id', '.my-class', 'div.container > p')
        frame_id: Optional frame ID to target (get from browser_list_frames). Omit for top-level frame.
    """
    kwargs = dict(tabId=tab_id, selector=selector)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("querySelector", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error', 'Unknown error')}"
    data = result.get("data")
    if data is None:
        hint = result.get("hint", "")
        return hint if hint else f"No element found matching: {selector}"
    return json.dumps(data, indent=2)


@mcp.tool()
async def browser_query_all(tab_id: int | str, selector: str, limit: int = 0, frame_id: int | None = None) -> str:
    """Query all DOM elements matching a CSS selector. Returns list of element details.
    
    Args:
        tab_id: ID of the tab to query (get from browser_list_tabs)
        selector: CSS selector
        limit: Maximum number of elements to return (default 0 = all)
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    kwargs = dict(tabId=tab_id, selector=selector, limit=limit)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("querySelectorAll", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


@mcp.tool()
async def browser_get_text(tab_id: int | str, selector: str, frame_id: int | None = None) -> str:
    """Get the inner text content of a DOM element.
    
    Args:
        tab_id: ID of the tab to query (get from browser_list_tabs)
        selector: CSS selector
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    kwargs = dict(tabId=tab_id, selector=selector)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("getInnerText", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    data = result.get("data")
    if isinstance(data, dict):
        return data.get("text", "")
    return str(data) if data is not None else ""


@mcp.tool()
async def browser_get_html(tab_id: int | str, selector: str, max_length: int = 0, frame_id: int | None = None) -> str:
    """Get the outer HTML of a DOM element.
    
    Args:
        tab_id: ID of the tab to query (get from browser_list_tabs)
        selector: CSS selector
        max_length: Maximum characters to return (default 0 = no limit)
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    kwargs = dict(tabId=tab_id, selector=selector, maxLength=max_length)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("getOuterHTML", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    data = result.get("data")
    if data is None:
        return "Element not found"
    return data


@mcp.tool()
async def browser_get_attribute(tab_id: int | str, selector: str, attribute: str, frame_id: int | None = None) -> str:
    """Get an HTML attribute value from a DOM element.
    
    Args:
        tab_id: ID of the tab to query (get from browser_list_tabs)
        selector: CSS selector
        attribute: Attribute name (e.g., 'href', 'src', 'data-id')
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    kwargs = dict(tabId=tab_id, selector=selector, attribute=attribute)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("getAttribute", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    val = result.get("data")
    return str(val) if val is not None else "null"


@mcp.tool()
async def browser_wait_for(tab_id: int | str, selector: str, timeout: int = 10000, frame_id: int | None = None) -> str:
    """Wait for a DOM element to appear. Polls every 200ms until found or timeout.
    
    Args:
        tab_id: ID of the tab to watch (get from browser_list_tabs)
        selector: CSS selector to wait for
        timeout: Maximum wait time in milliseconds (default 10000)
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    kwargs = dict(tabId=tab_id, selector=selector, timeout=timeout)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("waitForSelector", _timeout=timeout/1000 + 5, **kwargs)
    if not result.get("success"):
        return f"Timeout: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


@mcp.tool()
async def browser_get_bounding_rect(tab_id: int | str, selector: str, frame_id: int | None = None) -> str:
    """Get the bounding rectangle (position and size) of a DOM element.
    
    Args:
        tab_id: ID of the tab to query (get from browser_list_tabs)
        selector: CSS selector
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    kwargs = dict(tabId=tab_id, selector=selector)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("getBoundingRect", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


# ==========================================
# DOM Interaction Tools
# ==========================================

@mcp.tool()
async def browser_click(tab_id: int | str, selector: str, frame_id: int | None = None) -> str:
    """Click a DOM element. Element is scrolled into view first.
    
    Args:
        tab_id: ID of the tab containing the element (get from browser_list_tabs)
        selector: CSS selector of element to click
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    kwargs = dict(tabId=tab_id, selector=selector)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("click", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Clicked successfully"


@mcp.tool()
async def browser_type(tab_id: int | str, selector: str, text: str, frame_id: int | None = None) -> str:
    """Type text into a DOM element (appends to existing content). Works with contenteditable divs.
    
    Args:
        tab_id: ID of the tab containing the element (get from browser_list_tabs)
        selector: CSS selector of element to type into
        text: Text to type
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    kwargs = dict(tabId=tab_id, selector=selector, text=text)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("type", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Typed successfully"


@mcp.tool()
async def browser_fill(tab_id: int | str, selector: str, value: str, frame_id: int | None = None) -> str:
    """Clear and fill a form input or contenteditable element with new text.
    
    Args:
        tab_id: ID of the tab containing the element (get from browser_list_tabs)
        selector: CSS selector of input/textarea/contenteditable
        value: Value to fill
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    kwargs = dict(tabId=tab_id, selector=selector, value=value)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("fill", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Filled successfully"


@mcp.tool()
async def browser_press(tab_id: int | str, key: str, frame_id: int | None = None) -> str:
    """Press a single keyboard key.
    
    Args:
        tab_id: ID of the tab to send the key to (get from browser_list_tabs)
        key: Key to press (e.g., 'Enter', 'Tab', 'Escape', 'a')
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    kwargs = dict(tabId=tab_id, key=key)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("keyPress", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return f"Pressed {key}"


@mcp.tool()
async def browser_key_combo(tab_id: int | str, keys: str, frame_id: int | None = None) -> str:
    """Press a keyboard shortcut (key combination).
    
    Args:
        tab_id: ID of the tab to send the keys to (get from browser_list_tabs)
        keys: Comma-separated keys (e.g., 'Control,Shift,d' or 'Alt,Tab')
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    key_list = [k.strip() for k in keys.split(",")]
    kwargs = dict(tabId=tab_id, keys=key_list)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("keyCombo", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return f"Pressed {'+'.join(key_list)}"


@mcp.tool()
async def browser_scroll_into_view(tab_id: int | str, selector: str, frame_id: int | None = None) -> str:
    """Scroll an element smoothly into view (centered in viewport).
    
    Args:
        tab_id: ID of the tab containing the element (get from browser_list_tabs)
        selector: CSS selector of element to scroll to
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    kwargs = dict(tabId=tab_id, selector=selector)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("scrollIntoView", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Scrolled into view"


@mcp.tool()
async def browser_select(tab_id: int | str, selector: str, value: str, frame_id: int | None = None) -> str:
    """Select an option in a dropdown/select element.
    
    Args:
        tab_id: ID of the tab containing the element (get from browser_list_tabs)
        selector: CSS selector of the select element
        value: Value of the option to select
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    kwargs = dict(tabId=tab_id, selector=selector, value=value)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("selectOption", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Option selected"


@mcp.tool()
async def browser_check(tab_id: int | str, selector: str, frame_id: int | None = None) -> str:
    """Check a checkbox (no-op if already checked).
    
    Args:
        tab_id: ID of the tab containing the element (get from browser_list_tabs)
        selector: CSS selector of the checkbox
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    kwargs = dict(tabId=tab_id, selector=selector)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("check", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Checked"


@mcp.tool()
async def browser_uncheck(tab_id: int | str, selector: str, frame_id: int | None = None) -> str:
    """Uncheck a checkbox (no-op if already unchecked).
    
    Args:
        tab_id: ID of the tab containing the element (get from browser_list_tabs)
        selector: CSS selector of the checkbox
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    kwargs = dict(tabId=tab_id, selector=selector)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("uncheck", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Unchecked"


@mcp.tool()
async def browser_hover(tab_id: int | str, selector: str, frame_id: int | None = None) -> str:
    """Hover over a DOM element (triggers mouseenter, mouseover, mousemove).
    Useful for revealing dropdown menus, tooltips, and hover-activated UI.

    Args:
        tab_id: ID of the tab containing the element (get from browser_list_tabs)
        selector: CSS selector of element to hover over
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    kwargs = dict(tabId=tab_id, selector=selector)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("hover", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Hovered"


@mcp.tool()
async def browser_drag_and_drop(tab_id: int | str, source_selector: str, target_selector: str, frame_id: int | None = None) -> str:
    """Drag an element and drop it onto another element using the HTML5 Drag API.
    Works for drag-enabled libraries (Kanban boards, sortable lists, file drop zones).

    Args:
        tab_id: ID of the tab (get from browser_list_tabs)
        source_selector: CSS selector of the element to drag
        target_selector: CSS selector of the drop target
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    kwargs = dict(tabId=tab_id, sourceSelector=source_selector, targetSelector=target_selector)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("dragAndDrop", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Drag and drop completed"


# ==========================================
# Navigation Tools
# ==========================================

# Note: browser_focus, browser_blur, browser_double_click were removed.
# Use browser_evaluate() for these trivial operations:
#   focus:        browser_evaluate(tab_id, 'document.querySelector("#id").focus()')
#   blur:         browser_evaluate(tab_id, 'document.querySelector("#id").blur()')
#   double-click: browser_evaluate(tab_id, 'document.querySelector("#id").dispatchEvent(new MouseEvent("dblclick",{bubbles:true}))')

@mcp.tool()
async def browser_navigate(tab_id: int | str, url: str) -> str:
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
async def browser_reload(tab_id: int | str) -> str:
    """Reload the current page.
    
    Args:
        tab_id: ID of the tab to reload (get from browser_list_tabs)
    """
    result = await send_command("reloadTab", tabId=tab_id)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Page reloaded"


@mcp.tool()
async def browser_forward(tab_id: int | str) -> str:
    """Go forward in browser history.

    Args:
        tab_id: ID of the tab to go forward in (get from browser_list_tabs)
    """
    result = await send_command("goForward", tabId=tab_id)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Navigated forward"


@mcp.tool()
async def browser_wait_for_url(tab_id: int | str, pattern: str, timeout: int = 10000) -> str:
    """Wait for the tab's URL to match a pattern. Ideal for SPA navigation.
    Pattern can be a substring (e.g., '/dashboard') or a regex (e.g., '/order/[0-9]+/').

    Args:
        tab_id: ID of the tab to watch (get from browser_list_tabs)
        pattern: Substring or /regex/ to match against the URL
        timeout: Maximum wait time in milliseconds (default 10000)
    """
    result = await send_command("waitForUrl", tabId=tab_id, pattern=pattern,
                                timeout=timeout, _timeout=timeout / 1000 + 5)
    if not result.get("success"):
        return f"Timeout: {result.get('error')}"
    return result.get("data", {}).get("url", "URL matched")


@mcp.tool()
async def browser_scroll_to(tab_id: int | str, x: int = 0, y: int = 0, frame_id: int | None = None) -> str:
    """Scroll the page to specific coordinates.

    Args:
        tab_id: ID of the tab (get from browser_list_tabs)
        x: Horizontal scroll position in pixels (default 0)
        y: Vertical scroll position in pixels (default 0)
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    kwargs = dict(tabId=tab_id, x=x, y=y)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("scrollTo", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return f"Scrolled to ({x}, {y})"


@mcp.tool()
async def browser_back(tab_id: int | str) -> str:
    """Go back in browser history.

    Args:
        tab_id: ID of the tab to go back in (get from browser_list_tabs)
    """
    result = await send_command("goBack", tabId=tab_id)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Navigated back"


@mcp.tool()
async def browser_get_url(tab_id: int | str) -> str:
    """Get the current page URL.
    
    Args:
        tab_id: ID of the tab to get URL from (get from browser_list_tabs)
    """
    result = await send_command("getURL", tabId=tab_id)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return result.get("data", "")


@mcp.tool()
async def browser_get_title(tab_id: int | str) -> str:
    """Get the current page title.
    
    Args:
        tab_id: ID of the tab to get title from (get from browser_list_tabs)
    """
    result = await send_command("getTitle", tabId=tab_id)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return result.get("data", "")


@mcp.tool()
async def browser_get_page_text(tab_id: int | str, max_length: int = 0, frame_id: int | None = None) -> str:
    """Get the full visible text content of the current page.
    
    Args:
        tab_id: ID of the tab to get text from (get from browser_list_tabs)
        max_length: Maximum characters to return (default 0 = no limit)
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    kwargs = dict(tabId=tab_id, maxLength=max_length)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("getPageText", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    data = result.get("data", "")
    return str(data) if data is not None else ""


@mcp.tool()
async def browser_get_page_html(tab_id: int | str, max_length: int = 0, frame_id: int | None = None) -> str:
    """Get the full HTML of the current page.
    
    Args:
        tab_id: ID of the tab to get HTML from (get from browser_list_tabs)
        max_length: Maximum characters to return (default 0 = no limit)
        frame_id: Optional frame ID to target (get from browser_list_frames)
    """
    kwargs = dict(tabId=tab_id, maxLength=max_length)
    if frame_id is not None: kwargs['frameId'] = frame_id
    result = await send_command("getPageHTML", **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    data = result.get("data", "")
    return str(data) if data is not None else ""


@mcp.tool()
async def browser_screenshot(tab_id: int | str, save_path: str | None = None) -> str:
    """Take a screenshot of the specified tab. Returns base64 PNG data URL.
    
    Uses CDP (chrome.debugger) for silent capture — no window focus stealing,
    no tab activation, no rate limits. Falls back to captureVisibleTab if CDP
    is unavailable (e.g., DevTools is open on the target tab).
    
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
        b64 = data_url.split(",", 1)[-1] if "," in data_url else data_url
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(base64.b64decode(b64))
        return f"Screenshot saved to: {os.path.abspath(save_path)}"

    return data_url or "Screenshot failed"


@mcp.tool()
async def browser_screenshot_full_page(tab_id: int | str, max_height: int = 20000, save_path: str | None = None) -> str:
    """Take a full-page screenshot by scrolling and stitching viewport captures.
    Captures the entire document, not just the visible area. Sticky/fixed elements
    are automatically hidden during middle frames to avoid duplication.
    
    Uses CDP single-shot capture when available — renders the full page in one
    pass without scrolling or focus stealing. Falls back to scroll-and-stitch
    via captureVisibleTab if CDP is unavailable.
    
    Args:
        tab_id: ID of the tab to screenshot (get from browser_list_tabs)
        max_height: Maximum page height to capture in pixels (default 20000). Prevents memory issues on infinite-scroll pages.
        save_path: Optional file path to save the screenshot as PNG. If provided, saves to disk and returns the file path.
    """
    result = await send_command("captureFullPageScreenshot", tabId=tab_id, maxHeight=max_height, _timeout=120)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    data = result.get("data", {})
    data_url = data.get("dataUrl", "")
    dims = data.get("dimensions", {})

    if save_path and data_url:
        b64 = data_url.split(",", 1)[-1] if "," in data_url else data_url
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(base64.b64decode(b64))
        return f"Full-page screenshot saved to: {os.path.abspath(save_path)} ({dims.get('width')}x{dims.get('height')}px, {dims.get('frames')} frames)"

    return data_url or "Full-page screenshot failed"


@mcp.tool()
async def browser_evaluate(tab_id: int | str, code: str, world: str = "MAIN") -> str:
    """Execute arbitrary JavaScript code in the specified world context.
    - MAIN (default): Standard page context (window, document).
    - ISOLATED: Content script context (can access chrome.runtime, chrome.storage, etc).
    
    Args:
        tab_id: ID of the tab to execute JS in
        code: JavaScript code to evaluate
        world: "MAIN" or "ISOLATED"
    """
    result = await send_command("evaluate", tabId=tab_id, code=code, world=world)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    data = result.get("data")
    if data is None:
        return "null"
    return json.dumps(data) if isinstance(data, (dict, list)) else str(data)


@mcp.tool()
async def browser_list_frames(tab_id: int | str) -> str:
    """List all frames (iframes, framesets) in a tab. Returns URL, title, and body
    presence for each frame. Essential for pages where standard tools return null
    because the UI lives inside a <frame> or <iframe> (e.g., Gmail compose, OAuth dialogs).

    Args:
        tab_id: ID of the tab to enumerate frames in (get from browser_list_tabs)
    """
    result = await send_command("listFrames", tabId=tab_id)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


@mcp.tool()
async def browser_evaluate_all_frames(tab_id: int | str, code: str, world: str = "MAIN") -> str:
    """Execute JavaScript in ALL frames of a tab and return per-frame results.
    Use when the target content lives inside a <frame> or <iframe> and standard
    browser_evaluate returns null. Each result includes frameIndex and frameId.

    Args:
        tab_id: ID of the tab to execute JS in (get from browser_list_tabs)
        code: JavaScript code to evaluate in every frame
        world: "MAIN" or "ISOLATED"
    """
    result = await send_command("executeScriptAllFrames", tabId=tab_id, code=code, world=world)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


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
async def browser_close_tab(tab_id: int | str) -> str:
    """Close a browser tab.
    
    Args:
        tab_id: ID of the tab to close (get from browser_list_tabs)
    """
    result = await send_command("closeTab", tabId=tab_id)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return f"Tab {tab_id} closed"


@mcp.tool()
async def browser_switch_tab(tab_id: int | str) -> str:
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
async def browser_resize_window(window_id: int, width: int | None = None, height: int | None = None) -> str:
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
# Network Capture Tools
# ==========================================

@mcp.tool()
async def browser_start_net_capture() -> str:
    """Start capturing all network requests and response headers in the browser."""
    result = await send_command("startNetCapture")
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "Network capture started"


@mcp.tool()
async def browser_stop_net_capture() -> str:
    """Stop the current network capture."""
    result = await send_command("stopNetCapture")
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


@mcp.tool()
async def browser_get_net_capture() -> str:
    """Retrieve all captured network requests and responses since capture started."""
    result = await send_command("getNetCapture")
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


@mcp.tool()
async def browser_set_cookie(
    url: str,
    name: str,
    value: str,
    domain: str | None = None,
    path: str | None = None,
    secure: bool | None = None,
    http_only: bool | None = None,
    expiration_date: float | None = None,
) -> str:
    """Set a cookie in the browser.

    Args:
        url:             URL the cookie belongs to (e.g., 'https://example.com')
        name:            Cookie name
        value:           Cookie value
        domain:          Optional cookie domain
        path:            Optional cookie path (default '/')
        secure:          Optional secure flag
        http_only:       Optional httpOnly flag
        expiration_date: Optional Unix timestamp for expiry
    """
    details: dict = {"url": url, "name": name, "value": value}
    if domain is not None:
        details["domain"] = domain
    if path is not None:
        details["path"] = path
    if secure is not None:
        details["secure"] = secure
    if http_only is not None:
        details["httpOnly"] = http_only
    if expiration_date is not None:
        details["expirationDate"] = expiration_date
    result = await send_command("setCookie", details=details)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return f"Cookie '{name}' set for {url}"


@mcp.tool()
async def browser_delete_cookie(url: str, name: str) -> str:
    """Delete a cookie from the browser.

    Args:
        url:  URL the cookie belongs to (e.g., 'https://example.com')
        name: Name of the cookie to delete
    """
    result = await send_command("deleteCookie", url=url, name=name)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return f"Cookie '{name}' deleted"


@mcp.tool()
async def browser_upload_file(tab_id: int | str, selector: str, data_url: str) -> str:
    """Set a file on an input[type=file] element using a data URL.
    Use browser_evaluate to read a local file as base64 first, or construct
    a data URL directly (e.g., 'data:image/png;base64,...').

    Args:
        tab_id:    ID of the tab containing the file input (get from browser_list_tabs)
        selector:  CSS selector of the input[type=file] element
        data_url:  Data URL of the file (e.g., 'data:image/png;base64,iVBOR...')
    """
    result = await send_command("setInputFiles", tabId=tab_id, selector=selector, dataUrl=data_url)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return "File set on input element"


@mcp.tool()
async def browser_proxy_fetch(
    tab_id: int | str,
    url: str,
    method: str = "GET",
    headers: dict | None = None,
    body: Any = None,
    body_type: str = "json",
) -> str:
    """Perform an HTTP request through the browser's fetch() API.
    Uses the real browser's TLS fingerprint (JA3/JA4), cookies, and session — bypasses
    Cloudflare and other bot-detection systems that check TLS fingerprints.

    Args:
        tab_id:    ID of any tab in the target browser (used for routing only)
        url:       URL to fetch
        method:    HTTP method (default 'GET')
        headers:   Optional dict of request headers
        body:      Optional request body
        body_type: How to encode the body: 'json', 'text', 'formdata', or 'base64file'
    """
    kwargs: dict = {"url": url, "method": method}
    if headers:
        kwargs["headers"] = headers
    if body is not None:
        kwargs["body"] = body
    kwargs["bodyType"] = body_type
    result = await send_command("proxyFetch", tabId=tab_id, **kwargs)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


@mcp.tool()
async def browser_list_connections() -> str:
    """List all browser connections currently active on the bridge.
    Useful when multiple browsers (e.g., Brave + Chrome) are connected simultaneously.
    Each tab's 'virtualId' encodes its browser label (e.g., 'brave:12345').
    browser_list_tabs() already aggregates all browsers, so this is only needed for diagnostics.
    """
    result = await send_command("listConnections")
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


# ==========================================
# Entry Point
# ==========================================

def main() -> None:
    logger.info("StealthDOM MCP Server starting...")
    logger.info("Connecting to bridge at %s", BRIDGE_URL)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
