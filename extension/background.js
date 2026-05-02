/**
 * StealthDOM -- Background Service Worker
 * 
 * Handles operations that content scripts can't do:
 * - Tab management (list, open, close, switch)
 * - Screenshots (captureVisibleTab)
 * - Cookies (get, set, delete)
 * - Navigation (via chrome.tabs API)
 * - MAIN world script execution (CSP-safe, pre-compiled functions)
 * - Network traffic capture (request/response headers)
 * 
 * Communicates with content scripts via chrome.runtime messaging.
 */

// Keep-alive: prevent browser from killing the service worker
const KEEPALIVE_INTERVAL = 20000;  // 20s (well under 5min timeout)

setInterval(() => {
    // Touching chrome.runtime keeps the worker alive
    chrome.runtime.getPlatformInfo(() => { });
}, KEEPALIVE_INTERVAL);

// ==========================================
// On-Demand Content Script Injection
// ==========================================
// Content script is NOT declared in manifest.json.
// Instead, we inject it lazily on first command to each tab,
// saving memory and CPU across all untouched tabs/frames.

const _injectedTabs = new Set();

/**
 * Ensure the content script is injected into a tab before sending it commands.
 * Injects into all frames (allFrames: true) so frame_id targeting works.
 * No-ops if already injected into this tab.
 * 
 * @param {number} tabId - The numeric Chrome tab ID
 * @returns {Promise<void>}
 */
async function ensureContentScriptInjected(tabId) {
    if (_injectedTabs.has(tabId)) return;

    try {
        await chrome.scripting.executeScript({
            target: { tabId, allFrames: true },
            files: ['content_script.js'],
        });
        _injectedTabs.add(tabId);
    } catch (e) {
        // Don't add to set — let the next command retry
        throw new Error(`Content script injection failed: ${e.message}. If the tab is sleeping/discarded, use browser_reload or browser_switch_tab to wake it up first.`);
    }
}

// Clean up injection tracking when tabs navigate or close
chrome.tabs.onRemoved.addListener((tabId) => {
    _injectedTabs.delete(tabId);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
    // When a tab navigates to a new page, the injected script is gone
    if (changeInfo.status === 'loading') {
        _injectedTabs.delete(tabId);
    }
});

// ==========================================
// Global Enable/Disable State
// ==========================================

let _enabled = true;  // Default: enabled

// Load persisted state on startup
chrome.storage.local.get(['stealthdom_enabled'], (result) => {
    _enabled = result.stealthdom_enabled !== false;
    if (_enabled) {
        enableCSPStripping();
    } else {
        disableCSPStripping();
    }
    updateIcon(_enabled);
});

function enableCSPStripping() {
    chrome.declarativeNetRequest.updateDynamicRules({
        removeRuleIds: [9999],
        addRules: [{
            id: 9999,
            priority: 1,
            action: {
                type: 'modifyHeaders',
                responseHeaders: [
                    { header: 'content-security-policy', operation: 'remove' },
                    { header: 'content-security-policy-report-only', operation: 'remove' }
                ]
            },
            condition: {
                resourceTypes: ['main_frame', 'sub_frame']
            }
        }]
    }).then(() => {
        console.log('[StealthDOM] CSP header stripping enabled');
    });
}

let _blockConversations = false;
function enableConversationBlocking() {
    chrome.declarativeNetRequest.updateDynamicRules({
        removeRuleIds: [8888],
        addRules: [{
            id: 8888,
            priority: 2,
            action: { type: 'block' },
            condition: {
                urlFilter: 'backend-anon/conversation',
                resourceTypes: ['xmlhttprequest']
            }
        }]
    }).then(() => {
        console.log('[StealthDOM] Conversation blocking enabled');
    });
}

function disableConversationBlocking() {
    chrome.declarativeNetRequest.updateDynamicRules({
        removeRuleIds: [8888]
    }).then(() => {
        console.log('[StealthDOM] Conversation blocking disabled');
    });
}

function disableCSPStripping() {
    chrome.declarativeNetRequest.updateDynamicRules({
        removeRuleIds: [9999],
        addRules: []
    }).then(() => {
        console.log('[StealthDOM] CSP header stripping disabled');
    }).catch(err => {
        console.warn('[StealthDOM] Failed to remove CSP stripping rule:', err);
    });
}

function setEnabled(enabled) {
    _enabled = enabled;
    chrome.storage.local.set({ stealthdom_enabled: enabled });

    if (enabled) {
        enableCSPStripping();
        bridgeConnect();
        updateIcon(true);
        console.log('[StealthDOM] Enabled');
    } else {
        disableCSPStripping();
        bridgeDisconnect();
        updateIcon(false);
        console.log('[StealthDOM] Disabled');
    }
}

/**
 * Update the toolbar icon to reflect enabled/disabled state.
 * Enabled: normal colored icon, no badge.
 * Disabled: greyscale icon + red "OFF" badge.
 */
async function updateIcon(enabled) {
    if (enabled) {
        // Restore original icon
        chrome.action.setIcon({
            path: { '16': 'icon16.png', '48': 'icon48.png', '128': 'icon128.png' }
        });
        chrome.action.setBadgeText({ text: '' });
    } else {
        // Greyscale icon via OffscreenCanvas
        try {
            const sizes = [16, 48];
            const imageData = {};
            for (const size of sizes) {
                const resp = await fetch(`icon${size}.png`);
                const blob = await resp.blob();
                const bmp = await createImageBitmap(blob);
                const canvas = new OffscreenCanvas(size, size);
                const ctx = canvas.getContext('2d');
                ctx.drawImage(bmp, 0, 0, size, size);
                const data = ctx.getImageData(0, 0, size, size);
                // Convert to greyscale
                for (let i = 0; i < data.data.length; i += 4) {
                    const grey = Math.round(
                        data.data[i] * 0.299 + data.data[i+1] * 0.587 + data.data[i+2] * 0.114
                    );
                    data.data[i] = grey;
                    data.data[i+1] = grey;
                    data.data[i+2] = grey;
                    data.data[i+3] = Math.round(data.data[i+3] * 0.6); // Slightly transparent
                }
                imageData[size] = data;
            }
            chrome.action.setIcon({ imageData });
        } catch (e) {
            console.warn('[StealthDOM] Failed to create greyscale icon:', e);
        }
        // Red "OFF" badge
        chrome.action.setBadgeText({ text: 'OFF' });
        chrome.action.setBadgeBackgroundColor({ color: '#DC2626' });
    }
}

function bridgeDisconnect() {
    if (_bridgeWs) {
        _bridgeWs.onclose = null;  // Prevent auto-reconnect
        _bridgeWs.close();
        _bridgeWs = null;
    }
    bridgeCleanup();
    clearTimeout(_bridgeReconnect);
}

// CSP stripping is now managed by enableCSPStripping() / disableCSPStripping() above.

// ==========================================
// Network Traffic Capture
// ==========================================

// ==========================================
// Circular Buffer for Network Capture
// ==========================================

/**
 * Fixed-size circular buffer. Overwrites oldest entries when full.
 * Tracks overflow count so agents know if data was lost.
 */
class CircularBuffer {
    constructor(maxSize) {
        this._buf = new Array(maxSize);
        this._maxSize = maxSize;
        this._head = 0;       // Next write position
        this._size = 0;       // Current fill level
        this._overflowCount = 0;
    }
    push(item) {
        if (this._size >= this._maxSize) {
            this._overflowCount++;
        } else {
            this._size++;
        }
        this._buf[this._head] = item;
        this._head = (this._head + 1) % this._maxSize;
    }
    toArray() {
        if (this._size < this._maxSize) {
            return this._buf.slice(0, this._size);
        }
        // Buffer is full — items start from _head (oldest) wrapping around
        return [...this._buf.slice(this._head), ...this._buf.slice(0, this._head)];
    }
    clear() {
        this._head = 0;
        this._size = 0;
        this._overflowCount = 0;
    }
    get overflowCount() { return this._overflowCount; }
    get size() { return this._size; }
    get maxSize() { return this._maxSize; }
}

const NET_CAPTURE_MAX = 5000;
const _netCapture = new CircularBuffer(NET_CAPTURE_MAX);
let _netCaptureActive = false;

