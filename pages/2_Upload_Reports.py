"""Upload Reports (manager only): PDF upload -> extract -> review before commit.

Every upload gets a review step. Names commit to the cross-reference only after
the manager confirms them. Scanned PDFs (OCR) are flagged for extra scrutiny."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import auth, db, ingest_pdf, matching
from core.normalize import normalize_name

user = auth.require_login()
auth.require_manager(user)           # THE GATE: readers are stopped here, in code

st.title("📤 Upload Agency Reports")
st.caption("Upload a PDF honor roll or donor report. The tool extracts names and "
           "gift ranges for you to review. Nothing is added until you confirm.")

c1, c2 = st.columns(2)
report_name = c1.text_input("Report name", placeholder="e.g. 2025 Federation Honor Roll")
agency = c2.text_input("Agency", placeholder="e.g. Jewish Federation")

uploaded = st.file_uploader("PDF report", type=["pdf"])

if uploaded is not None:
    file_bytes = uploaded.getvalue()
    # Re-extract only when a new file arrives.
    key = f"{uploaded.name}:{len(file_bytes)}"
    if st.session_state.get("_report_key") != key:
        with st.spinner("Reading the PDF (running OCR if it is scanned)…"):
            extracted = ingest_pdf.extract(file_bytes)
        st.session_state["_report_key"] = key
        st.session_state["_extracted"] = extracted
        st.session_state["_editor_df"] = pd.DataFrame([
            {"confirmed": True, "raw_name": n["raw_name"],
             "gift_range": n["gift_range"] or ""}
            for n in extracted["names"]
        ])

    extracted = st.session_state["_extracted"]

    if extracted.get("ocr_error"):
        st.error("⚠️ " + extracted["ocr_error"] + " Upload a clean/digital PDF "
                 "here, or wait until the tool is deployed (OCR runs on the host).")
    elif extracted["is_scanned"]:
        st.warning("⚠️ This looks like a **scanned** PDF, read via OCR. OCR can "
                   "misread names — please check each row carefully before committing.")
    else:
        st.success("✅ Clean digital PDF — text extracted directly. A quick check "
                   "is still good practice.")

    st.markdown(f"**{len(extracted['names'])}** names found across "
                f"{extracted['page_count']} page(s). Edit, uncheck, or fix any row:")

    edited = st.data_editor(
        st.session_state["_editor_df"],
        use_container_width=True, hide_index=True, num_rows="dynamic",
        column_config={
            "confirmed": st.column_config.CheckboxColumn("Keep?", default=True),
            "raw_name": st.column_config.TextColumn("Name"),
            "gift_range": st.column_config.TextColumn("Gift range"),
        },
        key="report_editor",
    )

    if st.button("✅ Commit reviewed names", type="primary"):
        keep = edited[edited["confirmed"] == True]  # noqa: E712
        keep = keep[keep["raw_name"].astype(str).str.strip() != ""]
        if keep.empty:
            st.error("No confirmed names to commit.")
            st.stop()

        report_id = db.insert_report(
            report_name or uploaded.name, agency or "(unknown)",
            user.email, extracted["is_scanned"],
        )
        rows = [
            {"raw_name": str(r.raw_name).strip(),
             "normalized_name": normalize_name(str(r.raw_name)),
             "gift_range": (str(r.gift_range).strip() or None)}
            for r in keep.itertuples()
        ]
        db.insert_report_names(report_id, rows)
        # Mark each confirmed and commit the report.
        db.execute("UPDATE report_names SET confirmed = TRUE WHERE report_id = :id",
                   {"id": report_id})
        db.commit_report(report_id)

        # Now that names are committed, look for near matches to known people.
        counts = matching.refresh_review_queue(db.load_all_tables())

        st.success(f"Committed {len(rows)} names from “{report_name or uploaded.name}”. "
                   f"New review items — near matches: {counts['near']}, "
                   f"common-name: {counts['common_name']}. "
                   "Check the Review Matches page.")
        for k in ("_report_key", "_extracted", "_editor_df"):
            st.session_state.pop(k, None)

st.divider()
st.subheader("Previously uploaded reports")
reports = db.read_table("reports")
if reports.empty:
    st.caption("No reports uploaded yet.")
else:
    show = reports[["report_name", "agency", "uploaded_by", "is_scanned", "status"]]
    st.dataframe(show, use_container_width=True, hide_index=True)
