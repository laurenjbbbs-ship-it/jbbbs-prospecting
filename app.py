"""JBBBS Prospecting Tool — Streamlit entry point: nav + role gate.

Readers see Ranked List and Lookup. Managers also see Upload Reports and Review
Matches. The nav below hides the manager pages from readers, AND each manager
page re-checks the role in its own code (defense in depth), so a reader who
navigates straight to a restricted page is stopped, not just missing a link.
"""
from __future__ import annotations

import streamlit as st

from core import auth, db

st.set_page_config(page_title="JBBBS Prospecting Tool", page_icon="🤝",
                   layout="wide")


@st.cache_resource(show_spinner="Connecting to the database…")
def _init_once() -> bool:
    db.init_schema()
    return True


_init_once()

user = auth.require_login()
auth.sidebar_identity(user)

ranked = st.Page("pages/1_Ranked_List.py", title="Ranked List", icon="📋",
                 default=True)
lookup = st.Page("pages/4_Lookup.py", title="Lookup", icon="🔎")
upload = st.Page("pages/2_Upload_Reports.py", title="Upload Reports", icon="📤")
review = st.Page("pages/3_Review_Matches.py", title="Review Matches", icon="✅")

# Role-based navigation.
pages = [ranked, lookup]
if user.is_manager:
    pages += [upload, review]

st.navigation(pages).run()
