# Example: YouTube Shorts Remover

## The Prompt

> "Create a script that uses StealthDOM so that when I browse YouTube, it automatically removes all the short video suggestions from search results or the main page."

The agent explored YouTube's DOM, discovered the elements used for Shorts across different page types, and built a background polling script that continuously cleans them out as the user browses.

## What the AI Agent Did

### 1. Explored YouTube's DOM

The agent navigated to YouTube and queried the page to find Shorts elements:

```
browser_list_tabs()                                     # Discover tab IDs
browser_navigate(tab_id, "https://www.youtube.com")
browser_query_all(tab_id, "ytd-rich-shelf-renderer", limit=5)
```

This revealed that homepage Shorts appear as `ytd-rich-shelf-renderer` elements with "Shorts" as their title text.

### 2. Tested on Search Results

The agent then navigated to search results and discovered a different element type:

```
browser_navigate(tab_id, "https://www.youtube.com/results?search_query=...")
browser_query_all(tab_id, "ytd-item-section-renderer #contents > *", limit=5)
```

Search results use `grid-shelf-view-model` — a newer YouTube element that wasn't caught by the initial approach. The agent updated the script to target both.

### 3. Chose the Right Tool

YouTube enforces **Trusted Types CSP**, which historically blocked `eval()` and dynamic script injection. StealthDOM solves this by automatically stripping CSP headers on page load, so `browser_evaluate()` now works on YouTube too.

However, for simple element removal, the agent chose StealthDOM's `removeByText` command — a lightweight approach that operates directly on the DOM through the content script without needing JavaScript evaluation.

### 4. Built a Background Poller

Since YouTube dynamically loads content as you scroll, a one-time cleanup isn't enough. The script runs as a continuous background process that:

1. Checks if the active browser tab is YouTube
2. Removes all Shorts elements (shelves, grids, sidebar links, individual short videos)
3. Waits 3 seconds and repeats
4. Catches newly loaded Shorts as the user scrolls or navigates

### 5. Targets These Elements

| Selector | Location |
|----------|----------|
| `ytd-rich-shelf-renderer` | Shorts shelves on the homepage |
| `ytd-rich-section-renderer` | Shorts sections in subscription feed |
| `grid-shelf-view-model` | Shorts grids in search results |
| `ytd-reel-shelf-renderer` | Legacy Shorts reel shelves |
| `ytd-guide-entry-renderer` | "Shorts" link in the sidebar |
| `ytd-mini-guide-entry-renderer` | "Shorts" icon in the collapsed sidebar |
| `ytd-video-renderer` | Individual Shorts in search results |
| `ytd-compact-video-renderer` | Shorts in the watch page sidebar |

## Output

```
============================================================
  StealthDOM Example: YouTube Shorts Remover
============================================================

Connecting to StealthDOM bridge at ws://127.0.0.1:9878...
[OK] Connected!
[*] Polling every 3s. Press Ctrl+C to stop.
[*] Open YouTube in your browser to start removing Shorts.

[REMOVED] Hid 2 Shorts element(s)  (total: 2)
[REMOVED] Hid 1 Shorts element(s)  (total: 3)
[REMOVED] Hid 9 Shorts element(s)  (total: 12)
[REMOVED] Hid 4 Shorts element(s)  (total: 16)
[REMOVED] Hid 4 Shorts element(s)  (total: 20)
[REMOVED] Hid 11 Shorts element(s)  (total: 31)
[REMOVED] Hid 6 Shorts element(s)  (total: 37)
[REMOVED] Hid 4 Shorts element(s)  (total: 41)
[REMOVED] Hid 2 Shorts element(s)  (total: 43)
```

During a live test session, the script removed **49 Shorts elements** as the user browsed YouTube — across the homepage, search results, and while scrolling.

## Why This Matters

1. **Works on YouTube** — YouTube's Trusted Types CSP historically blocked `eval()` and script injection. StealthDOM strips CSP headers automatically, so both `evaluate` and native DOM commands work. This example uses `removeByText` as a lightweight, targeted approach.

2. **No dedicated extension needed** — Most "remove Shorts" solutions require installing a Chrome extension. This is a simple Python script you start and stop at will.

3. **Real-time cleanup** — YouTube dynamically loads Shorts as you scroll. The polling approach catches new ones every 3 seconds, so the page stays clean.

4. **AI-generated** — The agent discovered all the DOM selectors, chose the right tool for the job, adapted when search results used different elements than the homepage, and built the entire script autonomously.

## Running It

```bash
# Make sure bridge is running
python bridge_server.py

# Run the Shorts remover (runs until you press Ctrl+C)
python examples/youtube_shorts_remover/youtube_shorts_remover.py
```

Prerequisites:
- Bridge server running
- StealthDOM extension loaded
- YouTube open in your browser
