# StealthDOM Test Suite

This directory contains the integration tests for the StealthDOM Manifest V3 extension. 

The test runner (`test_stealth_dom.py`) connects to the local StealthDOM websocket bridge and executes a comprehensive suite of tests verifying DOM interaction, tab management, cross-frame execution, and network capturing.

## How It Works

- **Tab Reuse:** The test runner is designed to be completely silent (no popups) for the majority of the tests. It accomplishes this by dynamically creating base test tabs (`httpbin.org/html` and `example.com`) on the first run, and then silently reusing and reloading those same tabs on subsequent runs.
- **CDP vs. Fallback:** The suite tests both the primary Chrome DevTools Protocol (CDP) screenshot engine (which captures the DOM in the background without stealing focus) and the fallback `captureVisibleTab` engine (which requires window focus).
- **Automated Cleanup:** Every time `python test_stealth_dom.py` is executed, the script automatically deletes all previously generated `*.png` screenshots and the `TEST_REPORT.md` file from this folder to ensure a clean slate.
- **Reporting:** Upon completion, the test runner outputs a dynamic `TEST_REPORT.md` file. This report contains the full execution log, the pass/fail results, and detailed diagnostic context for any tests that failed.

## Running the Tests

Ensure the StealthDOM extension is loaded in your browser and the Python bridge server is running, then execute:

```bash
python test_stealth_dom.py
```

Check this directory after execution for the resulting `TEST_REPORT.md` and any generated `*.png` screenshots.

### Clean Execution & Window State
The test suite is designed to be completely non-intrusive.
1. **Window State Restoration**: At the start of the test suite, it captures the exact state of your browser windows (e.g., `minimized`, `normal`, `maximized`). At the end of the run, it seamlessly restores all windows to that exact original state, allowing you to test background agent scripts without disrupting your desktop.
2. **Tab Isolation**: The suite actively manages its own background tabs (`ensure_test_tab`) and closes them appropriately to clear out any dangling Chrome DevTools Protocol (CDP) debuggers from previous crashes.
3. **Clean Canvas Testing (`example.com`)**: Several tests dynamically inject custom HTML into `example.com`. This domain is globally reserved by IANA for documentation and testing. It loads instantly, has zero tracking scripts, and provides a perfectly stable, blank slate. This ensures DOM interaction tests (like file uploads or drag-and-drop) never fail due to random layout changes on third-party websites.

## Common Errors & Diagnostic Explanations

If a test fails, `TEST_REPORT.md` will automatically provide a clean, grouped markdown report with diagnostic context. Here are the common errors you may encounter:

### Command captureScreenshot timed out
**Chromium Compositor Paused / Tab Asleep**
When a browser window is 100% occluded by an "Always on Top" application (like your IDE or a system overlay), Chromium completely pauses its rendering compositor to save battery. Because the fallback `captureVisibleTab` API explicitly waits for a fully rendered frame, it will hang indefinitely in this state. The primary CDP screenshot path normally bypasses this, but if CDP falls back to `captureVisibleTab` (e.g., because DevTools is open on the target tab), it will trigger this timeout.
*Note:* This timeout also occurs if the target tab is a background tab that Chrome's "Memory Saver" has frozen (which causes the CDP command to hang indefinitely). The test suite now prevents this by explicitly using dedicated, active test tabs.
*Fix: Ensure the target tab is not frozen by Memory Saver, DevTools is closed on the target tab, and the browser window is at least partially visible if relying on the fallback path.*

### Failed to connect to bridge
**Bridge Server Not Running**
The Python integration tests require the StealthDOM extension to be actively running in a browser, with the native messaging host connected. 
*Fix: Ensure the browser is open, the extension is enabled, and the WebSocket bridge (`app.py` or equivalent) is running.*

### MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND
**Chrome Quota Exceeded**
Chrome heavily rate-limits the `captureVisibleTab` API. The fallback mechanism includes a mutex lock to serialize calls, but if too many commands are forced rapidly across multiple parallel agents, it may still exceed the strict 2 calls/sec limit. The primary CDP path does not have this limit.
*Fix: Ensure tests or agents are utilizing the CDP path whenever possible, which has no rate limits.*
