"""
StealthDOM Example: Grok Chat (xAI)

This script sends a query to Grok (grok.com) and returns the response.
It handles the full flow: finding or creating a Grok tab, signing in via
your existing X session if needed, submitting the query, and extracting
the streamed response text.

How it works:
- Finds an existing grok.com tab or opens a new one
- If not signed in, initiates the Login with X → OAuth flow
- Fills the contenteditable chat input and submits via Enter keydown
- Polls for the response text until streaming is complete
- Prints the response to stdout

Prerequisites:
- Bridge server running (python bridge_server.py)
- StealthDOM extension loaded in browser
- User is already logged into X (x.com) in the browser

Usage:
    python grok_chat.py "What is the capital of France?"
    python grok_chat.py "Tell me more about its history."   (continues same chat)
    python grok_chat.py --new "Start a different topic."     (forces new chat)
"""

import argparse
import asyncio
import json
import sys
import uuid
import websockets

# Fix Windows terminal encoding for unicode
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BRIDGE_URL = "ws://127.0.0.1:9878"
GROK_URL = "https://grok.com/"


async def send(ws, action, _bridge_timeout=15, **kwargs):
    """Send a command to StealthDOM and return the result."""
    msg_id = str(uuid.uuid4())[:8]
    msg = {"action": action, "_timeout": _bridge_timeout, "_msg_id": msg_id, **kwargs}
    await ws.send(json.dumps(msg))
    while True:
        response = json.loads(await ws.recv())
        if response.pop("_msg_id", None) == msg_id:
            break
    if not response.get("success"):
        error = response.get("error", "Unknown error")
        print(f"  [!] {action} failed: {error}")
    return response


async def js(ws, tab_id, code, timeout=15):
    """Execute JavaScript in the MAIN world and return the result."""
    r = await send(ws, "executeScript", tabId=tab_id, code=code, _bridge_timeout=timeout)
    return r.get("data")


async def wait_ms(ws, tab_id, ms):
    """Wait for a specified number of milliseconds via the browser."""
    await js(ws, tab_id, f"new Promise(r => setTimeout(r, {ms})).then(() => 'ok')")


async def find_or_open_grok_tab(ws):
    """Find an existing grok.com tab or open a new one."""
    r = await send(ws, "listTabs")
    tabs = r.get("data", [])

    # Look for existing grok.com tab
    for tab in tabs:
        if "grok.com" in tab.get("url", "") and not tab.get("incognito"):
            print(f"  [✓] Found existing Grok tab (id={tab['id']})")
            return tab["id"]

    # No existing tab — open one
    print("  [→] Opening new Grok tab...")
    r = await send(ws, "newTab", url=GROK_URL)
    if not r.get("success"):
        raise RuntimeError(f"Failed to open Grok tab: {r.get('error')}")

    tab_id = r["data"]["tabId"]
    await wait_ms(ws, tab_id, 3000)
    print(f"  [✓] Opened Grok tab (id={tab_id})")
    return tab_id


async def ensure_signed_in(ws, tab_id):
    """Check if signed in to Grok. If not, sign in via X OAuth.
    
    Returns True if signed in (or just signed in), False on failure.
    """
    # Check if signed in by looking for authenticated UI elements.
    # When signed in, the sidebar shows "Chat", "Voice", "Projects", etc.
    # When not signed in, there's a "Sign in" / "Sign up" button pair in the header.
    has_sign_in = await js(ws, tab_id,
        "!!Array.from(document.querySelectorAll('a, button')).find(e => e.textContent.trim() === 'Sign in')"
    )

    if not has_sign_in:
        print("  [✓] Already signed in to Grok")
        return True

    print("  [→] Not signed in. Initiating Login with X...")

    # Click "Sign in" link
    clicked = await js(ws, tab_id, """
        const link = Array.from(document.querySelectorAll('a'))
            .find(a => a.textContent.trim() === 'Sign in');
        if (link) { link.click(); 'ok' } else { null }
    """)

    if not clicked:
        print("  [!] Could not find Sign in link")
        return False

    await wait_ms(ws, tab_id, 4000)

    # Should now be on accounts.x.ai — click "Login with X"
    url = await js(ws, tab_id, "location.href")
    print(f"  [→] Redirected to: {url}")

    clicked = await js(ws, tab_id, """
        const btn = Array.from(document.querySelectorAll('button'))
            .find(b => b.textContent.includes('Login with'));
        if (btn) { btn.click(); 'ok' } else { null }
    """)

    if not clicked:
        print("  [!] Could not find 'Login with X' button")
        return False

    await wait_ms(ws, tab_id, 5000)

    # Should now be on X OAuth page — click "Authorize app"
    url = await js(ws, tab_id, "location.href")
    print(f"  [→] OAuth page: {url}")

    if "oauth2/authorize" in (url or ""):
        clicked = await js(ws, tab_id, """
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.includes('Authorize'));
            if (btn) { btn.click(); 'ok' } else { null }
        """)

        if clicked:
            print("  [→] Clicked 'Authorize app', waiting for redirect...")
            await wait_ms(ws, tab_id, 6000)
        else:
            print("  [!] Could not find 'Authorize app' button")
            return False

    # Verify we're back on grok.com and signed in
    url = await js(ws, tab_id, "location.href")
    if "grok.com" in (url or ""):
        print("  [✓] Successfully signed in to Grok")
        return True

    print(f"  [!] Unexpected URL after sign-in: {url}")
    return False


