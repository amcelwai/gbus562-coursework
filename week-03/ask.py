#!/usr/bin/env python3
"""ask.py - answer questions about a folder of documents with retrieval-augmented generation (RAG).

How it works:
  1. Every document in the folder is split into one chunk per section. Each chunk starts with its
     document's title and section heading, and records which file it came from.
  2. The chunks are stored in a local Chroma database, embedded with Chroma's built-in embedding
     model. Each document folder gets its own database under week-03/chroma/ (kept out of Git).
  3. For a question, the 4 most similar chunks are retrieved and printed.
  4. Claude answers from those chunks only, citing the source file for each fact.

Usage (from the top of the repository):
  .venv/bin/python week-03/ask.py "Can I expense a $70 dinner in Chicago?"
  .venv/bin/python week-03/ask.py --rebuild                  # after adding or removing documents
  .venv/bin/python week-03/ask.py --docs week-03/other-docs "Question"
  .venv/bin/python week-03/ask.py --save week-03/runs/q1.txt "Question"

Supported file types: .html/.htm, .pdf, .md/.markdown, .txt, .docx. Other files are skipped with a warning.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent            # .../gbus562-coursework/week-03
REPO_ROOT = SCRIPT_DIR.parent                            # .../gbus562-coursework
KEY_DIR = REPO_ROOT.parent                               # folder that contains the repository
KEY_FILENAME = "API-Key.txt"                             # matched without regard to upper/lower case
DEFAULT_DOCS = SCRIPT_DIR / "copperline-docs"
DB_ROOT = SCRIPT_DIR / "chroma"     # one database per document folder inside; kept out of Git by week-03/.gitignore

MODEL = "claude-sonnet-5"
TOP_K = 4
PREVIEW_CHARS = 150
MAX_CHUNK_WORDS = 400       # a section longer than this is split at paragraph boundaries

SUPPORTED = {".html", ".htm", ".pdf", ".md", ".markdown", ".txt", ".docx"}

# Short notes added to chunks whose section depends on a definition given elsewhere in the same
# document, so the chunk still makes sense on its own. Key: (file name, section heading), where
# "*" as the heading means "every section of that file except the one the note came from".
# Add entries here when new documents have the same problem.
CONTEXT_NOTES: dict[tuple[str, str], str] = {
    ("month-end-close-calendar.html", "*"): (
        "Note: deadlines are counted in business days. Business day 1 is the first business day of "
        "the new month; business day minus 1 is the last business day of the month being closed."
    ),
    ("travel-expense-policy.html", "Hotels"): (
        "Note: Tier 1 cities are New York, San Francisco, Boston, Chicago, Washington DC, Los Angeles, "
        "and Seattle. Tier 2 cities are every other city in the United States."
    ),
}
# The sections the "*" notes were taken from (they already contain the definition).
NOTE_SOURCE_SECTIONS = {("month-end-close-calendar.html", "How the close calendar works")}

SYSTEM_PROMPT = """You answer employees' questions using only the source excerpts provided in the \
user's message. Each excerpt is wrapped in a <source> tag whose "file" attribute names the document \
it came from.

