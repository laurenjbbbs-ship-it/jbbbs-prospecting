"""Cross-source matching: confident vs. near matches, and the common-name safeguard.

- Confident: normalized names identical AND context (city) does not conflict.
  These aggregate into one person automatically (handled in ranking.py).
- Near: same last name + same first initial, names not identical. Routed to the
  Review Matches queue. Never merged automatically.
- Common-name safeguard: same normalized name but conflicting city. Routed to
  review, never fused. City is the tiebreaker context.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from core import db
from core.normalize import first_initial, last_name_key


# Sources that make someone a real person-record for matching/ranking.
VOLUNTEER_SOURCES = {"volunteer"}
DONOR_SOURCES = {"donor"}
CONNECTION_SOURCES = {"board", "linkedin", "attendee"}


@dataclass
class Record:
    source: str            # volunteer | donor | attendee | linkedin | board | report
    label: str             # display name from the raw row
    normalized_name: str
    city: str | None
    payload: dict[str, Any] = field(default_factory=dict)


def _label(first: Any, last: Any, fallback: Any = "") -> str:
    parts = [str(first or "").strip(), str(last or "").strip()]
    name = " ".join(p for p in parts if p)
    return name or str(fallback or "").strip()


def collect_records(tables: dict[str, pd.DataFrame]) -> list[Record]:
    """Flatten every source into a uniform list of person-records.

    Only committed + confirmed report names are included (report-only names still
    participate so they can be matched and appear in Lookup — but the ranking gate
    keeps report-only people off the ranked list)."""
    records: list[Record] = []

    for _, r in tables.get("volunteers", pd.DataFrame()).iterrows():
        records.append(Record("volunteer", _label(r.get("first_name"), r.get("last_name")),
                              r.get("normalized_name") or "", _clean(r.get("city")),
                              r.to_dict()))
    for _, r in tables.get("donors", pd.DataFrame()).iterrows():
        records.append(Record("donor", _label(r.get("first_name"), r.get("last_name")),
                              r.get("normalized_name") or "", _clean(r.get("city")),
                              r.to_dict()))
    for _, r in tables.get("attendees", pd.DataFrame()).iterrows():
        records.append(Record("attendee", _label(r.get("first_name"), r.get("last_name")),
                              r.get("normalized_name") or "", _clean(r.get("city")),
                              r.to_dict()))
    for _, r in tables.get("linkedin", pd.DataFrame()).iterrows():
        records.append(Record("linkedin", _label(r.get("first_name"), r.get("last_name")),
                              r.get("normalized_name") or "", None, r.to_dict()))
    for _, r in tables.get("board_connections", pd.DataFrame()).iterrows():
        records.append(Record("board", _label(r.get("first_name"), r.get("last_name")),
                              r.get("normalized_name") or "", _clean(r.get("city")),
                              r.to_dict()))

    # Committed + confirmed report names.
    report_names = tables.get("report_names", pd.DataFrame())
    reports = tables.get("reports", pd.DataFrame())
    if not report_names.empty and not reports.empty:
        committed = set(reports.loc[reports["status"] == "committed", "id"].tolist())
        for _, r in report_names.iterrows():
            if r.get("report_id") in committed and bool(r.get("confirmed")):
                agency = ""
                match = reports.loc[reports["id"] == r.get("report_id"), "agency"]
                if not match.empty:
                    agency = str(match.iloc[0] or "")
                records.append(Record(
                    "report", str(r.get("raw_name") or ""),
                    r.get("normalized_name") or "", None,
                    {"gift_range": r.get("gift_range"), "agency": agency},
                ))
    return records


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def refresh_review_queue(tables: dict[str, pd.DataFrame]) -> dict[str, int]:
    """Scan all records and enqueue near matches + common-name conflicts.

    Idempotent: db.upsert_near_match skips pairs already queued or decided.
    Returns counts of newly considered items by kind."""
    records = collect_records(tables)
    counts = {"near": 0, "common_name": 0}

    # --- Common-name safeguard: same normalized name, conflicting city. ---
    by_name: dict[str, list[Record]] = {}
    for rec in records:
        if rec.normalized_name:
            by_name.setdefault(rec.normalized_name, []).append(rec)

    for name, recs in by_name.items():
        cities = {rec.city for rec in recs if rec.city}
        if len(cities) >= 2:
            # Pair the first city's record against each other distinct city.
            ordered = sorted(cities)
            base = next(r for r in recs if r.city == ordered[0])
            for other_city in ordered[1:]:
                other = next(r for r in recs if r.city == other_city)
                db.upsert_near_match({
                    "kind": "common_name",
                    "left_source": base.source, "left_label": base.label,
                    "left_city": base.city,
                    "right_source": other.source, "right_label": other.label,
                    "right_city": other.city,
                    "norm_a": name, "norm_b": name,
                })
                counts["common_name"] += 1

    # --- Near matches: same last name + first initial, names not identical. ---
    by_key: dict[tuple[str, str], list[Record]] = {}
    for rec in records:
        if rec.normalized_name:
            key = (last_name_key(rec.normalized_name), first_initial(rec.normalized_name))
            by_key.setdefault(key, []).append(rec)

    seen_pairs: set[tuple[str, str]] = set()
    for _, recs in by_key.items():
        for i in range(len(recs)):
            for j in range(i + 1, len(recs)):
                a, b = recs[i], recs[j]
                if a.normalized_name == b.normalized_name:
                    continue  # identical -> confident, not a near match
                pair = tuple(sorted([a.normalized_name, b.normalized_name]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                db.upsert_near_match({
                    "kind": "near",
                    "left_source": a.source, "left_label": a.label, "left_city": a.city,
                    "right_source": b.source, "right_label": b.label, "right_city": b.city,
                    "norm_a": a.normalized_name, "norm_b": b.normalized_name,
                })
                counts["near"] += 1

    return counts