// Capture all requests when enabled
chrome.webRequest.onBeforeRequest.addListener(
    (details) => {
        if (!_netCaptureActive) return;
        _netCapture.push({
            timestamp: Date.now(),
            type: details.type,
            method: details.method,
            url: details.url,
            tabId: details.tabId,
            requestBody: details.requestBody ? {
                raw: details.requestBody.raw ? details.requestBody.raw.map(r => {
                    if (r.bytes) {
                        try {
                            const decoder = new TextDecoder('utf-8');
                            return { text: decoder.decode(r.bytes) };
                        } catch (e) {
                            return { bytes: Array.from(new Uint8Array(r.bytes)) };
                        }
                    }
                    return { file: r.file };
                }) : null,
                formData: details.requestBody.formData || null,
            } : null,
        });
    },
    {
        urls: ['<all_urls>'],
        types: ['main_frame', 'sub_frame', 'script', 'xmlhttprequest', 'ping', 'other']
    },
    ['requestBody']
);

// Also capture response headers
chrome.webRequest.onHeadersReceived.addListener(
    (details) => {
        if (!_netCaptureActive) return;
        // Find matching request and add response info
        const arr = _netCapture.toArray();
        const match = arr.find(r => r.url === details.url && !r.responseHeaders);
        if (match) {
            match.statusCode = details.statusCode;
            match.responseHeaders = {};
            for (const h of (details.responseHeaders || [])) {
                match.responseHeaders[h.name.toLowerCase()] = h.value;
            }
        }
    },
    {
        urls: ['<all_urls>'],
        types: ['main_frame', 'sub_frame', 'script', 'xmlhttprequest', 'ping', 'other']
    },
    ['responseHeaders']
);

// Capture request headers (auth tokens, content-type, etc.)
chrome.webRequest.onBeforeSendHeaders.addListener(
    (details) => {
        if (!_netCaptureActive) return;
        const arr = _netCapture.toArray();
        const match = arr.find(r => r.url === details.url && !r.requestHeaders);
        if (match) {
            match.requestHeaders = {};
            for (const h of (details.requestHeaders || [])) {
                match.requestHeaders[h.name.toLowerCase()] = h.value;
            }
        }
    },
    {
        urls: ['<all_urls>'],
        types: ['main_frame', 'sub_frame', 'script', 'xmlhttprequest', 'ping', 'other']
    },
    ['requestHeaders']
);

// ==========================================
// Message Handler from Content Scripts
// ==========================================

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    // Handle popup messages (enable/disable toggle)
    if (msg.type === 'setEnabled') {
        setEnabled(msg.enabled);
        sendResponse({ ok: true });
        return true;
    }
    if (msg.type === 'getStatus') {
        sendResponse({
            enabled: _enabled,
            bridgeConnected: _bridgeWs && _bridgeWs.readyState === WebSocket.OPEN,
        });
        return true;
    }

    if (msg.target !== 'background') return false;

    // Pass sender tab ID so commands run in the correct tab context
    if (sender.tab) msg._senderTabId = sender.tab.id;

    handleBackgroundCommand(msg)
        .then(result => sendResponse(result))
        .catch(err => sendResponse({ success: false, error: err.message }));

    return true;  // Keep channel open for async response
});

async function handleBackgroundCommand(msg) {
    const { action } = msg;

    switch (action) {
        // === Tab Management ===
        case 'listTabs':
            return await cmdListTabs();
        case 'newTab':
            return await cmdNewTab(msg.url);
        case 'closeTab':
            return await cmdCloseTab(msg.tabId);
        case 'switchTab':
            return await cmdSwitchTab(msg.tabId);
        case 'reloadTab':
            return await cmdReloadTab(msg.tabId);

        // === Navigation ===
        case 'navigate':
            return await cmdNavigate(msg.url, msg.tabId);
        case 'goBack':
            return await cmdGoBack(msg.tabId);
        case 'goForward':
            return await cmdGoForward(msg.tabId);

        // === Screenshots ===
        case 'captureScreenshot':
            return await cmdCaptureScreenshot(msg.tabId);
        case 'captureFullPageScreenshot':
            return await cmdCaptureFullPageScreenshot(msg.tabId, msg.maxHeight);

        // === Native Mouse (CDP) ===
        case 'mouseMoveCDP':
            return await cmdMouseMoveCDP(msg.tabId, msg.x, msg.y, msg.steps, msg.duration);
        case 'mouseClickCDP':
            return await cmdMouseClickCDP(msg.tabId, msg.x, msg.y, msg.button, msg.clickCount);
        case 'mouseDownCDP':
            return await cmdMouseDownCDP(msg.tabId, msg.x, msg.y, msg.button);
        case 'mouseUpCDP':
            return await cmdMouseUpCDP(msg.tabId, msg.x, msg.y, msg.button);
        case 'mouseDragCDP':
            return await cmdMouseDragCDP(msg.tabId, msg.startX, msg.startY, msg.endX, msg.endY, msg.steps, msg.duration);
        case 'mouseWheelCDP':
            return await cmdMouseWheelCDP(msg.tabId, msg.x, msg.y, msg.deltaX, msg.deltaY);

        // === Cookies ===
        case 'getCookies':
            return await cmdGetCookies(msg.url, msg.tabId, msg.storeId);
        case 'setCookie':
            return await cmdSetCookie(msg.details);
        case 'deleteCookie':
            return await cmdDeleteCookie(msg.url, msg.name);
        case 'listCookieStores':
            return await cmdListCookieStores();

        // === Script Execution (CSP bypass) ===
        case 'executeScript':
            return await cmdExecuteScript(msg.code, msg._senderTabId || msg.tabId, msg.world);
        case 'executeScriptAllFrames':
            return await cmdExecuteScriptAllFrames(msg.code, msg.tabId, msg.world);

        // === Frame Enumeration ===
        case 'listFrames':
            return await cmdListFrames(msg.tabId);

        // === Window Management ===
        case 'newWindow':
            return await cmdNewWindow(msg.url);
        case 'newIncognitoWindow':
            return await cmdNewIncognitoWindow(msg.url);
        case 'listWindows':
            return await cmdListWindows();
        case 'closeWindow':
            return await cmdCloseWindow(msg.windowId);
        case 'resizeWindow':
            return await cmdResizeWindow(msg.windowId, msg.width, msg.height, msg.left, msg.top, msg.state);

        // === Network Capture ===
        case 'startNetCapture':
            _netCapture.clear();
            _netCaptureActive = true;
            return { success: true, data: 'Capture started' };
        case 'stopNetCapture':
            _netCaptureActive = false;
            return { success: true, data: { requestCount: _netCapture.size } };
        case 'getNetCapture':
            return {
                success: true,
                data: {
                    requests: _netCapture.toArray(),
                    overflowCount: _netCapture.overflowCount,
                    bufferSize: _netCapture.maxSize,
                    capturedCount: _netCapture.size,
                }
            };
        case 'clearNetCapture':
            _netCapture.clear();
            return { success: true };

        // === URL Waiting ===
        case 'waitForUrl':
            return await cmdWaitForUrl(msg.tabId, msg.pattern, msg.timeout);
        case 'enableBlock':
            enableConversationBlocking();
            return { success: true, data: "Blocking enabled" };
        case 'disableBlock':
            disableConversationBlocking();
            return { success: true, data: "Blocking disabled" };

        default:
            return { success: false, error: `Unknown background action: ${action}` };
    }
}

// ==========================================
// WebSocket Bridge Connection
// ==========================================
// The bridge connection lives HERE in the background script
// instead of in content scripts. This is critical because:
// 1. Background scripts are NOT subject to page CSP restrictions
// 2. No "Private Network Access" popups (the page isn't making the connection)
// 3. Single persistent connection regardless of which tab is active
// 4. Works on ALL sites including Gmail, Google, etc.

const WS_URL = 'ws://127.0.0.1:9877';
const RECONNECT_INTERVAL = 3000;
const HEARTBEAT_INTERVAL = 5000;

let _bridgeWs = null;
let _bridgeHeartbeat = null;
let _bridgeReconnect = null;

