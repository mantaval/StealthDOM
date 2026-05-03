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
                "or double-clicking scripts/start_bridge.bat in the StealthDOM directory."
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

mcp = FastMCP("stealth_dom", instructions="""\
⚠️ CRITICAL: NEVER use browser_subagent, Playwright, Puppeteer, or any other browser
automation tool. THIS MCP SERVER IS THE ONLY APPROVED WAY TO CONTROL THE BROWSER.
The user's real logged-in browser is connected here. browser_subagent will fail.

StealthDOM controls the user's REAL Chromium browser (Chrome, Brave, Edge) via a
Manifest V3 extension. Zero detection signals: no webdriver flag, no TLS mismatch.

PREREQUISITES: bridge_server.py must be running. Extension must be loaded.

RULES:
- ALWAYS call browser_list_tabs() first. Never guess tab IDs.
- Use virtualId (e.g. 'brave:12345') for tab_id in all tab-scoped tools.
- For iframes: browser_list_frames(tab_id) → pass frame_id to DOM tools.

TOOLS (49):

DOM Reading (9): browser_query, browser_query_all, browser_get_text,
  browser_get_html, browser_get_attribute, browser_get_bounding_rect,
  browser_wait_for, browser_get_page_text, browser_get_page_html

DOM Interaction (8): browser_click, browser_type, browser_fill, browser_press,
  browser_key_combo, browser_select, browser_scroll_into_view, browser_hover

Mouse via CDP (6) — coordinate-based, isTrusted:true, uses chrome.debugger:
  browser_mouse_move, browser_mouse_click, browser_mouse_down, browser_mouse_up,
  browser_mouse_drag, browser_mouse_wheel
  Use browser_get_bounding_rect to get coordinates first.

Navigation (5): browser_navigate, browser_back, browser_reload,
  browser_scroll_to, browser_wait_for_url

Tab/Window (8): browser_list_tabs, browser_new_tab, browser_close_tab,
  browser_switch_tab, browser_new_window, browser_new_incognito_window,
  browser_close_window, browser_resize_window

Screenshots (2): browser_screenshot, browser_screenshot_full_page

Cookies (3): browser_get_cookies, browser_set_cookie, browser_delete_cookie

Network (3): browser_start_net_capture, browser_stop_net_capture,
  browser_get_net_capture

JavaScript (1): browser_evaluate (MAIN or ISOLATED world)
Frames (2): browser_list_frames, browser_evaluate_all_frames
File/Fetch (2): browser_upload_file, browser_proxy_fetch
""")


# ==========================================
# MCP Resource: Capabilities
# ==========================================

