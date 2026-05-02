# Why StealthDOM?

## The Problem with Browser Automation Today

Every mainstream browser automation tool — Playwright, Puppeteer, Selenium — controls the browser **from outside** using the Chrome DevTools Protocol (CDP). This means launching Chrome with special flags, injecting commands through a debugging port, and hoping the target website doesn't notice.

They always notice.

### How Bot Detection Works

Modern anti-bot systems (Cloudflare, DataDome, PerimeterX, Akamai) check for automation signals at multiple layers:

| Layer | What They Check | Why External Tools Fail |
|---|---|---|
| **JavaScript** | `navigator.webdriver`, `window.cdc_`, CDP artifacts | Playwright sets `navigator.webdriver = true` by default |
| **Network** | TLS fingerprint (JA3/JA4), open debugging ports | CDP proxy alters the TLS handshake; port 9222 is scannable |
| **Behavioral** | Mouse jitter, scroll entropy, typing cadence | Programmatic input lacks human noise |
| **Session** | Cookies, login state, browsing history | Automation tools start with blank profiles |
| **Browser** | Missing `chrome.runtime`, unusual process flags | CDP-launched browsers lack extension ecosystem signals |

Even "stealth" forks (Playwright Stealth, undetected-chromedriver) only patch the JavaScript layer. They can't fix the TLS fingerprint, the missing extension ecosystem, or the blank session history. Cloudflare Turnstile catches all of them.

### The Real-World Impact

If you've used Playwright or any browser agent (including IDE-integrated browser tools), you've seen these problems:

- **"Please verify you are human"** — Cloudflare blocks the automation before it even starts
- **"You are not logged in"** — The automated browser has no cookies, no sessions, no saved passwords
- **Blank profiles** — No browsing history, no extensions, no bookmarks — obvious bot signal
- **CAPTCHAs on every page** — Bot scoring gets worse with every request
- **Banking/enterprise sites** — Refuse to load entirely in automation browsers

These aren't edge cases. They're the default experience with external automation.

---

## The Solution: Automate from Inside the Browser

StealthDOM takes a fundamentally different approach. Instead of controlling the browser from outside, it runs **inside your actual browser** as a native Manifest V3 extension.

```
Your Python script / AI Agent / MCP Client
        │
        ▼
localhost WebSocket (:9878)  ← Just a local network request
        │
        ▼
Bridge Server (relay)
        │
        ▼
Background Service Worker  ← Lives inside the browser
        │
        ▼
Content Script → DOM (native access, indistinguishable from user)
```

Because StealthDOM is a browser extension — not an external debugger — it inherits everything the browser already has:

- **Your real cookies and sessions** — already logged into Gmail, ChatGPT, banking sites? StealthDOM uses those sessions directly
- **Your real TLS fingerprint** — the browser handles TLS natively; no proxy, no mismatch
- **Your real browser profile** — history, extensions, bookmarks, preferences — all present
- **`navigator.webdriver = false`** — naturally, because there's no automation flag to set
- **Real `chrome.runtime`** — because it IS a real extension
- **No detectable difference from manual browsing** — because there is none

---

## Proof: Zero Detection Across All Major Test Suites

StealthDOM achieves **100% invisibility** against every major bot detection benchmark:

| Test Suite | Result | What It Checks |
|---|---|---|
| **Sannysoft** | ✅ PASSED | `navigator.webdriver`, Chrome attributes, permissions |
| **Fingerprint-Scan** | ✅ 0/100 risk | CDP artifacts, TLS fingerprint, Playwright/Selenium flags |
| **BrowserScan** | ✅ 85% authentic | Full browser authenticity (typical real-user score) |
| **CreepJS** | ✅ 0% headless | The most aggressive fingerprinting benchmark available |
| **Antoine Vastel** | ✅ NOT headless | Headless Chrome detection specialist |

These scores are identical to a human manually browsing. Playwright, even with stealth plugins, fails multiple checks on every one of these suites.

---

## StealthDOM vs Playwright