function bridgeConnect() {
    if (_bridgeWs && (_bridgeWs.readyState === WebSocket.OPEN || _bridgeWs.readyState === WebSocket.CONNECTING)) return;

    try {
        _bridgeWs = new WebSocket(WS_URL);
        console.log('[StealthDOM] Connecting to bridge...');
    } catch (e) {
        console.error('[StealthDOM] WebSocket creation failed:', e);
        bridgeScheduleReconnect();
        return;
    }

    _bridgeWs.onopen = () => {
        console.log('[StealthDOM] Connected to bridge from background script');
        clearTimeout(_bridgeReconnect);

        // Auto-detect browser label for multi-browser support
        const ua = navigator.userAgent || '';
        const browserLabel = ua.includes('Brave') ? 'brave'
            : ua.includes('Edg/') ? 'edge'
            : ua.includes('Chrome') ? 'chrome'
            : 'browser';

        bridgeSend({
            type: 'handshake',
            label: browserLabel,
            url: 'extension-background',
            title: 'StealthDOM Service Worker',
            timestamp: Date.now(),
        });

        _bridgeHeartbeat = setInterval(() => {
            bridgeSend({ type: 'heartbeat', timestamp: Date.now() });
        }, HEARTBEAT_INTERVAL);
    };

    _bridgeWs.onmessage = async (event) => {
        try {
            const msg = JSON.parse(event.data);
            const response = await bridgeRouteCommand(msg);
            bridgeSend({ type: 'response', id: msg.id, ...response });
        } catch (e) {
            console.error('[StealthDOM] Bridge message error:', e);
        }
    };

    _bridgeWs.onclose = () => {
        console.log('[StealthDOM] Bridge connection closed');
        bridgeCleanup();
        bridgeScheduleReconnect();
    };

    _bridgeWs.onerror = (err) => {
        console.error('[StealthDOM] Bridge error');
    };
}

function bridgeSend(data) {
    if (_bridgeWs && _bridgeWs.readyState === WebSocket.OPEN) {
        _bridgeWs.send(JSON.stringify(data));
    }
}

function bridgeCleanup() {
    if (_bridgeHeartbeat) {
        clearInterval(_bridgeHeartbeat);
        _bridgeHeartbeat = null;
    }
}

function bridgeScheduleReconnect() {
    if (!_enabled) return;  // Don't reconnect when disabled
    clearTimeout(_bridgeReconnect);
    _bridgeReconnect = setTimeout(bridgeConnect, RECONNECT_INTERVAL);
}

/**
 * Route incoming bridge commands to either background handlers or content scripts.
 */
async function bridgeRouteCommand(msg) {
    // Reject commands if disabled
    if (!_enabled) {
        return { success: false, error: 'StealthDOM is disabled. Enable it from the extension popup.' };
    }

    const { action } = msg;

    // These actions are handled directly in the background script
    const bgActions = [
        'listTabs', 'newTab', 'closeTab', 'switchTab', 'reloadTab',
        'navigate', 'goBack', 'goForward',
        'captureScreenshot', 'captureFullPageScreenshot',
        'mouseMoveCDP', 'mouseClickCDP', 'mouseDownCDP', 'mouseUpCDP', 'mouseDragCDP', 'mouseWheelCDP',
        'getCookies', 'setCookie', 'deleteCookie', 'listCookieStores',
        'startNetCapture', 'stopNetCapture', 'getNetCapture', 'clearNetCapture',
        'newWindow', 'newIncognitoWindow', 'listWindows', 'closeWindow', 'resizeWindow',
        'executeScript', 'executeScriptAllFrames', 'listFrames',
        'enableBlock', 'disableBlock',
        'waitForUrl',
    ];

    try {
        if (bgActions.includes(action)) {
            return await handleBackgroundCommand(msg);
        } else {
            // Forward DOM commands to the active tab's content script
            return await bridgeForwardToContentScript(msg);
        }
    } catch (e) {
        return { success: false, error: e.message };
    }
}

/**
 * Forward a command to a content script via chrome.tabs.sendMessage.
 * Lazily injects the content script on first use per tab.
 */
async function bridgeForwardToContentScript(msg) {
    try {
        const targetId = msg.tabId;
        if (!targetId) {
            return { success: false, error: 'tabId required. Use browser_list_tabs to get tab IDs.' };
        }
        const tab = await chrome.tabs.get(targetId);

        // Can't inject into browser internal pages
        if (tab.url.startsWith('chrome://') || tab.url.startsWith('brave://') || tab.url.startsWith('edge://')) {
            return { success: false, error: `Cannot run commands on browser internal pages (${tab.url.split('/')[2]})` };
        }

        // Ensure content script is injected (no-op if already done for this tab)
        await ensureContentScriptInjected(targetId);

        // Build sendMessage options — target a specific frame.
        // Default to frameId 0 (top-level frame) when none specified.
        // Without this, sendMessage broadcasts to ALL frames and returns
        // whichever responds first — on SPAs with hidden iframes (tracking
        // pixels, OAuth, etc.), a hidden iframe can respond before the
        // main page, causing DOM queries to return wrong/empty results.
        const sendOpts = { frameId: 0 };
        if (msg.frameId !== undefined && msg.frameId !== null) {
            sendOpts.frameId = msg.frameId;
        }

        const contentMsg = { ...msg, target: 'content' };

        // Try targeted frame first, fall back to broadcast if no response.
        // This handles frameset pages (Gmail) where frame 0 may not have a
        // content script listener, while still defaulting to frame 0 for
        // SPAs (Twitter) that have hidden iframes.
        const result = await new Promise((resolve) => {
            const staleTip = " (If the extension was recently reloaded or the tab is unresponsive, use browser_reload to refresh the tab and re-inject the script)";
            chrome.tabs.sendMessage(targetId, contentMsg, sendOpts, (response) => {
                if (chrome.runtime.lastError) {
                    // Frame 0 had no content script — retry without frameId (broadcast)
                    if (msg.frameId === undefined || msg.frameId === null) {
                        chrome.tabs.sendMessage(targetId, contentMsg, {}, (fallbackResp) => {
                            if (chrome.runtime.lastError) {
                                resolve({ success: false, error: `Content script error: ${chrome.runtime.lastError.message}.${staleTip}` });
                            } else {
                                resolve(fallbackResp || { success: false, error: `No response from content script.${staleTip}` });
                            }
                        });
                    } else {
                        resolve({ success: false, error: `Content script error: ${chrome.runtime.lastError.message}.${staleTip}` });
                    }
                } else {
                    resolve(response || { success: false, error: `No response from content script.${staleTip}` });
                }
            });
        });
        return result;
    } catch (e) {
        return { success: false, error: `Forward failed: ${e.message}` };
    }
}

// Start bridge connection if enabled
if (_enabled) bridgeConnect();

// ==========================================
// Tab Management
// ==========================================

async function cmdListTabs() {
    const windows = await chrome.windows.getAll();
    const windowIncognito = {};
    windows.forEach(w => { windowIncognito[w.id] = w.incognito; });

    const tabs = await chrome.tabs.query({});
    return {
        success: true,
        data: tabs.map(t => ({
            id: t.id,
            url: t.url,
            title: t.title,
            active: t.active,
            windowId: t.windowId,
            cookieStoreId: t.cookieStoreId,
            incognito: windowIncognito[t.windowId] || false,
            index: t.index,
        }))
    };
}

async function cmdNewTab(url) {
    const tab = await chrome.tabs.create({ url: url || 'about:blank' });
    return {
        success: true,
        data: { tabId: tab.id, url: tab.url }
    };
}

async function cmdCloseTab(tabId) {
    if (!tabId) {
        return { success: false, error: 'tabId required' };
    }
    await chrome.tabs.remove(tabId);
    return { success: true };
}

async function cmdSwitchTab(tabId) {
    if (!tabId) {
        return { success: false, error: 'tabId required' };
    }
    await chrome.tabs.update(tabId, { active: true });
    // Also focus the window
    const tab = await chrome.tabs.get(tabId);
    await chrome.windows.update(tab.windowId, { focused: true });
    return { success: true };
}

async function cmdReloadTab(tabId) {
    if (!tabId) return { success: false, error: 'tabId required' };
    await chrome.tabs.reload(tabId);
    return { success: true };
}

// ==========================================
// Navigation
// ==========================================

async function cmdNavigate(url, tabId) {
    if (!url) return { success: false, error: 'url required' };
    if (!tabId) return { success: false, error: 'tabId required' };
    await chrome.tabs.update(tabId, { url });
    return { success: true };
}

async function cmdGoBack(tabId) {
    if (!tabId) return { success: false, error: 'tabId required' };
    await chrome.tabs.goBack(tabId);
    return { success: true };
}

