"""Postgres (Neon) connection, schema creation, and safe read/write helpers.

Source tables are fully replaced on re-import. Report tables accumulate. Every
name-bearing row stores a normalized_name, the join key across all tables.
"""
from __future__ import annotations

import json
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from core.config import get_database_url

# Source tables that get FULLY REPLACED whenever a fresh export is imported.
SOURCE_TABLES = [
    "volunteers",
    "donors",
    "attendees",
    "linkedin",
    "board_connections",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS volunteers (
    id                 SERIAL PRIMARY KEY,
    first_name         TEXT,
    last_name          TEXT,
    program            TEXT,          -- Mentorship (MatchForce) or Friendship (Salesforce)
    status             TEXT,          -- current | former
    city               TEXT,
    birthday           TEXT,
    match_date         TEXT,
    match_closure_date TEXT,
    match_length_months INTEGER,
    job_title          TEXT,
    industry           TEXT,
    employer           TEXT,
    spouse_or_household TEXT,
    normalized_name    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS donors (
    id              SERIAL PRIMARY KEY,
    first_name      TEXT,
    last_name       TEXT,
    organization    TEXT,
    city            TEXT,
    first_gift      NUMERIC,
    last_gift       NUMERIC,
    average_gift    NUMERIC,
    tier            TEXT,             -- Tier 1..4, derived from last_gift
    amount          NUMERIC,          -- = last_gift, the capacity signal
    normalized_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attendees (
    id              SERIAL PRIMARY KEY,
    first_name      TEXT,
    last_name       TEXT,
    organization    TEXT,
    city            TEXT,
    event_attended  TEXT,
    normalized_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS linkedin (
    id              SERIAL PRIMARY KEY,
    first_name      TEXT,
    last_name       TEXT,
    company         TEXT,
    position        TEXT,
    connected_date  TEXT,
    normalized_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS board_connections (
    id                      SERIAL PRIMARY KEY,
    first_name              TEXT,
    last_name               TEXT,
    connecting_board_member TEXT,
    city                    TEXT,
    normalized_name         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id          SERIAL PRIMARY KEY,
    report_name TEXT,
    agency      TEXT,
    uploaded_by TEXT,
    uploaded_at TIMESTAMPTZ DEFAULT now(),
    is_scanned  BOOLEAN DEFAULT FALSE,
    status      TEXT DEFAULT 'pending_review'   -- pending_review | committed
);

CREATE TABLE IF NOT EXISTS report_names (
    id              SERIAL PRIMARY KEY,
    report_id       INTEGER REFERENCES reports(id) ON DELETE CASCADE,
    raw_name        TEXT,
    normalized_name TEXT,
    gift_range      TEXT,
    confirmed       BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS near_matches (
    id           SERIAL PRIMARY KEY,
    kind         TEXT,          -- 'near' | 'common_name'
    left_source  TEXT,
    left_label   TEXT,
    left_city    TEXT,
    right_source TEXT,
    right_label  TEXT,
    right_city   TEXT,
    norm_a       TEXT,
    norm_b       TEXT,
    decision     TEXT DEFAULT 'pending',   -- pending | confirmed | rejected
    decided_by   TEXT,
    created_at   TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source_mappings (
    source     TEXT PRIMARY KEY,
    mapping    JSONB,
    updated_at TIMESTAMPTZ DEFAULT now()
);
"""


def _normalize_url(url: str) -> str:
    """Ensure SQLAlchemy uses the psycopg (v3) driver."""
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


_ENGINE: Engine | None = None


def get_engine() -> Engine:
    """Return a cached SQLAlchemy engine for the Neon database."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(
            _normalize_url(get_database_url()),
            pool_pre_ping=True,
            pool_recycle=300,
        )
    return _ENGINE


def init_schema() -> None:
    """Create all tables if they do not already exist. Safe to call repeatedly."""
    engine = get_engine()
    with engine.begin() as conn:
        for statement in _SCHEMA.split(";"):
            if statement.strip():
                conn.execute(text(statement))


def replace_source_table(table: str, df: pd.DataFrame,
                         where: dict[str, Any] | None = None) -> int:
    """Replace a source table's contents with df. Returns rows written.

    `where` scopes the delete to one partition of a shared table — used for
    volunteers, where MatchForce (Mentorship) and Salesforce (Friendship) share
    one table and a fresh export must replace only its own program's rows."""
    if table not in SOURCE_TABLES:
        raise ValueError(f"{table} is not a replaceable source table")
    engine = get_engine()
    with engine.begin() as conn:
        if where:
            clause = " AND ".join(f"{col} = :{col}" for col in where)
            conn.execute(text(f"DELETE FROM {table} WHERE {clause}"), where)
        else:
            conn.execute(text(f"DELETE FROM {table}"))
        if not df.empty:
            df.to_sql(table, conn, if_exists="append", index=False)
    return len(df)


def read_table(table: str) -> pd.DataFrame:
    """Read a whole table into a DataFrame (empty frame if it has no rows)."""
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql(text(f"SELECT * FROM {table}"), conn)


ALL_TABLES = SOURCE_TABLES + ["reports", "report_names", "near_matches"]


def load_all_tables() -> dict[str, pd.DataFrame]:
    """Load every table into a dict of DataFrames for the ranking/matching engine."""
    return {name: read_table(name) for name in ALL_TABLES}


def execute(sql: str, params: dict[str, Any] | None = None) -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(sql), params or {})


def fetch_df(sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


# --- Reports -------------------------------------------------------------

def insert_report(report_name: str, agency: str, uploaded_by: str,
                  is_scanned: bool) -> int:
    """Create a pending report row and return its id."""
    engine = get_engine()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO reports (report_name, agency, uploaded_by, is_scanned, status) "
                "VALUES (:n, :a, :u, :s, 'pending_review') RETURNING id"
            ),
            {"n": report_name, "a": agency, "u": uploaded_by, "s": is_scanned},
        ).first()
        return int(row[0])


def insert_report_names(report_id: int, rows: list[dict[str, Any]]) -> None:
    """Insert extracted names (raw_name, normalized_name, gift_range) for review."""
    if not rows:
        return
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO report_names (report_id, raw_name, normalized_name, gift_range, confirmed) "
                "VALUES (:rid, :raw, :norm, :gift, FALSE)"
            ),
            [
                {"rid": report_id, "raw": r.get("raw_name"),
                 "norm": r.get("normalized_name"), "gift": r.get("gift_range")}
                for r in rows
            ],
        )


def commit_report(report_id: int) -> None:
    """Mark a report and its confirmed names as committed to the cross-reference."""
    execute("UPDATE reports SET status = 'committed' WHERE id = :id",
            {"id": report_id})


# --- Near-match queue ----------------------------------------------------

def upsert_near_match(item: dict[str, Any]) -> None:
    """Insert a review item only if this exact pair is not already queued/decided.

    Deduped on the unordered (norm_a, norm_b) + kind pair so re-running the
    matcher never creates duplicates.
    """
    engine = get_engine()
    a, b = sorted([item.get("norm_a") or "", item.get("norm_b") or ""])
    with engine.begin() as conn:
        exists = conn.execute(
            text(
                "SELECT 1 FROM near_matches WHERE kind = :k AND "
                "((norm_a = :a AND norm_b = :b) OR (norm_a = :b AND norm_b = :a)) LIMIT 1"
            ),
            {"k": item.get("kind"), "a": a, "b": b},
        ).first()
        if exists:
            return
        conn.execute(
            text(
                "INSERT INTO near_matches (kind, left_source, left_label, left_city, "
                "right_source, right_label, right_city, norm_a, norm_b, decision) "
                "VALUES (:kind, :ls, :ll, :lc, :rs, :rl, :rc, :a, :b, 'pending')"
            ),
            {
                "kind": item.get("kind"),
                "ls": item.get("left_source"), "ll": item.get("left_label"),
                "lc": item.get("left_city"),
                "rs": item.get("right_source"), "rl": item.get("right_label"),
                "rc": item.get("right_city"),
                "a": a, "b": b,
            },
        )


def set_near_match_decision(match_id: int, decision: str, decided_by: str) -> None:
    execute(
        "UPDATE near_matches SET decision = :d, decided_by = :who WHERE id = :id",
        {"d": decision, "who": decided_by, "id": match_id},
    )


def confirmed_links() -> list[tuple[str, str]]:
    """Return (norm_a, norm_b) pairs a manager confirmed as the same person."""
    df = fetch_df(
        "SELECT norm_a, norm_b FROM near_matches WHERE decision = 'confirmed'"
    )
    return [(r.norm_a, r.norm_b) for r in df.itertuples()]


# --- Source column mappings ---------------------------------------------

def save_mapping(source: str, mapping: dict[str, str]) -> None:
    execute(
        "INSERT INTO source_mappings (source, mapping, updated_at) "
        "VALUES (:s, :m, now()) "
        "ON CONFLICT (source) DO UPDATE SET mapping = :m, updated_at = now()",
        {"s": source, "m": json.dumps(mapping)},
    )


def load_mapping(source: str) -> dict[str, str] | None:
    df = fetch_df("SELECT mapping FROM source_mappings WHERE source = :s",
                  {"s": source})
    if df.empty:
        return None
    value = df.iloc[0]["mapping"]
    return value if isinstance(value, dict) else json.loads(value)
