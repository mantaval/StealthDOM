"""
StealthDOM Example: Read Gmail Inbox

This script demonstrates using StealthDOM's WebSocket API to:
1. Navigate to Gmail
2. Wait for the inbox to load
3. Find the first email with "reward" in the subject
4. Open it and display the subject, from, date, and full body

Prerequisites:
- Bridge server running (python bridge_server.py)
- StealthDOM extension loaded in browser
- User is already logged into Gmail in the browser

Usage:
    python gmail_read_inbox.py
"""

import asyncio
import json
import sys
import websockets

# Fix Windows terminal encoding for unicode
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BRIDGE_URL = "ws://127.0.0.1:9878"
SEARCH_KEYWORD = "reward"  # Change this to search for different keywords


async def send(ws, action, **kwargs):
    """Send a command to StealthDOM and return the result."""
    msg = {"action": action, "_timeout": 15, **kwargs}
    await ws.send(json.dumps(msg))
    response = json.loads(await ws.recv())
    if not response.get("success"):
        print(f"  [!] {action} failed: {response.get('error')}")
    return response


async def get_text(ws, selector):
    """Get the text content of an element."""
    result = await send(ws, "getInnerText", selector=selector)
    if result.get("success"):
        data = result.get("data", "")
        # Handle both string and dict responses
        if isinstance(data, dict):
            return data.get("text", "")
        return str(data)
    return ""


async def get_attribute(ws, selector, attribute):
    """Get an attribute value of an element."""
    result = await send(ws, "getAttribute", selector=selector, attribute=attribute)
    if result.get("success"):
        data = result.get("data", "")
        if isinstance(data, dict):
            return data.get("value", "") or data.get("text", "")
        return str(data) if data else ""
    return ""


def escape_css_id(raw_id):
    """Escape special characters in a CSS ID selector."""
    return "".join(f"\\{c}" if c in ":.[],>+~()#" else c for c in raw_id)


async def main():
    print("=" * 60)
    print("  StealthDOM Example: Gmail Inbox Reader")
    print("=" * 60)
    print(f"\nConnecting to StealthDOM bridge at {BRIDGE_URL}...")

    ws = await websockets.connect(BRIDGE_URL)

    try:
        # Step 1: Navigate to Gmail inbox
        print("\n[1] Navigating to Gmail...")
        await send(ws, "navigate", url="https://mail.google.com/mail/u/0/#inbox")

        # Step 2: Wait for inbox to load (Gmail is a heavy SPA)
        print("[2] Waiting for inbox to load...")
        await asyncio.sleep(4)

        result = await send(ws, "waitForSelector", selector="tr.zA")
        if not result.get("success"):
            print("[X] Gmail inbox didn't load. Are you logged in?")
            return

        print("[OK] Inbox loaded!")

        # Step 3: Scan email rows for the search keyword
        print(f'\n[3] Searching for emails with "{SEARCH_KEYWORD}" in the subject...')
        result = await send(ws, "querySelectorAll", selector="tr.zA", limit=50)
        if not result.get("success"):
            print("[X] Could not query email rows.")
            return

        rows = result.get("data", {}).get("elements", [])
        print(f"    Scanning {len(rows)} emails...")

        # Find first email containing the keyword
        match_index = None
        for i, row in enumerate(rows):
            text = row.get("innerText", "").lower()
            if SEARCH_KEYWORD.lower() in text:
                preview = row.get("innerText", "").split("\n")[0:2]
                print(f'    [MATCH] Row {i + 1}: {" - ".join(preview)}')
                match_index = i
                break

        if match_index is None:
            print(f'    [X] No emails with "{SEARCH_KEYWORD}" found.')
            return

        # Step 4: Click to open the email
        # Use CSS-escaped ID selector for Gmail's colon-prefixed IDs
        row_id = rows[match_index].get("id", "")
        if row_id:
            click_selector = f"tr#{escape_css_id(row_id)}"
        else:
            click_selector = f"tr.zA:nth-child({match_index + 1})"

        print(f"\n[4] Opening email...")
        await send(ws, "click", selector=click_selector)

        # Step 5: Wait for email content to load
        await asyncio.sleep(2)
        await send(ws, "waitForSelector", selector=".a3s")

        # Step 6: Extract email details
        #   Gmail DOM selectors:
        #   h2.hP       = Subject line
        #   span.gD     = Sender name (email attr has address)
        #   span.g3     = Date/time
        #   .a3s.aiL    = Email body
        subject = await get_text(ws, "h2.hP")
        sender = await get_text(ws, "span.gD")
        email_addr = await get_attribute(ws, "span.gD", "email")
        date = await get_text(ws, "span.g3")
        body = await get_text(ws, ".a3s.aiL")

        # Step 7: Display results
        print("\n" + "=" * 60)
        print("  EMAIL DETAILS")
        print("=" * 60)
        print(f"\n  Subject:  {subject}")
        print(f"  From:     {sender} <{email_addr}>")
        print(f"  Date:     {date}")
        print(f"\n{'-' * 60}")
        print("  BODY:")
        print(f"{'-' * 60}")

        body_clean = (body or "").strip()
        if body_clean:
            for line in body_clean.split("\n"):
                line = line.strip()
                if line:
                    print(f"  {line}")
        else:
            print("  (empty body)")

        print(f"\n{'=' * 60}")
        print("  Done!")
        print(f"{'=' * 60}")

    finally:
        await ws.close()
        print("\nConnection closed.")


if __name__ == "__main__":
    asyncio.run(main())