async function cmdGoForward(tabId) {
    if (!tabId) return { success: false, error: 'tabId required' };
    await chrome.tabs.goForward(tabId);
    return { success: true };
}

// ==========================================
// Screenshots
// ==========================================

/**
 * CDP-based screenshot via chrome.debugger API.
 * 
 * Uses the Page.captureScreenshot CDP command, which renders directly from
 * the compositor pipeline — no window focus, no tab activation, no rate limits.
 * 
 * The chrome.debugger API is a built-in Manifest V3 extension API. It does NOT:
 * - Set navigator.webdriver (only --remote-debugging-port does that)
 * - Open a network port (no port scanning possible)
 * - Change the TLS fingerprint
 * 
 * The only visible side effect is a brief yellow infobar ("Extension is debugging
 * this browser") that appears during the attach/detach window (~100-300ms). This
 * is a browser chrome UI element — no page script can detect it, and it typically
 * appears on the automated tab's window, not the window the user is working in.
 * 
 * Failure modes (all handled with graceful fallback to captureVisibleTab):
 * - Another debugger is already attached to the tab (e.g., DevTools is open on it)
 * - Tab is a browser-internal page (chrome://, brave://, etc.) — already blocked upstream
 */
async function cmdCaptureScreenshotCDP(tabId) {
    const target = { tabId };
    try {
        await chrome.debugger.attach(target, '1.3');
        const result = await chrome.debugger.sendCommand(target, 'Page.captureScreenshot', {
            format: 'png',
            quality: 100,
            fromSurface: true,
        });
        await chrome.debugger.detach(target);
        return {
            success: true,
            data: {
                dataUrl: 'data:image/png;base64,' + result.data,
                format: 'png',
                tabId,
                method: 'cdp',
            }
        };
    } catch (e) {
        // Ensure detach on any error
        try { await chrome.debugger.detach(target); } catch (_) {}
        throw e; // Rethrow so caller can fall back to captureVisibleTab
    }
}

/**
 * CDP-based full-page screenshot.
 * 
 * Uses Page.getLayoutMetrics to measure the full document, then
 * Emulation.setDeviceMetricsOverride to expand the viewport to the full
 * page height, and Page.captureScreenshot with captureBeyondViewport to
 * capture everything in a single shot — no scrolling, no stitching.
 * 
 * For very tall pages (>16384px), Chrome may fail the single-shot capture
 * due to GPU texture limits. In that case, the caller falls back to the
 * scroll-stitch approach using captureVisibleTab.
 */
async function cmdCaptureFullPageScreenshotCDP(tabId, maxHeight = 20000) {
    const target = { tabId };
    try {
        await chrome.debugger.attach(target, '1.3');

        // Get full page dimensions
        const metrics = await chrome.debugger.sendCommand(target, 'Page.getLayoutMetrics');
        const contentHeight = Math.min(
            Math.ceil(metrics.contentSize.height),
            maxHeight
        );
        const contentWidth = Math.ceil(metrics.contentSize.width);

        // Override device metrics to render the full page in one viewport
        await chrome.debugger.sendCommand(target, 'Emulation.setDeviceMetricsOverride', {
            width: contentWidth,
            height: contentHeight,
            deviceScaleFactor: 1,
            mobile: false,
        });

        // Brief pause for re-layout
        await new Promise(r => setTimeout(r, 100));

        const result = await chrome.debugger.sendCommand(target, 'Page.captureScreenshot', {
            format: 'png',
            quality: 100,
            captureBeyondViewport: true,
            clip: { x: 0, y: 0, width: contentWidth, height: contentHeight, scale: 1 },
        });

        // Reset device metrics to original
        await chrome.debugger.sendCommand(target, 'Emulation.clearDeviceMetricsOverride');
        await chrome.debugger.detach(target);

        return {
            success: true,
            data: {
                dataUrl: 'data:image/png;base64,' + result.data,
                format: 'png',
                tabId,
                method: 'cdp',
                fullPage: true,
                dimensions: {
                    width: contentWidth,
                    height: contentHeight,
                    frames: 1,
                    maxHeight,
                    actualHeight: contentHeight,
                },
            }
        };
    } catch (e) {
        // Ensure detach + metrics reset on any error
        try { await chrome.debugger.sendCommand(target, 'Emulation.clearDeviceMetricsOverride'); } catch (_) {}
        try { await chrome.debugger.detach(target); } catch (_) {}
        throw e; // Rethrow so caller can fall back to scroll-stitch
    }
}

/**
 * Wrapper around captureVisibleTab that retries on quota errors.
 * Chrome limits captureVisibleTab to ~2 calls/sec. If we exceed that
 * (e.g., rapid full-page scroll loop) we back off and retry automatically.
 *
 * Includes an in-memory mutex so that only one captureVisibleTab call
 * can be in-flight at a time — prevents parallel MCP tool calls from
 * saturating the quota simultaneously.
 *
 * This is the FALLBACK path — only used when CDP (chrome.debugger) is
 * unavailable (e.g., DevTools is open on the target tab).
 */
let _screenshotLock = null; // Promise-based mutex

async function captureWithRetry(windowId, options, maxAttempts = 5) {
    // Wait for any in-flight screenshot to complete
    while (_screenshotLock) {
        await _screenshotLock;
    }

    let resolveLock;
    _screenshotLock = new Promise(r => { resolveLock = r; });

    try {
        let delay = 600; // ms — start above the 1-second quota window
        for (let attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
                return await chrome.tabs.captureVisibleTab(windowId, options);
            } catch (e) {
                if (e.message && e.message.includes('MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND') && attempt < maxAttempts) {
                    await new Promise(r => setTimeout(r, delay));
                    delay = Math.min(delay * 1.5, 3000); // cap at 3s
                    continue;
                }
                throw e;
            }
        }
    } finally {
        _screenshotLock = null;
        resolveLock();
    }
}

async function cmdCaptureScreenshot(tabId) {
    try {
        if (!tabId) return { success: false, error: 'tabId required' };

        // Primary path: CDP via chrome.debugger (no focus-stealing, no quota)
        try {
            return await cmdCaptureScreenshotCDP(tabId);
        } catch (cdpError) {
            // CDP unavailable (DevTools open on this tab, or internal page)
            // Fall back to captureVisibleTab
            console.log('[StealthDOM] CDP screenshot unavailable, falling back to captureVisibleTab:', cdpError.message);
        }

        // Fallback path: captureVisibleTab (requires focus)
        // Remember which window was focused so we can restore it after capture
        const [prevWindow] = await chrome.windows.getAll({ populate: false })
            .then(ws => ws.filter(w => w.focused));
        const prevWindowId = prevWindow?.id;

        // Get the target tab so we know which window it's in
        const tab = await chrome.tabs.get(tabId);

        // Remember this window's state BEFORE we force it to the front
        const targetWindow = await chrome.windows.get(tab.windowId);
        const wasMinimized = targetWindow.state === 'minimized';

        await chrome.tabs.update(tabId, { active: true });
        await chrome.windows.update(tab.windowId, { focused: true, state: 'normal' });
        // Brief delay to let the tab render after activation
        await new Promise(r => setTimeout(r, 150));

        const dataUrl = await captureWithRetry(tab.windowId, {
            format: 'png',
            quality: 90,
        });

        // If the window was minimized before we stole focus, put it back
        if (wasMinimized) {
            chrome.windows.update(tab.windowId, { state: 'minimized' }).catch(() => {});
        }

        return {
            success: true,
            data: {
                dataUrl,
                format: 'png',
                tabId: tabId,
                method: 'captureVisibleTab',
            }
        };
    } catch (e) {
        return { success: false, error: `Screenshot failed: ${e.message}` };
    }
}

/**
 * Full-page screenshot — tries CDP single-shot first, falls back to scroll-and-stitch.
 * 
 * CDP path: Uses Page.captureScreenshot with captureBeyondViewport — captures the
 * entire page in one shot without scrolling. No focus stealing, no rate limits.
 * 
 * Fallback path (captureVisibleTab scroll-stitch):
 * 1. Measures the full scrollHeight and viewport dimensions
 * 2. Detects and hides sticky/fixed elements during middle frames
 * 3. Scrolls through the page, capturing each viewport chunk
 * 4. Stitches all frames into a single PNG using OffscreenCanvas
 */