async def wait_for_editor(ws, tab_id, retries=10):
    """Poll until the contenteditable input appears."""
    for _ in range(retries):
        has_editor = await js(ws, tab_id,
            "!!document.querySelector('div[contenteditable=\"true\"]')"
        )
        if has_editor:
            return True
        await wait_ms(ws, tab_id, 500)
    return False


async def ensure_chat_ready(ws, tab_id, new_chat=False):
    """Ensure the Grok tab has a chat input ready.
    
    By default, continues in the current chat (multi-turn conversation).
    If new_chat=True or the tab isn't on a chat page, navigates to a fresh chat.
    """
    if not new_chat:
        # Check if we already have an active chat with an editor
        has_editor = await js(ws, tab_id,
            "!!document.querySelector('div[contenteditable=\"true\"]')"
        )
        if has_editor:
            url = await js(ws, tab_id, "location.href")
            if "grok.com" in (url or ""):
                is_continuation = "/c/" in (url or "")
                if is_continuation:
                    print("  [✓] Continuing existing conversation")
                else:
                    print("  [✓] Ready on fresh chat page")
                return

    # Navigate to grok.com home for a fresh chat
    if new_chat:
        print("  [→] Starting new conversation...")
    else:
        print("  [→] Navigating to Grok...")

    await send(ws, "navigate", tabId=tab_id, url=GROK_URL)
    await asyncio.sleep(3)  # Let SPA hydrate before querying DOM
    await wait_for_editor(ws, tab_id)
    print("  [✓] On fresh Grok chat page")


async def submit_query(ws, tab_id, query):
    """Fill the chat input and submit the query.
    
    Grok uses a contenteditable <div> as its input, not a standard
    <textarea> or <input>. We set textContent directly and dispatch
    an input event so React picks up the change, then submit with
    a KeyboardEvent('keydown', {key: 'Enter'}).
    """
    print(f"  [→] Submitting query: {query[:80]}{'...' if len(query) > 80 else ''}")

    # Escape the query for safe JS injection
    safe_query = json.dumps(query)

    filled = await js(ws, tab_id, f"""
        const editor = document.querySelector('div[contenteditable="true"]');
        if (!editor) {{ null }}
        else {{
            editor.focus();
            editor.textContent = {safe_query};
            editor.dispatchEvent(new Event('input', {{ bubbles: true }}));
            'ok'
        }}
    """)

    if not filled:
        raise RuntimeError("Could not find Grok's chat input (contenteditable div)")

    # Small delay for React to process the input event
    await wait_ms(ws, tab_id, 300)

    # Submit by dispatching Enter keydown on the editor
    submitted = await js(ws, tab_id, """
        const editor = document.querySelector('div[contenteditable="true"]');
        if (!editor) { null }
        else {
            editor.focus();
            const e = new KeyboardEvent('keydown', {
                key: 'Enter', code: 'Enter', keyCode: 13, which: 13,
                bubbles: true, cancelable: true
            });
            editor.dispatchEvent(e);
            'ok'
        }
    """)

    if not submitted:
        raise RuntimeError("Failed to submit query — contenteditable not found on retry")

    print("  [✓] Query submitted")


