# Week 02: Prompt Lab

## Assignment

Use Claude Code to build a Prompt Lab: a single-file web app in plain JavaScript for testing prompts against Claude through the Anthropic API. It runs by opening the file in a browser, with no server.

## What was built

[`prompt-lab.html`](prompt-lab.html) is a prompt-testing app built with Claude Code:

- **Model:** `claude-sonnet-5`, shown at the top of the page.
- **API key field:** password-style. The key is held only in the open page's memory and is never saved or written to any file, so it's pasted in each time the page is opened.
- **System prompt:** an optional box whose text stays in place after sending.
- **Prompt box:** clears after each send. Ctrl/Cmd + Enter also sends.
- **Conversation log:** a scrollable log that labels every message System, You or Claude and keeps line breaks in replies. Each prompt is sent with the full conversation so far, so the log shows exactly what Claude sees.
- **System prompt changes:** if the system prompt is changed mid-conversation, the log notes the change and shows the new text.
- **Waiting and errors:** a "Claude is responding..." indicator shows while waiting. Any error appears in the log, and the failed prompt is put back in the prompt box so it can be retried.
- **New Conversation:** clears the log and starts fresh.
- **Export:** downloads the conversation as a Markdown file, with the model name on the first line and each message under a `### System`, `### You` or `### Claude` heading.

## How to run

1. Download `prompt-lab.html` and open it in any web browser. No installation or server is needed.
2. Paste an Anthropic API key into the API key field.
3. Optionally add a system prompt, then type a prompt and press **Send**.

The page calls the Anthropic API directly from the browser, so the key is inside the page while it's open. That's fine for personal use, but never host this page publicly with a key built in.

## Testing

Claude checked the page's JavaScript for syntax errors, and scanned every file and all commit history to confirm that no API key was saved in the repository. The app had not yet been tested against the live API when it was committed.

## Reflection

_Add your notes here: what worked well, what you would change in the prompt, and what you learned about working with an AI coding assistant._
