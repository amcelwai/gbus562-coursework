# Week 03: RAG Tool for Company Documents

## What was built

[`ask.py`](ask.py) is a command-line tool, built with Claude Code, that answers questions from a folder of company documents using retrieval-augmented generation (RAG):

1. **Chunking:** each document is split into one chunk per section. Every chunk starts with its document's title and section heading and records the file it came from. Sections longer than 400 words are split at paragraph boundaries.
2. **Storage:** the chunks are embedded with Chroma's built-in embedding model and stored in a local Chroma database. Each document folder gets its own database under `week-03/chroma/`, which is kept out of Git.
3. **Retrieval:** for a question, the 4 most similar chunks (by cosine similarity) are retrieved and printed with their rank, similarity score and source file.
4. **Answer:** Claude (`claude-sonnet-5`) answers using only those chunks and cites the source file after every fact. If the chunks don't contain the answer, it says what is missing instead of guessing.

The tool reads HTML, PDF, Markdown, plain-text and Word (.docx) files. If the documents change, it warns that the database is out of date.

## Document sets

| Folder | Company | Contents |
|---|---|---|
| [`copperline-docs/`](copperline-docs/) | Copperline Manufacturing (finance) | Corporate card FAQ, month-end close calendar, purchasing approval matrix, travel expense policy, vendor payment terms (PDF) |
| [`larkfield-docs/`](larkfield-docs/) | Larkfield Credit Union (member services) | Card dispute procedure, consumer fee schedule, fee refund guide, funds availability policy, share certificates |
| [`larkfield-docs-archive/`](larkfield-docs-archive/) | Larkfield Credit Union | The replaced Version 7 fee schedule, kept out of the searched folder (see below) |

## How to run

From the top of the repository, using the repo's `.venv`:

```
.venv/bin/pip install -r week-03/requirements.txt

# Ask about the Copperline documents (the default folder)
.venv/bin/python week-03/ask.py "Can I expense a $70 dinner in Chicago?"

# Ask about another folder, and save the full output to a text file
.venv/bin/python week-03/ask.py --docs week-03/larkfield-docs --save week-03/runs/q1-after.txt "How much is the fee when a member overdraws their checking account?"

# Rebuild a folder's database after adding, removing or editing documents
.venv/bin/python week-03/ask.py --docs week-03/larkfield-docs --rebuild
```

`--save` writes every retrieved chunk in full (rank, similarity score, source file), then a line containing only `ANSWER`, then Claude's answer.

The database for a folder is built automatically the first time it is used. The API key is read at runtime from `API-Key.txt` in the folder that contains the repository, or from the `ANTHROPIC_API_KEY` environment variable. It is never stored in the repository.

## Experiment: an outdated document in the folder

The Larkfield folder originally held two versions of the consumer fee schedule. Both were marked "(current)", but Version 8 (`consumer-fee-schedule.html`) states that it replaces Version 7 (`consumer-fee-schedule-v7.html`). The overdraft fee is $29 in Version 8 and $35 in Version 7.

I asked the same question before and after moving Version 7 to `larkfield-docs-archive/`: *"How much is the fee when a member overdraws their checking account?"*

| | [Before](runs/q1-before.txt): both versions in the folder | [After](runs/q1-after.txt): Version 7 archived |
|---|---|---|
| Retrieved chunks | 2 of 4 from the outdated Version 7; the monthly-fees section was retrieved twice, once from each version | All 4 from Version 8, no duplicates |
| Answer | $29, plus a note that Version 7 says $35 and that it is unclear which version is in effect | $29 with its conditions (three-fee daily cap, no fee if overdrawn by $10 or less), all cited |

**What this showed:**

- An outdated document doesn't just risk a wrong answer. Its near-duplicate chunks also crowd out other results, since only 4 chunks are retrieved.
- Claude reached the right number but claimed the versions were ambiguous. It missed the "Replaces Version 7" line, which sits in each document's header rather than in the chunk text.
- The most reliable fix was cleaning up the source folder, not changing the code: keep only current documents in the folder that gets searched.
- Even after the cleanup, two of the four retrieved chunks (dormant accounts, stop payments) were unrelated to overdrafts. Retrieval always returns 4 chunks; Claude ignored the unrelated ones.

## Reflection

See [`writeup.md`](writeup.md) for my full writeup: what I built, why I chose this chunking approach, an example run (q4), and a reflection on the outdated fee schedule fix and the out-of-scope mortgage question (q6).
