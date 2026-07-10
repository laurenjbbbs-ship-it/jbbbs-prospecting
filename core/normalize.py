"""Name normalization — the single join key across every source.

Rules (from the spec): lowercase, trim, collapse whitespace, convert
"Last, First" to "First Last", strip suffixes (Jr, Sr, II, III, IV) and
punctuation, fold accents.
"""
from __future__ import annotations

import re
import unicodedata

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_PUNCT_RE = re.compile(r"[^\w\s]")  # drop punctuation, keep word chars + spaces
_WS_RE = re.compile(r"\s+")


def _fold_accents(text: str) -> str:
    """Café -> cafe. Decompose then drop combining marks."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_name(raw: str | None) -> str:
    """Return the canonical form used for matching. Empty string if no input."""
    if not raw:
        return ""
    text = str(raw).strip()

    # "Last, First" -> "First Last" (only when a single comma splits two parts).
    if "," in text:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) == 2 and parts[0] and parts[1]:
            text = f"{parts[1]} {parts[0]}"

    text = _fold_accents(text)
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)          # punctuation -> space
    tokens = _WS_RE.sub(" ", text).strip().split(" ")
    tokens = [t for t in tokens if t and t not in _SUFFIXES]
    return " ".join(tokens)


def normalize_from_parts(first: str | None, last: str | None) -> str:
    """Normalize a first + last pair (the common CSV case)."""
    first = (first or "").strip()
    last = (last or "").strip()
    return normalize_name(f"{first} {last}".strip())


def last_name_key(normalized: str) -> str:
    """Last token of a normalized name — used to group near matches."""
    if not normalized:
        return ""
    return normalized.split(" ")[-1]


def first_initial(normalized: str) -> str:
    """First letter of a normalized name — used to group near matches."""
    if not normalized:
        return ""
    return normalized[0]
