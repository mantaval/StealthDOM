# StealthDOM Performance & Bot Detection Results

This document records the results of various bot detection and browser fingerprinting tests performed on StealthDOM.

## Summary

As of April 2026, StealthDOM achieves **100% invisibility** against all major bot detection suites. Because it operates within a native browser context (via a Manifest V3 extension and background service worker) rather than through the Chrome DevTools Protocol (CDP), it leaves no automation signals.

| Test Suite | Result | Key Findings |
| :--- | :--- | :--- |
| **Sannysoft** | ✅ PASSED | `navigator.webdriver` is missing; all Chrome-specific tests passed. |
| **Fingerprint-Scan** | ✅ 0/100 RISK | Zero risk score; identified as a genuine Chromium browser. |
| **BrowserScan** | ✅ NO BOT | 85% authenticity score; correctly identified as real browser on Windows. |
| **CreepJS** | ✅ 0% HEADLESS | Zero headless/stealth signals detected; High confidence. |
| **Antoine Vastel** | ✅ PASSED | Confirmed "You are not Chrome headless". |

---

## Detailed Results

### 1. Sannysoft (bot.sannysoft.com)
The gold standard for basic automation signals.

*   **User Agent**: Matches real user session.
*   **WebDriver**: `missing (passed)`
*   **Chrome Attributes**: `present (passed)`
*   **Permissions**: Correctly reports human-like status.

### 2. Fingerprint-Scan (fingerprint-scan.com)
Advanced scanner that checks for CDP (Chrome DevTools Protocol) artifacts.

*   **Bot Risk Score**: `0 / 100`
*   **CDP Check**: `false` (Bypassed due to background bridge architecture)
*   **Is Playwright/Selenium**: `false`
*   **TLS Fingerprint**: Matches native browser fingerprint.

### 3. BrowserScan (browserscan.net)
*   **Bot Detection**: `No`
*   **Authenticity**: `85%` (Typical for real users; higher than most automation tools).
*   **Canvas Fingerprint**: Correctly identifies the browser's fingerprint (Brave adds built-in noise protection).

### 4. CreepJS (abrahamjuliot.github.io/creepjs/)
The most aggressive browser fingerprinting benchmark available.

*   **Headless Score**: `0%`
*   **Stealth Score**: `0%` (Indicating a genuine browser with no detection-evasion scripts detected).
*   **Trust Score**: High Confidence.
*   **Detection**: Identified as a genuine browser on Windows.

### 5. Headless Check (arh.antoinevastel.com/bots/areyouheadless)
*   **Result**: `You are not Chrome headless`

---

## Why StealthDOM Passes
1.  **No CDP usage**: Unlike Playwright/Puppeteer, StealthDOM does not use the Chrome DevTools Protocol, which is the #1 way bots are detected (via `Runtime.enable` and other artifacts).
2.  **Native Extension Context**: Commands are executed by the browser's own extension engine, making them indistinguishable from user actions or legitimate extensions.
3.  **Native Browser Engine**: Running inside a real Chromium browser provides authentic fingerprints that further mask automation.