Rules:
- Use only facts stated in the sources. Do not add outside knowledge, assumptions, or general advice.
- After every fact you state, cite the source file it came from in square brackets, for example \
[travel-expense-policy.html].
- Sections sometimes refer to other sections or documents. Combine sources when the question needs it.
- If the sources do not contain the answer, or contain only part of it, say so plainly and name \
what is missing. Do not guess.
- Keep the answer short and direct: lead with the answer, then the supporting detail."""


# ---------------------------------------------------------------------------
# Document model
# ---------------------------------------------------------------------------

@dataclass
class Section:
    heading: str
    blocks: list[str] = field(default_factory=list)   # paragraphs, or list items written "- item"


@dataclass
class Document:
    source: str                # file path relative to the docs folder
    title: str
    info: str = ""             # version / owner line, if the document has one
    sections: list[Section] = field(default_factory=list)


@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def title_from_filename(path: Path) -> str:
    return path.stem.replace("-", " ").replace("_", " ").strip().title()


# ---------------------------------------------------------------------------
# Loaders: one per file type, each returning a Document
# ---------------------------------------------------------------------------

def load_html(path: Path, source: str) -> Document:
    from bs4 import BeautifulSoup, NavigableString, Tag

    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()

    container = soup.find("main") or soup.find("article") or soup.body or soup
    if container is soup.body or container is soup:
        # No <main>: drop page furniture such as navigation, banners and footers.
        for tag in container.find_all(["nav", "header", "footer", "aside"]):
            tag.decompose()

    h1 = container.find("h1")
    title = clean(h1.get_text(" ")) if h1 else ""
    if not title and soup.title:
        title = clean(soup.title.get_text(" ").split("|")[0])
    title = title or title_from_filename(path)

    meta = container.find(class_="meta")
    info = clean(meta.get_text(" ")) if meta else ""

    # Split at the highest heading level below <h1> that the page uses (usually <h2>).
    split_level = next((lvl for lvl in ("h2", "h3", "h4") if container.find(lvl)), None)
    doc = Document(source=source, title=title, info=info)
    current = Section(heading="Overview")

    def add_block(text: str) -> None:
        text = clean(text)
        if text:
            current.blocks.append(text)

    def walk(node: Tag) -> None:
        nonlocal current
        for child in node.children:
            if isinstance(child, NavigableString):
                add_block(str(child))
                continue
            if not isinstance(child, Tag) or child is h1 or child is meta:
                continue
            name = child.name
            if name == split_level:
                if current.blocks:
                    doc.sections.append(current)
                current = Section(heading=clean(child.get_text(" ")))
            elif name in ("ul", "ol"):
                for li in child.find_all("li", recursive=False):
                    add_block("- " + li.get_text(" "))
            elif name == "table":
                for row in child.find_all("tr"):
                    cells = [clean(c.get_text(" ")) for c in row.find_all(["th", "td"])]
                    add_block(" | ".join(c for c in cells if c))
            elif name in ("div", "section", "article", "main", "header"):
                walk(child)
            else:   # p, lower-level headings, blockquote, pre, dl, ...
                add_block(child.get_text(" "))

    walk(container)
    if current.blocks:
        doc.sections.append(current)
    return doc


def load_pdf(path: Path, source: str) -> Document:
    """Rebuild headings and paragraphs from a PDF using font size and weight, since PDF text has no tags."""
    import pdfplumber

    lines = []   # each: dict(text, size, bold, top, page)
    with pdfplumber.open(path) as pdf:
        meta_title = clean((pdf.metadata or {}).get("Title", "") or "")
        for page_no, page in enumerate(pdf.pages):
            words = page.extract_words(extra_attrs=["size", "fontname"], use_text_flow=True)
            footer_line = page.height - 45     # running footers / page numbers live below this
            for word in words:
                if word["top"] > footer_line:
                    continue
                if lines and lines[-1]["page"] == page_no and abs(lines[-1]["top"] - word["top"]) < 2:
                    line = lines[-1]
                    line["text"] += " " + word["text"]
                    line["sizes"].append(round(word["size"], 1))
                    line["bold"].append("bold" in word["fontname"].lower())
                else:
                    lines.append({"text": word["text"], "sizes": [round(word["size"], 1)],
                                  "bold": ["bold" in word["fontname"].lower()],
                                  "top": word["top"], "bottom": word["bottom"], "page": page_no})
                lines[-1]["bottom"] = max(lines[-1]["bottom"], word["bottom"])

    if not lines:
        raise ValueError("no extractable text (a scanned PDF would need OCR)")

    for line in lines:
        line["size"] = Counter(line["sizes"]).most_common(1)[0][0]
        line["is_bold"] = sum(line["bold"]) > len(line["bold"]) / 2

    # The most common font size (weighted by words) is the body text size.
    body_size = Counter(s for line in lines for s in line["sizes"]).most_common(1)[0][0]

    def is_heading(line: dict) -> bool:
        text = line["text"]
        if len(text) > 90 or text.endswith((".", ",", ";", ":")):
            return False
        return line["size"] >= body_size * 1.15 or (line["is_bold"] and line["size"] >= body_size)

    # Title, first choice: a line matching the PDF's metadata title or one part of it
    # (e.g. "Vendor Payment Terms | Copperline Manufacturing" -> "Vendor Payment Terms").
    # Parts are tried in order, because titles put the document name first ("Document | Company").
    title_parts = [meta_title] + [clean(p) for p in re.split(r"\s+[|–—-]\s+", meta_title) if clean(p)]
    heading_idxs = [i for i, l in enumerate(lines) if is_heading(l)]
    title_idx = next((i for part in title_parts if part
                      for i in heading_idxs[:5] if lines[i]["text"] == part), None)
    if title_idx is None and heading_idxs:
        # Fallback: section headings share the most common heading size. The title is the last line
        # larger than that before the first section heading (letterhead such as a company name sits above it).
        section_size = Counter(lines[i]["size"] for i in heading_idxs).most_common(1)[0][0]
        first_section = next((i for i in heading_idxs if lines[i]["size"] == section_size), len(lines))
        bigger = [i for i in heading_idxs if i < first_section and lines[i]["size"] > section_size]
        title_idx = bigger[-1] if bigger else None
    title = lines[title_idx]["text"] if title_idx is not None else (meta_title or title_from_filename(path))

    doc = Document(source=source, title=title)
    current: Section | None = None
    # Plain lines above the title (e.g. "Finance Department, Accounts Payable") describe the owner.
    info_lines: list[str] = [l["text"] for l in lines[:title_idx or 0] if not is_heading(l)]
    prev = None
    start = (title_idx + 1) if title_idx is not None else 0

    for line in lines[start:]:
        if is_heading(line):
            if current and current.blocks:
                doc.sections.append(current)
            current = Section(heading=line["text"])
            prev = None
            continue
        if current is None:            # text between the title and the first section heading
            info_lines.append(line["text"])
            continue
        starts_bullet = line["text"][:1] in "•-–*▪"
        new_paragraph = (
            prev is None
            or starts_bullet
            or line["page"] != prev["page"] and prev["text"].endswith(".")
            or line["page"] == prev["page"] and line["top"] - prev["bottom"] > line["size"] * 0.9
        )
        if new_paragraph:
            text = "- " + line["text"].lstrip("•-–*▪ ") if starts_bullet else line["text"]
            current.blocks.append(text)
        else:
            last = current.blocks[-1]
            current.blocks[-1] = last[:-1] + line["text"] if last.endswith("-") and line["text"][:1].islower() \
                else last + " " + line["text"]
        prev = line

    if current and current.blocks:
        doc.sections.append(current)
    doc.info = "; ".join(clean(l) for l in info_lines if clean(l))
    return doc


def load_markdown(path: Path, source: str) -> Document:
    text = path.read_text(encoding="utf-8", errors="replace")
    heading_re = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
    levels = [len(m.group(1)) for line in text.splitlines() if (m := heading_re.match(line))]
    title_level = min(levels) if levels else None
    split_level = min((lvl for lvl in levels if lvl > title_level), default=None) if levels else None

    doc = Document(source=source, title=title_from_filename(path))
    current = Section(heading="Overview")
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            current.blocks.append(clean(" ".join(paragraph)))
            paragraph.clear()

    for line in text.splitlines():
        m = heading_re.match(line)
        if m and len(m.group(1)) == title_level and split_level is not None:
            flush()
            doc.title = clean(m.group(2))
        elif m and len(m.group(1)) == (split_level or title_level):
            flush()
            if current.blocks:
                doc.sections.append(current)
            current = Section(heading=clean(m.group(2)))
        elif not line.strip():
            flush()
        elif re.match(r"^\s*([-*+]|\d+[.)])\s+", line):
            flush()
            current.blocks.append("- " + clean(re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", line)))
        else:
            paragraph.append(line.strip())
    flush()
    if current.blocks:
        doc.sections.append(current)
    return doc


def load_text(path: Path, source: str) -> Document:
    text = path.read_text(encoding="utf-8", errors="replace")
    paragraphs = [clean(p) for p in re.split(r"\n\s*\n", text) if clean(p)]
    return Document(source=source, title=title_from_filename(path),
                    sections=[Section(heading="Full text", blocks=paragraphs)] if paragraphs else [])


def load_docx(path: Path, source: str) -> Document:
    import docx

    d = docx.Document(str(path))
    paras = [(p.style.name if p.style is not None else "", clean(p.text)) for p in d.paragraphs]
    paras = [(style, text) for style, text in paras if text]

    def heading_level(style: str) -> int | None:
        if style == "Title":
            return 0
        m = re.match(r"Heading (\d)", style)
        return int(m.group(1)) if m else None

    levels = sorted({lvl for style, _ in paras if (lvl := heading_level(style)) is not None})
    title_level = levels[0] if levels else None
    split_level = levels[1] if len(levels) > 1 else None

    doc = Document(source=source, title=title_from_filename(path))
    current = Section(heading="Overview")
    for style, text in paras:
        lvl = heading_level(style)
        if lvl is not None and lvl == title_level and split_level is not None:
            doc.title = text
        elif lvl is not None and lvl == (split_level if split_level is not None else title_level):
            if current.blocks:
                doc.sections.append(current)
            current = Section(heading=text)
        elif "List" in style:
            current.blocks.append("- " + text)
        else:
            current.blocks.append(text)
    for table in d.tables:
        for row in table.rows:
            current.blocks.append(" | ".join(clean(c.text) for c in row.cells if clean(c.text)))
    if current.blocks:
        doc.sections.append(current)
    return doc


LOADERS = {
    ".html": load_html, ".htm": load_html, ".pdf": load_pdf,
    ".md": load_markdown, ".markdown": load_markdown, ".txt": load_text, ".docx": load_docx,
}


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def context_note(filename: str, heading: str) -> str:
    if (filename, heading) in CONTEXT_NOTES:
        return CONTEXT_NOTES[(filename, heading)]
    if (filename, "*") in CONTEXT_NOTES and (filename, heading) not in NOTE_SOURCE_SECTIONS:
        return CONTEXT_NOTES[(filename, "*")]
    return ""


def document_files(docs_dir: Path) -> tuple[list[Path], list[Path]]:
    files, skipped = [], []
    for path in sorted(docs_dir.rglob("*")):
        rel = path.relative_to(docs_dir)
        if not path.is_file() or any(part.startswith((".", "~$")) for part in rel.parts):
            continue
        (files if path.suffix.lower() in SUPPORTED else skipped).append(path)
    return files, skipped


def build_chunks(docs_dir: Path) -> list[Chunk]:
    files, skipped = document_files(docs_dir)
    for path in skipped:
        print(f"  skipped (unsupported file type): {path.relative_to(docs_dir)}")

    chunks: list[Chunk] = []
    for path in files:
        source = path.relative_to(docs_dir).as_posix()
        try:
            doc = LOADERS[path.suffix.lower()](path, source)
        except Exception as exc:   # one unreadable file should not stop the whole build
            print(f"  skipped (could not read {source}: {exc})")
            continue

        n_before = len(chunks)
        for s_idx, section in enumerate(doc.sections):
            note = context_note(path.name, section.heading)
            # Group the section's blocks into parts of at most MAX_CHUNK_WORDS words (never splitting a block).
            parts: list[list[str]] = [[]]
            for block in section.blocks:
                if parts[-1] and len(" ".join(parts[-1] + [block]).split()) > MAX_CHUNK_WORDS:
                    parts.append([])
                parts[-1].append(block)
            for p_idx, blocks in enumerate(parts):
                heading = section.heading + (f" (part {p_idx + 1} of {len(parts)})" if len(parts) > 1 else "")
                body = "\n".join(([note] if note else []) + blocks)
                text = f"Document: {doc.title}\nSection: {heading}\n\n{body}"
                chunks.append(Chunk(
                    id=f"{source}::{s_idx:03d}-{p_idx:02d}",
                    text=text,
                    metadata={"source": source, "title": doc.title, "section": heading, "doc_info": doc.info},
                ))
        print(f"  {source}: {len(chunks) - n_before} chunks")
    return chunks


# ---------------------------------------------------------------------------
# Chroma database
# ---------------------------------------------------------------------------

def fingerprint(docs_dir: Path) -> str:
    """Changes whenever a supported document is added, removed, or edited."""
    h = hashlib.sha256()
    for path in document_files(docs_dir)[0]:
        st = path.stat()
        h.update(f"{path.relative_to(docs_dir).as_posix()}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()[:16]


def collection_name(docs_dir: Path) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", docs_dir.name).strip("-_") or "docs"
    return (name + "-chunks")[:63] if len(name) >= 3 else f"docs-{name}-chunks"


def db_dir(docs_dir: Path) -> Path:
    """The folder holding this document folder's own Chroma database, e.g. week-03/chroma/larkfield-docs-1a2b3c4d.
    The short hash of the full path keeps two folders with the same name apart."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", docs_dir.name).strip("-_") or "docs"
    return DB_ROOT / f"{slug}-{hashlib.sha256(str(docs_dir).encode()).hexdigest()[:8]}"


