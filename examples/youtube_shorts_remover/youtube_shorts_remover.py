"""
StealthDOM Example: YouTube Shorts Remover

This script connects to StealthDOM and continuously removes YouTube Shorts
from the homepage, search results, and subscription feed. It runs as a
background process, polling every few seconds to catch dynamically loaded
Shorts as you scroll.

How it works:
- Uses the 'removeByText' DOM command (no JavaScript eval needed)
- This bypasses YouTube's Trusted Types CSP that blocks script execution
- Targets shelf/section renderers whose text content starts with "Shorts"

Prerequisites:
- Bridge server running (python bridge_server.py)
- StealthDOM extension loaded in browser
- A YouTube tab open in the browser

Usage:
    python youtube_shorts_remover.py
"""

import asyncio
import json
import sys
import uuid
import websockets

# Fix Windows terminal encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BRIDGE_URL = "ws://127.0.0.1:9878"
POLL_INTERVAL = 3  # seconds between scans


async def send(ws, action, **kwargs):
    """Send a command to StealthDOM and return the result."""
    msg_id = str(uuid.uuid4())[:8]
    msg = {"action": action, "_timeout": 10, "_msg_id": msg_id, **kwargs}
    await ws.send(json.dumps(msg))
    while True:
        response = json.loads(await ws.recv())
        if response.pop("_msg_id", None) == msg_id:
            return response


def log(msg):
    """Print with flush for real-time output."""
    print(msg, flush=True)


async def remove_shorts(ws, tab_id):
    """Remove all Shorts elements from the current YouTube page.
    
    Returns the number of elements removed.
    """
    total = 0

    # 1. Homepage & subscription feed: ytd-rich-shelf-renderer and
    #    ytd-rich-section-renderer with "Shorts" in their text
    for selector in ["ytd-rich-shelf-renderer", "ytd-rich-section-renderer"]:
        result = await send(
            ws, "removeByText",
            selector=selector,
            texts=["Shorts"],
            tabId=tab_id
        )
        if result.get("success"):
            count = result.get("data", {}).get("removed", 0)
            total += count

    # 2. Search results: Shorts shelves (multiple possible element types)
    for selector in ["ytd-reel-shelf-renderer", "grid-shelf-view-model"]:
        result = await send(
            ws, "removeByText",
            selector=selector,
            texts=["Shorts"],
            tabId=tab_id
        )
        if result.get("success"):
            total += result.get("data", {}).get("removed", 0)

    # 3. Sidebar Shorts link
    result = await send(
        ws, "removeByText",
        selector="ytd-guide-entry-renderer",
        texts=["Shorts"],
        tabId=tab_id
    )
    if result.get("success"):
        total += result.get("data", {}).get("removed", 0)

    # 4. Mini sidebar Shorts link
    result = await send(
        ws, "removeByText",
        selector="ytd-mini-guide-entry-renderer",
        texts=["Shorts"],
        tabId=tab_id
    )
    if result.get("success"):
        total += result.get("data", {}).get("removed", 0)

    # 5. Individual Shorts in search results — these are regular video
    #    renderers but with a "SHORTS" badge on the thumbnail
    result = await send(
        ws, "removeByChildText",
        parentSelector="ytd-video-renderer",
        childSelector="ytd-thumbnail-overlay-time-status-renderer",
        texts=["SHORTS"],
        tabId=tab_id
    )
    if result.get("success"):
        total += result.get("data", {}).get("removed", 0)

    # 6. Shorts in the watch page sidebar suggestions
    result = await send(
        ws, "removeByChildText",
        parentSelector="ytd-compact-video-renderer",
        childSelector="ytd-thumbnail-overlay-time-status-renderer",
        texts=["SHORTS"],
        tabId=tab_id
    )
    if result.get("success"):
        total += result.get("data", {}).get("removed", 0)

    # 5. Individual Shorts in search results — the SHORTS badge text
    #    is part of the parent ytd-video-renderer's innerText
    result = await send(
        ws, "removeByText",
        selector="ytd-video-renderer",
        texts=["SHORTS"],
        tabId=tab_id
    )
    if result.get("success"):
        total += result.get("data", {}).get("removed", 0)

    # 6. Shorts in the watch page sidebar suggestions
    result = await send(
        ws, "removeByText",
        selector="ytd-compact-video-renderer",
        texts=["SHORTS"],
        tabId=tab_id
    )
    if result.get("success"):
        total += result.get("data", {}).get("removed", 0)

    return total


async def main():
    log("=" * 60)
    log("  StealthDOM Example: YouTube Shorts Remover")
    log("=" * 60)
    log(f"\nConnecting to StealthDOM bridge at {BRIDGE_URL}...")

    ws = await websockets.connect(BRIDGE_URL)
    total_removed = 0

    try:
        log("[OK] Connected!")
        log(f"[*] Polling every {POLL_INTERVAL}s. Press Ctrl+C to stop.")
        log("[*] Open YouTube in your browser to start removing Shorts.\n")

        while True:
            # Check which tab is active and if it's YouTube
            tabs_result = await send(ws, "listTabs")
            if not tabs_result.get("success"):
                await asyncio.sleep(POLL_INTERVAL)
                continue

            tabs = tabs_result.get("data", [])
            if isinstance(tabs, dict):
                tabs = tabs.get("tabs", [])
            youtube_tabs = [
                t for t in tabs
                if t.get("active") and "youtube.com" in (t.get("url") or "")
            ]

            if not youtube_tabs:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # Switch to the YouTube tab (ensures commands target it)
            tab_id = youtube_tabs[0]["id"]
            await send(ws, "switchTab", tabId=tab_id)

            # Remove Shorts elements
            count = await remove_shorts(ws, tab_id)

            if count > 0:
                total_removed += count
                log(f"[REMOVED] Hid {count} Shorts element(s)  (total: {total_removed})")

            await asyncio.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        log(f"\n[*] Stopped. Total Shorts elements removed: {total_removed}")
    finally:
        await ws.close()
        log("Connection closed.")


if __name__ == "__main__":
    asyncio.run(main())
