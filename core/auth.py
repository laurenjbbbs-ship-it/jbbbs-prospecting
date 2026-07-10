"""Sign-in identity -> role. Enforces the manager vs. reader gate.

Local development: if [dev].allow_role_override is set in secrets AND the DEV_ROLE
env var is 'manager'/'reader', sign-in is skipped and that role is used. This lets
Lauren test both roles without five Google accounts. In the Cloud deploy the
[dev] section is omitted, so real Google sign-in is always required there.

The gate is enforced in code on each restricted page (require_manager), not only
by hiding nav links — a reader who navigates straight to a manager page is stopped.
"""
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from core import config


@dataclass
class User:
    email: str
    name: str
    role: str | None       # 'manager' | 'reader' | None (blocked)

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
    """Return the signed-in user, or None if not signed in.

    A signed-in but non-allowlisted email returns a User with role=None (blocked).
    """
    dev = _dev_user()
    if dev:
        return dev

    try:
        logged_in = bool(st.user.is_logged_in)
    except Exception:
        logged_in = False
    if not logged_in:
        return None

    email = getattr(st.user, "email", None)
    name = getattr(st.user, "name", None) or email or "User"
    role = config.role_for_email(email)
    return User(email=email or "", name=name, role=role)


def require_login() -> User:
    """Gate the whole app. Renders a login button and stops if not signed in.

    Returns an allowed User, or stops the page for anyone not signed in / not on
    the allowlist."""
    user = current_user()
    if user is None:
        st.title("JBBBS Prospecting Tool")
        st.info("Please sign in with your JBBBS Google account to continue.")
        try:
            st.button("Sign in with Google", type="primary",
                      on_click=st.login)  # type: ignore[arg-type]
        except Exception:
            st.warning(
                "Google sign-in is not configured yet. For local testing, set the "
                "DEV_ROLE environment variable to 'manager' or 'reader'."
            )
        st.stop()

    if not user.is_allowed:
        st.title("JBBBS Prospecting Tool")
        st.error(
            f"The account **{user.email}** is not on the approved list for this "
            "tool. Ask Dayna or Lauren to add you."
        )
        try:
            st.button("Sign out", on_click=st.logout)  # type: ignore[arg-type]
        except Exception:
            pass
        st.stop()

    return user


def require_manager(user: User) -> None:
    """Stop a reader who reaches a manager-only page (the real gate, in code)."""
    if not user.is_manager:
        st.error(
            "This page is for the tool **manager** only. Your role is **reader**, "
            "which can view the Ranked List and Lookup. If you need upload or "
            "review access, ask Dayna or Lauren."
        )
        st.stop()


def sidebar_identity(user: User) -> None:
    """Show who is signed in and their role, with a sign-out control."""
    with st.sidebar:
        st.caption(f"Signed in as **{user.name}**")
        st.caption(f"Role: **{user.role}**")
        try:
            if not str(user.email).endswith("@local"):
                st.button("Sign out", on_click=st.logout)  # type: ignore[arg-type]
        except Exception:
            pass
