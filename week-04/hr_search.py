"""hr_search.py - semantic search over one organization's HR documents.

An organization folder holds hr-docs/, employees.csv, sample-emails/ and system_prompt.txt.
Call configure(org_dir) before searching; without it, week-04/hartwell-hr is used. Each
organization gets its own Chroma database in week-04/chroma/<folder name>/ (kept out of Git).

Adapted from week-03/ask.py: the same one-chunk-per-section HTML loading, the same Chroma database
with Chroma's built-in embedding model and cosine distance, and the same fingerprint that notices when
documents change. Unlike ask.py it does not call Claude: it only returns the closest chunks, and the
AI app calling the MCP server writes the answer.

Everything is logged to stderr, never stdout, because stdout carries the MCP server's messages.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

WEEK_DIR = Path(__file__).resolve().parent               # .../gbus562-coursework/week-04
DEFAULT_ORG_DIR = WEEK_DIR / "hartwell-hr"
CHROMA_ROOT = WEEK_DIR / "chroma"                        # kept out of Git by week-04/.gitignore

# Set by configure(); the defaults are Hartwell's.
ORG_DIR = DEFAULT_ORG_DIR
DOCS_DIR = ORG_DIR / "hr-docs"
DB_DIR = CHROMA_ROOT / ORG_DIR.name                      # one database per organization
COLLECTION = f"{ORG_DIR.name}-docs"

TOP_K = 4
MAX_CHUNK_WORDS = 400       # a section longer than this is split at paragraph boundaries
SUPPORTED = {".html", ".htm"}

# Short notes added to a chunk whose section depends on a definition given elsewhere in the same
# document, so the chunk still makes sense on its own (same mechanism as week-03/ask.py).
# Key: (file name, section heading). None are needed for the documents so far.
CONTEXT_NOTES: dict[tuple[str, str], str] = {}


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def configure(org_dir: Path) -> None:
    """Point the search at one organization's folder (its hr-docs/ and its own database)."""
    global ORG_DIR, DOCS_DIR, DB_DIR, COLLECTION, _collection
    org_dir = Path(org_dir).resolve()
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", org_dir.name).strip("-_").lower() or "org"
    ORG_DIR = org_dir
    DOCS_DIR = org_dir / "hr-docs"
    DB_DIR = CHROMA_ROOT / slug
    COLLECTION = f"{slug}-docs"[:63]
    _collection = None


# ---------------------------------------------------------------------------
# Document model and HTML loader
# ---------------------------------------------------------------------------

@dataclass
class Section:
    heading: str
    blocks: list[str] = field(default_factory=list)   # paragraphs, or list items written "- item"


@dataclass
class Document:
    source: str                # file name relative to the docs folder
    title: str
    info: str = ""             # version / owner line, if the document has one
    sections: list[Section] = field(default_factory=list)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def load_html(path: Path, source: str) -> Document:
    from bs4 import BeautifulSoup, NavigableString, Tag

    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()

    container = soup.find("main") or soup.find("article") or soup.body or soup
    if container is soup.body or container is soup:
        for tag in container.find_all(["nav", "header", "footer", "aside"]):
            tag.decompose()

    h1 = container.find("h1")
    title = clean(h1.get_text(" ")) if h1 else ""
    if not title and soup.title:
        title = clean(soup.title.get_text(" ").split("|")[0])
    title = title or path.stem.replace("-", " ").title()

    meta = container.find(class_="meta")
    info = clean(meta.get_text(" ")) if meta else ""

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
            else:
                add_block(child.get_text(" "))

    walk(container)
    if current.blocks:
        doc.sections.append(current)
    return doc


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def document_files() -> list[Path]:
    return [p for p in sorted(DOCS_DIR.iterdir())
            if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in SUPPORTED]


