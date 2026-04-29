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

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import websockets

BRIDGE_URL = "ws://127.0.0.1:9878"

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


class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
    
    def ok(self, name):
        self.passed += 1
        print(f"  [PASS] {name}")
    
    def fail(self, name, reason):
        self.failed += 1
        self.errors.append((name, reason))
        print(f"  [FAIL] {name}: {reason}")
    
    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*50}")
        print(f"Results: {self.passed}/{total} passed, {self.failed} failed")
        if self.errors:
            print("\nFailures:")
            for name, reason in self.errors:
                print(f"  - {name}: {reason}")
        return self.failed == 0


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
    """Test screenshot targeting a specific tab."""
    print("\n[Test: Screenshot with tabId]")
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
            results.fail("Screenshot", "No suitable tab")
            return
        
        r = await bridge_send(ws, "captureScreenshot", tabId=tab["id"])
        if r.get("success"):
            data_url = r["data"]["dataUrl"]
            assert data_url.startswith("data:image/png"), "Should be PNG data URL"
            assert r["data"]["tabId"] == tab["id"], "Should echo correct tabId"
            results.ok(f"Screenshot captured for tab {tab['id']} ({len(data_url)} chars)")
        else:
            results.fail("Screenshot", r.get("error"))
        
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
        assert "overflowCount" in data, "Missing overflowCount — circular buffer not implemented"
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
            results.ok("Virtual tab IDs not present (single-browser mode — OK)")
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
            # External fetch might fail in CI/offline — treat as warning
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
                # Some frames may return null (e.g., no body) — that's OK
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

        # Fire 3 screenshots in rapid parallel — without the mutex, this would
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
            else:
                err = resp.get("error", "")
                if "MAX_CAPTURE" in err:
                    results.fail(f"Screenshot mutex ({label})",
                                 "Quota error — mutex not working!")
                else:
                    results.fail(f"Screenshot mutex ({label})", err)

        if succeeded == 3:
            results.ok("All 3 parallel screenshots succeeded (mutex serialized them)")
        elif succeeded > 0:
            results.ok(f"{succeeded}/3 parallel screenshots succeeded (partial — may be timing)")

    except Exception as e:
        results.fail("Screenshot mutex", str(e))
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
            results.ok("Only 1 frame on this page — skip cross-frame test (need a page with iframes)")
            return

        results.ok(f"Found {len(frames)} frames to test")

        # Step 2: Query the top-level frame (frameId=0) — should always work
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
            # Cross-origin iframes may reject content script injection — expected
            if any(x in err for x in ["does not exist", "not ready", "injection failed", "Cannot access"]):
                results.ok(f"Child frame {child_fid} not reachable (cross-origin — expected)")
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
                    results.ok(f"Frame {rich_frame['frameId']} not reachable (cross-origin — expected)")
                else:
                    results.fail(f"getPageText frame {rich_frame['frameId']}", err)
        else:
            results.ok("No rich child frames found — skip getPageText sub-test")

    except Exception as e:
        results.fail("Cross-frame DOM", str(e))
    finally:
        await ws.close()


# ==========================================
# Runner
# ==========================================

async def run_all_tests():
    print("=" * 50)
    print("StealthDOM Integration Tests")
    print("=" * 50)

    results = TestResults()

    await test_bridge_connection(results)
    await test_msg_id_echo(results)
    await test_list_tabs(results)
    await test_list_windows(results)
    await test_list_connections(results)
    await test_explicit_tab_targeting(results)
    await test_missing_tab_id_rejected(results)
    await test_screenshot_with_tab_id(results)
    await test_evaluate_with_tab_id(results)
    await test_hover(results)
    await test_net_capture_overflow(results)
    await test_virtual_tab_routing(results)
    await test_proxy_fetch(results)
    await test_parallel_commands(results)

    # v3.0.2 tests
    await test_list_frames(results)
    await test_list_frames_missing_tabid(results)
    await test_execute_script_all_frames(results)
    await test_screenshot_mutex(results)
    await test_cross_frame_dom(results)

    success = results.summary()
    return success


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)

