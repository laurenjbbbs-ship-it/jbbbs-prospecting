"""CSV ingestion: guess a column mapping, let the user confirm, then import.

Re-import fully replaces that source's table. Mappings are saved per source and
reused silently on later imports.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

import pandas as pd

from core import db
from core.config import PROGRAM_BY_SOURCE_LABEL, SOURCE_FIELD_SYNONYMS
from core.enrich import tier_from_amount
from core.normalize import normalize_from_parts

# Logical source key -> destination table.
SOURCE_TO_TABLE = {
    "matchforce": "volunteers",
    "salesforce": "volunteers",
    "donors": "donors",
    "attendees": "attendees",
    "linkedin": "linkedin",
    "board": "board_connections",
}

SOURCE_LABELS = {
    "matchforce": "MatchForce (Mentorship volunteers)",
    "salesforce": "Salesforce (Friendship volunteers)",
    "donors": "Donor list",
    "attendees": "Event attendees",
    "linkedin": "LinkedIn connections",
    "board": "Board connections",
}


def table_for(source_key: str) -> str:
    return SOURCE_TO_TABLE[source_key]


def guess_mapping(source_key: str, headers: list[str]) -> dict[str, str]:
    """Pre-select a source header for each canonical field from header text."""
    table = table_for(source_key)
    synonyms = SOURCE_FIELD_SYNONYMS[table]
    lowered = {h.lower().strip(): h for h in headers}
    mapping: dict[str, str] = {}
    for field, options in synonyms.items():
        for opt in options:
            if opt in lowered:
                mapping[field] = lowered[opt]
                break
        else:
            # loose contains match
            for low, original in lowered.items():
                if any(opt in low for opt in options):
                    mapping[field] = original
                    break
    return mapping


def _parse_date(value: Any) -> _dt.date | None:
    if value is None or str(value).strip() == "":
        return None
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return _dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _months_between(start: _dt.date | None, end: _dt.date | None) -> int | None:
    if not start:
        return None
    end = end or _dt.date.today()
    return max(0, (end.year - start.year) * 12 + (end.month - start.month))


def _col(row: pd.Series, mapping: dict[str, str], field: str) -> Any:
    src = mapping.get(field)
    if not src:
        return None
    value = row.get(src)
    if pd.isna(value):
        return None
    return value


def build_rows(source_key: str, df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """Transform a raw CSV into rows matching the destination table's schema."""
    table = table_for(source_key)
    out: list[dict[str, Any]] = []

    for _, row in df.iterrows():
        first = _col(row, mapping, "first_name")
        last = _col(row, mapping, "last_name")
        norm = normalize_from_parts(
            str(first) if first is not None else "",
            str(last) if last is not None else "",
        )
        if not norm:
            continue

        if table == "volunteers":
            match_date = _parse_date(_col(row, mapping, "match_date"))
            closure = _parse_date(_col(row, mapping, "match_closure_date"))
            status = "former" if closure else "current"
            out.append({
                "first_name": first, "last_name": last,
                "email": _col(row, mapping, "email"),
                "program": PROGRAM_BY_SOURCE_LABEL.get(source_key),
                "status": status,
                "city": _col(row, mapping, "city"),
                "birthday": _col(row, mapping, "birthday"),
                "match_date": str(match_date) if match_date else None,
                "match_closure_date": str(closure) if closure else None,
                "match_length_months": _months_between(match_date, closure),
                "job_title": _col(row, mapping, "job_title"),
                "industry": _col(row, mapping, "industry"),
                "employer": _col(row, mapping, "employer"),
                "spouse_or_household": _col(row, mapping, "spouse_or_household"),
                "normalized_name": norm,
            })
        elif table == "donors":
            last_gift = _to_float(_col(row, mapping, "last_gift"))
            out.append({
                "first_name": first, "last_name": last,
                "email": _col(row, mapping, "email"),
                "organization": _col(row, mapping, "organization"),
                "city": _col(row, mapping, "city"),
                "first_gift": _to_float(_col(row, mapping, "first_gift")),
                "last_gift": last_gift,
                "average_gift": _to_float(_col(row, mapping, "average_gift")),
                "tier": tier_from_amount(last_gift),
                "amount": last_gift,
                "normalized_name": norm,
            })
        elif table == "attendees":
            out.append({
                "first_name": first, "last_name": last,
                "email": _col(row, mapping, "email"),
                "organization": _col(row, mapping, "organization"),
                "city": _col(row, mapping, "city"),
                "event_attended": _col(row, mapping, "event_attended"),
                "normalized_name": norm,
            })
        elif table == "linkedin":
            out.append({
                "first_name": first, "last_name": last,
                "email": _col(row, mapping, "email"),
                "company": _col(row, mapping, "company"),
                "position": _col(row, mapping, "position"),
                "connected_date": _col(row, mapping, "connected_date"),
                "normalized_name": norm,
            })
        elif table == "board_connections":
            out.append({
                "first_name": first, "last_name": last,
                "connecting_board_member": _col(row, mapping, "connecting_board_member"),
                "city": _col(row, mapping, "city"),
                "normalized_name": norm,
            })

    return pd.DataFrame(out)


def _to_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def import_csv(source_key: str, df: pd.DataFrame, mapping: dict[str, str]) -> int:
    """Transform + replace the source's rows. Saves the mapping. Returns rows.

    MatchForce and Salesforce share the volunteers table, so each replaces only
    its own program's rows rather than the whole table."""
    rows = build_rows(source_key, df, mapping)
    where = None
    if source_key in PROGRAM_BY_SOURCE_LABEL:
        where = {"program": PROGRAM_BY_SOURCE_LABEL[source_key]}
    count = db.replace_source_table(table_for(source_key), rows, where)
    db.save_mapping(source_key, mapping)
    return count