async function cmdCaptureFullPageScreenshot(tabId, maxHeight = 20000) {
    try {
        if (!tabId) return { success: false, error: 'tabId required' };

        // Primary path: CDP full-page capture (no scrolling, no focus)
        try {
            return await cmdCaptureFullPageScreenshotCDP(tabId, maxHeight);
        } catch (cdpError) {
            console.log('[StealthDOM] CDP full-page screenshot unavailable, falling back to scroll-stitch:', cdpError.message);
        }

        // Fallback path: scroll-and-stitch via captureVisibleTab

        // Remember which window was focused so we can restore it after capture
        const [prevWindow] = await chrome.windows.getAll({ populate: false })
            .then(ws => ws.filter(w => w.focused));
        const prevWindowId = prevWindow?.id;

        // Activate tab and focus window (required for captureVisibleTab)
        const tab = await chrome.tabs.get(tabId);
        // Remember this window's state BEFORE we force it to the front
        const targetWindow = await chrome.windows.get(tab.windowId);
        const wasMinimized = targetWindow.state === 'minimized';

        await chrome.tabs.update(tabId, { active: true });
        await chrome.windows.update(tab.windowId, { focused: true, state: 'normal' });
        await new Promise(r => setTimeout(r, 200));

        // Step 1: Measure page dimensions
        const measureResults = await chrome.scripting.executeScript({
            target: { tabId },
            world: 'MAIN',
            func: () => ({
                scrollHeight: document.documentElement.scrollHeight,
                scrollWidth: document.documentElement.scrollWidth,
                viewportHeight: window.innerHeight,
                viewportWidth: window.innerWidth,
                currentScrollY: window.scrollY,
                devicePixelRatio: window.devicePixelRatio || 1,
            }),
        });

        if (!measureResults || !measureResults[0]) {
            return { success: false, error: 'Failed to measure page dimensions' };
        }

        const dims = measureResults[0].result;
        const { viewportHeight, viewportWidth, devicePixelRatio } = dims;
        // Cap the scroll height to prevent memory issues
        const totalHeight = Math.min(dims.scrollHeight, maxHeight);
        const frameCount = Math.ceil(totalHeight / viewportHeight);
        const MAX_FRAMES = 50;

        if (frameCount > MAX_FRAMES) {
            return { success: false, error: `Page too tall: ${totalHeight}px would need ${frameCount} frames (max ${MAX_FRAMES}). Increase maxHeight or reduce page size.` };
        }

        // If the page fits in one viewport, just use regular screenshot
        if (frameCount <= 1) {
            return await cmdCaptureScreenshot(tabId);
        }

        // Step 2: Scroll to top and detect sticky elements
        await chrome.scripting.executeScript({
            target: { tabId },
            world: 'MAIN',
            func: () => {
                window.scrollTo(0, 0);
                // Find and tag sticky/fixed elements for later hiding
                const stickyEls = [];
                const allEls = document.querySelectorAll('*');
                for (const el of allEls) {
                    const style = window.getComputedStyle(el);
                    if (style.position === 'fixed' || style.position === 'sticky') {
                        // Only hide elements that are visible and take up space
                        if (el.offsetHeight > 0 && el.offsetWidth > 0) {
                            el.dataset.__stealthdomOrigPos = style.position;
                            el.dataset.__stealthdomOrigVis = el.style.visibility || '';
                            stickyEls.push(el);
                        }
                    }
                }
                window.__stealthdomStickyCount = stickyEls.length;
            },
        });
        await new Promise(r => setTimeout(r, 200));

        // Step 3: Capture loop
        const frames = [];
        for (let i = 0; i < frameCount; i++) {
            const scrollY = i * viewportHeight;
            const isFirst = i === 0;
            const isLast = i === frameCount - 1;

            // Scroll to position
            await chrome.scripting.executeScript({
                target: { tabId },
                world: 'MAIN',
                func: (y, hideSticky) => {
                    window.scrollTo(0, y);
                    // Hide sticky elements during middle frames to avoid duplication
                    if (hideSticky) {
                        const els = document.querySelectorAll('[data-__stealthdom-orig-pos]');
                        els.forEach(el => { el.style.visibility = 'hidden'; });
                    } else {
                        // Restore for first/last frames
                        const els = document.querySelectorAll('[data-__stealthdom-orig-pos]');
                        els.forEach(el => {
                            el.style.visibility = el.dataset.__stealthdomOrigVis || '';
                        });
                    }
                },
                args: [scrollY, !isFirst && !isLast],
            });

            // Wait for lazy content to hydrate
            await new Promise(r => setTimeout(r, 150));

            // Capture this frame
            const dataUrl = await captureWithRetry(tab.windowId, {
                format: 'png',
                quality: 100,
            });
            frames.push({ dataUrl, scrollY });
        }

        // Step 4: Restore sticky elements and original scroll position
        await chrome.scripting.executeScript({
            target: { tabId },
            world: 'MAIN',
            func: (origScrollY) => {
                const els = document.querySelectorAll('[data-__stealthdom-orig-pos]');
                els.forEach(el => {
                    el.style.visibility = el.dataset.__stealthdomOrigVis || '';
                    delete el.dataset.__stealthdomOrigPos;
                    delete el.dataset.__stealthdomOrigVis;
                });
                window.scrollTo(0, origScrollY);
            },
            args: [dims.currentScrollY],
        });

        // Step 5: Stitch frames using OffscreenCanvas
        // The actual pixel dimensions of each capture depend on devicePixelRatio
        const pixelWidth = viewportWidth * devicePixelRatio;
        const pixelViewportHeight = viewportHeight * devicePixelRatio;

        // Calculate the actual total pixel height
        // Last frame may be a partial viewport
        const lastFrameContentHeight = totalHeight - (frameCount - 1) * viewportHeight;
        const pixelTotalHeight = ((frameCount - 1) * viewportHeight + lastFrameContentHeight) * devicePixelRatio;

        const canvas = new OffscreenCanvas(pixelWidth, pixelTotalHeight);
        const ctx = canvas.getContext('2d');

        for (let i = 0; i < frames.length; i++) {
            const frame = frames[i];
            // Convert data URL to blob to ImageBitmap
            const resp = await fetch(frame.dataUrl);
            const blob = await resp.blob();
            const bmp = await createImageBitmap(blob);

            const drawY = i * pixelViewportHeight;

            if (i === frames.length - 1) {
                // Last frame: only draw the portion that contains new content
                // (avoid overlapping with the previous frame)
                const remainingHeight = pixelTotalHeight - drawY;
                // The captured image is a full viewport, but we only need the bottom portion
                const sourceY = bmp.height - remainingHeight;
                if (sourceY > 0) {
                    ctx.drawImage(bmp, 0, sourceY, bmp.width, remainingHeight, 0, drawY, bmp.width, remainingHeight);
                } else {
                    ctx.drawImage(bmp, 0, drawY);
                }
            } else {
                ctx.drawImage(bmp, 0, drawY);
            }
            bmp.close();
        }

        // Export as PNG
        const resultBlob = await canvas.convertToBlob({ type: 'image/png' });

        // Convert blob to data URL
        const arrayBuffer = await resultBlob.arrayBuffer();
        const uint8 = new Uint8Array(arrayBuffer);
        // Chunk-spread approach: 8192 args is well under V8 stack limit (~125k)
        // and orders of magnitude faster than char-by-char concatenation.
        const CHUNK = 8192;
        let binary = '';
        for (let i = 0; i < uint8.length; i += CHUNK) {
            binary += String.fromCharCode(...uint8.subarray(i, i + CHUNK));
        }
        const base64 = btoa(binary);
        const resultDataUrl = `data:image/png;base64,${base64}`;

        // If the window was minimized before we stole focus, put it back
        if (wasMinimized) {
            chrome.windows.update(tab.windowId, { state: 'minimized' }).catch(() => {});
        }

        return {
            success: true,
            data: {
                dataUrl: resultDataUrl,
                format: 'png',
                tabId: tabId,
                method: 'captureVisibleTab',
                fullPage: true,
                dimensions: {
                    width: pixelWidth,
                    height: pixelTotalHeight,
                    frames: frameCount,
                    maxHeight: maxHeight,
                    actualHeight: totalHeight,
                },
            },
        };
    } catch (e) {
        // Best-effort cleanup of sticky element markers
        try {
            await chrome.scripting.executeScript({
                target: { tabId },
                world: 'MAIN',
                func: () => {
                    const els = document.querySelectorAll('[data-__stealthdom-orig-pos]');
                    els.forEach(el => {
                        el.style.visibility = el.dataset.__stealthdomOrigVis || '';
                        delete el.dataset.__stealthdomOrigPos;
                        delete el.dataset.__stealthdomOrigVis;
                    });
                },
            });
        } catch (_) { /* ignore cleanup errors */ }
        return { success: false, error: `Full-page screenshot failed: ${e.message}` };
    }
}

