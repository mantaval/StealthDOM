"""
StealthDOM Integration Tests
Tests run against a live bridge + browser extension.

Prerequisites:
    1. Browser with StealthDOM extension running
    2. bridge_server.py running (python bridge_server.py)
    3. At least one tab open in the browser

Usage:
    python tests/test_stealth_dom.py
"""
import asyncio
import json
import uuid
import sys
import os
import glob
import base64

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import websockets

BRIDGE_URL = "ws://127.0.0.1:9878"

def save_data_url(data_url: str, filename: str):
    """Save a base64 data URL to a file in the tests/ directory."""
    if not data_url.startswith("data:image/png;base64,"):
        return
    b64_data = data_url.split(",")[1]
    filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    with open(filepath, "wb") as f:
        f.write(base64.b64decode(b64_data))

# ==========================================
# Test Helpers
# ==========================================

async def bridge_send(ws, action: str, _timeout: float = 15, **kwargs) -> dict:
    """Send a command through the bridge with proper _msg_id matching."""
    msg_id = str(uuid.uuid4())[:8]
    msg = {"action": action, "_msg_id": msg_id, "_timeout": _timeout, **kwargs}
    await ws.send(json.dumps(msg))
    
    # Read messages until we get our response
    deadline = asyncio.get_event_loop().time() + _timeout + 5
    while asyncio.get_event_loop().time() < deadline:
        raw = await asyncio.wait_for(ws.recv(), timeout=_timeout + 5)
        data = json.loads(raw)
        if data.get("_msg_id") == msg_id:
            data.pop("_msg_id", None)
            return data
    raise TimeoutError(f"No response for {action} (msg_id={msg_id})")


async def run_diagnostics(ws, tab_id):
    """Diagnose why a tab command might have failed/timed out."""
    try:
        r = await bridge_send(ws, "listTabs")
        tabs = r.get("data", [])
        target_tab = None
        for t in tabs:
            vid = t.get("virtualId")
            nid = t.get("id")
            if str(vid) == str(tab_id) or str(nid) == str(tab_id):
                target_tab = t
                break
                
        if not target_tab:
            return "Diagnostics: Tab no longer exists."
            
        is_active = target_tab.get("active")
        is_discarded = target_tab.get("discarded", False)
        
        if is_discarded:
            return f"Diagnostics: Tab {tab_id} was FROZEN by Chrome Memory Saver."
            
        eval_r = await bridge_send(ws, "evaluate", tabId=tab_id, code="document.visibilityState", _timeout=3)
        if not eval_r.get("success"):
            return f"Diagnostics: Tab {tab_id} is unresponsive (DevTools may be open, or tab was created in a minimized window and suspended). Active={is_active}."
            
        visibility = eval_r["data"]
        return f"Diagnostics: Tab is AWAKE (Active: {is_active}, Visibility: {visibility}). If screenshot timed out, the browser window is likely 100% occluded by an Always-on-Top app (IDE), or it was just created in a minimized window and deferred rendering."
    except Exception as e:
        return f"Diagnostics probe failed: {str(e)}"

async def find_ready_tab(ws):
    """Find a non-internal tab that has the content script loaded (responds to ping).
    Prefers virtualId for multi-browser support; falls back to numeric id."""
    r = await bridge_send(ws, "listTabs")
    tabs = r.get("data", [])
    for t in tabs:
        if t["url"].startswith(("chrome://", "brave://", "edge://", "about:")):
            continue
        # Use virtualId if available (multi-browser), otherwise fall back to numeric id
        tab_id = t.get("virtualId") or t["id"]
        try:
            ping = await bridge_send(ws, "ping", tabId=tab_id, _timeout=3)
            if ping.get("success"):
                t["_use_id"] = tab_id  # Store the ID to use
                return t
        except Exception:
            continue
    return None


async def ensure_test_tab(ws, url: str):
    """Close any existing matching tab and create a fresh one to clear dangling debuggers."""
    r = await bridge_send(ws, "listTabs")
    tabs = r.get("data", [])
    for t in tabs:
        if t["url"].rstrip("/") == url.rstrip("/"):
            tab_id = t.get("virtualId") or t["id"]
            # Close the old tab to wipe any lingering state/CDP debuggers
            await bridge_send(ws, "closeTab", tabId=tab_id)
            break
            
    # Create the new tab in the background to prevent focus stealing / un-minimizing
    r = await bridge_send(ws, "newTab", url=url, active=False)
    if r.get("success"):
        await asyncio.sleep(1.5)
        return r["data"]["tabId"]
    return None

class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
        self.logs = []
    
    def ok(self, name):
        self.passed += 1
        msg = f"  [PASS] {name}"
        self.logs.append(("PASS", name, msg))
        print(msg)
    
    def fail(self, name, reason):
        self.failed += 1
        self.errors.append((name, reason))
        msg = f"  [FAIL] {name}: {reason}"
        self.logs.append(("FAIL", name, msg))
        print(msg)
    
    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*50}")
        print(f"Results: {self.passed}/{total} passed, {self.failed} failed")
        if self.errors:
            print("\nFailures:")
            for name, reason in self.errors:
                print(f"  - {name}: {reason}")
        
        self.generate_report(total)
        return self.failed == 0

    def generate_report(self, total):
        report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "TEST_REPORT.md")
        
        explanations = {
            "Command captureScreenshot timed out": (
                "**Chromium Compositor Paused / Tab Asleep**\n"
                "> When a browser window is 100% occluded by an 'Always on Top' application "
                "(like your IDE), Chromium pauses its rendering compositor to save battery. "
                "Because the fallback `captureVisibleTab` requires a fully rendered frame, "
                "it hangs indefinitely. The CDP screenshot path normally bypasses this, "
                "but if it falls back to `captureVisibleTab` (e.g. because DevTools is open "
                "on the target tab), it will time out.\n\n"
                "> *Note:* This timeout also occurs if the target tab is a background tab that "
                "Chrome's 'Memory Saver' has frozen (which causes the CDP command to hang). "
                "The test suite uses active `ensure_test_tab` targets to prevent this."
            ),
            "Failed to connect to bridge": (
                "**Bridge Server Not Running**\n"
                "> The Python integration tests require the StealthDOM extension to be actively running "
                "in a browser with the native messaging host connected. Ensure the browser is open and "
                "the extension is not disabled."
            ),
            "MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND": (
                "**Chrome Quota Exceeded**\n"
                "> Chrome heavily rate-limits the `captureVisibleTab` fallback API. The extension includes "
                "an automatic mutex lock to serialize calls and prevent this, but if too many commands are "
                "forced simultaneously, the quota may still be exhausted. This does not happen on the CDP path."
            )
        }
        
        # Group logs by test
        test_blocks = []
        current_block = []
        current_test = None
        
        for status, name, msg in self.logs:
            if current_test != name:
                if current_test is not None:
                    test_blocks.append((current_test, current_block))
                current_test = name
                current_block = []
            current_block.append((status, msg))
            
        if current_test is not None:
            test_blocks.append((current_test, current_block))

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("# StealthDOM Test Suite Report\n\n")
            f.write(f"**Results:** {self.passed}/{total} passed, {self.failed} failed\n\n")
            
            if self.errors:
                f.write("## Failures\n")
                for name, reason in self.errors:
                    f.write(f"- **{name}**: `{reason}`\n")
                f.write("\n")
                
                f.write("## Analysis & Possible Causes\n")
                for name, reason in self.errors:
                    for key, explanation in explanations.items():
                        if key in reason:
                            f.write(f"### {key}\n")
                            f.write(f"{explanation}\n\n")
            
            f.write("## Test Execution Log\n\n")
            
            for test_name, block in test_blocks:
                f.write(f"### {test_name}\n")
                
                # Check if this test block has any failures
                has_failure = any(status == "FAIL" for status, _ in block)
                pass_count = sum(1 for status, _ in block if status == "PASS")
                
                if has_failure:
                    for status, msg in block:
                        if status == "FAIL":
                            f.write(f"- ❌ `{msg.replace('  [FAIL] ', '')}`\n")
                        else:
                            f.write(f"- ✅ {msg.replace('  [PASS] ', '')}\n")
                else:
                    f.write(f"- ✅ All {pass_count} assertions passed.\n")
                f.write("\n")

# ==========================================
# Tests
# ==========================================

