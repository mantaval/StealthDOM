# StealthDOM Test Suite Report

**Results:** 96/99 passed, 3 failed

## Failures
- **Screenshot**: `Command captureScreenshot timed out after 15s | Diagnostics: Tab is AWAKE (Active: True, Visibility: visible). If screenshot timed out, the browser window is likely 100% occluded by an Always-on-Top app (IDE), or it was just created in a minimized window and deferred rendering.`
- **Screenshot no focus steal**: `Command captureScreenshot timed out after 15s | Diagnostics: Tab is AWAKE (Active: False, Visibility: visible). If screenshot timed out, the browser window is likely 100% occluded by an Always-on-Top app (IDE), or it was just created in a minimized window and deferred rendering.`
- **Mouse CDP**: `'charmap' codec can't encode character '\u2192' in position 41: character maps to <undefined>`

## Analysis & Possible Causes
### Command captureScreenshot timed out
**Chromium Compositor Paused / Tab Asleep**
> When a browser window is 100% occluded by an 'Always on Top' application (like your IDE), Chromium pauses its rendering compositor to save battery. Because the fallback `captureVisibleTab` requires a fully rendered frame, it hangs indefinitely. The CDP screenshot path normally bypasses this, but if it falls back to `captureVisibleTab` (e.g. because DevTools is open on the target tab), it will time out.

> *Note:* This timeout also occurs if the target tab is a background tab that Chrome's 'Memory Saver' has frozen (which causes the CDP command to hang). The test suite uses active `ensure_test_tab` targets to prevent this.

### Command captureScreenshot timed out
**Chromium Compositor Paused / Tab Asleep**
> When a browser window is 100% occluded by an 'Always on Top' application (like your IDE), Chromium pauses its rendering compositor to save battery. Because the fallback `captureVisibleTab` requires a fully rendered frame, it hangs indefinitely. The CDP screenshot path normally bypasses this, but if it falls back to `captureVisibleTab` (e.g. because DevTools is open on the target tab), it will time out.

> *Note:* This timeout also occurs if the target tab is a background tab that Chrome's 'Memory Saver' has frozen (which causes the CDP command to hang). The test suite uses active `ensure_test_tab` targets to prevent this.

## Test Execution Log

### Connect to bridge
- ✅ All 1 assertions passed.

### _msg_id echoed correctly
- ✅ All 1 assertions passed.

### listTabs succeeds
- ✅ All 1 assertions passed.

### Found 16 tabs
- ✅ All 1 assertions passed.

### Tab has all required fields (id, url, title, active, windowId, incognito)
- ✅ All 1 assertions passed.

### virtualId present: chrome:1653965342
- ✅ All 1 assertions passed.

### browserId present: chrome
- ✅ All 1 assertions passed.

### listWindows succeeds
- ✅ All 1 assertions passed.

### Window has all required fields (id, type, incognito, focused)
- ✅ All 1 assertions passed.

### listConnections: 1 browser(s) connected, primary='chrome'
- ✅ All 1 assertions passed.

### Using tab 1653965342: https://mail.google.com/mail/u/0/#inbox
- ✅ All 1 assertions passed.

### getTitle with explicit tabId returned: Inbox (171) - mantaval@gmail.com - Gmail
- ✅ All 1 assertions passed.

### getURL with explicit tabId returned: https://mail.google.com/mail/u/0/#inbox
- ✅ All 1 assertions passed.

### navigate correctly rejects missing tabId
- ✅ All 1 assertions passed.

### goBack correctly rejects missing tabId
- ✅ All 1 assertions passed.

### goForward correctly rejects missing tabId
- ✅ All 1 assertions passed.

### reloadTab correctly rejects missing tabId
- ✅ All 1 assertions passed.

### captureScreenshot correctly rejects missing tabId
- ✅ All 1 assertions passed.

### querySelector correctly rejects missing tabId
- ✅ All 1 assertions passed.

### virtualId routing OK: 'chrome:1653965342' -> title='Inbox (171) - mantaval@gmail.com - Gmail'
- ✅ All 1 assertions passed.

### All parallel commands returned correct response types (no cross-talk)
- ✅ All 1 assertions passed.

### Screenshot
- ❌ `Screenshot: Command captureScreenshot timed out after 15s | Diagnostics: Tab is AWAKE (Active: True, Visibility: visible). If screenshot timed out, the browser window is likely 100% occluded by an Always-on-Top app (IDE), or it was just created in a minimized window and deferred rendering.`

### Full-page screenshot captured (314682 chars)
- ✅ All 1 assertions passed.

### All 3 parallel screenshots succeeded (mutex serialized them)
- ✅ All 1 assertions passed.

### Screenshot no focus steal
- ❌ `Screenshot no focus steal: Command captureScreenshot timed out after 15s | Diagnostics: Tab is AWAKE (Active: False, Visibility: visible). If screenshot timed out, the browser window is likely 100% occluded by an Always-on-Top app (IDE), or it was just created in a minimized window and deferred rendering.`

### Screenshot captured successfully via CDP (137742 chars)
- ✅ All 1 assertions passed.

### Full-page captured in single CDP shot: 1438x807px
- ✅ All 1 assertions passed.

### querySelector body returned correct tagName
- ✅ All 1 assertions passed.

### querySelectorAll returned 1823 elements (limit=5)
- ✅ All 1 assertions passed.

### getInnerText returned dict (frameset â€” accepted)
- ✅ All 1 assertions passed.

### getOuterHTML returned 500 chars (maxLength=500)
- ✅ All 1 assertions passed.