def open_db(docs_dir: Path):
    import chromadb
    from chromadb.config import Settings

    path = db_dir(docs_dir)
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path), settings=Settings(anonymized_telemetry=False))


def build_collection(client, docs_dir: Path):
    name = collection_name(docs_dir)
    if name in [c if isinstance(c, str) else c.name for c in client.list_collections()]:
        client.delete_collection(name)
    print(f"Building the database from {docs_dir} ...")
    chunks = build_chunks(docs_dir)
    if not chunks:
        sys.exit(f"No readable documents found in {docs_dir}.")
    collection = client.create_collection(
        name=name,
        metadata={"hnsw:space": "cosine", "docs_fingerprint": fingerprint(docs_dir)},
    )   # no embedding function given, so Chroma uses its built-in default model
    collection.add(ids=[c.id for c in chunks], documents=[c.text for c in chunks],
                   metadatas=[c.metadata for c in chunks])
    print(f"Stored {len(chunks)} chunks in {db_dir(docs_dir).relative_to(REPO_ROOT)} (collection '{name}').\n")
    return collection


def get_collection(client, docs_dir: Path, rebuild: bool):
    name = collection_name(docs_dir)
    if rebuild:
        return build_collection(client, docs_dir)
    try:
        collection = client.get_collection(name)
    except Exception:
        return build_collection(client, docs_dir)   # first run for this folder
    if collection.count() == 0:
        return build_collection(client, docs_dir)
    if (collection.metadata or {}).get("docs_fingerprint") != fingerprint(docs_dir):
        print("Warning: documents in this folder changed since the database was built. "
              "Run again with --rebuild to include the changes.\n")
    return collection


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------

