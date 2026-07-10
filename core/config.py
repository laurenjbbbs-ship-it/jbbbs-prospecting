"""Central configuration: secrets access, DB URL, Tesseract path, column mappings.

Values are read from Streamlit secrets when running inside the app, and fall back
to environment variables so scripts (like seed_sample_data.py) can run outside
Streamlit. Nothing sensitive is hard-coded here.
"""
from __future__ import annotations

import os
from typing import Any

try:  # Streamlit is available inside the app but not in plain scripts / tests.
    import streamlit as st

    def _secret(path: str, default: Any = None) -> Any:
        """Read a dotted key from st.secrets, e.g. 'dev.allow_role_override'."""
        node: Any = st.secrets
        try:
            for part in path.split("."):
                node = node[part]
            return node
        except Exception:
            return default

    def _has_streamlit_secrets() -> bool:
        try:
            _ = st.secrets  # touching it raises if no secrets file
            return True
        except Exception:
            return False

except ModuleNotFoundError:  # pragma: no cover - only in bare scripts
    st = None  # type: ignore

    def _secret(path: str, default: Any = None) -> Any:
        return default

    def _has_streamlit_secrets() -> bool:
        return False


def get_database_url() -> str:
    """Postgres URL. Env var wins (for scripts); otherwise Streamlit secrets."""
    url = os.environ.get("DATABASE_URL") or _secret("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "No DATABASE_URL found. Set it in .streamlit/secrets.toml "
            "or as an environment variable."
        )
    return url


def get_tesseract_cmd() -> str | None:
    """Path to the Tesseract executable, if configured. None = rely on PATH."""
    explicit = os.environ.get("TESSERACT_CMD") or _secret("tesseract.cmd")
    if explicit:
        return explicit
    # Common Windows install location from the UB-Mannheim installer.
    default_win = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.name == "nt" and os.path.exists(default_win):
        return default_win
    return None


def dev_role_override() -> str | None:
    """Return a forced role ('manager'/'reader') for LOCAL testing, else None.

    Only active when BOTH the secrets flag [dev].allow_role_override is true AND
    the DEV_ROLE env var is set. The Cloud deploy omits the [dev] section, so this
    can never take effect in production even if someone sets the env var.
    """
    if not _secret("dev.allow_role_override", False):
        return None
    role = os.environ.get("DEV_ROLE", "").strip().lower()
    return role if role in ("manager", "reader") else None


def role_for_email(email: str | None) -> str | None:
    """Map a signed-in email to 'manager' or 'reader' via the allowlist.

    Returns None if the email is not on the list (blocked)."""
    if not email:
        return None
    roles = _secret("roles", {}) or {}
    # Case-insensitive match.
    email_l = email.strip().lower()
    for listed_email, role in dict(roles).items():
        if str(listed_email).strip().lower() == email_l:
            return str(role).strip().lower()
    return None


# ---------------------------------------------------------------------------
# Column-mapping guesses. First import of each source shows a mapping screen
# that pre-selects these guesses from the header text; the user confirms.
# ---------------------------------------------------------------------------

# Canonical fields the tool understands per source -> list of header synonyms.
SOURCE_FIELD_SYNONYMS: dict[str, dict[str, list[str]]] = {
    "volunteers": {
        "first_name": ["first name", "first", "fname", "firstname"],
        "last_name": ["last name", "last", "lname", "lastname", "surname"],
        "city": ["city", "town", "municipality"],
        "birthday": ["birthday", "birth date", "dob", "date of birth"],
        "match_date": ["match date", "matched", "match start", "start date"],
        "match_closure_date": ["match closure date", "closure", "closed",
                                "match closed", "closure date", "end date"],
        "job_title": ["title", "job title", "position", "role"],
        "industry": ["industry", "sector"],
        "employer": ["employer", "company", "organization", "organisation"],
        "spouse_or_household": ["spouse", "household", "partner"],
    },
    "donors": {
        "first_name": ["first name", "first", "fname"],
        "last_name": ["last name", "last", "lname", "surname"],
        "organization": ["organization", "organisation", "company", "employer"],
        "city": ["city", "town"],
        "first_gift": ["first gift", "first donation", "initial gift"],
        "last_gift": ["last gift", "most recent gift", "recent gift", "last donation"],
        "average_gift": ["average gift", "avg gift", "mean gift"],
    },
    "attendees": {
        "first_name": ["first name", "first", "fname"],
        "last_name": ["last name", "last", "lname", "surname"],
        "organization": ["organization", "organisation", "company", "employer"],
        "city": ["city", "town"],
        "event_attended": ["event", "event attended", "event name"],
    },
    "linkedin": {
        "first_name": ["first name", "first"],
        "last_name": ["last name", "last", "surname"],
        "company": ["company", "employer", "organization"],
        "position": ["position", "title", "job title"],
        "connected_date": ["connected on", "connected date", "connected"],
    },
    "board_connections": {
        "first_name": ["first name", "first"],
        "last_name": ["last name", "last", "surname"],
        "connecting_board_member": ["board member", "connecting board member",
                                     "introduced by", "connection", "referred by"],
        "city": ["city", "town"],
    },
}

# Program is fixed per source file: MatchForce = Mentorship, Salesforce = Friendship.
PROGRAM_BY_SOURCE_LABEL = {
    "matchforce": "Mentorship",
    "salesforce": "Friendship",
}