def build_chunks() -> tuple[list[str], list[str], list[dict]]:
    ids, texts, metadatas = [], [], []
    for path in document_files():
        source = path.name
        try:
            doc = load_html(path, source)
        except Exception as exc:   # one unreadable file should not stop the whole build
            log(f"  skipped (could not read {source}: {exc})")
            continue
        n_before = len(ids)
        for s_idx, section in enumerate(doc.sections):
            note = CONTEXT_NOTES.get((source, section.heading), "")
            parts: list[list[str]] = [[]]
            for block in section.blocks:
                if parts[-1] and len(" ".join(parts[-1] + [block]).split()) > MAX_CHUNK_WORDS:
                    parts.append([])
                parts[-1].append(block)
            for p_idx, blocks in enumerate(parts):
                heading = section.heading + (f" (part {p_idx + 1} of {len(parts)})" if len(parts) > 1 else "")
                body = "\n".join(([note] if note else []) + blocks)
                ids.append(f"{source}::{s_idx:03d}-{p_idx:02d}")
                texts.append(f"Document: {doc.title}\nSection: {heading}\n\n{body}")
                metadatas.append({"source": source, "title": doc.title, "section": heading, "doc_info": doc.info})
        log(f"  {source}: {len(ids) - n_before} chunks")
    return ids, texts, metadatas


# ---------------------------------------------------------------------------
# Chroma database
# ---------------------------------------------------------------------------

def fingerprint() -> str:
    """Changes whenever an HR document is added, removed, or edited."""
    h = hashlib.sha256()
    for path in document_files():
        st = path.stat()
        h.update(f"{path.name}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()[:16]


def _client():
    import chromadb
    from chromadb.config import Settings

    DB_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(DB_DIR), settings=Settings(anonymized_telemetry=False))


def build_index(client=None):
    """(Re)build the database from the documents and return the collection."""
    client = client or _client()
    if COLLECTION in [c if isinstance(c, str) else c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION)
    log(f"Building the search database from {DOCS_DIR} ...")
    ids, texts, metadatas = build_chunks()
    if not ids:
        raise RuntimeError(f"No readable HR documents found in {DOCS_DIR}.")
    collection = client.create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine", "docs_fingerprint": fingerprint()},
    )   # no embedding function given, so Chroma uses its built-in default model
    # Keep stdout clean: the first build may download the embedding model and print progress.
    with contextlib.redirect_stdout(sys.stderr):
        collection.add(ids=ids, documents=texts, metadatas=metadatas)
    log(f"Stored {len(ids)} chunks in {DB_DIR.relative_to(WEEK_DIR.parent)} (collection '{COLLECTION}').")
    return collection


_collection = None


def get_index(rebuild: bool = False):
    """Return the collection, building it if it is missing, empty, rebuild is asked for, or the documents changed."""
    global _collection
    if _collection is not None and not rebuild:
        if (_collection.metadata or {}).get("docs_fingerprint") == fingerprint():
            return _collection
        log("HR documents changed since the database was built; rebuilding.")
        rebuild = True
    client = _client()
    if rebuild:
        _collection = build_index(client)
        return _collection
    try:
        collection = client.get_collection(COLLECTION)
    except Exception:
        collection = None
    if (collection is None or collection.count() == 0
            or (collection.metadata or {}).get("docs_fingerprint") != fingerprint()):
        collection = build_index(client)
    _collection = collection
    return _collection


def search(query: str, k: int = TOP_K) -> list[dict]:
    """Return the k chunks closest to the query, most similar first."""
    collection = get_index()
    with contextlib.redirect_stdout(sys.stderr):
        result = collection.query(query_texts=[query], n_results=min(k, collection.count()))
    return [
        {"source": meta["source"], "document": meta.get("title", ""), "section": meta.get("section", ""),
         "document_info": meta.get("doc_info", ""), "similarity": round(1 - distance, 3), "text": text}
        for text, meta, distance in zip(result["documents"][0], result["metadatas"][0], result["distances"][0])
    ]
