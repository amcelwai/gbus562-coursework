## What I Built
I built ask.py, a command-line RAG tool that answers staff questions from a folder of company documents. It splits each document into one chunk per section, stores the chunks in a local Chroma database, retrieves the 4 most similar chunks for a question, and has Claude (claude-sonnet-5) answer from those chunks only, citing the source file for every fact. To make it work with Larkfield Credit Union's documents as well as Copperline's, ask.py takes a --docs option that names the document folder (Copperline stays the default), keeps a separate Chroma database for each folder (kept out of Git), and has a --save option that writes the full retrieved chunks and Claude's answer to a text file. I saved seven runs on the Larkfield documents in week-03/runs: the overdraft-fee question before and after removing an outdated fee schedule (q1-before.txt and q1-after.txt), then rush delivery for a replacement debit card (q2), liability for a lost card reported the same day (q3), refunding an international wire fee (q4), next-day availability of a deposited paycheck (q5), and a 30-year mortgage rate that the documents don't cover (q6).

## Why This Approach
Chunking method: structure
Makes sense on its own: Partly, because each chunk starts with "Document:" and "Section:" lines, so a chunk such as "Fee Refund Guide for Member Service Staff / Refunds that need a branch manager" reads on its own, but the version number is not in the chunk text: in q1-before.txt the Version 7 and Version 8 fee schedule chunks both begin "Document: Consumer Fee Schedule", so only the source file name tells them apart.
Label and source: Both, because build_chunks in ask.py starts every chunk's text with the document title and section heading and stores the file name in the chunk's metadata, and every saved run shows both: each chunk is listed with "source: <file name>" above its "Document:" and "Section:" lines.
Short enough: Yes, because my longest Larkfield chunk, the "Overdraft and returned item fees" section of consumer-fee-schedule.html, is 117 words including its two label lines (107 words of body text), well under the roughly 190-word limit, and the 30 Larkfield chunks range from 31 to 117 words.

## Example Run
```text
#1  similarity 0.640  source: consumer-fee-schedule.html
Document: Consumer Fee Schedule
Section: Wire transfers

- Incoming domestic wire transfer: $10.
- Incoming international wire transfer: $15.
- Outgoing domestic wire transfer: $25.
- Outgoing international wire transfer: $45. The receiving bank or an intermediary bank may deduct its own fees from the amount sent.

#2  similarity 0.603  source: fee-refund-guide.html
Document: Fee Refund Guide for Member Service Staff
Section: Refunds that need a branch manager

A refund needs the branch manager's approval when the fee is more than $30, when the member has already had a refund in the last 90 days, or when the member asks for several fees to be refunded at once. A branch manager may approve refunds of up to $150 in total for one member in any 90-day period.

#3  similarity 0.574  source: fee-refund-guide.html
Document: Fee Refund Guide for Member Service Staff
Section: What a member service representative can approve

A member service representative may approve a refund of a single fee of $30 or less without anyone else's approval. A representative may approve only one refund for the same member in any 90-day period.

#4  similarity 0.493  source: fee-refund-guide.html
Document: Fee Refund Guide for Member Service Staff
Section: Refunds that need the Member Services Director

Refunds of more than $150 in total for one member in any 90-day period need the Member Services Director's approval. So does any refund for a business account.

ANSWER
No — a member service representative cannot approve this without manager approval.

The outgoing international wire transfer fee is $45 [consumer-fee-schedule.html]. A representative may only approve a refund of a single fee of $30 or less without anyone else's approval [fee-refund-guide.html]. Since $45 exceeds $30, the refund needs the branch manager's approval [fee-refund-guide.html].
```

## Reflection
What was wrong: consumer-fee-schedule-v7.html, an outdated Version 7 fee schedule that Version 8 (consumer-fee-schedule.html) replaces, was still in the searched folder. In q1-before.txt, 2 of the 4 retrieved chunks came from it: #2, an overdraft section saying $35 per item and up to four fees a day (similarity 0.700), and #3, a copy of the "Checking account monthly fees" section that also appeared as #4 from Version 8 (both 0.639). Claude gave the right $29 fee but added that it was unclear which version was in effect. In q1-after.txt, all 4 chunks came from consumer-fee-schedule.html, with no duplicates, and the answer gave $29 with no conflict.
How I fixed it: Moved consumer-fee-schedule-v7.html out of week-03/larkfield-docs into week-03/larkfield-docs-archive and rebuilt the database for week-03/larkfield-docs, which went from 39 chunks to 30.
Prevention: Archive process, meaning that whenever Larkfield publishes a new version of a document, the document's owner moves the old version into an archive folder that the tool does not search and rebuilds the database the same day, because Version 7 was left in place still labeled "(current)".
Question 6: Declined, because retrieval returned four unrelated chunks (share certificate dividend rates and maturity, stop payments, and checking account monthly fees) with similarity scores from 0.187 to 0.246, far below the 0.529 to 0.707 of the top chunks in my other runs, and Claude said it could not answer from those sources.
