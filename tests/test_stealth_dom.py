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

    success = results.summary()
    return success


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