// ==========================================
// Native Mouse (CDP) — isTrusted: true events
// ==========================================

/**
 * Shared helper: attach chrome.debugger, run an async function, detach.
 * Reuses the same lifecycle pattern as CDP screenshots.
 * @param {number} tabId
 * @param {function(target): Promise<any>} fn - receives {tabId} target
 * @returns {Promise<any>}
 */
async function withDebugger(tabId, fn) {
    const target = { tabId };
    try {
        await chrome.debugger.attach(target, '1.3');
        const result = await fn(target);
        await chrome.debugger.detach(target);
        return result;
    } catch (e) {
        try { await chrome.debugger.detach(target); } catch (_) {}
        throw e;
    }
}

/**
 * Map button name to CDP button enum and bitmask.
 * CDP uses: 'none'=0, 'left'=1, 'middle'=2, 'right'=4 for buttons bitmask
 * and 'left', 'middle', 'right' for button name.
 */
function cdpButtonInfo(button = 'left') {
    switch (button) {
        case 'right':  return { button: 'right',  buttons: 2 };
        case 'middle': return { button: 'middle', buttons: 4 };
        default:       return { button: 'left',   buttons: 1 };
    }
}

/**
 * Small random jitter for mouse movements (±1-3px).
 * Makes trajectories look more human.
 */
function jitter(val, amount = 2) {
    return val + (Math.random() * amount * 2 - amount);
}

/**
 * CDP mouse move: interpolate from origin (0,0) to (x,y) with realistic steps.
 * Each intermediate point gets small random jitter.
 */
async function cmdMouseMoveCDP(tabId, x, y, steps = 10, duration = 300) {
    if (!tabId) return { success: false, error: 'tabId required' };
    if (x === undefined || y === undefined) return { success: false, error: 'x and y required' };

    try {
        return await withDebugger(tabId, async (target) => {
            const stepDelay = Math.max(1, Math.floor(duration / steps));

            for (let i = 1; i <= steps; i++) {
                const t = i / steps;
                const cx = i < steps ? jitter(x * t) : x;
                const cy = i < steps ? jitter(y * t) : y;

                await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
                    type: 'mouseMoved',
                    x: Math.round(cx),
                    y: Math.round(cy),
                });

                if (i < steps) {
                    await new Promise(r => setTimeout(r, stepDelay));
                }
            }

            return {
                success: true,
                data: { x, y, steps, duration, method: 'cdp' }
            };
        });
    } catch (e) {
        return { success: false, error: `Mouse move failed: ${e.message}` };
    }
}

/**
 * CDP mouse click: move to coords, press, release.
 * Supports left/right/middle and double-click via clickCount.
 */
async function cmdMouseClickCDP(tabId, x, y, button = 'left', clickCount = 1) {
    if (!tabId) return { success: false, error: 'tabId required' };
    if (x === undefined || y === undefined) return { success: false, error: 'x and y required' };

    const btn = cdpButtonInfo(button);

    try {
        return await withDebugger(tabId, async (target) => {
            // Move to position first
            await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
                type: 'mouseMoved',
                x, y,
            });
            await new Promise(r => setTimeout(r, 20));

            // Press
            await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
                type: 'mousePressed',
                x, y,
                button: btn.button,
                buttons: btn.buttons,
                clickCount,
            });
            await new Promise(r => setTimeout(r, 30 + Math.random() * 50));

            // Release
            await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
                type: 'mouseReleased',
                x, y,
                button: btn.button,
                buttons: 0,
                clickCount,
            });

            return {
                success: true,
                data: { x, y, button, clickCount, method: 'cdp' }
            };
        });
    } catch (e) {
        return { success: false, error: `Mouse click failed: ${e.message}` };
    }
}

/**
 * CDP mouse down: press and hold at coordinates.
 * Use with mouseUpCDP for atomic hold/release scenarios.
 */
async function cmdMouseDownCDP(tabId, x, y, button = 'left') {
    if (!tabId) return { success: false, error: 'tabId required' };
    if (x === undefined || y === undefined) return { success: false, error: 'x and y required' };

    const btn = cdpButtonInfo(button);

    try {
        return await withDebugger(tabId, async (target) => {
            await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
                type: 'mouseMoved',
                x, y,
            });
            await new Promise(r => setTimeout(r, 10));

            await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
                type: 'mousePressed',
                x, y,
                button: btn.button,
                buttons: btn.buttons,
                clickCount: 1,
            });

            return {
                success: true,
                data: { x, y, button, method: 'cdp' }
            };
        });
    } catch (e) {
        return { success: false, error: `Mouse down failed: ${e.message}` };
    }
}

/**
 * CDP mouse up: release button at coordinates.
 * Completes a hold started by mouseDownCDP.
 */
async function cmdMouseUpCDP(tabId, x, y, button = 'left') {
    if (!tabId) return { success: false, error: 'tabId required' };
    if (x === undefined || y === undefined) return { success: false, error: 'x and y required' };

    const btn = cdpButtonInfo(button);

    try {
        return await withDebugger(tabId, async (target) => {
            await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
                type: 'mouseReleased',
                x, y,
                button: btn.button,
                buttons: 0,
                clickCount: 1,
            });

            return {
                success: true,
                data: { x, y, button, method: 'cdp' }
            };
        });
    } catch (e) {
        return { success: false, error: `Mouse up failed: ${e.message}` };
    }
}

/**
 * CDP mouse drag: full drag sequence in a single debugger session.
 * Press at start, interpolate movement to end, release.
 */
async function cmdMouseDragCDP(tabId, startX, startY, endX, endY, steps = 20, duration = 500) {
    if (!tabId) return { success: false, error: 'tabId required' };
    if (startX === undefined || startY === undefined || endX === undefined || endY === undefined) {
        return { success: false, error: 'startX, startY, endX, endY required' };
    }

    try {
        return await withDebugger(tabId, async (target) => {
            const stepDelay = Math.max(1, Math.floor(duration / steps));

            // Move to start position
            await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
                type: 'mouseMoved',
                x: startX,
                y: startY,
            });
            await new Promise(r => setTimeout(r, 30));

            // Press at start
            await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
                type: 'mousePressed',
                x: startX,
                y: startY,
                button: 'left',
                buttons: 1,
                clickCount: 1,
            });
            await new Promise(r => setTimeout(r, 30));

            // Interpolated move from start to end
            for (let i = 1; i <= steps; i++) {
                const t = i / steps;
                const cx = i < steps ? jitter(startX + (endX - startX) * t) : endX;
                const cy = i < steps ? jitter(startY + (endY - startY) * t) : endY;

                await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
                    type: 'mouseMoved',
                    x: Math.round(cx),
                    y: Math.round(cy),
                    buttons: 1,
                });

                await new Promise(r => setTimeout(r, stepDelay));
            }

            // Release at end
            await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
                type: 'mouseReleased',
                x: endX,
                y: endY,
                button: 'left',
                buttons: 0,
                clickCount: 1,
            });

            return {
                success: true,
                data: { startX, startY, endX, endY, steps, duration, method: 'cdp' }
            };
        });
    } catch (e) {
        return { success: false, error: `Mouse drag failed: ${e.message}` };
    }
}

/**
 * CDP mouse wheel: dispatch native scroll wheel event at coordinates.
 */
async function cmdMouseWheelCDP(tabId, x, y, deltaX = 0, deltaY = 0) {
    if (!tabId) return { success: false, error: 'tabId required' };
    if (x === undefined || y === undefined) return { success: false, error: 'x and y required' };

    try {
        return await withDebugger(tabId, async (target) => {
            await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
                type: 'mouseWheel',
                x, y,
                deltaX: deltaX || 0,
                deltaY: deltaY || 0,
            });

            return {
                success: true,
                data: { x, y, deltaX, deltaY, method: 'cdp' }
            };
        });
    } catch (e) {
        return { success: false, error: `Mouse wheel failed: ${e.message}` };
    }
}

