/**
 * StealthDOM -- Content Script
 * 
 * Injected ON-DEMAND into tabs when the first command targets them.
 * NOT declared in manifest.json — the background service worker
 * uses chrome.scripting.executeScript to inject this lazily,
 * saving memory and CPU across all untouched tabs.
 * 
 * Receives DOM commands from the background service worker
 * via chrome.runtime messaging.
 * 
 * This runs INSIDE the real browser -- completely undetectable.
 * No CDP, no Playwright, no automation flags.
 * 
 * The WebSocket bridge connection is handled by background.js,
 * which forwards DOM commands here. This avoids CSP restrictions
 * and Private Network Access popups on sites like Gmail.
 */

(() => {
    'use strict';

    // Guard against double-injection (on-demand injection may fire multiple times)
    // Uses a Symbol on window so the guard is invisible to Object.keys/for-in/JSON.stringify,
    // and the symbol description is generic to avoid identifying the extension.
    const _guard = Symbol.for('__cs_init');
    if (window[_guard]) return;
    Object.defineProperty(window, _guard, { value: true, configurable: false });

    // ==========================================
    // Message Listener (from Background Script)
    // ==========================================

    chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
        if (msg.target !== 'content') return false;

        handleDOMCommand(msg.action, msg)
            .then(result => sendResponse(result))
            .catch(err => sendResponse({ success: false, error: err.message }));

        return true; // Keep channel open for async response
    });

    async function handleDOMCommand(action, msg) {
        switch (action) {
            // === Lifecycle ===
            case 'ping':
                return { success: true, data: 'pong' };
            case 'getStatus':
                return cmdGetStatus();


            // === DOM Queries ===
            case 'querySelector':
                return cmdQuerySelector(msg.selector);
            case 'querySelectorAll':
                return cmdQuerySelectorAll(msg.selector, msg.limit);
            case 'getInnerText':
                return cmdGetInnerText(msg.selector);
            case 'getOuterHTML':
                return cmdGetOuterHTML(msg.selector, msg.maxLength);
            case 'getAttribute':
                return cmdGetAttribute(msg.selector, msg.attribute);
            case 'getProperty':
                return cmdGetProperty(msg.selector, msg.property);
            case 'getComputedStyle':
                return cmdGetComputedStyleProp(msg.selector, msg.property);
            case 'getBoundingRect':
                return cmdGetBoundingRect(msg.selector);
            case 'waitForSelector':
                return await cmdWaitForSelector(msg.selector, msg.timeout);
            case 'waitForText':
                return await cmdWaitForText(msg.selector, msg.text, msg.timeout);

            // === DOM Interaction ===
            case 'click':
                return cmdClick(msg.selector);
            case 'dblclick':
                return cmdDblClick(msg.selector);
            case 'hover':
                return cmdHover(msg.selector);
            case 'dragAndDrop':
                return await cmdDragAndDrop(msg.sourceSelector, msg.targetSelector);
            case 'type':
                return cmdType(msg.selector, msg.text);
            case 'fill':
                return cmdFill(msg.selector, msg.value);
            case 'focus':
                return cmdFocus(msg.selector);
            case 'blur':
                return cmdBlur(msg.selector);
            case 'check':
                return cmdCheck(msg.selector);
            case 'uncheck':
                return cmdUncheck(msg.selector);
            case 'selectOption':
                return cmdSelectOption(msg.selector, msg.value);
            case 'scrollIntoView':
                return cmdScrollIntoView(msg.selector);
            case 'scrollTo':
                return cmdScrollTo(msg.x, msg.y);

            // === Keyboard ===
            case 'keyPress':
                return await cmdKeyPress(msg.key);
            case 'keyCombo':
                return await cmdKeyCombo(msg.keys);


            // === Page Info ===
            case 'getURL':
                return { success: true, data: window.location.href };
            case 'getTitle':
                return { success: true, data: document.title };
            case 'getPageText':
                return { success: true, data: (document.body.innerText || '').substring(0, msg.maxLength || Infinity) };
            case 'getPageHTML':
                return { success: true, data: msg.maxLength ? document.documentElement.outerHTML.substring(0, msg.maxLength) : document.documentElement.outerHTML };

            // === Advanced ===
            case 'evaluate':
                // Runs arbitrary JS in the page's MAIN world via chrome.scripting.executeScript.
                // Works on ALL sites — CSP headers are stripped by declarativeNetRequest.
                // Supports expressions ('document.title') and return statements
                // ('return document.querySelectorAll("a").length').
                return await forwardToBackground({ action: 'executeScript', code: msg.code });
            case 'setInputFiles':
                return await cmdSetInputFiles(msg.selector, msg.dataUrl);
            case 'proxyFetch':
                return await cmdProxyFetch(msg.url, msg.method, msg.headers, msg.body, msg.bodyType);

            // === DOM Manipulation (no eval needed, works on all sites) ===
            case 'removeByText': {
                const selector = msg.selector || '*';
                const texts = (msg.texts || []).map(t => t.toLowerCase());
                const elements = document.querySelectorAll(selector);
                let removed = 0;
                elements.forEach(el => {
                    const content = (el.innerText || '').toLowerCase();
                    if (texts.some(t => content.includes(t))) {
                        el.remove();
                        removed++;
                    }
                });
                return { success: true, data: { removed, selector, texts: msg.texts } };
            }

            default:
                return { success: false, error: `Unknown action: ${action}` };
        }
    }

    // ==========================================
    // Background Forwarding
    // ==========================================

    function forwardToBackground(msg) {
        return new Promise((resolve) => {
            chrome.runtime.sendMessage(
                { ...msg, target: 'background' },
                (response) => {
                    if (chrome.runtime.lastError) {
                        resolve({ success: false, error: chrome.runtime.lastError.message });
                    } else {
                        resolve(response || { success: false, error: 'No response from background' });
                    }
                }
            );
        });
    }

    // ==========================================
    // Error Helpers
    // ==========================================

    function elementNotFoundError(selector) {
        return { 
            success: false, 
            error: `Element not found: ${selector}. (Hint: If the page is still loading, use browser_wait_for. If the element is inside an iframe, use browser_list_frames and pass frame_id. Otherwise, check your selector.)` 
        };
    }

    // ==========================================
    // Page Status
    // ==========================================

    function cmdGetStatus() {
        return {
            success: true,
            data: {
                url: window.location.href,
                title: document.title,
            }
        };
    }

    // ==========================================
    // DOM Query Commands
    // ==========================================

    function cmdQuerySelector(selector) {
        const el = document.querySelector(selector);
        if (!el) {
            // Check if iframes exist — hint the agent to use frame_id
            const frameCount = document.querySelectorAll('iframe, frame').length;
            const hint = frameCount > 0
                ? ` (page has ${frameCount} iframe(s) — try browser_list_frames and pass frame_id)`
                : '';
            return { success: true, data: null, hint: `No element found matching: ${selector}${hint}` };
        }
        return { success: true, data: serializeElement(el) };
    }

    function cmdQuerySelectorAll(selector, limit = 0) {
        const els = document.querySelectorAll(selector);
        const max = limit > 0 ? Math.min(els.length, limit) : els.length;
        const results = [];
        for (let i = 0; i < max; i++) {
            results.push(serializeElement(els[i]));
        }
        return { success: true, data: { count: els.length, elements: results } };
    }

    function cmdGetInnerText(selector) {
        const el = document.querySelector(selector);
        return { success: true, data: { text: el ? (el.innerText || el.textContent || '') : '' } };
    }

    function cmdGetOuterHTML(selector, maxLength = 0) {
        const el = document.querySelector(selector);
        if (!el) return { success: true, data: null };
        const html = el.outerHTML;
        return { success: true, data: maxLength > 0 ? html.substring(0, maxLength) : html };
    }

    function cmdGetAttribute(selector, attribute) {
        const el = document.querySelector(selector);
        if (!el) return elementNotFoundError(selector);
        return { success: true, data: el.getAttribute(attribute) };
    }

    function cmdGetProperty(selector, property) {
        const el = document.querySelector(selector);
        if (!el) return elementNotFoundError(selector);
        return { success: true, data: el[property] };
    }

    function cmdGetComputedStyleProp(selector, property) {
        const el = document.querySelector(selector);
        if (!el) return elementNotFoundError(selector);
        const style = window.getComputedStyle(el);
        return { success: true, data: style.getPropertyValue(property) };
    }

    function cmdGetBoundingRect(selector) {
        const el = document.querySelector(selector);
        if (!el) return elementNotFoundError(selector);
        const rect = el.getBoundingClientRect();
        return {
            success: true,
            data: { x: rect.x, y: rect.y, width: rect.width, height: rect.height, top: rect.top, left: rect.left, bottom: rect.bottom, right: rect.right }
        };
    }

    async function cmdWaitForSelector(selector, timeout = 10000) {
        const start = Date.now();
        while (Date.now() - start < timeout) {
            const el = document.querySelector(selector);
            if (el) {
                // Small debounce: SPAs (React/Angular) attach event listeners
                // slightly after DOM insertion. Wait 50ms for hydration.
                await sleep(50);
                return { success: true, data: serializeElement(el) };
            }
            await sleep(200);
        }
        return { success: false, error: `Timeout waiting for: ${selector}` };
    }

    async function cmdWaitForText(selector, text, timeout = 10000) {
        const start = Date.now();
        while (Date.now() - start < timeout) {
            const el = document.querySelector(selector);
            if (el && (el.innerText || '').includes(text)) {
                return { success: true, data: { text: el.innerText } };
            }
            await sleep(200);
        }
        return { success: false, error: `Timeout waiting for text "${text}" in ${selector}` };
    }

    // ==========================================
    // DOM Interaction Commands
    // ==========================================

    function cmdClick(selector) {
        const el = document.querySelector(selector);
        if (!el) return elementNotFoundError(selector);
        el.scrollIntoView({ block: 'center' });
        // Full event sequence for better SPA compatibility
        const rect = el.getBoundingClientRect();
        const x = rect.left + rect.width / 2;
        const y = rect.top + rect.height / 2;
        const opts = { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0 };
        el.dispatchEvent(new MouseEvent('mousedown', opts));
        el.dispatchEvent(new MouseEvent('mouseup', opts));
        el.click();
        return { success: true };
    }

    function cmdDblClick(selector) {
        const el = document.querySelector(selector);
        if (!el) return elementNotFoundError(selector);
        el.scrollIntoView({ block: 'center' });
        el.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, cancelable: true }));
        return { success: true };
    }

    /**
     * Hover over an element. Triggers mouseenter + mouseover + mousemove.
     * Useful for revealing dropdown menus, tooltips, hover states.
     */
    function cmdHover(selector) {
        const el = document.querySelector(selector);
        if (!el) return elementNotFoundError(selector);
        el.scrollIntoView({ block: 'center' });
        const rect = el.getBoundingClientRect();
        const cx = Math.round(rect.left + rect.width / 2);
        const cy = Math.round(rect.top + rect.height / 2);
        const opts = { bubbles: true, cancelable: true, clientX: cx, clientY: cy };
        el.dispatchEvent(new MouseEvent('mouseenter', opts));
        el.dispatchEvent(new MouseEvent('mouseover', opts));
        el.dispatchEvent(new MouseEvent('mousemove', opts));
        return { success: true };
    }

    /**
     * Drag-and-drop from source element to target element.
     * Uses the HTML5 DragEvent API. Works for elements with draggable=true
     * and libraries that listen for drag events (Kanban boards, sortable lists).
     */
    async function cmdDragAndDrop(sourceSelector, targetSelector) {
        const source = document.querySelector(sourceSelector);
        if (!source) return { success: false, error: `Source not found: ${sourceSelector}` };
        const target = document.querySelector(targetSelector);
        if (!target) return { success: false, error: `Target not found: ${targetSelector}` };

        source.scrollIntoView({ block: 'center' });
        const dt = new DataTransfer();

        source.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt }));
        await sleep(50);
        target.scrollIntoView({ block: 'center' });
        target.dispatchEvent(new DragEvent('dragenter', { bubbles: true, cancelable: true, dataTransfer: dt }));
        target.dispatchEvent(new DragEvent('dragover',  { bubbles: true, cancelable: true, dataTransfer: dt }));
        await sleep(50);
        target.dispatchEvent(new DragEvent('drop',    { bubbles: true, cancelable: true, dataTransfer: dt }));
        source.dispatchEvent(new DragEvent('dragend',  { bubbles: true, cancelable: true, dataTransfer: dt }));

        return { success: true };
    }

    function cmdType(selector, text) {
        const el = document.querySelector(selector);
        if (!el) return elementNotFoundError(selector);
        el.focus();
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
            // Use native value setter for proper React/Vue/Angular compatibility
            const nativeSetter = Object.getOwnPropertyDescriptor(
                el.tagName === 'INPUT' ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype,
                'value'
            );
            if (nativeSetter && nativeSetter.set) {
                nativeSetter.set.call(el, el.value + text);
            } else {
                el.value += text;
            }
            el.dispatchEvent(new InputEvent('input', { bubbles: true, data: text, inputType: 'insertText' }));
        } else {
            // contenteditable: execCommand is still the most reliable for Chromium
            document.execCommand('insertText', false, text);
        }
        return { success: true };
    }

    function cmdFill(selector, value) {
        const el = document.querySelector(selector);
        if (!el) return elementNotFoundError(selector);
        el.focus();
        // For regular inputs
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
            const nativeSetter = Object.getOwnPropertyDescriptor(
                el.tagName === 'INPUT' ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype,
                'value'
            );
            if (nativeSetter && nativeSetter.set) {
                nativeSetter.set.call(el, value);
            } else {
                el.value = value;
            }
            el.dispatchEvent(new InputEvent('input', { bubbles: true, data: value, inputType: 'insertText' }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        } else {
            // For contenteditable (ProseMirror, Slate, etc.)
            document.execCommand('selectAll', false, null);
            document.execCommand('insertText', false, value);
        }
        return { success: true };
    }

    function cmdFocus(selector) {
        const el = document.querySelector(selector);
        if (!el) return elementNotFoundError(selector);
        el.focus();
        return { success: true };
    }

    function cmdBlur(selector) {
        const el = document.querySelector(selector);
        if (!el) return elementNotFoundError(selector);
        el.blur();
        return { success: true };
    }

    function cmdCheck(selector) {
        const el = document.querySelector(selector);
        if (!el) return elementNotFoundError(selector);
        if (!el.checked) el.click();
        return { success: true };
    }

    function cmdUncheck(selector) {
        const el = document.querySelector(selector);
        if (!el) return elementNotFoundError(selector);
        if (el.checked) el.click();
        return { success: true };
    }

    function cmdSelectOption(selector, value) {
        const el = document.querySelector(selector);
        if (!el) return elementNotFoundError(selector);
        el.value = value;
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return { success: true };
    }

    function cmdScrollIntoView(selector) {
        const el = document.querySelector(selector);
        if (!el) return elementNotFoundError(selector);
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return { success: true };
    }

    function cmdScrollTo(x, y) {
        window.scrollTo({ left: x || 0, top: y || 0, behavior: 'smooth' });
        return { success: true };
    }

    // ==========================================
    // Keyboard Commands
    // ==========================================

    async function cmdKeyPress(key) {
        const target = document.activeElement || document;
        target.dispatchEvent(new KeyboardEvent('keydown', {
            key, code: key, keyCode: key.charCodeAt?.(0) || 0,
            bubbles: true, cancelable: true,
        }));
        await sleep(30);
        target.dispatchEvent(new KeyboardEvent('keyup', {
            key, code: key, keyCode: key.charCodeAt?.(0) || 0,
            bubbles: true, cancelable: true,
        }));
        return { success: true };
    }

    async function cmdKeyCombo(keys) {
        if (!keys || !Array.isArray(keys)) {
            return { success: false, error: 'keys must be an array' };
        }
        const modifiers = ['Control', 'Shift', 'Alt', 'Meta'];
        const actualKey = keys.find(k => !modifiers.includes(k));

        const eventInit = {
            bubbles: true, cancelable: true,
            ctrlKey: keys.includes('Control'),
            shiftKey: keys.includes('Shift'),
            altKey: keys.includes('Alt'),
            metaKey: keys.includes('Meta'),
        };
        if (actualKey) {
            eventInit.key = actualKey;
            eventInit.code = `Key${actualKey.toUpperCase()}`;
        }

        const target = document.activeElement || document;
        target.dispatchEvent(new KeyboardEvent('keydown', eventInit));
        await sleep(50);
        target.dispatchEvent(new KeyboardEvent('keyup', eventInit));
        return { success: true };
    }


    // ==========================================
    // Advanced Commands
    // ==========================================

    function cmdEvaluate(code) {
        // CSP blocks both eval() and inline script injection.
        // Forward to background.js which uses chrome.scripting.executeScript
        // to run code in the page's MAIN world — bypasses CSP entirely.
        return new Promise((resolve) => {
            chrome.runtime.sendMessage(
                { target: 'background', action: 'executeScript', code },
                (response) => {
                    if (chrome.runtime.lastError) {
                        resolve({ success: false, error: chrome.runtime.lastError.message });
                    } else {
                        resolve(response || { success: false, error: 'No response from background' });
                    }
                }
            );
        });
    }

    async function cmdProxyFetch(url, method = 'GET', headers = {}, body = null, bodyType = 'json') {
        // Make an HTTP request FROM the browser context.
        // This inherits the browser's TLS fingerprint, cookies, CF tokens, etc.
        // bodyType: 'json' | 'text' | 'formdata' | 'base64file'
        try {
            const fetchOpts = {
                method,
                headers: { ...headers },
                credentials: 'include',  // Send cookies automatically
            };

            if (body && method !== 'GET') {
                if (bodyType === 'base64file') {
                    // body is { fieldName, fileName, mimeType, data (base64) }
                    const binaryStr = atob(body.data);
                    const bytes = new Uint8Array(binaryStr.length);
                    for (let i = 0; i < binaryStr.length; i++) {
                        bytes[i] = binaryStr.charCodeAt(i);
                    }
                    const blob = new Blob([bytes], { type: body.mimeType || 'application/octet-stream' });
                    const formData = new FormData();
                    formData.append(body.fieldName || 'file', blob, body.fileName || 'upload');
                    fetchOpts.body = formData;
                    // Don't set Content-Type — browser will set multipart boundary automatically
                    delete fetchOpts.headers['Content-Type'];
                    delete fetchOpts.headers['content-type'];
                } else if (bodyType === 'formdata') {
                    const formData = new FormData();
                    for (const [k, v] of Object.entries(body)) {
                        formData.append(k, v);
                    }
                    fetchOpts.body = formData;
                    delete fetchOpts.headers['Content-Type'];
                } else if (bodyType === 'json') {
                    fetchOpts.body = JSON.stringify(body);
                    fetchOpts.headers['Content-Type'] = 'application/json';
                } else {
                    fetchOpts.body = body;
                }
            }

            const response = await fetch(url, fetchOpts);
            const contentType = response.headers.get('content-type') || '';

            let responseData;
            if (contentType.includes('application/json')) {
                responseData = await response.json();
            } else {
                responseData = await response.text();
            }

            return {
                success: true,
                data: {
                    status: response.status,
                    statusText: response.statusText,
                    headers: Object.fromEntries(response.headers.entries()),
                    body: responseData,
                }
            };
        } catch (e) {
            return { success: false, error: `proxyFetch failed: ${e.message}` };
        }
    }

    async function cmdSetInputFiles(selector, dataUrl) {
        const el = document.querySelector(selector);
        if (!el || el.type !== 'file') {
            return { success: false, error: 'File input not found' };
        }

        try {
            // Convert data URL to File object
            const res = await fetch(dataUrl);
            const blob = await res.blob();
            const file = new File([blob], 'upload', { type: blob.type });

            const dt = new DataTransfer();
            dt.items.add(file);
            el.files = dt.files;
            el.dispatchEvent(new Event('change', { bubbles: true }));

            return { success: true };
        } catch (e) {
            return { success: false, error: `File upload failed: ${e.message}` };
        }
    }

    // evaluate is handled via forwardToBackground -> executeScript

    // ==========================================
    // Helpers
    // ==========================================



    function serializeElement(el) {
        return {
            tagName: el.tagName,
            id: el.id || null,
            className: typeof el.className === 'string' ? el.className : '',
            innerText: el.innerText || '',
            value: el.value !== undefined ? el.value : null,
            href: el.href || null,
            src: el.src || null,
            type: el.type || null,
            checked: el.checked !== undefined ? el.checked : null,
            disabled: el.disabled || false,
            visible: el.offsetParent !== null,
            childCount: el.children.length,
        };
    }

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    // ==========================================
    // Anti-Throttle
    // ==========================================

    function setupAntiThrottle() {
        try {
            Object.defineProperty(document, 'hidden', { value: false, configurable: true });
        } catch (e) { }
        try {
            Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
        } catch (e) { }
        try {
            document.addEventListener('visibilitychange', (e) => {
                e.stopImmediatePropagation();
            }, true);
        } catch (e) { }

        setInterval(() => {
            try {
                if (!document.body) return;
                const el = document.createElement('span');
                el.style.display = 'none';
                document.body.appendChild(el);
                document.body.removeChild(el);
            } catch (e) { }
        }, 15000);  // 15s — just prevents browser from fully suspending the tab
    }

    // ==========================================
    // Initialization
    // ==========================================

    // Only log in top frame to reduce noise
    if (window === window.top) {
        console.log('[StealthDOM] Content script injected (on-demand)');
    }
    try {
        setupAntiThrottle();
    } catch (e) {
        // Silently fail — anti-throttle is optional
    }

})();