### getAttribute returned successfully
- ✅ All 1 assertions passed.

### getBoundingRect body: 1438x807 at (0,0)
- ✅ All 1 assertions passed.

### waitForSelector found 'body' immediately
- ✅ All 1 assertions passed.

### waitForSelector correctly timed out on nonexistent element
- ✅ All 1 assertions passed.

### getPageText returned 1000 chars (maxLength=1000)
- ✅ All 1 assertions passed.

### getPageHTML returned 2000 chars (maxLength=2000)
- ✅ All 1 assertions passed.

### Test HTML injected into about:blank tab
- ✅ All 1 assertions passed.

### fill succeeded
- ✅ All 1 assertions passed.

### fill correctly set input value to 'hello world'
- ✅ All 1 assertions passed.

### click succeeded
- ✅ All 1 assertions passed.

### selectOption succeeded
- ✅ All 1 assertions passed.

### check succeeded
- ✅ All 1 assertions passed.

### uncheck succeeded
- ✅ All 1 assertions passed.

### keyPress 'a' succeeded
- ✅ All 1 assertions passed.

### keyCombo ['Control','a'] succeeded
- ✅ All 1 assertions passed.

### scrollTo(0, 100) succeeded
- ✅ All 1 assertions passed.

### scrollIntoView body succeeded
- ✅ All 1 assertions passed.

### hover command succeeded
- ✅ All 1 assertions passed.

### Got target coordinates (719, 39)
- ✅ All 1 assertions passed.

### mouseMoveCDP succeeded
- ✅ All 1 assertions passed.

### mouseClickCDP (single left) succeeded
- ✅ All 1 assertions passed.

### mouseClickCDP (double-click) succeeded
- ✅ All 1 assertions passed.

### mouseDownCDP succeeded
- ✅ All 1 assertions passed.

### mouseUpCDP succeeded
- ✅ All 1 assertions passed.

### mouseDragCDP succeeded (719,39) → (819,89)
- ✅ All 1 assertions passed.

### Mouse CDP
- ❌ `Mouse CDP: 'charmap' codec can't encode character '\u2192' in position 41: character maps to <undefined>`

### evaluate returned: None
- ✅ All 1 assertions passed.

### listFrames returned 7 frame(s)
- ✅ All 1 assertions passed.

### Frame structure OK: url=https://mail.google.com/mail/u/0/#inbox, hasBody=True
- ✅ All 1 assertions passed.

### Frame enrichment: elementCount=4763
- ✅ All 1 assertions passed.

### Frame enrichment: isFrameset=False
- ✅ All 1 assertions passed.

### listFrames correctly rejects missing tabId
- ✅ All 1 assertions passed.

### executeScriptAllFrames returned 7 result(s)
- ✅ All 1 assertions passed.

### Frame 0 result: title='None'
- ✅ All 1 assertions passed.

### Complex eval returned: None
- ✅ All 1 assertions passed.

### Found 7 frames to test
- ✅ All 1 assertions passed.

### querySelector in top-level frame (frameId=0) succeeded
- ✅ All 1 assertions passed.

### querySelector in child frame (frameId=291) succeeded
- ✅ All 1 assertions passed.

### getPageText in frame 291: 500 chars
- ✅ All 1 assertions passed.

### navigate to httpbin.org/html succeeded
- ✅ All 1 assertions passed.

### URL confirmed: https://httpbin.org/html
- ✅ All 1 assertions passed.

### goBack: Cannot find a next page in history. (may be expected)
- ✅ All 1 assertions passed.

### reloadTab succeeded
- ✅ All 1 assertions passed.

### newTab created tab 1653965634
- ✅ All 1 assertions passed.

### New tab found in listTabs
- ✅ All 1 assertions passed.

### switchTab succeeded
- ✅ All 1 assertions passed.

### closeTab succeeded
- ✅ All 1 assertions passed.

### Closed tab no longer in listTabs
- ✅ All 1 assertions passed.

### newWindow created window 1653965636
- ✅ All 1 assertions passed.

### resizeWindow to 800x600 succeeded
- ✅ All 1 assertions passed.

### New window found in listWindows
- ✅ All 1 assertions passed.

### closeWindow succeeded
- ✅ All 1 assertions passed.

### setCookie succeeded
- ✅ All 1 assertions passed.

### getCookies found test cookie among 1 cookies
- ✅ All 1 assertions passed.

### deleteCookie succeeded
- ✅ All 1 assertions passed.

### Cookie correctly deleted (verified)
- ✅ All 1 assertions passed.

### getNetCapture structure OK: bufferSize=5000, overflowCount=0
- ✅ All 1 assertions passed.

### proxyFetch succeeded (status=200)
- ✅ All 1 assertions passed.

### type command succeeded
- ✅ All 1 assertions passed.

### type correctly appended text: 'abc'
- ✅ All 1 assertions passed.

### dragAndDrop command accepted
- ✅ All 1 assertions passed.

### waitForUrl matched 'example.com' immediately
- ✅ All 1 assertions passed.

### waitForUrl correctly timed out on non-matching pattern
- ✅ All 1 assertions passed.

### setInputFiles accepted data URL
- ✅ All 1 assertions passed.

### File input has 1 file(s) set
- ✅ All 1 assertions passed.

### newIncognitoWindow created window 1653965647
- ✅ All 1 assertions passed.

### Incognito window confirmed in listWindows
- ✅ All 1 assertions passed.

### Incognito window closed
- ✅ All 1 assertions passed.

