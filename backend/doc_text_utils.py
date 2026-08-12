"""
doc_text_utils.py
-------------------
Downloads and extracts plain text from the PDF/DOCX handouts matched by
drive_documents_utils.py, so their content can be searched (see
GET /api/search-docs in main.py). Text is extracted once per video and
cached in Redis (doc_texts_all — see main.py's module docstring), never
re-extracted unless the matched file changes.

Only PDF is extracted when both PDF and DOCX exist for the same video
(see build_doc_texts_index) — they're the same handout exported twice,
so indexing both would just duplicate every search hit.
"""

import io
import re

from docx import Document as DocxDocument
import pdfplumber

from drive_documents_utils import _get_drive_service

# Strips Hebrew niqqud/cantillation marks (combining marks in this Unicode
# block) so searches match regardless of whether the source document has
# vowel points - e.g. "הֲלָכָה" and "הלכה" become the same string.
_NIQQUD_RE = re.compile(r"[֑-ׇ]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_hebrew(text: str) -> str:
    if not text:
        return ""
    text = _NIQQUD_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _download_file_bytes(service, file_id: str) -> bytes:
    return service.files().get_media(fileId=file_id).execute()


def extract_pdf_text(data: bytes) -> str:
    """
    pdfplumber's own extract_text() lays out characters by ascending
    x-position - correct for LTR text, but for Hebrew (stored in these
    PDFs in pure "visual" order, i.e. the order glyphs are painted
    left-to-right on the page) that produces every line backwards AND
    with word order reversed relative to actual reading order. Confirmed
    empirically against a real handout: a "בס"ד" header and a Hebrew date
    only read correctly once each line's characters are reversed.

    Fix: group this page's characters into lines by vertical position,
    sort each line's characters by ascending x (the visual/painted
    order), then reverse the whole line. This is the standard trick for
    "visual order" Hebrew PDF extraction.

    Known limitation: a line reversed this way also flips any embedded
    LTR run within it (e.g. digits, page numbers) - acceptable here since
    this text only feeds substring search (GET /api/search-docs), not
    verbatim display; the vast majority of a halachic handout is plain
    Hebrew prose, so search-relevant matches are unaffected.
    """
    lines_out = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            chars = sorted(page.chars, key=lambda c: (round(c["top"], 1), c["x0"]))
            current_top = None
            current_line = []
            for c in chars:
                if current_top is None or abs(c["top"] - current_top) > 2.5:
                    if current_line:
                        lines_out.append("".join(x["text"] for x in current_line)[::-1])
                    current_line = [c]
                    current_top = c["top"]
                else:
                    current_line.append(c)
            if current_line:
                lines_out.append("".join(x["text"] for x in current_line)[::-1])
    return "\n".join(lines_out)


def extract_docx_text(data: bytes) -> str:
    doc = DocxDocument(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text)


def extract_document_text(service, doc_entry: dict) -> str:
    """doc_entry: one of documents["pdf"]/documents["docx"] (has file_id)."""
    data = _download_file_bytes(service, doc_entry["file_id"])
    name = doc_entry.get("name", "")
    if name.lower().endswith(".docx"):
        return extract_docx_text(data)
    return extract_pdf_text(data)


def build_doc_texts_index(videos: list, existing: dict, max_new: int | None = None) -> tuple[dict, int]:
    """
    For every video with a `documents` field (see drive_documents_utils.py)
    not already present in `existing` (a {video_id: text} dict, e.g.
    loaded from the doc_texts_all Redis key), downloads and extracts text
    from its handout - PDF preferred over DOCX, since they're the same
    content exported twice.

    max_new caps how many NEW extractions run in this call (a PDF
    download + parse is much heavier than a Drive metadata lookup) - the
    daily sync passes a small cap so it can't blow the Vercel timeout;
    backfill_document_texts.py is meant to run locally/manually without a
    cap to catch up the rest.

    Returns (updated_index, extracted_count). `existing` itself is not
    mutated - callers persist the returned dict.
    """
    index = dict(existing)
    candidates = [
        v for v in videos
        if v.get("documents") and v.get("id") not in index
        and (v["documents"].get("pdf") or v["documents"].get("docx"))
    ]
    if max_new is not None:
        candidates = candidates[:max_new]
    if not candidates:
        return index, 0

    service = _get_drive_service()
    extracted = 0
    for v in candidates:
        docs = v["documents"]
        doc_entry = docs.get("pdf") or docs.get("docx")
        try:
            text = extract_document_text(service, doc_entry)
        except Exception as e:
            print(f"[doc-text] extraction failed for {v.get('id')} "
                  f"({doc_entry.get('name')}): {e}")
            continue
        if text.strip():
            index[v["id"]] = text
            extracted += 1

    return index, extracted
