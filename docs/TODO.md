# StealthDOM Future Work & Ideas

This document tracks upcoming features, architectural ideas, and improvements for the StealthDOM ecosystem.

## Pending Implementation
- [ ] **Tab Discarding (`browser_discard_tab`)**
  - **Description**: Add a new background command `chrome.tabs.discard(tabId)` to forcefully put a tab into Memory Saver (sleeping) mode.
  - **Purpose**: Allows developers to write test cases that explicitly test an agent's ability to handle and recover from discarded tabs.

## Architectural Ideas
- [ ] **JavaScript Render Composition Fallback (html2canvas)**
  - **Description**: If CDP `captureScreenshot` fails (e.g., because the browser is fully occluded or minimized), automatically inject a library like `html2canvas` into the content script to manually read the DOM tree and paint it onto an HTML5 `<canvas>`.
  - **Purpose**: Provides a highly resilient visual fallback for Vision-Language Models that works completely independently of the Chromium graphics compositor.
