# Example: Google Voice SMS Sender

## The Prompt

> "Create a script that uses StealthDOM to send SMS messages through Google Voice. It should take a phone number and message as arguments."

The agent explored Google Voice's DOM, found the message input and send button selectors, and built a command-line tool that navigates to the right conversation thread and sends a message — just like a human would.

## What the AI Agent Did

### 1. Explored Google Voice's DOM

The agent navigated to Google Voice and identified the key UI elements:

```
browser_list_tabs()                                                            # Discover tab IDs
browser_query_all(tab_id, "textarea, input[type=text], [contenteditable=true]")
browser_query(tab_id, "button.send-button")
```

This revealed:
- **Message input**: `textarea.message-input` — a standard textarea for composing messages
- **Send button**: `button.send-button` — disabled until text is entered, then enabled automatically
- **New message button**: `div.threads-button` — opens a new conversation with a recipient input

### 2. Discovered the URL Pattern

Google Voice uses predictable URL patterns for conversations:

```
https://voice.google.com/u/0/messages?itemId=t.+15551234567   (full US number)
https://voice.google.com/u/0/messages?itemId=t.69525           (short code)
```

By navigating directly to the URL, the agent skips the need to search through the conversation list.

### 3. Built the Send Flow

The script follows this sequence:
1. Connect to StealthDOM via WebSocket
2. Find or open a Google Voice tab
3. Navigate to the conversation URL for the target number
4. Wait for the message input to appear
5. Click, type the message, verify the send button is enabled
6. Click send and confirm delivery

### 4. Handles Multiple Number Formats

The script normalizes phone numbers automatically:

| Input | Normalized |
|-------|------------|
| `5551234567` | `+15551234567` |
| `15551234567` | `+15551234567` |
| `+15551234567` | `+15551234567` |
| `69525` | `69525` (short code) |

## Output

```
============================================================
  StealthDOM Example: Google Voice SMS Sender
============================================================

  To:      697326
  Message: Hello from the StealthDOM SMS example script!

Connecting to StealthDOM bridge at ws://127.0.0.1:9878...
[OK] Connected!

[1] Finding Google Voice tab...
  [OK] Switched to existing Google Voice tab

[2] Opening conversation with 697326...
  [*] Opening conversation: 697326
  [OK] Conversation loaded

[3] Sending message...

============================================================
  MESSAGE SENT SUCCESSFULLY!
============================================================

  To:      697326
  Message: Hello from the StealthDOM SMS example script!

============================================================

Connection closed.
```

## Why This Matters

1. **Real browser session** — Uses your existing Google Voice login. No API keys, no OAuth setup, no Google Cloud project required.

2. **Works with any number format** — Full international numbers, 10-digit US numbers, and short codes all work. The script normalizes them automatically.

3. **Undetectable** — The message is sent through the real Google Voice web interface, indistinguishable from a human typing and clicking.

4. **Simple CLI interface** — Pass a phone number and message as arguments. Easy to integrate into shell scripts, cron jobs, or other automation.

5. **AI-generated** — The agent discovered all the DOM selectors, URL patterns, and the send flow autonomously.

## Running It

```bash
# Make sure bridge is running
python bridge_server.py

# Send an SMS
python examples/google_voice_sms/google_voice_sms.py +15551234567 "Hello from StealthDOM!"

# Works with different number formats
python examples/google_voice_sms/google_voice_sms.py 5551234567 "Meeting at 3pm"
python examples/google_voice_sms/google_voice_sms.py 69525 "Test"
```

Prerequisites:
- Bridge server running
- StealthDOM extension loaded
- Logged into Google Voice in your browser