| Aspect | Playwright | StealthDOM |
|---|---|---|
| Detection risk | High — CDP, webdriver flag, TLS | **Zero** — native browser citizen |
| Cloudflare / DataDome | Frequently blocked | **Never blocked** |
| Uses real browser profile | Hacky (`executable_path`) | **Natively** — your actual browser |
| Logged-in sessions | Must re-authenticate | **Uses existing sessions** |
| Human behavior simulation | Must fake (bezier curves, delays) | **Already human** — real browser |
| JavaScript execution | Built-in | **Built-in** (arbitrary JS, CSP-safe) |
| Screenshots | Silent (CDP `Page.captureScreenshot`) | **Silent** (CDP via `chrome.debugger`, v3.2.0) |
| Network requests with real TLS | Not possible | **Built-in** (`proxyFetch`) |
| Setup complexity | Install Python + Playwright + browsers | **Load one extension** |

### What StealthDOM Can't Do (Yet)

- **No headless mode** — requires a visible browser window (can be minimized)
- **No multi-browser orchestration** — one browser instance at a time per bridge
- **No built-in waiting strategies** — you manage retries and polling yourself (or let your AI agent handle it)

These are acceptable trade-offs. If you need headless, parallel browser farms, Playwright is the right tool. If you need to automate sites that detect and block bots — which is increasingly every site — StealthDOM is the only tool that works.

---

## What You Can Do with StealthDOM

### Interact with Any Page — Even Ones That Block Bots

Click buttons, fill forms, read text, extract tables — on any site, including Cloudflare-protected ones:

```python
# Click a button on a Cloudflare-protected site (Playwright would be blocked)
await send(ws, "click", selector="#submit-btn", tabId=tab_id)

# Fill a login form using your existing session cookies
await send(ws, "fill", selector="#email", value="user@example.com", tabId=tab_id)

# Extract text from any element
result = await send(ws, "getInnerText", selector=".price-display", tabId=tab_id)
```

### Take Screenshots Without Stealing Focus

CDP-based screenshots (v3.2.0) capture any tab silently — no window activation, no flicker:

```python
# Screenshot a background tab — window stays minimized
result = await send(ws, "captureScreenshot", tabId=tab_id)

# Full-page screenshot in a single shot — no scrolling
result = await send(ws, "captureFullPageScreenshot", tabId=tab_id)
```

### Execute Arbitrary JavaScript

Run any JS on any page, including sites with strict Content Security Policy (YouTube, Gmail):

```python
# Extract all links from a page
result = await send(ws, "evaluate",
    code="return [...document.querySelectorAll('a')].map(a => ({text: a.innerText, href: a.href}))",
    tabId=tab_id)

# Read a table as structured data
result = await send(ws, "evaluate",
    code="""return [...document.querySelectorAll('table tr')].map(row =>
        [...row.querySelectorAll('td, th')].map(cell => cell.innerText))""",
    tabId=tab_id)
```

### Make HTTP Requests with the Browser's Real TLS Fingerprint

Bypass API-level bot detection by routing requests through the browser's native `fetch()`:

```python
# This request has the same TLS fingerprint as your browser
result = await send(ws, "proxyFetch",
    url="https://api.protected-site.com/data",
    method="POST",
    headers={"Content-Type": "application/json"},
    body={"query": "search term"},
    tabId=tab_id)
```

### Work Across Frames and Iframes

Access content inside iframes, framesets, and cross-origin embedded content:

```python
# List all frames in a tab (finds iframes, framesets, embedded content)
frames = await send(ws, "listFrames", tabId=tab_id)

# Target a specific frame by its ID
result = await send(ws, "querySelector",
    selector="#compose-body",
    tabId=tab_id,
    frameId=frames["data"]["frames"][1]["frameId"])
```

For the complete API with all 57 MCP tools and WebSocket commands, see the [API Reference](03_api_reference.md).

---

## Getting Started

1. **Load the extension** → [Installation Guide](02_installation_guide.md)
2. **Browse the full API** → [API Reference](03_api_reference.md)
3. **Understand the architecture** → [Architecture & Design](01_architecture.md)