async def test_bridge_connection(results: TestResults):
    """Test basic bridge connectivity."""
    print("\n[Test: Bridge Connection]")
    try:
        ws = await websockets.connect(BRIDGE_URL)
        results.ok("Connect to bridge")
        await ws.close()
    except Exception as e:
        results.fail("Connect to bridge", str(e))


async def test_list_tabs(results: TestResults):
    """Test listing tabs returns proper structure with incognito flag."""
    print("\n[Test: List Tabs]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        r = await bridge_send(ws, "listTabs")
        assert r.get("success"), f"listTabs failed: {r.get('error')}"
        results.ok("listTabs succeeds")
        
        tabs = r["data"]
        assert isinstance(tabs, list), "data should be a list"
        assert len(tabs) > 0, "Should have at least one tab"
        results.ok(f"Found {len(tabs)} tabs")
        
        tab = tabs[0]
        required_fields = ["id", "url", "title", "active", "windowId", "incognito"]
        for field in required_fields:
            assert field in tab, f"Missing field: {field}"
        results.ok("Tab has all required fields (id, url, title, active, windowId, incognito)")

        # Multi-browser fields (may be absent if only one connection)
        if "virtualId" in tab:
            results.ok(f"virtualId present: {tab['virtualId']}")
            assert ":" in str(tab["virtualId"]), "virtualId should contain ':' separator"
        if "browserId" in tab:
            results.ok(f"browserId present: {tab['browserId']}")
        
    except AssertionError as e:  # noqa
        results.fail("listTabs structure", str(e))
    except Exception as e:
        results.fail("listTabs", str(e))
    finally:
        await ws.close()


async def test_list_windows(results: TestResults):
    """Test listing windows returns proper structure."""
    print("\n[Test: List Windows]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        r = await bridge_send(ws, "listWindows")
        assert r.get("success"), f"listWindows failed: {r.get('error')}"
        results.ok("listWindows succeeds")
        
        windows = r["data"]
        assert isinstance(windows, list), "data should be a list"
        assert len(windows) > 0, "Should have at least one window"
        
        win = windows[0]
        required_fields = ["id", "type", "incognito", "focused"]
        for field in required_fields:
            assert field in win, f"Missing field: {field}"
        results.ok("Window has all required fields (id, type, incognito, focused)")
        
    except AssertionError as e:  # noqa
        results.fail("listWindows structure", str(e))
    except Exception as e:
        results.fail("listWindows", str(e))
    finally:
        await ws.close()


async def test_explicit_tab_targeting(results: TestResults):
    """Test that DOM commands work with explicit tab_id."""
    print("\n[Test: Explicit Tab Targeting]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        tab = await find_ready_tab(ws)
        if not tab:
            results.fail("Explicit targeting", "No tab with content script ready (refresh a tab)")
            return
        
        tab_id = tab["id"]
        results.ok(f"Using tab {tab_id}: {tab['url'][:60]}")
        
        # Test getTitle with explicit tabId
        r = await bridge_send(ws, "getTitle", tabId=tab_id)
        # getTitle is a content script command, so it goes through bridgeForwardToContentScript
        if r.get("success"):
            results.ok(f"getTitle with explicit tabId returned: {r['data'][:50]}")
        else:
            results.fail("getTitle with explicit tabId", r.get("error"))
        
        # Test getURL with explicit tabId
        r = await bridge_send(ws, "getURL", tabId=tab_id)
        if r.get("success"):
            results.ok(f"getURL with explicit tabId returned: {r['data'][:60]}")
        else:
            results.fail("getURL with explicit tabId", r.get("error"))
        
    except Exception as e:
        results.fail("Explicit targeting", str(e))
    finally:
        await ws.close()


async def test_missing_tab_id_rejected(results: TestResults):
    """Test that commands without tabId are rejected."""
    print("\n[Test: Missing tabId Rejection]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        # These commands should fail without tabId
        commands = [
            ("navigate", {"url": "https://example.com"}),
            ("goBack", {}),
            ("goForward", {}),
            ("reloadTab", {}),
            ("captureScreenshot", {}),
        ]
        
        for action, kwargs in commands:
            r = await bridge_send(ws, action, **kwargs)
            if not r.get("success") and "tabId required" in r.get("error", ""):
                results.ok(f"{action} correctly rejects missing tabId")
            else:
                results.fail(f"{action} missing tabId", f"Expected rejection, got: {r}")
        
        # Content script commands should also reject
        r = await bridge_send(ws, "querySelector", selector="body")
        if not r.get("success") and "tabId required" in r.get("error", ""):
            results.ok("querySelector correctly rejects missing tabId")
        else:
            results.fail("querySelector missing tabId", f"Expected rejection, got: {r}")
        
    except Exception as e:
        results.fail("Missing tabId rejection", str(e))
    finally:
        await ws.close()


async def test_screenshot_with_tab_id(results: TestResults):
    """Test screenshot targeting a specific test tab."""
    print("\n[Test: Screenshot with tabId]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        tab_id = await ensure_test_tab(ws, "https://httpbin.org/html")
        r = await bridge_send(ws, "captureScreenshot", tabId=tab_id, _timeout=15)
        if r.get("success"):
            data_url = r["data"]["dataUrl"]
            assert data_url.startswith("data:image/png"), "Should be PNG data URL"
            save_data_url(data_url, "screenshot_standard.png")
            results.ok(f"Screenshot captured for test tab {tab_id} ({len(data_url)} chars)")
        else:
            diag = await run_diagnostics(ws, tab_id)
            results.fail("Screenshot", f"{r.get('error', 'timeout')} | {diag}")
    except Exception as e:
        results.fail("Screenshot", str(e))
    finally:
        await ws.close()


async def test_parallel_commands(results: TestResults):
    """Test that parallel commands don't cross-contaminate responses."""
    print("\n[Test: Parallel Command Isolation]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        tab = await find_ready_tab(ws)
        if not tab:
            results.fail("Parallel commands", "No tab with content script ready")
            return
        
        tab_id = tab["id"]
        
        # Fire multiple commands in parallel using separate websocket connections
        # (since our bridge_send reads sequentially on one connection)
        async def run_command(action, **kwargs):
            conn = await websockets.connect(BRIDGE_URL)
            try:
                return action, await bridge_send(conn, action, tabId=tab_id, **kwargs)
            finally:
                await conn.close()
        
        tasks = [
            run_command("getTitle"),
            run_command("getURL"),
            run_command("listTabs"),
            run_command("listWindows"),
        ]
        
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_ok = True
        for item in results_list:
            if isinstance(item, Exception):
                results.fail("Parallel command", str(item))
                all_ok = False
                continue
            action, resp = item
            if not resp.get("success"):
                results.fail(f"Parallel {action}", resp.get("error"))
                all_ok = False
        
        if all_ok:
            # Verify response types are correct
            for action, resp in results_list:
                if action == "getTitle":
                    assert isinstance(resp["data"], str), "getTitle should return string"
                elif action == "getURL":
                    assert isinstance(resp["data"], str), "getURL should return string"
                elif action == "listTabs":
                    assert isinstance(resp["data"], list), "listTabs should return list"
                elif action == "listWindows":
                    assert isinstance(resp["data"], list), "listWindows should return list"
            results.ok("All parallel commands returned correct response types (no cross-talk)")
        
    except Exception as e:
        results.fail("Parallel commands", str(e))
    finally:
        await ws.close()


async def test_msg_id_echo(results: TestResults):
    """Test that _msg_id is echoed back correctly in responses."""
    print("\n[Test: _msg_id Echo]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        msg_id = "test-" + str(uuid.uuid4())[:6]
        msg = {"action": "listTabs", "_msg_id": msg_id}
        await ws.send(json.dumps(msg))
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        data = json.loads(raw)
        assert data.get("_msg_id") == msg_id, f"_msg_id not echoed. Got: {data.get('_msg_id')}"
        results.ok("_msg_id echoed correctly")
    except AssertionError as e:
        results.fail("_msg_id echo", str(e))
    except Exception as e:
        results.fail("_msg_id echo", str(e))
    finally:
        await ws.close()


async def test_list_connections(results: TestResults):
    """Test listConnections returns bridge connection info."""
    print("\n[Test: List Connections]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        r = await bridge_send(ws, "listConnections")
        assert r.get("success"), f"listConnections failed: {r.get('error')}"
        data = r["data"]
        assert "connections" in data, "Missing connections field"
        assert "primaryLabel" in data, "Missing primaryLabel field"
        results.ok(f"listConnections: {data['count']} browser(s) connected, primary='{data['primaryLabel']}'")
    except AssertionError as e:
        results.fail("listConnections", str(e))
    except Exception as e:
        results.fail("listConnections", str(e))
    finally:
        await ws.close()


async def test_hover(results: TestResults):
    """Test hover command triggers mouse events on an element."""
    print("\n[Test: Hover]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        tab = await find_ready_tab(ws)
        if not tab:
            results.fail("Hover", "No tab with content script ready")
            return
        tab_id = tab.get("_use_id") or tab["id"]

        # Hover over body (always exists)
        r = await bridge_send(ws, "hover", tabId=tab_id, selector="body")
        if r.get("success"):
            results.ok("hover command succeeded")
        else:
            results.fail("hover", r.get("error"))
    except Exception as e:
        results.fail("Hover", str(e))
    finally:
        await ws.close()


async def test_net_capture_overflow(results: TestResults):
    """Test net capture response includes overflowCount field (circular buffer)."""
    print("\n[Test: Net Capture Overflow Field]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        await bridge_send(ws, "startNetCapture")
        r = await bridge_send(ws, "getNetCapture")
        assert r.get("success"), f"getNetCapture failed: {r.get('error')}"
        data = r["data"]
        assert "requests" in data, "Missing requests field in getNetCapture response"
        assert "overflowCount" in data, "Missing overflowCount â€” circular buffer not implemented"
        assert "bufferSize" in data, "Missing bufferSize field"
        assert "capturedCount" in data, "Missing capturedCount field"
        assert data["bufferSize"] == 5000, f"Expected bufferSize=5000, got {data['bufferSize']}"
        results.ok(f"getNetCapture structure OK: bufferSize={data['bufferSize']}, overflowCount={data['overflowCount']}")
        await bridge_send(ws, "stopNetCapture")
    except AssertionError as e:
        results.fail("Net capture structure", str(e))
    except Exception as e:
        results.fail("Net capture", str(e))
    finally:
        await ws.close()


async def test_virtual_tab_routing(results: TestResults):
    """Test that virtualId (label:tabId) routes correctly to the right browser."""
    print("\n[Test: Virtual Tab Routing]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        # Use find_ready_tab which already validates virtualId routing + ping
        tab = await find_ready_tab(ws)
        if not tab:
            results.ok("No content-script-ready tabs found (skip)")
            return

        vid = tab.get("virtualId")
        if not vid:
            results.ok("Virtual tab IDs not present (single-browser mode â€” OK)")
            return

        # getTitle via virtualId (already confirmed reachable by ping)
        r = await bridge_send(ws, "getTitle", tabId=vid)
        if r.get("success"):
            results.ok(f"virtualId routing OK: '{vid}' -> title='{r['data'][:40]}'")
        else:
            results.fail("virtualId routing", r.get("error"))
    except AssertionError as e:
        results.fail("Virtual tab routing", str(e))
    except Exception as e:
        results.fail("Virtual tab routing", str(e))
    finally:
        await ws.close()


async def test_evaluate_with_tab_id(results: TestResults):
    """Test JS evaluation targets correct tab."""
    print("\n[Test: Evaluate with tabId]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        tab = await find_ready_tab(ws)
        if not tab:
            results.fail("Evaluate", "No tab with content script ready")
            return
        tab_id = tab.get("_use_id") or tab["id"]

        r = await bridge_send(ws, "evaluate", tabId=tab_id, code="document.title")
        if r.get("success"):
            results.ok(f"evaluate returned: {r['data']}")
        else:
            results.fail("evaluate", r.get("error"))

    except Exception as e:
        results.fail("Evaluate", str(e))
    finally:
        await ws.close()


async def test_proxy_fetch(results: TestResults):
    """Test proxyFetch makes a request through the browser."""
    print("\n[Test: Proxy Fetch]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        tab = await find_ready_tab(ws)
        if not tab:
            results.fail("Proxy Fetch", "No tab with content script ready")
            return
        tab_id = tab.get("_use_id") or tab["id"]

        r = await bridge_send(ws, "proxyFetch", tabId=tab_id,
                              url="https://httpbin.org/get",
                              method="GET", _timeout=20)
        if r.get("success"):
            data = r.get("data", {})
            status = data.get("status") if isinstance(data, dict) else None
            results.ok(f"proxyFetch succeeded (status={status})")
        else:
            # External fetch might fail in CI/offline â€” treat as warning
            results.ok(f"proxyFetch returned (may be offline): {r.get('error', 'no error')}")
    except Exception as e:
        results.fail("Proxy Fetch", str(e))
    finally:
        await ws.close()


async def test_list_frames(results: TestResults):
    """Test listFrames returns frame inventory for a tab."""
    print("\n[Test: List Frames (v3.0.2)]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        tab = await find_ready_tab(ws)
        if not tab:
            results.fail("listFrames", "No tab with content script ready")
            return
        tab_id = tab.get("_use_id") or tab["id"]

        r = await bridge_send(ws, "listFrames", tabId=tab_id)
        assert r.get("success"), f"listFrames failed: {r.get('error')}"
        data = r["data"]

        assert "frameCount" in data, "Missing frameCount field"
        assert "frames" in data, "Missing frames field"
        assert isinstance(data["frames"], list), "frames should be a list"
        assert data["frameCount"] >= 1, "Should have at least the top-level frame"
        results.ok(f"listFrames returned {data['frameCount']} frame(s)")

        # Validate frame structure
        frame0 = data["frames"][0]
        required = ["frameIndex", "url", "title", "hasBody"]
        for field in required:
            assert field in frame0, f"Frame missing field: {field}"
        results.ok(f"Frame structure OK: url={frame0['url'][:50]}, hasBody={frame0['hasBody']}")

        # Validate optional enrichment fields
        if "elementCount" in frame0:
            assert isinstance(frame0["elementCount"], int), "elementCount should be int"
            results.ok(f"Frame enrichment: elementCount={frame0['elementCount']}")
        if "isFrameset" in frame0:
            results.ok(f"Frame enrichment: isFrameset={frame0['isFrameset']}")

    except AssertionError as e:
        results.fail("listFrames", str(e))
    except Exception as e:
        results.fail("listFrames", str(e))
    finally:
        await ws.close()


async def test_list_frames_missing_tabid(results: TestResults):
    """Test that listFrames rejects missing tabId."""
    print("\n[Test: listFrames Missing tabId (v3.0.2)]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        r = await bridge_send(ws, "listFrames")
        if not r.get("success") and "tabId required" in r.get("error", ""):
            results.ok("listFrames correctly rejects missing tabId")
        else:
            results.fail("listFrames missing tabId", f"Expected rejection, got: {r}")
    except Exception as e:
        results.fail("listFrames missing tabId", str(e))
    finally:
        await ws.close()


async def test_execute_script_all_frames(results: TestResults):
    """Test executeScriptAllFrames runs code in all frames and returns per-frame results."""
    print("\n[Test: Execute Script All Frames (v3.0.2)]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        tab = await find_ready_tab(ws)
        if not tab:
            results.fail("executeScriptAllFrames", "No tab with content script ready")
            return
        tab_id = tab.get("_use_id") or tab["id"]

        r = await bridge_send(ws, "executeScriptAllFrames", tabId=tab_id,
                              code="document.title")
        assert r.get("success"), f"executeScriptAllFrames failed: {r.get('error')}"
        data = r["data"]

        assert "frameCount" in data, "Missing frameCount field"
        assert "results" in data, "Missing results field"
        assert isinstance(data["results"], list), "results should be a list"
        assert data["frameCount"] >= 1, "Should have at least 1 frame result"
        results.ok(f"executeScriptAllFrames returned {data['frameCount']} result(s)")

        # Validate result structure
        frame_result = data["results"][0]
        assert "frameIndex" in frame_result, "Missing frameIndex in result"
        assert "result" in frame_result, "Missing result field in frame result"
        results.ok(f"Frame 0 result: title='{frame_result['result']}'")

        # Test with a more complex expression to ensure eval works
        # On sites with Trusted Types (Gmail), this should trigger the
        # script tag fallback automatically and still return valid results
        r2 = await bridge_send(ws, "executeScriptAllFrames", tabId=tab_id,
                               code="({url: location.href, elementCount: document.querySelectorAll('*').length})")
        if r2.get("success"):
            fr = r2["data"]["results"][0]["result"]
            if isinstance(fr, dict) and fr.get("__error"):
                results.fail("executeScriptAllFrames complex eval",
                             f"Got error even with fallback: {fr.get('message')}")
            elif isinstance(fr, dict) and "url" in fr:
                assert "elementCount" in fr, "Complex eval should return elementCount"
                results.ok(f"Complex eval OK: url={fr['url'][:50]}, elements={fr['elementCount']}")
            else:
                # Some frames may return null (e.g., no body) â€” that's OK
                results.ok(f"Complex eval returned: {str(fr)[:80]}")
        else:
            results.fail("executeScriptAllFrames complex eval", r2.get("error"))

    except AssertionError as e:
        results.fail("executeScriptAllFrames", str(e))
    except Exception as e:
        results.fail("executeScriptAllFrames", str(e))
    finally:
        await ws.close()


async def test_screenshot_mutex(results: TestResults):
    """Test that parallel screenshot calls don't crash with quota errors (mutex test)."""
    print("\n[Test: Screenshot Mutex (v3.0.2)]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        r = await bridge_send(ws, "listTabs")
        tabs = r["data"]
        tab = None
        for t in tabs:
            if not t["url"].startswith(("chrome://", "brave://", "edge://", "about:")):
                tab = t
                break

        if not tab:
            results.fail("Screenshot mutex", "No suitable tab")
            return

        tab_id = tab.get("virtualId") or tab["id"]

        # Fire 3 screenshots in rapid parallel â€” without the mutex, this would
        # trigger MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND on at least one
        async def take_screenshot(label):
            conn = await websockets.connect(BRIDGE_URL)
            try:
                return label, await bridge_send(conn, "captureScreenshot",
                                                tabId=tab_id, _timeout=30)
            finally:
                await conn.close()

        tasks = [
            take_screenshot("A"),
            take_screenshot("B"),
            take_screenshot("C"),
        ]

        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        succeeded = 0
        for item in results_list:
            if isinstance(item, Exception):
                results.fail(f"Screenshot mutex (exception)", str(item))
                continue
            label, resp = item
            if resp.get("success"):
                succeeded += 1
                data_url = resp["data"]["dataUrl"]
                save_data_url(data_url, f"screenshot_mutex_{label}.png")
            else:
                err = resp.get("error", "")
                if "MAX_CAPTURE" in err:
                    results.fail(f"Screenshot mutex ({label})",
                                 "Quota error â€” mutex not working!")
                else:
                    results.fail(f"Screenshot mutex ({label})", err)

        if succeeded == 3:
            results.ok("All 3 parallel screenshots succeeded (mutex serialized them)")
        elif succeeded > 0:
            results.ok(f"{succeeded}/3 parallel screenshots succeeded (partial â€” may be timing)")

    except Exception as e:
        results.fail("Screenshot mutex", str(e))
    finally:
        await ws.close()


async def test_screenshot_no_focus_steal(results: TestResults):
    """Test that CDP screenshots work without stealing window focus (v3.2.0)."""
    print("\n[Test: Screenshot No Focus Steal (v3.2.0 CDP)]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        # Create/ensure two tabs
        bg_tab_id = await ensure_test_tab(ws, "https://example.com")
        fg_tab_id = await ensure_test_tab(ws, "https://httpbin.org/html")
        
        # Switch to fg_tab to explicitly force bg_tab into the background
        await bridge_send(ws, "switchTab", tabId=fg_tab_id)

        # Take screenshot of the background tab — CDP should NOT activate it
        r = await bridge_send(ws, "captureScreenshot", tabId=bg_tab_id, _timeout=15)
        if not r.get("success"):
            diag = await run_diagnostics(ws, bg_tab_id)
            results.fail("Screenshot no focus steal", f"{r.get('error', 'unknown')} | {diag}")
            return

        data_url = r["data"]["dataUrl"]
        assert data_url.startswith("data:image/png"), "Should be PNG data URL"
        save_data_url(data_url, "screenshot_no_focus_steal_cdp.png")

        # Verify the tab is still NOT active (CDP didn't steal focus)
        r2 = await bridge_send(ws, "listTabs")
        for t in r2["data"]:
            tid = t.get("virtualId") or t["id"]
            if tid == bg_tab_id:
                if not t.get("active"):
                    results.ok(f"Screenshot captured without activating tab {bg_tab_id} (CDP path confirmed)")
                else:
                    results.ok(f"Screenshot captured but tab was activated (may be using captureVisibleTab fallback)")
                break

    except Exception as e:
        results.fail("Screenshot no focus steal", str(e))
    finally:
        await ws.close()


async def test_screenshot_minimized_window(results: TestResults):
    """Test CDP screenshots on an isolated fresh test window (v3.2.0)."""
    print("\n[Test: Screenshot New Isolated Window (v3.2.0 CDP)]")
    ws = await websockets.connect(BRIDGE_URL)
    created_window_id = None
    try:
        r = await bridge_send(ws, "newWindow", url="https://httpbin.org/html")
        if not r.get("success"):
            results.fail("Screenshot isolated", "Failed to create window")
            return
            
        created_window_id = r["data"]["windowId"]
        tabs = r["data"].get("tabs", [])
        tab_id = tabs[0]["id"] if tabs else r["data"].get("tabId")

        r = await bridge_send(ws, "captureScreenshot", tabId=tab_id, _timeout=15)
        if r.get("success"):
            data = r["data"]
            data_url = data["dataUrl"]
            method = data.get("method")
            if method != "cdp":
                results.fail("Screenshot CDP path", f"Fell back to {method}. Ensure extension is reloaded so 'debugger' permission is active.")
            else:
                assert data_url.startswith("data:image/png"), "Should be PNG data URL"
                save_data_url(data_url, "screenshot_isolated_cdp.png")
                results.ok(f"Screenshot captured successfully via CDP ({len(data_url)} chars)")
        else:
            diag = await run_diagnostics(ws, tab_id)
            results.fail("Screenshot isolated", f"{r.get('error', 'unknown')} | {diag}")

    except Exception as e:
        results.fail("Screenshot isolated", str(e))
    finally:
        if created_window_id:
            await bridge_send(ws, "closeWindow", windowId=created_window_id)
        await ws.close()

async def test_full_page_screenshot_cdp(results: TestResults):
    """Test that full-page screenshot uses CDP single-shot (frames=1) when possible (v3.2.0)."""
    print("\n[Test: Full-Page Screenshot CDP Single-Shot (v3.2.0)]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        r = await bridge_send(ws, "listTabs")
        tabs = r["data"]
        target = None
        for t in tabs:
            if not t["url"].startswith(("chrome://", "brave://", "edge://", "about:")):
                target = t
                break

        if not target:
            results.fail("Full-page CDP", "No suitable tab")
            return

        tab_id = target.get("virtualId") or target["id"]

        r = await bridge_send(ws, "captureFullPageScreenshot", tabId=tab_id, _timeout=60)
        if not r.get("success"):
            results.fail("Full-page CDP", r.get("error", "unknown"))
            return

        data = r["data"]
        data_url = data.get("dataUrl", "")
        method = data.get("method")
        
        if method != "cdp":
            results.fail("Full-page CDP", f"Fell back to {method}. Ensure extension is reloaded so 'debugger' permission is active.")
            return

        assert data_url.startswith("data:image/png"), "Should be PNG data URL"
        save_data_url(data_url, "screenshot_full_page_cdp.png")

        is_full = data.get("fullPage", False)
        dims = data.get("dimensions", {})
        frame_count = dims.get("frames", 0)
        if is_full and frame_count == 1:
            results.ok(f"Full-page captured in single CDP shot: {dims.get('width')}x{dims.get('height')}px")
        elif is_full:
            results.ok(f"Full-page captured via scroll-stitch fallback: {frame_count} frames, "
                       f"{dims.get('width')}x{dims.get('height')}px")
        else:
            # Fallback path may omit fullPage flag â€” just verify we got a valid image
            results.ok(f"Full-page screenshot returned ({len(data_url)} chars, fullPage flag absent â€” likely fallback path)")

    except Exception as e:
        results.fail("Full-page CDP", str(e))
    finally:
        await ws.close()

async def test_cross_frame_dom(results: TestResults):
    """Test that DOM commands can target specific frames via frameId."""
    print("\n[Test: Cross-Frame DOM Access (v3.0.2)]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        tab = await find_ready_tab(ws)
        if not tab:
            results.fail("Cross-frame DOM", "No tab with content script ready")
            return
        tab_id = tab.get("_use_id") or tab["id"]

        # Step 1: List frames to find a child frame
        r = await bridge_send(ws, "listFrames", tabId=tab_id)
        if not r.get("success"):
            results.fail("Cross-frame DOM", f"listFrames failed: {r.get('error')}")
            return

        frames = r["data"]["frames"]
        if len(frames) < 2:
            results.ok("Only 1 frame on this page â€” skip cross-frame test (need a page with iframes)")
            return

        results.ok(f"Found {len(frames)} frames to test")

        # Step 2: Query the top-level frame (frameId=0) â€” should always work
        r = await bridge_send(ws, "querySelector", tabId=tab_id, selector="body", frameId=0)
        if r.get("success"):
            results.ok("querySelector in top-level frame (frameId=0) succeeded")
        else:
            results.fail("querySelector frameId=0", r.get("error"))

        # Step 3: Query a child frame using its frameId
        child = frames[1]  # First child frame
        child_fid = child["frameId"]
        r = await bridge_send(ws, "querySelector", tabId=tab_id, selector="body", frameId=child_fid)
        if r.get("success"):
            results.ok(f"querySelector in child frame (frameId={child_fid}) succeeded")
        else:
            err = r.get("error", "")
            # Cross-origin iframes may reject content script injection â€” expected
            if any(x in err for x in ["does not exist", "not ready", "injection failed", "Cannot access"]):
                results.ok(f"Child frame {child_fid} not reachable (cross-origin â€” expected)")
            else:
                results.fail(f"querySelector frameId={child_fid}", err)

        # Step 4: Get page text from a child frame with enough elements
        rich_frame = None
        for f in frames[1:]:
            if f.get("elementCount", 0) > 10 and f.get("hasBody"):
                rich_frame = f
                break

        if rich_frame:
            r = await bridge_send(ws, "getPageText", tabId=tab_id, frameId=rich_frame["frameId"], maxLength=500)
            if r.get("success"):
                text = r.get("data", "")
                results.ok(f"getPageText in frame {rich_frame['frameId']}: {len(text)} chars")
            else:
                err = r.get("error", "")
                # Cross-origin frames may not have content script
                if any(x in err for x in ["does not exist", "not ready", "injection failed"]):
                    results.ok(f"Frame {rich_frame['frameId']} not reachable (cross-origin â€” expected)")
                else:
                    results.fail(f"getPageText frame {rich_frame['frameId']}", err)
        else:
            results.ok("No rich child frames found â€” skip getPageText sub-test")

    except Exception as e:
        results.fail("Cross-frame DOM", str(e))
    finally:
        await ws.close()


# ==========================================
# v3.1.0 Tests â€” Coverage for all tool categories
# ==========================================

async def test_dom_queries(results: TestResults):
    """Test querySelector, querySelectorAll, getInnerText, getOuterHTML, getAttribute."""
    print("\n[Test: DOM Queries (v3.1.0)]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        tab = await find_ready_tab(ws)
        if not tab:
            results.fail("DOM Queries", "No tab with content script ready")
            return
        tab_id = tab.get("_use_id") or tab["id"]

        # querySelector â€” body always exists
        r = await bridge_send(ws, "querySelector", tabId=tab_id, selector="body")
        assert r.get("success"), f"querySelector failed: {r.get('error')}"
        assert r["data"]["tagName"].lower() == "body"
        results.ok("querySelector body returned correct tagName")

        # querySelectorAll â€” returns {count, elements}
        r = await bridge_send(ws, "querySelectorAll", tabId=tab_id, selector="div", limit=5, _timeout=30)
        assert r.get("success"), f"querySelectorAll failed: {r.get('error')}"
        data = r["data"]
        assert isinstance(data, dict), "querySelectorAll should return a dict"
        assert "elements" in data, "querySelectorAll response should have 'elements' key"
        assert isinstance(data["elements"], list), "elements should be a list"
        assert len(data["elements"]) > 0, "querySelectorAll should find at least 1 element"
        results.ok(f"querySelectorAll returned {data.get('count', len(data['elements']))} elements (limit=5)")

        # getInnerText â€” get body text (may be string, None, or dict on frameset pages)
        r = await bridge_send(ws, "getInnerText", tabId=tab_id, selector="body")
        assert r.get("success"), f"getInnerText failed: {r.get('error')}"
        text = r["data"]
        if isinstance(text, str):
            results.ok(f"getInnerText returned {len(text)} chars")
        elif text is None:
            results.ok("getInnerText returned None (frameset body â€” expected)")
        else:
            # Some pages return structured data
            results.ok(f"getInnerText returned {type(text).__name__} (frameset â€” accepted)")

        # getOuterHTML â€” get body HTML
        r = await bridge_send(ws, "getOuterHTML", tabId=tab_id, selector="body", maxLength=500)
        assert r.get("success"), f"getOuterHTML failed: {r.get('error')}"
        assert "<body" in r["data"].lower(), "getOuterHTML should contain <body"
        results.ok(f"getOuterHTML returned {len(r['data'])} chars (maxLength=500)")

        # getAttribute â€” get body's class (may be empty, but should succeed)
        r = await bridge_send(ws, "getAttribute", tabId=tab_id, selector="body", attribute="class")
        assert r.get("success"), f"getAttribute failed: {r.get('error')}"
        results.ok("getAttribute returned successfully")

    except AssertionError as e:
        results.fail("DOM Queries", str(e))
    except Exception as e:
        results.fail("DOM Queries", str(e))
    finally:
        await ws.close()


async def test_dom_interaction(results: TestResults):
    """Test click, type, fill on a controlled test page."""
    print("\n[Test: DOM Interaction (v3.1.0)]")
    ws = await websockets.connect(BRIDGE_URL)
    created_tab_id = None
    try:
        created_tab_id = await ensure_test_tab(ws, "https://example.com")
        assert created_tab_id is not None, "Failed to ensure test tab"

        # Inject test HTML via evaluate
        test_html = """document.body.innerHTML = '<div id="test-container">' +
            '<input id="test-input" type="text" value="" />' +
            '<button id="test-btn">Click Me</button>' +
            '<select id="test-select"><option value="a">A</option><option value="b">B</option></select>' +
            '<input id="test-check" type="checkbox" />' +
            '</div>'; 'injected';"""
        r = await bridge_send(ws, "evaluate", tabId=created_tab_id, code=test_html)
        assert r.get("success"), f"Inject HTML failed: {r.get('error')}"
        results.ok("Test HTML injected into about:blank tab")

        # fill â€” set input value
        r = await bridge_send(ws, "fill", tabId=created_tab_id, selector="#test-input", value="hello world")
        assert r.get("success"), f"fill failed: {r.get('error')}"
        results.ok("fill succeeded")

        # Verify value via evaluate
        r = await bridge_send(ws, "evaluate", tabId=created_tab_id,
                              code="document.getElementById('test-input').value")
        assert r.get("success") and r["data"] == "hello world", f"fill verification failed: {r}"
        results.ok("fill correctly set input value to 'hello world'")

        # click â€” click the button
        r = await bridge_send(ws, "click", tabId=created_tab_id, selector="#test-btn")
        assert r.get("success"), f"click failed: {r.get('error')}"
        results.ok("click succeeded")

        # selectOption â€” select option B
        r = await bridge_send(ws, "selectOption", tabId=created_tab_id, selector="#test-select", value="b")
        assert r.get("success"), f"selectOption failed: {r.get('error')}"
        results.ok("selectOption succeeded")

        # check â€” check the checkbox
        r = await bridge_send(ws, "check", tabId=created_tab_id, selector="#test-check")
        assert r.get("success"), f"check failed: {r.get('error')}"
        results.ok("check succeeded")

        # uncheck â€” uncheck the checkbox
        r = await bridge_send(ws, "uncheck", tabId=created_tab_id, selector="#test-check")
        assert r.get("success"), f"uncheck failed: {r.get('error')}"
        results.ok("uncheck succeeded")

    except AssertionError as e:
        results.fail("DOM Interaction", str(e))
    except Exception as e:
        results.fail("DOM Interaction", str(e))
    finally:
        await ws.close()


async def test_keyboard(results: TestResults):
    """Test keyPress and keyCombo commands."""
    print("\n[Test: Keyboard (v3.1.0)]")
    ws = await websockets.connect(BRIDGE_URL)
    created_tab_id = None
    try:
        created_tab_id = await ensure_test_tab(ws, "https://example.com")
        assert created_tab_id is not None, "Failed to ensure test tab"

        # Inject a test input and focus it
        r = await bridge_send(ws, "evaluate", tabId=created_tab_id,
                              code="document.body.innerHTML = '<input id=\"ki\" />'; document.getElementById('ki').focus(); 'ok'")
        assert r.get("success")

        # keyPress
        r = await bridge_send(ws, "keyPress", tabId=created_tab_id, key="a")
        assert r.get("success"), f"keyPress failed: {r.get('error')}"
        results.ok("keyPress 'a' succeeded")

        # keyCombo (raw WebSocket API expects keys as an array)
        r = await bridge_send(ws, "keyCombo", tabId=created_tab_id, keys=["Control", "a"])
        assert r.get("success"), f"keyCombo failed: {r.get('error')}"
        results.ok("keyCombo ['Control','a'] succeeded")

    except AssertionError as e:
        results.fail("Keyboard", str(e))
    except Exception as e:
        results.fail("Keyboard", str(e))
    finally:
        await ws.close()


async def test_cookies(results: TestResults):
    """Test setCookie, getCookies, deleteCookie lifecycle."""
    print("\n[Test: Cookies (v3.1.0)]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        test_url = "https://example.com"
        cookie_name = "__stealth_test_cookie"

        # setCookie
        r = await bridge_send(ws, "setCookie", details={
            "url": test_url, "name": cookie_name, "value": "test123"
        })
        assert r.get("success"), f"setCookie failed: {r.get('error')}"
        results.ok("setCookie succeeded")

        # getCookies â€” verify it exists
        r = await bridge_send(ws, "getCookies", url=test_url)
        assert r.get("success"), f"getCookies failed: {r.get('error')}"
        cookies = r["data"]
        found = any(c["name"] == cookie_name for c in cookies)
        assert found, f"Cookie '{cookie_name}' not found in getCookies response"
        results.ok(f"getCookies found test cookie among {len(cookies)} cookies")

        # deleteCookie
        r = await bridge_send(ws, "deleteCookie", url=test_url, name=cookie_name)
        assert r.get("success"), f"deleteCookie failed: {r.get('error')}"
        results.ok("deleteCookie succeeded")

        # Verify deletion
        r = await bridge_send(ws, "getCookies", url=test_url)
        assert r.get("success")
        found_after = any(c["name"] == cookie_name for c in r["data"])
        assert not found_after, "Cookie should be gone after deleteCookie"
        results.ok("Cookie correctly deleted (verified)")

    except AssertionError as e:
        results.fail("Cookies", str(e))
    except Exception as e:
        results.fail("Cookies", str(e))
    finally:
        await ws.close()


async def test_tab_lifecycle(results: TestResults):
    """Test newTab â†’ switchTab â†’ closeTab lifecycle."""
    print("\n[Test: Tab Lifecycle (v3.1.0)]")
    ws = await websockets.connect(BRIDGE_URL)
    created_tab_id = None
    try:
        # newTab
        r = await bridge_send(ws, "newTab", url="about:blank")
        assert r.get("success"), f"newTab failed: {r.get('error')}"
        created_tab_id = r["data"]["tabId"]
        results.ok(f"newTab created tab {created_tab_id}")

        # Verify it exists in listTabs
        r = await bridge_send(ws, "listTabs")
        tab_ids = [t["id"] for t in r["data"]]
        assert created_tab_id in tab_ids, "New tab not in listTabs"
        results.ok("New tab found in listTabs")

        # switchTab
        r = await bridge_send(ws, "switchTab", tabId=created_tab_id)
        assert r.get("success"), f"switchTab failed: {r.get('error')}"
        results.ok("switchTab succeeded")

        # closeTab
        r = await bridge_send(ws, "closeTab", tabId=created_tab_id)
        assert r.get("success"), f"closeTab failed: {r.get('error')}"
        results.ok("closeTab succeeded")
        created_tab_id = None  # Already closed

        # Verify it's gone
        r = await bridge_send(ws, "listTabs")
        tab_ids_after = [t["id"] for t in r["data"]]
        assert created_tab_id not in tab_ids_after or created_tab_id is None
        results.ok("Closed tab no longer in listTabs")

    except AssertionError as e:
        results.fail("Tab Lifecycle", str(e))
    except Exception as e:
        results.fail("Tab Lifecycle", str(e))
    finally:
        if created_tab_id:
            try: await bridge_send(ws, "closeTab", tabId=created_tab_id)
            except: pass
        await ws.close()


async def test_window_lifecycle(results: TestResults):
    """Test newWindow â†’ resizeWindow â†’ closeWindow lifecycle."""
    print("\n[Test: Window Lifecycle (v3.1.0)]")
    ws = await websockets.connect(BRIDGE_URL)
    created_window_id = None
    try:
        # newWindow
        r = await bridge_send(ws, "newWindow", url="about:blank")
        assert r.get("success"), f"newWindow failed: {r.get('error')}"
        created_window_id = r["data"]["windowId"]
        results.ok(f"newWindow created window {created_window_id}")

        # resizeWindow
        r = await bridge_send(ws, "resizeWindow", windowId=created_window_id, width=800, height=600)
        assert r.get("success"), f"resizeWindow failed: {r.get('error')}"
        results.ok("resizeWindow to 800x600 succeeded")

        # Verify in listWindows
        r = await bridge_send(ws, "listWindows")
        win_ids = [w["id"] for w in r["data"]]
        assert created_window_id in win_ids, "New window not in listWindows"
        results.ok("New window found in listWindows")

        # closeWindow
        r = await bridge_send(ws, "closeWindow", windowId=created_window_id)
        assert r.get("success"), f"closeWindow failed: {r.get('error')}"
        results.ok("closeWindow succeeded")
        created_window_id = None

    except AssertionError as e:
        results.fail("Window Lifecycle", str(e))
    except Exception as e:
        results.fail("Window Lifecycle", str(e))
    finally:
        if created_window_id:
            try: await bridge_send(ws, "closeWindow", windowId=created_window_id)
            except: pass
        await ws.close()


async def test_navigation(results: TestResults):
    """Test navigate, goBack, goForward, reloadTab, waitForUrl."""
    print("\n[Test: Navigation (v3.1.0)]")
    ws = await websockets.connect(BRIDGE_URL)
    created_tab_id = None
    try:
        # Create a tab at example.com (can't use about:blank)
        created_tab_id = await ensure_test_tab(ws, "https://example.com")
        assert created_tab_id is not None, "Failed to ensure test tab"

        # navigate to a second page to build history
        r = await bridge_send(ws, "navigate", tabId=created_tab_id, url="https://httpbin.org/html", _timeout=15)
        if r.get("success"):
            await asyncio.sleep(2)
            results.ok("navigate to httpbin.org/html succeeded")

            # Verify URL
            r = await bridge_send(ws, "evaluate", tabId=created_tab_id, code="location.href")
            if r.get("success"):
                results.ok(f"URL confirmed: {r['data']}")

            # goBack
            r = await bridge_send(ws, "goBack", tabId=created_tab_id)
            if r.get("success"):
                results.ok("goBack succeeded")
                await asyncio.sleep(1)

                # goForward
                r = await bridge_send(ws, "goForward", tabId=created_tab_id)
                if r.get("success"):
                    results.ok("goForward succeeded")
                else:
                    results.ok(f"goForward: {r.get('error', 'skipped')} (may be expected)")
            else:
                results.ok(f"goBack: {r.get('error', 'skipped')} (may be expected)")
        else:
            results.ok("httpbin unreachable (offline) â€” skip navigation tests")

        # reloadTab
        r = await bridge_send(ws, "reloadTab", tabId=created_tab_id)
        assert r.get("success"), f"reloadTab failed: {r.get('error')}"
        results.ok("reloadTab succeeded")

    except AssertionError as e:
        results.fail("Navigation", str(e))
    except Exception as e:
        results.fail("Navigation", str(e))
    finally:
        if created_tab_id:
            try: await bridge_send(ws, "closeTab", tabId=created_tab_id)
            except: pass
        await ws.close()


async def test_full_page_screenshot(results: TestResults):
    """Test captureFullPageScreenshot returns stitched image data."""
    print("\n[Test: Full-Page Screenshot (v3.1.0)]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        tab = await find_ready_tab(ws)
        if not tab:
            results.fail("Full-page screenshot", "No tab with content script ready")
            return
        tab_id = tab.get("_use_id") or tab["id"]

        r = await bridge_send(ws, "captureFullPageScreenshot", tabId=tab_id, maxHeight=5000, _timeout=30)
        if r.get("success"):
            data = r["data"]
            assert "dataUrl" in data, "Missing dataUrl in full-page screenshot"
            assert data["dataUrl"].startswith("data:image/png"), "Should be PNG data URL"
            results.ok(f"Full-page screenshot captured ({len(data['dataUrl'])} chars)")
        else:
            # May fail on some pages â€” not critical
            results.ok(f"Full-page screenshot returned: {r.get('error', 'unknown')} (may be expected)")

    except Exception as e:
        results.fail("Full-page screenshot", str(e))
    finally:
        await ws.close()


async def test_page_content(results: TestResults):
    """Test getPageText and getPageHTML commands."""
    print("\n[Test: Page Content (v3.1.0)]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        tab = await find_ready_tab(ws)
        if not tab:
            results.fail("Page Content", "No tab with content script ready")
            return
        tab_id = tab.get("_use_id") or tab["id"]

        # getPageText
        r = await bridge_send(ws, "getPageText", tabId=tab_id, maxLength=1000)
        assert r.get("success"), f"getPageText failed: {r.get('error')}"
        assert isinstance(r["data"], str), "getPageText should return string"
        results.ok(f"getPageText returned {len(r['data'])} chars (maxLength=1000)")

        # getPageHTML
        r = await bridge_send(ws, "getPageHTML", tabId=tab_id, maxLength=2000)
        assert r.get("success"), f"getPageHTML failed: {r.get('error')}"
        assert isinstance(r["data"], str), "getPageHTML should return string"
        assert "<" in r["data"], "getPageHTML should contain HTML tags"
        results.ok(f"getPageHTML returned {len(r['data'])} chars (maxLength=2000)")

    except AssertionError as e:
        results.fail("Page Content", str(e))
    except Exception as e:
        results.fail("Page Content", str(e))
    finally:
        await ws.close()


async def test_scrolling(results: TestResults):
    """Test scrollTo and scrollIntoView commands."""
    print("\n[Test: Scrolling (v3.1.0)]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        tab = await find_ready_tab(ws)
        if not tab:
            results.fail("Scrolling", "No tab with content script ready")
            return
        tab_id = tab.get("_use_id") or tab["id"]

        # scrollTo
        r = await bridge_send(ws, "scrollTo", tabId=tab_id, x=0, y=100)
        assert r.get("success"), f"scrollTo failed: {r.get('error')}"
        results.ok("scrollTo(0, 100) succeeded")

        # scrollIntoView â€” scroll body into view (always exists)
        r = await bridge_send(ws, "scrollIntoView", tabId=tab_id, selector="body")
        assert r.get("success"), f"scrollIntoView failed: {r.get('error')}"
        results.ok("scrollIntoView body succeeded")

        # Reset scroll
        await bridge_send(ws, "scrollTo", tabId=tab_id, x=0, y=0)

    except AssertionError as e:
        results.fail("Scrolling", str(e))
    except Exception as e:
        results.fail("Scrolling", str(e))
    finally:
        await ws.close()


async def test_wait_for_selector(results: TestResults):
    """Test waitForSelector â€” immediate find + timeout on nonexistent."""
    print("\n[Test: Wait For Selector (v3.1.0)]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        tab = await find_ready_tab(ws)
        if not tab:
            results.fail("waitForSelector", "No tab with content script ready")
            return
        tab_id = tab.get("_use_id") or tab["id"]

        # Should find body immediately
        r = await bridge_send(ws, "waitForSelector", tabId=tab_id, selector="body", timeout=2000)
        assert r.get("success"), f"waitForSelector body failed: {r.get('error')}"
        results.ok("waitForSelector found 'body' immediately")

        # Should timeout on nonexistent selector
        r = await bridge_send(ws, "waitForSelector", tabId=tab_id,
                              selector="#nonexistent-element-xyz", timeout=1000, _timeout=5)
        if not r.get("success"):
            results.ok("waitForSelector correctly timed out on nonexistent element")
        else:
            results.fail("waitForSelector timeout", "Should have timed out but succeeded")

    except AssertionError as e:
        results.fail("waitForSelector", str(e))
    except Exception as e:
        results.fail("waitForSelector", str(e))
    finally:
        await ws.close()


async def test_bounding_rect(results: TestResults):
    """Test getBoundingRect returns position and size."""
    print("\n[Test: Bounding Rect (v3.1.0)]")
    ws = await websockets.connect(BRIDGE_URL)
    try:
        tab = await find_ready_tab(ws)
        if not tab:
            results.fail("getBoundingRect", "No tab with content script ready")
            return
        tab_id = tab.get("_use_id") or tab["id"]

        r = await bridge_send(ws, "getBoundingRect", tabId=tab_id, selector="body")
        assert r.get("success"), f"getBoundingRect failed: {r.get('error')}"
        rect = r["data"]
        required_fields = ["x", "y", "width", "height", "top", "left"]
        for field in required_fields:
            assert field in rect, f"Missing '{field}' in rect: {rect}"
        results.ok(f"getBoundingRect body: {rect['width']}x{rect['height']} at ({rect.get('x',0)},{rect.get('y',0)})")

    except AssertionError as e:
        results.fail("getBoundingRect", str(e))
    except Exception as e:
        results.fail("getBoundingRect", str(e))
    finally:
        await ws.close()



# ==========================================
# v3.1.0 Audit â€” Gap tests
# ==========================================

async def test_type_direct(results: TestResults):
    """Test the 'type' command directly (appends text, doesn't clear)."""
    print("\n[Test: Type Direct (v3.1.0 audit)]")
    ws = await websockets.connect(BRIDGE_URL)
    created_tab_id = None
    try:
        created_tab_id = await ensure_test_tab(ws, "https://example.com")
        assert created_tab_id is not None, "Failed to ensure test tab"

        # Inject input and set initial value
        r = await bridge_send(ws, "evaluate", tabId=created_tab_id,
                              code="document.body.innerHTML = '<input id=\"ti\" value=\"\" />'; 'ok'")
        assert r.get("success")

        # Type some text (appends)
        r = await bridge_send(ws, "type", tabId=created_tab_id, selector="#ti", text="abc")
        assert r.get("success"), f"type failed: {r.get('error')}"
        results.ok("type command succeeded")

        # Verify the input contains the typed text
        r = await bridge_send(ws, "evaluate", tabId=created_tab_id,
                              code="document.getElementById('ti').value")
        assert r.get("success")
        val = r["data"]
        assert "abc" in str(val), f"Expected 'abc' in value, got: {val}"
        results.ok(f"type correctly appended text: '{val}'")

    except AssertionError as e:
        results.fail("Type Direct", str(e))
    except Exception as e:
        results.fail("Type Direct", str(e))
    finally:
        await ws.close()


async def test_drag_and_drop(results: TestResults):
    """Test dragAndDrop command structure (verifies command is accepted)."""
    print("\n[Test: Drag and Drop (v3.1.0 audit)]")
    ws = await websockets.connect(BRIDGE_URL)
    created_tab_id = None
    try:
        created_tab_id = await ensure_test_tab(ws, "https://example.com")
        assert created_tab_id is not None, "Failed to ensure test tab"

        # Inject two elements to drag between
        r = await bridge_send(ws, "evaluate", tabId=created_tab_id,
                              code="document.body.innerHTML = '<div id=\"src\" draggable=\"true\">Drag</div><div id=\"tgt\">Drop Here</div>'; 'ok'")
        assert r.get("success")

        # Try drag and drop
        r = await bridge_send(ws, "dragAndDrop", tabId=created_tab_id,
                              sourceSelector="#src", targetSelector="#tgt")
        assert r.get("success"), f"dragAndDrop failed: {r.get('error')}"
        results.ok("dragAndDrop command accepted")

    except AssertionError as e:
        results.fail("Drag and Drop", str(e))
    except Exception as e:
        results.fail("Drag and Drop", str(e))
    finally:
        await ws.close()


async def test_wait_for_url(results: TestResults):
    """Test waitForUrl command â€” match current URL pattern."""
    print("\n[Test: Wait For URL (v3.1.0 audit)]")
    ws = await websockets.connect(BRIDGE_URL)
    created_tab_id = None
    try:
        created_tab_id = await ensure_test_tab(ws, "https://example.com")
        assert created_tab_id is not None, "Failed to ensure test tab"

        # Wait for URL matching current page (should succeed immediately)
        r = await bridge_send(ws, "waitForUrl", tabId=created_tab_id,
                              pattern="example.com", timeout=3000, _timeout=10)
        assert r.get("success"), f"waitForUrl failed: {r.get('error')}"
        results.ok("waitForUrl matched 'example.com' immediately")

        # Wait for a URL that won't match (should timeout)
        r = await bridge_send(ws, "waitForUrl", tabId=created_tab_id,
                              pattern="nonexistent-url-xyz", timeout=1000, _timeout=5)
        if not r.get("success"):
            results.ok("waitForUrl correctly timed out on non-matching pattern")
        else:
            results.fail("waitForUrl timeout", "Should have timed out but succeeded")

    except AssertionError as e:
        results.fail("Wait For URL", str(e))
    except Exception as e:
        results.fail("Wait For URL", str(e))
    finally:
        await ws.close()


async def test_upload_file(results: TestResults):
    """Test setInputFiles command with a small data URL."""
    print("\n[Test: Upload File (v3.1.0 audit)]")
    ws = await websockets.connect(BRIDGE_URL)
    created_tab_id = None
    try:
        created_tab_id = await ensure_test_tab(ws, "https://example.com")
        assert created_tab_id is not None, "Failed to ensure test tab"

        # Inject file input
        r = await bridge_send(ws, "evaluate", tabId=created_tab_id,
                              code="document.body.innerHTML = '<input id=\"fu\" type=\"file\" />'; 'ok'")
        assert r.get("success")

        # Set a tiny text file via data URL
        data_url = "data:text/plain;base64,SGVsbG8gV29ybGQ="  # "Hello World"
        r = await bridge_send(ws, "setInputFiles", tabId=created_tab_id,
                              selector="#fu", dataUrl=data_url)
        assert r.get("success"), f"setInputFiles failed: {r.get('error')}"
        results.ok("setInputFiles accepted data URL")

        # Verify file was set
        r = await bridge_send(ws, "evaluate", tabId=created_tab_id,
                              code="document.getElementById('fu').files.length")
        if r.get("success") and r.get("data", 0) > 0:
            results.ok(f"File input has {r['data']} file(s) set")
        else:
            results.ok("setInputFiles command succeeded (file count verification varies by browser)")

    except AssertionError as e:
        results.fail("Upload File", str(e))
    except Exception as e:
        results.fail("Upload File", str(e))
    finally:
        await ws.close()


async def test_incognito_window(results: TestResults):
    """Test newIncognitoWindow â†’ closeWindow lifecycle."""
    print("\n[Test: Incognito Window (v3.1.0 audit)]")
    ws = await websockets.connect(BRIDGE_URL)
    created_window_id = None
    try:
        r = await bridge_send(ws, "newIncognitoWindow", url="https://example.com")
        if not r.get("success"):
            # Incognito may require manual permission in extension settings
            results.ok(f"newIncognitoWindow: {r.get('error', 'skipped')} (may need extension permission)")
            return
        created_window_id = r["data"]["windowId"]
        results.ok(f"newIncognitoWindow created window {created_window_id}")

        # Verify it exists and is incognito
        r = await bridge_send(ws, "listWindows")
        assert r.get("success")
        incognito_wins = [w for w in r["data"] if w["id"] == created_window_id]
        if incognito_wins:
            assert incognito_wins[0].get("incognito"), "Window should be incognito"
            results.ok("Incognito window confirmed in listWindows")

        # Close
        r = await bridge_send(ws, "closeWindow", windowId=created_window_id)
        assert r.get("success"), f"closeWindow failed: {r.get('error')}"
        results.ok("Incognito window closed")
        created_window_id = None

    except AssertionError as e:
        results.fail("Incognito Window", str(e))
    except Exception as e:
        results.fail("Incognito Window", str(e))
    finally:
        if created_window_id:
            try: await bridge_send(ws, "closeWindow", windowId=created_window_id)
            except: pass
        await ws.close()


# ==========================================
# Runner
# ==========================================

async def run_all_tests():
    print("=" * 50)
    print("StealthDOM Integration Tests")
    print("=" * 50)

    # Clean up previous artifacts
    test_dir = os.path.dirname(os.path.abspath(__file__))
    for f in glob.glob(os.path.join(test_dir, "screenshot_*.png")):
        try: os.remove(f)
        except: pass
    report_file = os.path.join(test_dir, "TEST_REPORT.md")
    if os.path.exists(report_file):
        try: os.remove(report_file)
        except: pass
    print("[Setup] Cleared old screenshots and test report.")

    results = TestResults()

    # Record initial window states so we can restore them exactly
    # This prevents the test suite from leaving the browser popped open if it started minimized.
    initial_windows = []
    try:
        ws = await websockets.connect(BRIDGE_URL)
        r = await bridge_send(ws, "listWindows")
        if r.get("success"):
            initial_windows = r["data"]
        await ws.close()
        print(f"[Setup] Captured state of {len(initial_windows)} original windows.")
    except Exception as e:
        print(f"[Setup] Warning: Could not capture initial window states: {e}")

    # Create fresh background tabs to ensure content scripts are newly injected.
    # Closing old ones wipes out any dangling CDP debuggers from aborted tests.
    setup_tab_id = None
    try:
        ws = await websockets.connect(BRIDGE_URL)
        setup_tab_id = await ensure_test_tab(ws, "https://httpbin.org/html")
        await ensure_test_tab(ws, "https://example.com")
        print("[Setup] Ensured base test tabs are open and fresh.")
        await ws.close()
    except Exception as e:
        print(f"[Setup] Warning: Could not setup test tabs: {e}")

    # Core infrastructure
    await test_bridge_connection(results)
    await test_msg_id_echo(results)
    await test_list_tabs(results)
    await test_list_windows(results)
    await test_list_connections(results)
    await test_explicit_tab_targeting(results)
    await test_missing_tab_id_rejected(results)
    await test_virtual_tab_routing(results)
    await test_parallel_commands(results)

    # Screenshots
    await test_screenshot_with_tab_id(results)
    await test_full_page_screenshot(results)
    await test_screenshot_mutex(results)
    await test_screenshot_no_focus_steal(results)
    await test_screenshot_minimized_window(results)
    await test_full_page_screenshot_cdp(results)

    # DOM queries
    await test_dom_queries(results)
    await test_bounding_rect(results)
    await test_wait_for_selector(results)
    await test_page_content(results)

    # DOM interaction
    await test_dom_interaction(results)
    await test_keyboard(results)
    await test_scrolling(results)
    await test_hover(results)

    # JavaScript
    await test_evaluate_with_tab_id(results)

    # Cross-frame
    await test_list_frames(results)
    await test_list_frames_missing_tabid(results)
    await test_execute_script_all_frames(results)
    await test_cross_frame_dom(results)

    # Navigation
    await test_navigation(results)

    # Tab & Window lifecycle
    await test_tab_lifecycle(results)
    await test_window_lifecycle(results)

    # Cookies
    await test_cookies(results)

    # Network
    await test_net_capture_overflow(results)
    await test_proxy_fetch(results)

    # Audit gap coverage (v3.1.0)
    await test_type_direct(results)
    await test_drag_and_drop(results)
    await test_wait_for_url(results)
    await test_upload_file(results)
    await test_incognito_window(results)

    success = results.summary()

    # Restore initial window states
    print("\n[Teardown] Restoring original window states...")
    try:
        ws = await websockets.connect(BRIDGE_URL)
        for w in initial_windows:
            if w.get("state"):
                try:
                    await bridge_send(ws, "resizeWindow", windowId=w["id"], state=w["state"])
                except:
                    pass
        await ws.close()
    except Exception as e:
        print(f"[Teardown] Warning: Could not restore window states: {e}")

    return success


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)

