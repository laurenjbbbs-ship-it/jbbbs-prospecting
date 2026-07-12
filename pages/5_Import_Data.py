"""Import Data (manager only): load/refresh the CSV sources with column mapping.

Upload a fresh export for a source, confirm which columns map to which fields,
and import. Re-importing a source fully replaces that source's data (MatchForce
and Salesforce each replace only their own program's volunteers)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import auth, db, matching
from core.config import SOURCE_FIELD_SYNONYMS
from core.ingest_csv import SOURCE_LABELS, guess_mapping, import_csv, table_for

user = auth.require_login()
auth.require_manager(user)           # THE GATE: readers stopped here, in code

st.title("📥 Import Data")
st.caption("Load or refresh your source exports. Re-importing a source replaces "
           "that source's data. Column choices are remembered for next time.")

# --- Current data at a glance ---
with st.expander("What's loaded now", expanded=True):
    counts = {
        "Volunteers (MatchForce + Salesforce)": len(db.read_table("volunteers")),
        "Donors": len(db.read_table("donors")),
        "Attendees": len(db.read_table("attendees")),
        "LinkedIn": len(db.read_table("linkedin")),
        "Board connections": len(db.read_table("board_connections")),
        "Reports": len(db.read_table("reports")),
    }
    st.table(pd.DataFrame({"Source": list(counts.keys()),
                           "Rows": list(counts.values())}))

st.divider()

# --- Pick a source and upload ---
source_key = st.selectbox(
    "Which source are you importing?",
    options=list(SOURCE_LABELS.keys()),
    format_func=lambda k: SOURCE_LABELS[k],
)

uploaded = st.file_uploader("CSV export", type=["csv"], key=f"csv_{source_key}")

if uploaded is not None:
    try:
        df = pd.read_csv(uploaded, dtype=str)
    except UnicodeDecodeError:
        uploaded.seek(0)
        df = pd.read_csv(uploaded, dtype=str, encoding="latin-1")

    st.markdown(f"**{len(df)} rows** found. First few:")
    st.dataframe(df.head(), use_container_width=True, hide_index=True)

    # Column mapping: pre-fill the tool's best guess, let the user confirm.
    st.markdown("**Match your columns** — the tool guessed; fix any that are wrong:")
    fields = SOURCE_FIELD_SYNONYMS[table_for(source_key)]
    guess = guess_mapping(source_key, list(df.columns))
    options = ["(none)"] + list(df.columns)

    mapping: dict[str, str] = {}
    cols = st.columns(2)
    for i, field in enumerate(fields):
        default = guess.get(field, "(none)")
        idx = options.index(default) if default in options else 0
        choice = cols[i % 2].selectbox(
            field.replace("_", " ").title(),
            options=options,
            index=idx,
            key=f"map_{source_key}_{field}",
        )
        if choice != "(none)":
            mapping[field] = choice

    if "first_name" not in mapping or "last_name" not in mapping:
        st.warning("First name and last name are required to match people. "
                   "Please map both before importing.")
    elif st.button("⬆️ Import (replaces this source)", type="primary"):
        n = import_csv(source_key, df, mapping)
        counts = matching.refresh_review_queue(db.load_all_tables())
        st.success(
            f"Imported {n} rows into **{SOURCE_LABELS[source_key]}**. "
            f"Review queue updated (near: {counts['near']}, "
            f"common-name: {counts['common_name']}). "
            "Check the Ranked List and Review Matches."
        )

st.divider()

# --- Danger zone: wipe everything for a clean start ---
with st.expander("⚠️ Danger zone — clear ALL data"):
    st.caption("Removes every source, report, and review item. Use this once, to "
               "clear the sample data before loading real data for the first time.")
    confirm = st.checkbox("Yes, I understand this deletes everything in the tool.")
    if st.button("Delete all data", disabled=not confirm):
        for t in ["near_matches", "report_names", "reports", "volunteers",
                  "donors", "attendees", "linkedin", "board_connections"]:
            db.execute(f"DELETE FROM {t}")
        st.success("All data cleared. Import your real exports above to start fresh.")
