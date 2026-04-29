# StealthDOM Examples

These examples demonstrate how an **AI agent used StealthDOM to autonomously build working automation scripts** — without any prior knowledge of the target websites.

In each case, the agent was given a plain-English prompt (e.g., *"remove Shorts from YouTube"*) and used StealthDOM's tools to:

1. **Explore the page** — query the DOM, read element attributes, test selectors
2. **Discover the interaction pattern** — find buttons, inputs, navigation flows
3. **Handle obstacles** — adapt when elements used unexpected structures or different selectors across page types
4. **Build a working script** — produce a standalone Python tool that anyone can run

The resulting scripts are included here as reference implementations. They show what's possible when you give an AI agent the ability to see and interact with a real browser.

## Available Examples

| Example | Description |
|---------|-------------|
| [**Gmail Inbox Reader**](gmail_read_inbox/) | Navigates to Gmail, searches for emails by keyword, opens the first match, and extracts subject, sender, date, and full body text |
| [**YouTube Shorts Remover**](youtube_shorts_remover/) | Continuously polls YouTube and removes all Shorts elements from the homepage, search results, and sidebar as you browse |
| [**Google Voice SMS Sender**](google_voice_sms/) | Sends SMS messages through Google Voice — takes a phone number and message as CLI arguments |
| [**Grok Chat**](grok_chat/) | Sends a query to Grok (xAI) and extracts the response — handles X OAuth sign-in, contenteditable input, and streaming response detection |

> [!TIP]
> See also: **[WebAIInvestigations](../../WebAIInvestigations/)** — a standalone project that systematically reverse-engineers every major AI chat platform (ChatGPT, Gemini, Claude, Copilot, DeepSeek, Grok) using StealthDOM.

## Important Disclaimer

> [!WARNING]
> **These scripts interact with live web pages through the browser's UI, not through official APIs.** They work by clicking buttons, typing into fields, and reading DOM elements — exactly like a human would.
>
> This means they are **inherently fragile**:
>
> - **DOM changes will break them.** When Google, YouTube, or any site updates their HTML structure, class names, or element IDs, these scripts will stop working until the selectors are updated.
> - **They are not production-grade.** These are demonstrations, not reliable integrations. For mission-critical automation, always prefer official APIs when available.
> - **They depend on your login session.** The scripts use whatever account is currently logged in to the browser. They cannot authenticate on their own.
>
> The real value here isn't the scripts themselves — it's the **process**. An AI agent can re-discover the DOM structure and rebuild these scripts in minutes whenever a site changes. That's the power of StealthDOM: giving AI agents eyes and hands inside a real browser.

## Running Any Example

All examples follow the same prerequisites:

```bash
# 1. Start the bridge server
python bridge_server.py

# 2. Make sure the StealthDOM extension is loaded and enabled in your browser

# 3. Run the example
python examples/<example_folder>/<script>.py
```

Each example's own `README.md` contains the specific prompt that was given to the AI agent, a walkthrough of how it discovered the solution, and usage instructions.
