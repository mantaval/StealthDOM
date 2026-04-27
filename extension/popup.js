/**
 * StealthDOM Popup — Enable/Disable Toggle
 * 
 * When disabled:
 * - Bridge WebSocket is disconnected
 * - CSP stripping rule is removed
 * - Commands are rejected
 * 
 * When enabled:
 * - Bridge reconnects
 * - CSP stripping rule is re-added
 * - Normal operation resumes
 */

const toggle = document.getElementById('toggleEnabled');
const statusDot = document.getElementById('statusDot');
const statusText = document.getElementById('statusText');

// Load current state
chrome.storage.local.get(['stealthdom_enabled'], (result) => {
    // Default to enabled if not set
    const enabled = result.stealthdom_enabled !== false;
    toggle.checked = enabled;
    updateStatus();
});

// Handle toggle
toggle.addEventListener('change', () => {
    const enabled = toggle.checked;

    // Tell background to enable/disable
    chrome.runtime.sendMessage({ type: 'setEnabled', enabled }, () => {
        // Immediate status update
        updateStatus();
        // Check again after bridge has time to connect (takes ~1s)
        if (enabled) {
            setTimeout(updateStatus, 1500);
            setTimeout(updateStatus, 3500);
        }
    });
});

function updateStatus() {
    chrome.runtime.sendMessage({ type: 'getStatus' }, (response) => {
        if (chrome.runtime.lastError || !response) {
            statusDot.className = 'status-dot disconnected';
            statusText.textContent = 'Background not responding';
            return;
        }

        if (!response.enabled) {
            statusDot.className = 'status-dot disabled';
            statusText.textContent = 'Disabled — not intercepting';
        } else if (response.bridgeConnected) {
            statusDot.className = 'status-dot connected';
            statusText.textContent = 'Connected to bridge';
        } else {
            statusDot.className = 'status-dot disconnected';
            statusText.textContent = 'Enabled — bridge not connected';
        }
    });
}

// Poll status every 2 seconds while popup is open
setInterval(updateStatus, 2000);