// ==========================================
// Cookies
// ==========================================

async function cmdGetCookies(url, tabId, storeId) {
    if (!url) {
        return { success: false, error: 'url required' };
    }
    const query = { url };
    if (storeId) {
        query.storeId = storeId;
    } else if (tabId) {
        const tab = await chrome.tabs.get(tabId);
        if (tab && tab.cookieStoreId) {
            query.storeId = tab.cookieStoreId;
        }
    }
    const cookies = await chrome.cookies.getAll(query);
    return {
        success: true,
        data: cookies.map(c => ({
            name: c.name,
            value: c.value,
            domain: c.domain,
            path: c.path,
            secure: c.secure,
            httpOnly: c.httpOnly,
            expirationDate: c.expirationDate,
        }))
    };
}

async function cmdSetCookie(details) {
    if (!details || !details.url) {
        return { success: false, error: 'details with url required' };
    }
    const cookie = await chrome.cookies.set(details);
    return { success: true, data: cookie };
}

async function cmdDeleteCookie(url, name) {
    if (!url || !name) {
        return { success: false, error: 'url and name required' };
    }
    await chrome.cookies.remove({ url, name });
    return { success: true };
}

async function cmdListCookieStores() {
    const stores = await chrome.cookies.getAllCookieStores();
    return { success: true, data: stores };
}

// ==========================================
// ==========================================
// Script Execution in MAIN world (arbitrary JS)
// ==========================================

async function cmdExecuteScript(code, tabId, world) {
    try {
        if (!tabId) return { success: false, error: 'tabId required' };
        const targetId = tabId;
        // Default to MAIN world for backward compatibility.
        const targetWorld = (world === 'ISOLATED') ? 'ISOLATED' : 'MAIN';

        const results = await chrome.scripting.executeScript({
            target: { tabId: targetId },
            world: targetWorld,
            func: (codeStr) => {
                try {
                    // Try eval first — handles expressions like 'document.title', '2+2'
                    // If the code contains 'return', eval will throw SyntaxError,
                    // so we fall back to new Function() which supports return statements.
                    let result;
                    try {
                        result = (0, eval)(codeStr);
                    } catch (evalErr) {
                        if (evalErr instanceof SyntaxError && codeStr.includes('return')) {
                            const fn = new Function(codeStr);
                            result = fn();
                        } else {
                            throw evalErr;
                        }
                    }
                    // Handle non-serializable results
                    if (result instanceof HTMLElement) {
                        return {
                            tagName: result.tagName,
                            id: result.id,
                            className: result.className,
                            innerText: (result.innerText || '').substring(0, 1000),
                        };
                    }
                    if (result === undefined) return null;
                    if (typeof result === 'function') return '[function]';
                    return result;
                } catch (e) {
                    return { __error: true, message: e.message, stack: e.stack };
                }
            },
            args: [code],
        });

        if (results && results.length > 0) {
            const data = results[0].result;
            if (data && data.__error) {
                // If eval was blocked (Trusted Types or CSP), use script tag injection
                if (data.message && (data.message.includes('Trusted Type') || data.message.includes('unsafe-eval'))) {
                    return cmdExecuteScriptViaTag(code, targetId);
                }
                return { success: false, error: `JS Error: ${data.message}` };
            }
            return { success: true, data };
        }
        return { success: false, error: 'No result from script execution' };
    } catch (e) {
        return { success: false, error: `executeScript failed: ${e.message}` };
    }
}

// Fallback: inject a <script> tag into the page from the ISOLATED world.
// The ISOLATED world can create DOM elements freely (no Trusted Types apply
// to extension-injected content scripts), and the <script> tag runs in the
// MAIN world automatically. Result is passed back via a data attribute.
async function cmdExecuteScriptViaTag(code, tabId) {
    try {
        const results = await chrome.scripting.executeScript({
            target: { tabId },
            world: 'ISOLATED',
            func: (codeStr) => {
                return new Promise((resolve) => {
                    const resultId = '__stealth_result_' + Date.now();
                    // Wrap code to capture result and store on a temp element
                    const wrappedCode = `
                        try {
                            const __r = (function(){ return ${codeStr} })();
                            const __el = document.getElementById('${resultId}');
                            if (__el) __el.dataset.result = JSON.stringify(
                                __r === undefined ? null :
                                __r instanceof HTMLElement ? {tagName:__r.tagName, id:__r.id, className:__r.className, innerText:(__r.innerText||'').substring(0,1000)} :
                                typeof __r === 'function' ? '[function]' : __r
                            );
                        } catch(e) {
                            const __el = document.getElementById('${resultId}');
                            if (__el) __el.dataset.result = JSON.stringify({__error:true, message:e.message});
                        }
                    `;
                    // Create a hidden div to receive the result
                    const div = document.createElement('div');
                    div.id = resultId;
                    div.style.display = 'none';
                    document.documentElement.appendChild(div);

                    // Inject script tag (runs in MAIN world)
                    const script = document.createElement('script');
                    script.textContent = wrappedCode;
                    document.documentElement.appendChild(script);
                    script.remove();

                    // Read result synchronously (script runs sync)
                    const resultStr = div.dataset.result;
                    div.remove();

                    if (resultStr) {
                        try {
                            const parsed = JSON.parse(resultStr);
                            if (parsed && parsed.__error) {
                                resolve({ __error: true, message: parsed.message });
                            } else {
                                resolve(parsed);
                            }
                        } catch (e) {
                            resolve(resultStr);
                        }
                    } else {
                        resolve(null);
                    }
                });
            },
            args: [code],
        });

        if (results && results.length > 0) {
            const data = results[0].result;
            if (data && data.__error) {
                return { success: false, error: `JS Error: ${data.message}` };
            }
            return { success: true, data };
        }
        return { success: false, error: 'No result from script tag execution' };
    } catch (e) {
        return { success: false, error: `executeScript (tag fallback) failed: ${e.message}` };
    }
}

// ==========================================
// Frame Enumeration (cross-frame support)
// ==========================================

/**
 * List all frames in a tab — discovers <frame>, <iframe>, and frameset content.
 * Returns { frameIndex, url, title, hasBody } for each frame.
 */
async function cmdListFrames(tabId) {
    try {
        if (!tabId) return { success: false, error: 'tabId required' };
        const results = await chrome.scripting.executeScript({
            target: { tabId, allFrames: true },
            world: 'MAIN',
            func: () => ({
                url: location.href,
                title: document.title || '',
                hasBody: !!document.body,
                tagName: document.documentElement?.tagName || '',
                isFrameset: !!document.querySelector('frameset'),
                elementCount: document.querySelectorAll('*').length,
            }),
        });
        if (!results || results.length === 0) {
            return { success: false, error: 'No frames found (page may not be loaded)' };
        }
        return {
            success: true,
            data: {
                frameCount: results.length,
                frames: results.map((r, i) => ({
                    frameIndex: i,
                    frameId: r.frameId ?? null,
                    ...r.result,
                })),
            },
        };
    } catch (e) {
        return { success: false, error: `listFrames failed: ${e.message}` };
    }
}

/**
 * Execute JavaScript in ALL frames of a tab.
 * Returns results from every frame — useful for finding content in
 * framesets, cross-origin iframes, or embedded widgets.
 */
async function cmdExecuteScriptAllFrames(code, tabId, world) {
    try {
        if (!tabId) return { success: false, error: 'tabId required' };
        const targetWorld = (world === 'ISOLATED') ? 'ISOLATED' : 'MAIN';

        const results = await chrome.scripting.executeScript({
            target: { tabId, allFrames: true },
            world: targetWorld,
            func: (codeStr) => {
                try {
                    let result;
                    try {
                        result = (0, eval)(codeStr);
                    } catch (evalErr) {
                        if (evalErr instanceof SyntaxError && codeStr.includes('return')) {
                            const fn = new Function(codeStr);
                            result = fn();
                        } else {
                            throw evalErr;
                        }
                    }
                    if (result instanceof HTMLElement) {
                        return {
                            tagName: result.tagName,
                            id: result.id,
                            className: result.className,
                            innerText: (result.innerText || '').substring(0, 1000),
                        };
                    }
                    if (result === undefined) return null;
                    if (typeof result === 'function') return '[function]';
                    return result;
                } catch (e) {
                    return { __error: true, message: e.message };
                }
            },
            args: [code],
        });

        if (!results || results.length === 0) {
            return { success: false, error: 'No results from any frame' };
        }

        // Check if ANY frame hit Trusted Types — if so, retry ALL frames via
        // script tag injection (ISOLATED world → <script> tag → MAIN world).
        // This matches the fallback in cmdExecuteScript → cmdExecuteScriptViaTag.
        const hasTrustedTypeError = results.some(r =>
            r.result && r.result.__error &&
            r.result.message && (r.result.message.includes('Trusted Type') ||
                                  r.result.message.includes('unsafe-eval'))
        );

        if (hasTrustedTypeError && targetWorld === 'MAIN') {
            return await cmdExecuteScriptAllFramesViaTag(code, tabId);
        }

        return {
            success: true,
            data: {
                frameCount: results.length,
                results: results.map((r, i) => ({
                    frameIndex: i,
                    frameId: r.frameId ?? null,
                    result: r.result,
                })),
            },
        };
    } catch (e) {
        return { success: false, error: `executeScriptAllFrames failed: ${e.message}` };
    }
}

