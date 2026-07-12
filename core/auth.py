"""Sign-in via a shared team password. Enforces the manager vs. reader gate.

A single shared 'manager_password' (set in secrets) gives everyone full access —
this is the configuration the team chose. An optional 'reader_password' can be
added later to grant a view-only role without any per-person accounts.

Local development: if [dev].allow_role_override is set in secrets AND the
DEV_ROLE env var is 'manager'/'reader', the password step is skipped and that
role is used. The Cloud deploy omits the [dev] section, so a password is always
required there.

The gate is enforced in code on each restricted page (require_manager), not only
by hiding nav links — someone with the reader password who navigates straight to
a manager page is stopped.
"""
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from core import config

_ROLE_KEY = "auth_role"


@dataclass
class User:
    email: str
    name: str
    role: str | None       # 'manager' | 'reader' | None

    @property
    def is_manager(self) -> bool:
        return self.role == "manager"

    @property
    def is_allowed(self) -> bool:
        return self.role in ("manager", "reader")


def _dev_user() -> User | None:
    role = config.dev_role_override()
    if role:
        return User(email=f"dev+{role}@local", name=f"DEV ({role})", role=role)
    return None


def current_user() -> User | None:
    """Return the signed-in user, or None if not signed in."""
    dev = _dev_user()
    if dev:
        return dev
    role = st.session_state.get(_ROLE_KEY)
    if role in ("manager", "reader"):
        label = "Manager" if role == "manager" else "Reader (view only)"
        return User(email="", name=label, role=role)
    return None


def require_login() -> User:
    """Gate the whole app behind the team password. Stops the page if not signed in."""
    user = current_user()
    if user:
        return user

    st.title("JBBBS Prospecting Tool")
    if not config.passwords_configured():
        st.error("Sign-in isn't configured yet — no team password has been set. "
                 "(Add a password in the app's Secrets.)")
        st.stop()

    st.write("Enter the team password to continue.")
    with st.form("signin", clear_on_submit=False):
        pw = st.text_input("Team password", type="password")
        submitted = st.form_submit_button("Enter", type="primary")
    if submitted:
        role = config.check_password(pw)
        if role:
            st.session_state[_ROLE_KEY] = role
            st.rerun()
        else:
            st.error("Incorrect password. Please try again.")
    st.stop()


def require_manager(user: User) -> None:
    """Stop a reader who reaches a manager-only page (the real gate, in code)."""
    if not user.is_manager:
        st.error(
            "This page is for managers only. Your access is view-only. If you need "
            "upload or review access, ask Lauren for the manager password."
        )
        st.stop()


def _sign_out() -> None:
    st.session_state.pop(_ROLE_KEY, None)


def sidebar_identity(user: User) -> None:
    """Show the current role with a sign-out control."""
    with st.sidebar:
        st.caption(f"Access: **{user.name}**")
        if not str(user.email).endswith("@local"):
            st.button("Sign out", on_click=_sign_out)
