"""Derived fields: donor tier from last gift, and age/life-stage from birthday."""
from __future__ import annotations

import datetime as _dt
import re


def tier_from_amount(amount: float | int | None) -> str | None:
    """Donor tier, set by the LAST gift amount (per the spec)."""
    if amount is None:
        return None
    try:
        a = float(amount)
    except (TypeError, ValueError):
        return None
    if a >= 10_000:
        return "Tier 1"
    if a >= 5_000:
        return "Tier 2"
    if a >= 1_000:
        return "Tier 3"
    if a > 0:
        return "Tier 4"
    return None


def tier_rank(tier: str | None) -> int:
    """Numeric rank for sorting/tiebreak. Higher = stronger capacity."""
    return {"Tier 1": 4, "Tier 2": 3, "Tier 3": 2, "Tier 4": 1}.get(tier or "", 0)


def _parse_year(text: str | None) -> int | None:
    if not text:
        return None
    s = str(text).strip()
    # Try a full date first, then a bare 4-digit year.
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%Y"):
        try:
            return _dt.datetime.strptime(s, fmt).year
        except ValueError:
            continue
    m = re.search(r"(19|20)\d{2}", s)
    return int(m.group(0)) if m else None


def life_stage_from_birthday(birthday: str | None) -> str | None:
    """Turn a birthday into an age + life-stage label for planned-giving signals."""
    year = _parse_year(birthday)
    if not year:
        return None
    age = _dt.date.today().year - year
    if age < 0 or age > 120:
        return None
    if age >= 70:
        stage = "planned giving / estate"
    elif age >= 55:
        stage = "pre-retirement"
    elif age >= 35:
        stage = "mid-career"
    else:
        stage = "early-career"
    return f"Age ~{age} ({stage})"
