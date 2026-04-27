# Example: Gmail Inbox Reader

## The Prompt

> "Use StealthDOM to create a standalone script that can go to Gmail, find the first email that contains the word 'reward' in the subject, open it, and show the subject, from, date, and body."

That's it. That was the entire instruction given to an AI agent (Antigravity IDE with StealthDOM MCP). The agent did everything else on its own.

## What the AI Agent Did

### 1. Explored the DOM

The agent used StealthDOM's MCP tools to navigate to Gmail and inspect the page structure:

```
browser_navigate("https://mail.google.com/mail/u/0/#inbox")
browser_wait_for("tr.zA")                    # Wait for email rows to appear
browser_query_all("tr.zA", limit=10)         # Get inbox rows and inspect their structure
```

Each email row (`tr.zA`) contains the sender, subject, snippet, and date as inner text. The agent discovered this by reading the DOM — no documentation or prior knowledge of Gmail's internal selectors was needed.

### 2. Found the Right Email

The agent scanned the `innerText` of each row looking for the keyword "reward":
```
Row 1: "Citibank Rewards - Your Citibank Rewards Order"  → MATCH
```

### 3. Opened the Email

Gmail uses colon-prefixed IDs like `:2e` which need CSS escaping. The agent clicked the matching row:

```
browser_click("tr#\:2e")
browser_wait_for(".a3s")    # Wait for email body to render
```

### 4. Extracted the Details

The agent discovered Gmail's DOM selectors by querying elements inside the opened email:

| Selector | Content |
|----------|---------|
| `h2.hP` | Subject line |
| `span.gD` | Sender display name |
| `span.gD[email]` | Sender email address (HTML attribute) |
| `span.g3` | Date and time |
| `.a3s.aiL` | Email body content |

### 5. Wrote the Python Script

Based on its exploration, the agent wrote `gmail_read_inbox.py` — a standalone Python script that uses StealthDOM's WebSocket API to replicate the entire workflow. The script was tested, debugged (CSS escaping, response parsing, Windows encoding), and finalized.

## Output

```
============================================================
  StealthDOM Example: Gmail Inbox Reader
============================================================

Connecting to StealthDOM bridge at ws://127.0.0.1:9878...

[1] Navigating to Gmail...
[2] Waiting for inbox to load...
[OK] Inbox loaded!

[3] Searching for emails with "reward" in the subject...
    Scanning 50 emails...
    [MATCH] Row 1: Citibank Rewards - Your Citibank Rewards Order

[4] Opening email...

============================================================
  EMAIL DETAILS
============================================================

  Subject:  Your Citibank Rewards Order
  From:     Citibank Rewards <rewards@notifications.citibank.com>
  Date:     Tue, Apr 21, 10:15 AM (5 days ago)

------------------------------------------------------------
  BODY:
------------------------------------------------------------
  Thank you for your Citibank Rewards redemption order!
  We're happy you're enjoying your cashback rewards...
  Order Confirmation Number: CTB-20260421-7842
  Order Date: 4/21/2026
  Total Redeemed: $35.00
  Remaining Balance: $142.50

============================================================
  Done!
============================================================
```

## Why This Matters

1. **No API setup needed** — Gmail has an API, but it requires OAuth credentials, Google Cloud project setup, and scope approvals. StealthDOM skips all of that — it just uses the session already open in your browser.

2. **Undetectable** — The script runs through a real browser extension. Gmail sees normal browser activity, not bot automation.

3. **AI-generated** — The entire Python script was written and tested by an AI agent in real-time. The human only described what they wanted; the agent figured out Gmail's DOM structure, handled edge cases, and produced working code.

4. **Reusable** — Change `SEARCH_KEYWORD` at the top of the script to search for any term. The same pattern works for any web application.

## Running It

```bash
# Make sure bridge is running
python bridge_server.py

# Run the example (from the StealthDOM root directory)
python examples/gmail_read_inbox/gmail_read_inbox.py
```

Prerequisites:
- Bridge server running
- StealthDOM extension loaded
- Logged into Gmail in your browser
