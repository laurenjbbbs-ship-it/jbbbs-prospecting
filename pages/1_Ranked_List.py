"""Ranked List (all users): the ranked prospect table with filters + export."""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from core import auth, db
from core.ranking import build_ranked_list


def _line(label: str, value) -> None:
    """Write one 'label: value' bullet, skipping blanks/NaN."""
    if value is None:
        return
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return
    st.markdown(f"- **{label}:** {s}")


def _show_profile(p) -> None:
    """Full profile card for a selected prospect."""
    st.divider()
    st.subheader(f"👤 {p.get('name')}")
    left, right = st.columns(2)
    with left:
        st.markdown("**Relationship & ranking**")
        _line("Segment", p.get("segment"))
        _line("Priority", p.get("priority"))
        _line("Program", p.get("program"))
        _line("Volunteer status", p.get("volunteer_status"))
        _line("Match history", p.get("match_history"))
        _line("Donor tier", p.get("donor_tier"))
        amt = p.get("amount")
        _line("Last gift", f"${amt:,.0f}" if pd.notna(amt) else None)
        _line("Outside sources", p.get("outside_sources"))
        _line("Capacity signal", p.get("capacity_hint"))
    with right:
        st.markdown("**Context (to prep the conversation)**")
        _line("Town", p.get("town"))
        _line("Email", p.get("email"))
        _line("Job title", p.get("job_title"))
        _line("Industry", p.get("industry"))
        _line("Employer", p.get("employer"))
        _line("Age / life stage", p.get("age_or_life_stage"))
        _line("Household / spouse", p.get("spouse_or_household"))
        _line("Connection source", p.get("connection_source"))


user = auth.require_login()          # all users allowed

st.title("📋 Ranked Prospect List")
st.caption(
    "Sorted by relationship first, not wealth. Volunteers and donors are high "
    "priority; connection-only names are low priority. Capacity is only a "
    "tiebreaker. Report-only names never appear here — use Lookup for those."
)

tables = db.load_all_tables()
df = build_ranked_list(tables)

if df.empty:
    st.info("No ranked prospects yet. Import your sources (or seed sample data) "
            "to populate the list.")
    st.stop()

# --- Filters ---
with st.expander("Filters", expanded=True):
    c1, c2, c3, c4 = st.columns(4)
    seg_opts = sorted(df["segment"].dropna().unique().tolist())
    prog_opts = sorted(df["program"].dropna().unique().tolist())
    tier_opts = sorted(df["donor_tier"].dropna().unique().tolist())
    prio_opts = sorted(df["priority"].dropna().unique().tolist())

    seg_sel = c1.multiselect("Segment", seg_opts, default=seg_opts)
    prog_sel = c2.multiselect("Program", prog_opts, default=prog_opts)
    tier_sel = c3.multiselect("Donor tier", tier_opts, default=tier_opts)
    prio_sel = c4.multiselect("Priority", prio_opts, default=prio_opts)

mask = df["segment"].isin(seg_sel) & df["priority"].isin(prio_sel)
# Program/tier are often blank (e.g., connection-only); keep blanks unless the
# user narrows those filters below the full set.
if prog_sel and len(prog_sel) < len(prog_opts):
    mask &= df["program"].isin(prog_sel)
if tier_sel and len(tier_sel) < len(tier_opts):
    mask &= df["donor_tier"].isin(tier_sel)

view = df[mask].reset_index(drop=True)

st.markdown(f"**{len(view)}** prospects shown "
            f"(of {len(df)} total). High priority: "
            f"{(view['priority'] == 'high').sum()} · "
            f"Low priority: {(view['priority'] == 'low').sum()}")

event = st.dataframe(
    view, use_container_width=True, hide_index=True,
    on_select="rerun", selection_mode="single-row", key="ranked_table",
    column_config={"amount": st.column_config.NumberColumn("amount", format="$%.0f")},
)

if event.selection.rows:
    _show_profile(view.iloc[event.selection.rows[0]])
else:
    st.caption("💡 Click any row above to open that person's full profile.")

# --- Export ---
csv_bytes = view.to_csv(index=False).encode("utf-8")
xlsx_buf = io.BytesIO()
with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
    view.to_excel(writer, index=False, sheet_name="Ranked Prospects")

e1, e2 = st.columns(2)
e1.download_button("⬇️ Download CSV", csv_bytes, "jbbbs_ranked_prospects.csv",
                   "text/csv", use_container_width=True)
e2.download_button("⬇️ Download Excel", xlsx_buf.getvalue(),
                   "jbbbs_ranked_prospects.xlsx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                   use_container_width=True)