/**
 * Fallback for executeScriptAllFrames on pages with Trusted Types (e.g., Gmail).
 * Injects a <script> tag from the ISOLATED world into each frame, which runs
 * in the MAIN world automatically — bypassing Trusted Types restrictions.
 */
async function cmdExecuteScriptAllFramesViaTag(code, tabId) {
    try {
        const results = await chrome.scripting.executeScript({
            target: { tabId, allFrames: true },
            world: 'ISOLATED',
            func: (codeStr) => {
                return new Promise((resolve) => {
                    const resultId = '__stealth_result_' + Date.now() + '_' + Math.random().toString(36).slice(2, 6);
                    const wrappedCode = `
                        try {
                            const __r = (function(){ return ${codeStr} })();
                            const __el = document.getElementById('${resultId}');
                            if (__el) __el.dataset.result = JSON.stringify(
                                __r === undefined ? null :
                                __r instanceof HTMLElement ? {tagName:__r.tagName, id:__r.id, className:__r.className, innerText:(__r.innerText||'').substring(0,1000)} :
                                typeof __r === 'function' ? '[function]' : __r
                            );
                        } catch(e) {
                            const __el = document.getElementById('${resultId}');
                            if (__el) __el.dataset.result = JSON.stringify({__error:true, message:e.message});
                        }
                    `;

                    const div = document.createElement('div');
                    div.id = resultId;
                    div.style.display = 'none';
                    document.documentElement.appendChild(div);

                    const script = document.createElement('script');
                    script.textContent = wrappedCode;
                    document.documentElement.appendChild(script);
                    script.remove();

                    const resultStr = div.dataset.result;
                    div.remove();

                    if (resultStr) {
                        try {
                            const parsed = JSON.parse(resultStr);
                            resolve(parsed);
                        } catch (e) {
                            resolve(resultStr);
                        }
                    } else {
                        resolve(null);
                    }
                });
            },
            args: [code],
        });

        if (!results || results.length === 0) {
            return { success: false, error: 'No results from any frame (tag fallback)' };
        }

        return {
            success: true,
            data: {
                frameCount: results.length,
                results: results.map((r, i) => ({
                    frameIndex: i,
                    frameId: r.frameId ?? null,
                    result: r.result,
                })),
            },
        };
    } catch (e) {
        return { success: false, error: `executeScriptAllFrames (tag fallback) failed: ${e.message}` };
    }
}

// ==========================================
// Window Management
// ==========================================

async function cmdNewWindow(url) {
    try {
        const createOpts = {};
        if (url) createOpts.url = url;
        const win = await chrome.windows.create(createOpts);
        return {
            success: true,
            data: {
                windowId: win.id,
                type: win.type,
                incognito: win.incognito,
                tabs: win.tabs ? win.tabs.map(t => ({ id: t.id, url: t.url || url || 'about:blank' })) : [],
            },
        };
    } catch (e) {
        return { success: false, error: `newWindow failed: ${e.message}` };
    }
}

async function cmdNewIncognitoWindow(url) {
    try {
        const createOpts = { incognito: true };
        if (url) createOpts.url = url;
        const win = await chrome.windows.create(createOpts);
        return {
            success: true,
            data: {
                windowId: win.id,
                type: win.type,
                incognito: win.incognito,
                tabs: win.tabs ? win.tabs.map(t => ({ id: t.id, url: t.url || url || 'about:blank' })) : [],
            },
        };
    } catch (e) {
        return { success: false, error: `newIncognitoWindow failed: ${e.message}` };
    }
}

async function cmdListWindows() {
    try {
        const windows = await chrome.windows.getAll({ populate: true });
        return {
            success: true,
            data: windows.map(w => ({
                id: w.id,
                type: w.type,
                state: w.state,
                incognito: w.incognito,
                focused: w.focused,
                width: w.width,
                height: w.height,
                left: w.left,
                top: w.top,
                tabCount: w.tabs ? w.tabs.length : 0,
            })),
        };
    } catch (e) {
        return { success: false, error: `listWindows failed: ${e.message}` };
    }
}

async function cmdCloseWindow(windowId) {
    try {
        await chrome.windows.remove(windowId);
        return { success: true };
    } catch (e) {
        return { success: false, error: `closeWindow failed: ${e.message}` };
    }
}

async function cmdResizeWindow(windowId, width, height, left, top, state) {
    try {
        const updateInfo = {};
        if (width) updateInfo.width = width;
        if (height) updateInfo.height = height;
        if (left !== undefined) updateInfo.left = left;
        if (top !== undefined) updateInfo.top = top;
        if (state) updateInfo.state = state;
        const win = await chrome.windows.update(windowId, updateInfo);
        return {
            success: true,
            data: { width: win.width, height: win.height, left: win.left, top: win.top, state: win.state },
        };
    } catch (e) {
        return { success: false, error: `resizeWindow failed: ${e.message}` };
    }
}


// ==========================================
// URL Waiting
// ==========================================

/**
 * Wait for a tab's URL to match a pattern.
 * Uses chrome.tabs.onUpdated for reliable SPA navigation detection.
 * Also checks the current URL immediately in case it already matches.
 *
 * @param {number} tabId  - Target tab ID
 * @param {string} pattern - String substring OR /regex/ pattern (e.g., '/checkout/')
 * @param {number} timeout - Max wait in milliseconds (default 10000)
 */
async function cmdWaitForUrl(tabId, pattern, timeout = 10000) {
    if (!tabId) return { success: false, error: 'tabId required' };
    if (!pattern) return { success: false, error: 'pattern required' };

    function urlMatches(url) {
        if (!url) return false;
        // Regex pattern: surrounded by /
        if (typeof pattern === 'string' && pattern.startsWith('/') && pattern.lastIndexOf('/') > 0) {
            try {
                const lastSlash = pattern.lastIndexOf('/');
                const flags = pattern.slice(lastSlash + 1);
                const body = pattern.slice(1, lastSlash);
                return new RegExp(body, flags).test(url);
            } catch (e) {
                // Fall through to substring match
            }
        }
        return url.includes(String(pattern));
    }

    return new Promise((resolve) => {
        const timer = setTimeout(() => {
            chrome.tabs.onUpdated.removeListener(listener);
            resolve({ success: false, error: `Timeout (${timeout}ms) waiting for URL matching: ${pattern}` });
        }, timeout);

        function listener(updatedTabId, changeInfo, tab) {
            if (updatedTabId !== tabId) return;
            const url = changeInfo.url || tab.url || '';
            if (urlMatches(url)) {
                clearTimeout(timer);
                chrome.tabs.onUpdated.removeListener(listener);
                resolve({ success: true, data: { url } });
            }
        }

        chrome.tabs.onUpdated.addListener(listener);

        // Check current URL immediately (in case it already matches)
        chrome.tabs.get(tabId, (tab) => {
            if (chrome.runtime.lastError) return;
            if (tab && urlMatches(tab.url)) {
                clearTimeout(timer);
                chrome.tabs.onUpdated.removeListener(listener);
                resolve({ success: true, data: { url: tab.url } });
            }
        });
    });
}

// ==========================================
// Helpers
// ==========================================

// All commands require an explicit tabId for reliable multi-window, multi-browser targeting.
// Use browser_list_tabs() to discover tab virtualIds.

console.log('[StealthDOM] Service worker started (bridge mode)');
