"""PDF report ingestion.

Try text extraction with PyMuPDF first. If a page yields little/no text it is
scanned: render it to an image and OCR with Tesseract. Detect a gift range near
each name where present. Names are NOT committed here; they go to the review
queue on the Upload page and commit only after the manager confirms them.
"""
from __future__ import annotations

import io
import re
from typing import Any

import fitz  # PyMuPDF

from core.config import get_tesseract_cmd
from core.normalize import normalize_name

# A gift range like "$1,000-$4,999", "$10,000+", "$500 – $999".
_RANGE_RE = re.compile(
    r"\$\s?[\d,]+(?:\s*(?:[-–—to]+)\s*\$?\s?[\d,]+|\s*\+)?", re.IGNORECASE
)
# Lines that are section headers / boilerplate, not people.
_SKIP_WORDS = re.compile(
    r"\b(honor roll|donors?|report|annual|thank|gift|giving|society|circle|"
    r"list|members?|supporters?|contributors?|foundation|fund|campaign)\b",
    re.IGNORECASE,
)
_TEXT_THRESHOLD = 30  # chars per page below which we treat the page as scanned


def _ocr_page(page: "fitz.Page") -> str:
    import pytesseract
    from PIL import Image

    cmd = get_tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    pix = page.get_pixmap(dpi=300)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img)


def extract(file_bytes: bytes) -> dict[str, Any]:
    """Return {is_scanned, page_count, names, ocr_error}.

    If a page is scanned but Tesseract is unavailable (e.g. not installed on a
    local machine), OCR is skipped for that page and `ocr_error` explains why,
    rather than crashing. On the host, Tesseract is present so OCR runs."""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    scanned_pages = 0
    all_text_parts: list[str] = []
    ocr_error: str | None = None

    for page in doc:
        text = page.get_text().strip()
        if len(text) < _TEXT_THRESHOLD:
            scanned_pages += 1
            try:
                text = _ocr_page(page)
            except Exception as exc:  # Tesseract missing or OCR failure
                ocr_error = (
                    "This PDF is scanned and needs OCR, but the OCR engine "
                    "(Tesseract) is not available in this environment. "
                    f"({type(exc).__name__})"
                )
                text = ""
        all_text_parts.append(text)

    is_scanned = scanned_pages > 0
    names = _parse_names("\n".join(all_text_parts))
    return {
        "is_scanned": is_scanned,
        "page_count": doc.page_count,
        "names": names,
        "ocr_error": ocr_error,
    }


def _looks_like_name(text: str) -> bool:
    tokens = [t for t in re.split(r"\s+", text.strip()) if t]
    if len(tokens) < 2 or len(tokens) > 5:
        return False
    # at least two tokens with letters
    lettery = [t for t in tokens if re.search(r"[A-Za-z]", t)]
    return len(lettery) >= 2


def _parse_names(text: str) -> list[dict[str, Any]]:
    current_range: str | None = None
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw_line in text.splitlines():
        line = raw_line.strip(" \t•-*")
        if not line:
            continue

        range_match = _RANGE_RE.search(line)
        line_no_range = _RANGE_RE.sub("", line).strip(" \t.–—-:")

        # A line that is essentially just a gift range = a section header.
        if range_match and not line_no_range:
            current_range = _clean_range(range_match.group(0))
            continue

        if _SKIP_WORDS.search(line) and not range_match:
            continue

        name = line_no_range
        if not _looks_like_name(name):
            continue

        norm = normalize_name(name)
        if not norm or norm in seen:
            continue
        seen.add(norm)

        gift_range = _clean_range(range_match.group(0)) if range_match else current_range
        out.append({
            "raw_name": name,
            "normalized_name": norm,
            "gift_range": gift_range,
        })
    return out


def _clean_range(text: str) -> str:
    return re.sub(r"\s+", " ", text).replace(" +", "+").strip()
