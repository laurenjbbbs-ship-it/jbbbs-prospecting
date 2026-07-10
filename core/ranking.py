"""The ranking engine: four gates -> segments + priority, plus Lookup.

Gate order (per person, aggregated across sources):
  1. Volunteer?      -> on the list. Nothing else required.
  2. Donor?          -> splits: volunteer+donor = upgrade, volunteer-only = first
                        ask, donor-only = existing donor. All HIGH priority.
  3. Connection only -> board / LinkedIn / attendee, not volunteer or donor.
                        On the list, LOW priority.
  4. No connection   -> off the list. A report-only appearance is NOT a
                        connection; it enriches ranked names and feeds Lookup,
                        but never surfaces a name on its own.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd

from core import db
from core.enrich import life_stage_from_birthday, tier_from_amount, tier_rank
from core.matching import Record, collect_records
from core.normalize import normalize_name

SEGMENT_ORDER = {
    "first ask": 0,
    "upgrade": 1,
    "existing donor": 2,
    "connection only": 3,
}

RANKED_COLUMNS = [
    "name", "segment", "priority", "program", "volunteer_status", "match_history",
    "donor_tier", "amount", "outside_sources", "num_outside_sources", "town",
    "job_title", "industry", "employer", "age_or_life_stage", "spouse_or_household",
    "connection_source", "capacity_hint",
]


# --- tiny union-find for confirmed near-match links ------------------------

class _UF:
    def __init__(self) -> None:
        self.parent: dict[Any, Any] = {}

    def find(self, x: Any) -> Any:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: Any, b: Any) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _first(records: list[Record], sources: list[str], key: str) -> Any:
    """First non-empty payload value for `key` among records in source priority."""
    for src in sources:
        for r in records:
            if r.source == src:
                v = r.payload.get(key)
                if v is not None and str(v).strip() != "":
                    return v
    return None


def build_persons(tables: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    """Aggregate all records into distinct people and apply the four gates."""
    records = collect_records(tables)

    # Common-name safeguard: a normalized name with 2+ distinct cities must not
    # fuse. Key those records by (name, city) so they stay separate people.
    name_cities: dict[str, set[str]] = defaultdict(set)
    for r in records:
        if r.normalized_name and r.city:
            name_cities[r.normalized_name].add(r.city)
    conflict_names = {n for n, c in name_cities.items() if len(c) >= 2}

    def person_key(r: Record) -> tuple[str, str]:
        if r.normalized_name in conflict_names:
            return (r.normalized_name, r.city or "?")
        return (r.normalized_name, "")

    # Merge people the manager confirmed as the same (approved near matches).
    uf = _UF()
    keys = {person_key(r) for r in records}
    for a, b in db.confirmed_links():
        if a == b:
            # Confirmed common-name pair: merge all city-split keys of this name.
            related = [k for k in keys if k[0] == a]
            for k in related[1:]:
                uf.union(related[0], k)
        else:
            ka, kb = (a, ""), (b, "")
            if ka in keys and kb in keys:
                uf.union(ka, kb)

    groups: dict[Any, list[Record]] = defaultdict(list)
    for r in records:
        groups[uf.find(person_key(r))].append(r)

    people: list[dict[str, Any]] = []
    for _, recs in groups.items():
        people.append(_aggregate(recs))
    return people


def _aggregate(recs: list[Record]) -> dict[str, Any]:
    sources = {r.source for r in recs}
    is_vol = "volunteer" in sources
    is_donor = "donor" in sources
    is_conn = bool({"board", "linkedin", "attendee"} & sources)
    report_recs = [r for r in recs if r.source == "report"]

    # Display name: prefer a volunteer/donor label, else anything non-empty.
    label = (_first(recs, ["volunteer", "donor", "board", "attendee", "linkedin", "report"],
                    "first_name") and None)
    label = None
    for src in ["volunteer", "donor", "board", "attendee", "linkedin", "report"]:
        for r in recs:
            if r.source == src and r.label:
                label = r.label
                break
        if label:
            break
    label = label or "(unknown)"

    # --- Gates ---
    if is_vol:
        segment = "upgrade" if is_donor else "first ask"
        priority = "high"
        on_list = True
    elif is_donor:
        segment = "existing donor"
        priority = "high"
        on_list = True
    elif is_conn:
        segment = "connection only"
        priority = "low"
        on_list = True
    else:
        segment = "off-list"     # report-only or nothing: NOT on the ranked list
        priority = None
        on_list = False

    # Volunteer fields.
    program = _first(recs, ["volunteer"], "program")
    status = _first(recs, ["volunteer"], "status")
    closure = _first(recs, ["volunteer"], "match_closure_date")
    length = _first(recs, ["volunteer"], "match_length_months")
    if status == "current":
        match_history = f"Active match ({program})" if program else "Active match"
    elif status == "former":
        bits = []
        if closure:
            bits.append(f"closed {closure}")
        if length:
            bits.append(f"ran {int(length)} mo")
        match_history = "Former: " + ", ".join(bits) if bits else "Former volunteer"
    else:
        match_history = None
    volunteer_status = (f"{status} ({program})" if status and program
                        else status or None)

    # Donor fields.
    donor_tier = _first(recs, ["donor"], "tier")
    amount = _first(recs, ["donor"], "amount")

    # Outside sources (reports, attendee, linkedin) for the multi-source tiebreak.
    outside: list[str] = []
    for r in report_recs:
        agency = r.payload.get("agency") or "report"
        outside.append(f"Report: {agency}")
    if "attendee" in sources:
        ev = _first(recs, ["attendee"], "event_attended")
        outside.append(f"Event: {ev}" if ev else "Event attendee")
    if "linkedin" in sources:
        outside.append("LinkedIn")
    num_outside = len(set(outside))

    # Context fields, from own records (blank for report-only names).
    town = _first(recs, ["volunteer", "donor", "board", "attendee"], "city")
    job_title = _first(recs, ["volunteer", "linkedin"], "job_title") or \
        _first(recs, ["linkedin"], "position")
    industry = _first(recs, ["volunteer"], "industry")
    employer = (_first(recs, ["volunteer"], "employer")
                or _first(recs, ["donor", "attendee"], "organization")
                or _first(recs, ["linkedin"], "company"))
    age_or_life_stage = life_stage_from_birthday(_first(recs, ["volunteer"], "birthday"))
    spouse_or_household = _first(recs, ["volunteer"], "spouse_or_household")

    connection_source = None
    board_member = _first(recs, ["board"], "connecting_board_member")
    if board_member:
        connection_source = f"Board: {board_member}"
    elif "attendee" in sources:
        ev = _first(recs, ["attendee"], "event_attended")
        connection_source = f"Event: {ev}" if ev else "Event"
    elif "linkedin" in sources:
        connection_source = "LinkedIn (Lauren)"

    # Capacity: donor tier first; else a report gift range enriches.
    capacity_hint = None
    if report_recs:
        ranges = [r.payload.get("gift_range") for r in report_recs
                  if r.payload.get("gift_range")]
        if ranges:
            capacity_hint = "; ".join(dict.fromkeys(ranges))
    cap_rank = tier_rank(donor_tier)

    return {
        "name": label,
        "segment": segment,
        "priority": priority,
        "on_list": on_list,
        "program": program,
        "volunteer_status": volunteer_status,
        "match_history": match_history,
        "donor_tier": donor_tier,
        "amount": float(amount) if amount is not None else None,
        "outside_sources": ", ".join(dict.fromkeys(outside)) or None,
        "num_outside_sources": num_outside,
        "town": town,
        "job_title": job_title,
        "industry": industry,
        "employer": employer,
        "age_or_life_stage": age_or_life_stage,
        "spouse_or_household": spouse_or_household,
        "connection_source": connection_source,
        "capacity_hint": capacity_hint,
        # hidden sort helpers
        "_segment_rank": SEGMENT_ORDER.get(segment, 99),
        "_cap_rank": cap_rank,
        "_amount": float(amount) if amount is not None else 0.0,
    }


def build_ranked_list(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return the ranked, on-list people as a display DataFrame.

    Default order: first ask -> upgrade -> existing donor (high) -> connection
    only (low). Within a segment: more outside sources first, then capacity."""
    people = [p for p in build_persons(tables) if p["on_list"]]
    if not people:
        return pd.DataFrame(columns=RANKED_COLUMNS)

    df = pd.DataFrame(people)
    df = df.sort_values(
        by=["_segment_rank", "num_outside_sources", "_cap_rank", "_amount", "name"],
        ascending=[True, False, False, False, True],
    ).reset_index(drop=True)
    return df[RANKED_COLUMNS]


