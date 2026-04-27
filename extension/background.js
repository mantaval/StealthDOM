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
    }).catch(err => {
        console.warn('[StealthDOM] Failed to set CSP stripping rule:', err);
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

let _netCapture = [];
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
                raw: details.requestBody.raw ? details.requestBody.raw.map(r => ({
                    bytes: r.bytes ? r.bytes.byteLength : 0,
                })) : null,
                formData: details.requestBody.formData || null,
            } : null,
        });
    },
    {
        urls: ['<all_urls>']
    },
    ['requestBody']
);

// Also capture response headers
chrome.webRequest.onHeadersReceived.addListener(
    (details) => {
        if (!_netCaptureActive) return;
        // Find matching request and add response info
        const match = _netCapture.find(r => r.url === details.url && !r.responseHeaders);
        if (match) {
            match.statusCode = details.statusCode;
            match.responseHeaders = {};
            for (const h of (details.responseHeaders || [])) {
                match.responseHeaders[h.name.toLowerCase()] = h.value;
            }
        }
    },
    {
        urls: ['<all_urls>']
    },
    ['responseHeaders']
);

// Capture request headers (auth tokens, content-type, etc.)
chrome.webRequest.onBeforeSendHeaders.addListener(
    (details) => {
        if (!_netCaptureActive) return;
        const match = _netCapture.find(r => r.url === details.url && !r.requestHeaders);
        if (match) {
            match.requestHeaders = {};
            for (const h of (details.requestHeaders || [])) {
                match.requestHeaders[h.name.toLowerCase()] = h.value;
            }
        }
    },
    {
        urls: ['<all_urls>']
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

        // === Cookies ===
        case 'getCookies':
            return await cmdGetCookies(msg.url);
        case 'setCookie':
            return await cmdSetCookie(msg.details);
        case 'deleteCookie':
            return await cmdDeleteCookie(msg.url, msg.name);

        // === Script Execution (CSP bypass) ===
        case 'executeScript':
            return await cmdExecuteScript(msg.code, msg._senderTabId || msg.tabId, msg.world);

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
            return await cmdResizeWindow(msg.windowId, msg.width, msg.height, msg.left, msg.top);

        // === Network Capture ===
        case 'startNetCapture':
            _netCapture = [];
            _netCaptureActive = true;
            return { success: true, data: 'Capture started' };
        case 'stopNetCapture':
            _netCaptureActive = false;
            return { success: true, data: { requestCount: _netCapture.length } };
        case 'getNetCapture':
            return { success: true, data: _netCapture };
        case 'clearNetCapture':
            _netCapture = [];
            return { success: true };

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

        bridgeSend({
            type: 'handshake',
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
        'captureScreenshot',
        'getCookies', 'setCookie', 'deleteCookie',
        'startNetCapture', 'stopNetCapture', 'getNetCapture', 'clearNetCapture',
        'newWindow', 'newIncognitoWindow', 'listWindows', 'closeWindow', 'resizeWindow',
        'executeScript',
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

        return await new Promise((resolve) => {
            chrome.tabs.sendMessage(targetId, { ...msg, target: 'content' }, (response) => {
                if (chrome.runtime.lastError) {
                    resolve({ success: false, error: `Content script not ready on this tab. Try refreshing the page. (${chrome.runtime.lastError.message})` });
                } else {
                    resolve(response || { success: false, error: 'No response from content script' });
                }
            });
        });
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

async function cmdCaptureScreenshot(tabId) {
    try {
        if (!tabId) return { success: false, error: 'tabId required' };
        // Activate the target tab and focus its window to ensure captureVisibleTab gets the right content
        const tab = await chrome.tabs.get(tabId);
        await chrome.tabs.update(tabId, { active: true });
        await chrome.windows.update(tab.windowId, { focused: true });
        // Brief delay to let the tab render after activation
        await new Promise(r => setTimeout(r, 150));

        const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
            format: 'png',
            quality: 90,
        });

        return {
            success: true,
            data: {
                dataUrl,
                format: 'png',
                tabId: tabId,
            }
        };
    } catch (e) {
        return { success: false, error: `Screenshot failed: ${e.message}` };
    }
}

// ==========================================
// Cookies
// ==========================================

async function cmdGetCookies(url) {
    if (!url) {
        return { success: false, error: 'url required' };
    }
    const cookies = await chrome.cookies.getAll({ url });
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

async function cmdResizeWindow(windowId, width, height, left, top) {
    try {
        const updateInfo = {};
        if (width) updateInfo.width = width;
        if (height) updateInfo.height = height;
        if (left !== undefined) updateInfo.left = left;
        if (top !== undefined) updateInfo.top = top;
        const win = await chrome.windows.update(windowId, updateInfo);
        return {
            success: true,
            data: { width: win.width, height: win.height, left: win.left, top: win.top },
        };
    } catch (e) {
        return { success: false, error: `resizeWindow failed: ${e.message}` };
    }
}


// ==========================================
// Helpers
// ==========================================

// getActiveTabId() has been removed.
// All commands now require an explicit tabId for reliable multi-window targeting.
// Use browser_list_tabs() to discover tab IDs.

console.log('[StealthDOM] Service worker started (bridge mode)');
