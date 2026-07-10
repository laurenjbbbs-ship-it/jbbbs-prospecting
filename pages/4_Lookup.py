"""Lookup (all users): single-name search across every source.

This is Zack Roe's screen for checking one new volunteer before onboarding. It
returns everything that exists for a name anywhere — including report-only names
that never appear on the ranked list."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import auth, db
from core.ranking import lookup

user = auth.require_login()

st.title("🔎 Single-Name Lookup")
st.caption("Type a name to see everything across every source: donor tier, "
           "listings from other agencies, LinkedIn, event attendance, board "
           "connections, and volunteer history.")

query = st.text_input("Name", placeholder="e.g. Sarah Levine")

if not query.strip():
    st.stop()

tables = db.load_all_tables()
result = lookup(tables, query)

if not result["appearances"]:
    st.warning(f"No records found for **{query}**.")
    st.stop()

if result["on_ranked_list"]:
    st.success("✅ This person is on the ranked prospect list (volunteer, donor, "
               "or other connection).")
else:
    st.info("ℹ️ This name appears only in outside sources (e.g. an agency report) "
            "and is **not** on the ranked list on its own.")

SOURCE_LABEL = {
    "volunteer": "Volunteer", "donor": "Donor", "attendee": "Event attendee",
    "linkedin": "LinkedIn connection", "board": "Board connection",
    "report": "Outside agency report",
}

rows = []
for a in result["appearances"]:
    detail_bits = []
    for k, v in a.items():
        if k in ("source", "name") or v in (None, ""):
            continue
        detail_bits.append(f"{k}: {v}")
    rows.append({
        "Source": SOURCE_LABEL.get(a["source"], a["source"]),
        "Name as listed": a["name"],
        "Details": " · ".join(detail_bits),
    })

st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