def lookup(tables: dict[str, pd.DataFrame], query: str) -> dict[str, Any]:
    """Return every appearance of a name across all sources (report-only included).

    This is Zack Roe's single-name screen. It intentionally shows names that are
    NOT on the ranked list (e.g. report-only), because the point is to check what
    exists anywhere before onboarding a volunteer."""
    q = normalize_name(query)
    if not q:
        return {"query": query, "normalized": "", "appearances": [], "on_ranked_list": False}

    records = collect_records(tables)
    appearances: list[dict[str, Any]] = []
    for r in records:
        if r.normalized_name == q or (q in r.normalized_name) or (r.normalized_name in q and r.normalized_name):
            detail = {"source": r.source, "name": r.label, "city": r.city}
            if r.source == "donor":
                detail["tier"] = r.payload.get("tier")
                detail["amount"] = r.payload.get("amount")
            if r.source == "volunteer":
                detail["program"] = r.payload.get("program")
                detail["status"] = r.payload.get("status")
            if r.source == "report":
                detail["agency"] = r.payload.get("agency")
                detail["gift_range"] = r.payload.get("gift_range")
            if r.source == "attendee":
                detail["event"] = r.payload.get("event_attended")
            if r.source == "linkedin":
                detail["company"] = r.payload.get("company")
                detail["position"] = r.payload.get("position")
            if r.source == "board":
                detail["board_member"] = r.payload.get("connecting_board_member")
            appearances.append(detail)

    on_ranked = any(
        p["on_list"] for p in build_persons(tables)
        if normalize_name(p["name"]) == q
    )
    return {
        "query": query,
        "normalized": q,
        "appearances": appearances,
        "on_ranked_list": on_ranked,
    }
