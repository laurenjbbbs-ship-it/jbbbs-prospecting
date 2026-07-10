"""Review Matches (manager only): the near-match + common-name safeguard queue.

Each row shows both candidate records side by side. Approve to link them as one
person, or reject to keep them separate. Nothing merges without a decision."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import auth, db, matching


def _town(value) -> str:
    """Display a town, treating NaN/None/empty as an em dash."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    s = str(value).strip()
    return s if s and s.lower() != "nan" else "—"

user = auth.require_login()
auth.require_manager(user)           # THE GATE: readers stopped here, in code

st.title("✅ Review Matches")
st.caption("The tool never merges two people on its own. Confident matches "
           "(identical names, no conflict) are linked automatically. These need "
           "your decision.")

if st.button("🔄 Re-scan for matches"):
    counts = matching.refresh_review_queue(db.load_all_tables())
    st.success(f"Scan complete. Near: {counts['near']}, "
               f"common-name: {counts['common_name']} (new items only).")

pending = db.fetch_df(
    "SELECT * FROM near_matches WHERE decision = 'pending' ORDER BY kind, id"
)

if pending.empty:
    st.info("No matches waiting for review. 🎉")
    st.stop()

KIND_HELP = {
    "near": ("🔗 Near match", "Same last name and first initial, but the names "
             "are not identical (e.g. Sara vs Sarah). Are these the same person?"),
    "common_name": ("⚠️ Common-name safeguard", "Same name, but the records carry "
                    "**different towns**. A shared name is a reason to check, not "
                    "to link. Are these the same person?"),
}

for row in pending.itertuples():
    title, help_text = KIND_HELP.get(row.kind, ("Match", ""))
    with st.container(border=True):
        st.markdown(f"### {title}")
        st.caption(help_text)
        left, mid, right = st.columns([5, 1, 5])
        with left:
            st.markdown(f"**{row.left_label}**")
            st.caption(f"Source: {row.left_source}")
            st.caption(f"Town: {_town(row.left_city)}")
        mid.markdown("### vs")
        with right:
            st.markdown(f"**{row.right_label}**")
            st.caption(f"Source: {row.right_source}")
            st.caption(f"Town: {_town(row.right_city)}")

        b1, b2, _ = st.columns([2, 2, 6])
        if b1.button("✅ Same person — link", key=f"ok_{row.id}", type="primary"):
            db.set_near_match_decision(row.id, "confirmed", user.email)
            st.rerun()
        if b2.button("❌ Different — keep apart", key=f"no_{row.id}"):
            db.set_near_match_decision(row.id, "rejected", user.email)
            st.rerun()
