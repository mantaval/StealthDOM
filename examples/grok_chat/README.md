# Grok Chat (xAI)

Send a query to [Grok](https://grok.com) and get the response — all through StealthDOM.

## What It Does

1. Finds an existing `grok.com` tab or opens a new one
2. Signs in via your existing X (Twitter) session if needed — fully automated OAuth flow
3. Fills the chat input and submits your query
4. Waits for Grok to finish streaming its response
5. Extracts and prints the response text

## How the Agent Discovered It

Grok's chat interface is a Next.js SPA with some non-obvious implementation details:

- **The visible "textarea" is actually a `<div contenteditable="true">`**, not a `<textarea>`. There IS a hidden `<textarea>` in the DOM, but it's a mirror element — React doesn't sync it to the contenteditable. Standard `fill`/`type` commands target the wrong element.
- **React state sync requires a native `input` event** after setting `textContent` on the contenteditable div. Without this, React's controlled component doesn't pick up the change and the send button stays disabled.
- **Submission works via `KeyboardEvent('keydown', {key: 'Enter'})`** dispatched on the contenteditable div. Clicking the send button with a programmatic `click()` doesn't trigger the form submission.
- **Sign-in flow**: Grok → `accounts.x.ai/sign-in` → "Login with X" → `x.com/i/oauth2/authorize` → "Authorize app" → redirect back to Grok. Since the user is already logged into X, the whole OAuth flow completes without entering any credentials.
- **Response detection**: Grok streams its response in real-time. The script polls for a timing badge (e.g., "851ms") and source count indicator, which only appear after streaming completes.

## Usage

```bash
# Simple question
python examples/grok_chat/grok_chat.py "What is the capital of France?"

# Longer query
python examples/grok_chat/grok_chat.py "Explain quantum computing in one sentence."

# Multi-word (quotes are optional if no special chars)
python examples/grok_chat/grok_chat.py What is the speed of light?
```

## Example Output

```
============================================================
  StealthDOM → Grok Chat
============================================================
  Query: What is StealthDOM? One sentence only.
============================================================

[1/5] Finding Grok tab...
  [✓] Found existing Grok tab (id=1653965212)

[2/5] Checking authentication...
  [✓] Already signed in to Grok

[3/5] Preparing chat...
  [✓] On fresh Grok chat page

[4/5] Sending query...
  [→] Submitting query: What is StealthDOM? One sentence only.
  [✓] Query submitted

[5/5] Waiting for response...
  [→] Waiting for Grok to respond...

============================================================
  Grok's Response:
============================================================

StealthDOM is a stealthy DOM manipulation technique (likely in
web/security contexts) that evades detection.

============================================================
```

## Prerequisites

- Bridge server running (`python bridge_server.py`)
- StealthDOM extension loaded and enabled
- Logged into X (x.com) in the browser — Grok authenticates via X