def read_api_key() -> str:
    """Read the key from API-Key.txt next to the repository (any capitalisation), else ANTHROPIC_API_KEY."""
    matches = [p for p in KEY_DIR.iterdir() if p.is_file() and p.name.lower() == KEY_FILENAME.lower()]
    if matches:
        key = matches[0].read_text(encoding="utf-8").strip()
        if key:
            return key
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    sys.exit(f"No API key found: expected {KEY_FILENAME} in {KEY_DIR} or the ANTHROPIC_API_KEY variable.")


def ask_claude(question: str, hits: list[dict]) -> str:
    import anthropic

    sources = "\n\n".join(
        f'<source file="{h["source"]}" document_info="{h["doc_info"]}">\n{h["text"]}\n</source>' for h in hits
    )
    user_message = f"<sources>\n{sources}\n</sources>\n\nQuestion: {question}"
    client = anthropic.Anthropic(api_key=read_api_key())

    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for text in stream.text_stream:
                print(text, end="", flush=True)
            final = stream.get_final_message()
    except anthropic.AuthenticationError:
        sys.exit("\nClaude rejected the API key. Check the key file.")
    except anthropic.NotFoundError:
        sys.exit(f"\nModel '{MODEL}' was not found for this API key.")
    except anthropic.RateLimitError:
        sys.exit("\nRate limited by the Claude API. Wait a moment and try again.")
    except anthropic.APIStatusError as exc:
        sys.exit(f"\nClaude API error {exc.status_code}: {exc.message}")
    except anthropic.APIConnectionError:
        sys.exit("\nCould not reach the Claude API. Check your internet connection.")
    print()

    answer = "".join(b.text for b in final.content if b.type == "text")
    if final.stop_reason == "refusal":
        answer += "\n[Claude declined to answer this question.]"
        print("[Claude declined to answer this question.]")
    elif final.stop_reason == "max_tokens":
        answer += "\n[Answer cut off at the length limit.]"
        print("[Answer cut off at the length limit.]")
    return answer


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Answer questions about a folder of documents using RAG and Claude.")
    parser.add_argument("question", nargs="*", help="the question to ask (quote it)")
    parser.add_argument("--docs", type=Path, default=DEFAULT_DOCS,
                        help="document folder (default: week-03/copperline-docs)")
    parser.add_argument("--rebuild", action="store_true",
                        help="rebuild the database from the documents (after adding or removing files)")
    parser.add_argument("--save", type=Path, help="also write the retrieved chunks and the answer to this text file")
    args = parser.parse_args()

    docs_dir = args.docs.resolve()
    if not docs_dir.is_dir():
        sys.exit(f"Document folder not found: {args.docs}")
    question = " ".join(args.question).strip()
    if not question and not args.rebuild:
        parser.error("give a question, or use --rebuild")

    client = open_db(docs_dir)
    collection = get_collection(client, docs_dir, args.rebuild)
    if not question:
        return

    result = collection.query(query_texts=[question], n_results=min(TOP_K, collection.count()))
    hits = [
        {"text": text, "source": meta["source"], "doc_info": meta.get("doc_info", ""),
         "similarity": 1 - distance}       # cosine distance -> cosine similarity
        for text, meta, distance in zip(result["documents"][0], result["metadatas"][0], result["distances"][0])
    ]

    report = [f"Question: {question}", "", f"Top {len(hits)} retrieved chunks:"]
    for rank, h in enumerate(hits, 1):
        preview = clean(h["text"])[:PREVIEW_CHARS]
        report += [f"#{rank}  similarity {h['similarity']:.3f}  source: {h['source']}", f"    {preview}..."]
    print("\n".join(report))
    print("\nANSWER")
    answer = ask_claude(question, hits)

    if args.save:
        # Saved file: every retrieved chunk in full (rank, similarity, source), then a line "ANSWER", then the answer.
        saved = []
        for rank, h in enumerate(hits, 1):
            saved += [f"#{rank}  similarity {h['similarity']:.3f}  source: {h['source']}", h["text"].strip(), ""]
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text("\n".join(saved) + "\nANSWER\n" + answer.strip() + "\n", encoding="utf-8")
        print(f"\nSaved to {args.save}")


if __name__ == "__main__":
    main()