async def wait_for_response(ws, tab_id, bubble_count_before, timeout_s=60):
    """Poll until Grok's response is fully streamed.
    
    Grok streams its response in real-time. We detect completion by
    watching for a new .message-bubble to appear (Grok's response)
    and then checking for the timing metadata that signals streaming is done.
    
    Args:
        bubble_count_before: Number of .message-bubble divs before submission.
            Used to detect when the new response bubble has appeared.
    """
    print("  [→] Waiting for Grok to respond...")

    poll_interval_ms = 1500
    elapsed = 0

    while elapsed < timeout_s:
        await wait_ms(ws, tab_id, poll_interval_ms)
        elapsed += poll_interval_ms / 1000

        # Check: has a new response bubble appeared and finished streaming?
        result = await js(ws, tab_id, f"""
            const bubbles = document.querySelectorAll('div.message-bubble');
            const currentCount = bubbles.length;
            
            // We need at least 2 new bubbles: the user query + Grok's response
            if (currentCount < {bubble_count_before} + 2) {{
                JSON.stringify({{ isDone: false, bubbles: currentCount }})
            }} else {{
                // Response bubble exists — check if streaming is done.
                // Grok shows a timing badge (e.g. "851ms") after the last response.
                const lastBubble = bubbles[currentCount - 1];
                const parent = lastBubble.closest('[class]')?.parentElement;
                // The timing badge is a sibling/nearby element after the response
                const bodyText = document.body.innerText;
                const hasTiming = /\\d+(\\.\\d+)?\\s*(ms|s)/.test(bodyText);
                JSON.stringify({{ isDone: hasTiming, bubbles: currentCount }})
            }}
        """)

        if result:
            data = json.loads(result)
            if data.get("isDone"):
                await wait_ms(ws, tab_id, 500)  # Final render settle
                return

        if elapsed % 5 < (poll_interval_ms / 1000):
            print(f"  [⏳] Still waiting... ({elapsed:.0f}s)")

    raise TimeoutError(f"Grok did not respond within {timeout_s}s")


async def extract_clean_response(ws, tab_id):
    """Extract just Grok's latest response text.
    
    Grok renders chat as alternating .message-bubble divs:
    user, grok, user, grok, ...
    The last bubble is always Grok's most recent response.
    """
    response = await js(ws, tab_id, """
        // Get the last message-bubble — that's Grok's latest response.
        const bubbles = document.querySelectorAll('div.message-bubble');
        if (bubbles.length >= 2) return bubbles[bubbles.length - 1].innerText.trim();
        
        // Fallback: last markdown container
        const md = document.querySelectorAll('.response-content-markdown');
        if (md.length >= 1) return md[md.length - 1].innerText.trim();
        
        return null;
    """)
    return response


def parse_args():
    parser = argparse.ArgumentParser(
        description="Send a query to Grok (xAI) via StealthDOM.",
        usage='python grok_chat.py [--new] "Your question here"',
    )
    parser.add_argument("query", nargs="+", help="The question to ask Grok")
    parser.add_argument(
        "--new", action="store_true",
        help="Start a new conversation instead of continuing the current one",
    )
    return parser.parse_args()


async def main():
    args = parse_args()
    query = " ".join(args.query)
    new_chat = args.new

    mode = "new chat" if new_chat else "continue"
    print(f"\n{'='*60}")
    print(f"  StealthDOM → Grok Chat  ({mode})")
    print(f"{'='*60}")
    print(f"  Query: {query}")
    print(f"{'='*60}\n")

    ws = await websockets.connect(BRIDGE_URL)
    try:
        # Step 1: Find or open Grok tab
        print("[1/5] Finding Grok tab...")
        tab_id = await find_or_open_grok_tab(ws)

        # Step 2: Ensure signed in
        print("\n[2/5] Checking authentication...")
        signed_in = await ensure_signed_in(ws, tab_id)
        if not signed_in:
            print("\n[!] Could not sign in to Grok. Make sure you're logged into X.")
            sys.exit(1)

        # Step 3: Prepare chat (continue existing or start new)
        print("\n[3/5] Preparing chat...")
        await ensure_chat_ready(ws, tab_id, new_chat=new_chat)

        # Snapshot bubble count before submission for change detection
        bubble_count = await js(ws, tab_id,
            "document.querySelectorAll('div.message-bubble').length"
        ) or 0

        # Step 4: Submit query
        print("\n[4/5] Sending query...")
        await submit_query(ws, tab_id, query)

        # Step 5: Wait for and extract response
        print("\n[5/5] Waiting for response...")
        await wait_for_response(ws, tab_id, bubble_count)

        # Extract the clean response
        response = await extract_clean_response(ws, tab_id)

        print(f"\n{'='*60}")
        print(f"  Grok's Response:")
        print(f"{'='*60}")
        print()
        if response:
            print(response)
        else:
            print("  (No response text extracted)")
        print()
        print(f"{'='*60}")

    finally:
        await ws.close()


if __name__ == "__main__":
    asyncio.run(main())