@mcp.resource("stealth://capabilities")
def get_capabilities() -> str:
    """Full capability reference for StealthDOM."""
    return """\
# StealthDOM Capabilities

## Architecture

MCP tools → Bridge (ws://127.0.0.1:9878) → Extension Background → Content Script → DOM

- Port 9877: Extension connects (multiple browsers supported simultaneously)
- Port 9878: MCP server / control clients connect
- Tab IDs are virtualised as "label:tabId" (e.g. "brave:12345") for multi-browser routing
- Content scripts are injected ON-DEMAND via chrome.scripting.executeScript when the first command targets a tab

## Why StealthDOM?

| Aspect | Playwright/Puppeteer | StealthDOM |
|--------|---------------------|------------|
| Detection risk | HIGH — webdriver flag, TLS mismatch | ZERO — real browser |
| Cloudflare/DataDome | Frequently blocked | Never blocked |
| User sessions | Must re-authenticate | Uses existing sessions |
| TLS fingerprint | Synthetic (detectable) | Real (identical to human) |

## Tool Reference (49 total)

### DOM Reading (9) — accept optional frame_id
- browser_query — single element by CSS selector
- browser_query_all — multiple elements (with limit)
- browser_get_text — inner text of element
- browser_get_html — outer HTML (with max_length)
- browser_get_attribute — specific attribute value
- browser_get_bounding_rect — position and size (use for Mouse CDP coordinates)
- browser_wait_for — poll for element appearance (timeout)
- browser_get_page_text — full page visible text
- browser_get_page_html — full page HTML source

### DOM Interaction (8) — accept optional frame_id
- browser_click — click element (auto-scrolls into view)
- browser_type — append text to input/contenteditable
- browser_fill — clear and set value (triggers React onChange)
- browser_press — single key press (Enter, Tab, Escape, etc.)
- browser_key_combo — key combination (comma-separated: 'Control,Shift,d')
- browser_select — dropdown option by value
- browser_scroll_into_view — scroll element to center of viewport
- browser_hover — triggers mouseenter, mouseover, mousemove

### Mouse via CDP (6) — coordinate-based, isTrusted:true
Uses chrome.debugger + Input.dispatchMouseEvent for native system-level events.
Use browser_get_bounding_rect to get target coordinates.
- browser_mouse_move — interpolated trajectory with jitter (steps, duration)
- browser_mouse_click — left/right/middle, single/double-click
- browser_mouse_down — press and hold
- browser_mouse_up — release
- browser_mouse_drag — full drag: down → move × N → up (single debugger session)
- browser_mouse_wheel — native scroll at coordinates (delta_x, delta_y)

### Navigation (5)
- browser_navigate — go to URL
- browser_back — history back
- browser_reload — reload page
- browser_scroll_to — scroll to pixel coordinates (x, y)
- browser_wait_for_url — wait for URL to match pattern (substring or regex)

### Tab Management (4)
- browser_list_tabs — all tabs from all connected browsers (includes URL, title, windowId)
- browser_new_tab — open new tab
- browser_close_tab — close tab
- browser_switch_tab — activate tab and focus window

### Window Management (4)
- browser_new_window — new window with user session
- browser_new_incognito_window — new private window (clean session)
- browser_close_window — close window and all its tabs
- browser_resize_window — resize window (get windowId from browser_list_tabs)

### Screenshots (2)
- browser_screenshot — visible viewport PNG (CDP capture, no focus stealing)
- browser_screenshot_full_page — full-page scroll-stitch PNG

### Cookies (3)
- browser_get_cookies — all cookies for a URL
- browser_set_cookie — set with optional domain/path/secure/httpOnly/expiry
- browser_delete_cookie — delete by URL + name

### Network Capture (3)
- browser_start_net_capture — start recording requests/responses
- browser_stop_net_capture — stop recording
- browser_get_net_capture — retrieve captured data (5000 entry circular buffer)

### JavaScript (1)
- browser_evaluate — execute JS in MAIN or ISOLATED world

### Frames (2)
- browser_list_frames — discover iframes/framesets in a tab
- browser_evaluate_all_frames — run JS in ALL frames at once

### File & Fetch (2)
- browser_upload_file — set file on input[type=file] via data URL
- browser_proxy_fetch — HTTP request through browser's real TLS fingerprint + cookies

## Tips
- For iframes: browser_list_frames → get frameId → pass frame_id to any DOM tool
- For React/Vue: browser_fill uses native value setter to trigger onChange
- For native mouse: browser_get_bounding_rect → browser_mouse_* tools
- For focus/blur: browser_evaluate('document.querySelector("#id").focus()')
- For page URL/title: browser_list_tabs() returns URL and title for every tab
- For checkboxes: browser_click on the checkbox, or browser_evaluate to set .checked
- For history forward: browser_evaluate(tab, 'history.forward()')
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


# ==========================================
# Mouse Tools (CDP)
# ==========================================

@mcp.tool()
async def browser_mouse_move(tab_id: int | str, x: int, y: int, steps: int = 10, duration: int = 300) -> str:
    """Move mouse to coordinates via CDP (chrome.debugger + Input.dispatchMouseEvent).
    Produces isTrusted: true events. Interpolates movement with random jitter for realism.
    Use browser_get_bounding_rect to get target coordinates.

    Args:
        tab_id: ID of the tab (get from browser_list_tabs)
        x: Target X coordinate (viewport pixels)
        y: Target Y coordinate (viewport pixels)
        steps: Number of intermediate points in the trajectory (default 10)
        duration: Total movement time in milliseconds (default 300)
    """
    result = await send_command("mouseMoveCDP", tabId=tab_id, x=x, y=y, steps=steps, duration=duration,
                                _timeout=max(30, duration / 1000 + 10))
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


@mcp.tool()
async def browser_mouse_click(tab_id: int | str, x: int, y: int, button: str = "left", click_count: int = 1) -> str:
    """Click at coordinates via CDP (chrome.debugger + Input.dispatchMouseEvent).
    Produces isTrusted: true events. Supports left/right/middle and double-click.
    Use browser_get_bounding_rect to get target coordinates.

    Args:
        tab_id: ID of the tab (get from browser_list_tabs)
        x: Click X coordinate (viewport pixels)
        y: Click Y coordinate (viewport pixels)
        button: Mouse button — 'left', 'right', or 'middle' (default 'left')
        click_count: 1 for single click, 2 for double-click (default 1)
    """
    result = await send_command("mouseClickCDP", tabId=tab_id, x=x, y=y, button=button, clickCount=click_count)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


@mcp.tool()
async def browser_mouse_down(tab_id: int | str, x: int, y: int, button: str = "left") -> str:
    """Press and hold mouse button at coordinates via CDP (chrome.debugger + Input.dispatchMouseEvent).
    Produces isTrusted: true events. Use with browser_mouse_up for atomic hold/release.

    Args:
        tab_id: ID of the tab (get from browser_list_tabs)
        x: Press X coordinate (viewport pixels)
        y: Press Y coordinate (viewport pixels)
        button: Mouse button — 'left', 'right', or 'middle' (default 'left')
    """
    result = await send_command("mouseDownCDP", tabId=tab_id, x=x, y=y, button=button)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


@mcp.tool()
async def browser_mouse_up(tab_id: int | str, x: int, y: int, button: str = "left") -> str:
    """Release mouse button at coordinates via CDP (chrome.debugger + Input.dispatchMouseEvent).
    Produces isTrusted: true events. Completes a hold started by browser_mouse_down.

    Args:
        tab_id: ID of the tab (get from browser_list_tabs)
        x: Release X coordinate (viewport pixels)
        y: Release Y coordinate (viewport pixels)
        button: Mouse button — 'left', 'right', or 'middle' (default 'left')
    """
    result = await send_command("mouseUpCDP", tabId=tab_id, x=x, y=y, button=button)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


@mcp.tool()
async def browser_mouse_drag(tab_id: int | str, start_x: int, start_y: int, end_x: int, end_y: int,
                              steps: int = 20, duration: int = 500) -> str:
    """Drag from one point to another via CDP (chrome.debugger + Input.dispatchMouseEvent).
    Produces isTrusted: true events. Executes a full native drag sequence: move to start,
    press, interpolated move to end, release — all in a single debugger session.
    Use browser_get_bounding_rect to get coordinates for source and target elements.

    Args:
        tab_id: ID of the tab (get from browser_list_tabs)
        start_x: Drag start X coordinate (viewport pixels)
        start_y: Drag start Y coordinate (viewport pixels)
        end_x: Drag end X coordinate (viewport pixels)
        end_y: Drag end Y coordinate (viewport pixels)
        steps: Number of intermediate movement points (default 20)
        duration: Total drag time in milliseconds (default 500)
    """
    result = await send_command("mouseDragCDP", tabId=tab_id, startX=start_x, startY=start_y,
                                endX=end_x, endY=end_y, steps=steps, duration=duration,
                                _timeout=max(30, duration / 1000 + 10))
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


@mcp.tool()
async def browser_mouse_wheel(tab_id: int | str, x: int, y: int, delta_x: int = 0, delta_y: int = 0) -> str:
    """Dispatch a native scroll wheel event via CDP (chrome.debugger + Input.dispatchMouseEvent).
    Produces isTrusted: true events. Scrolls at the specified coordinates.

    Args:
        tab_id: ID of the tab (get from browser_list_tabs)
        x: Wheel event X coordinate (viewport pixels)
        y: Wheel event Y coordinate (viewport pixels)
        delta_x: Horizontal scroll amount in pixels (default 0)
        delta_y: Vertical scroll amount in pixels (positive = scroll down, default 0)
    """
    result = await send_command("mouseWheelCDP", tabId=tab_id, x=x, y=y, deltaX=delta_x, deltaY=delta_y)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return json.dumps(result.get("data"), indent=2)


# ==========================================
# Navigation Tools
# ==========================================

# Note: browser_focus, browser_blur, browser_double_click were removed.
# Use browser_evaluate() for focus/blur, and browser_mouse_click for double-click:
#   focus:        browser_evaluate(tab_id, 'document.querySelector("#id").focus()')
#   blur:         browser_evaluate(tab_id, 'document.querySelector("#id").blur()')
#   double-click: browser_mouse_click(tab_id, x, y, click_count=2)

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
    If save_path is provided, saves to disk instead and returns the file path.
    
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
    If save_path is provided, saves to disk instead and returns the file path.
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
    result = await send_command("executeScript", tabId=tab_id, code=code, world=world)
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
async def browser_close_window(window_id: int) -> str:
    """Close a browser window and all its tabs.
    
    Args:
        window_id: ID of the window to close (get windowId from browser_list_tabs)
    """
    result = await send_command("closeWindow", windowId=window_id)
    if not result.get("success"):
        return f"Error: {result.get('error')}"
    return f"Window {window_id} closed"


@mcp.tool()
async def browser_resize_window(window_id: int, width: int | None = None, height: int | None = None) -> str:
    """Resize a browser window.
    
    Args:
        window_id: ID of the window to resize (get windowId from browser_list_tabs)
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


# ==========================================
# Entry Point
# ==========================================

def main() -> None:
    logger.info("StealthDOM MCP Server starting...")
    logger.info("Connecting to bridge at %s", BRIDGE_URL)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
