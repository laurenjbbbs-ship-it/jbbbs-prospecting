"""Seed synthetic sample data so the tool can be seen working before real data.

Run from the project folder:
    C:/Users/LaurenKorn/jvenv/Scripts/python.exe seed_sample_data.py

It writes sample CSV/PDF files into sample_data/ (so you can also practise the
Upload and Import screens by hand) AND loads them into the database so the Ranked
List is populated immediately.

The data is engineered to exercise every rule:
  - first ask (volunteer, no gift)         -> Rebecca Stern
  - upgrade (volunteer + donor)            -> Miriam Roth
  - existing donor (donor, not volunteer)  -> Nathan Blum
  - connection only, multi-source          -> Ellen Fisher (attendee + LinkedIn)
  - connection only, single source         -> Paul Adler (LinkedIn only)
  - near match (Sara vs Sarah)             -> volunteer Sara Levine / report Sarah Levine
  - common-name safeguard (diff towns)     -> David Cohen (Newton) vs David Cohen (Sharon)
  - report-only (must NOT appear ranked)   -> Jonah Pearl (report only)
All names are fictitious.
"""
from __future__ import annotations

import os
import pathlib

# --- Make DATABASE_URL available whether or not it's already in the env. ---
_PROJECT = pathlib.Path(__file__).resolve().parent
if not os.environ.get("DATABASE_URL"):
    try:
        import tomllib
        with open(_PROJECT / ".streamlit" / "secrets.toml", "rb") as fh:
            os.environ["DATABASE_URL"] = tomllib.load(fh)["DATABASE_URL"]
    except Exception as exc:  # pragma: no cover
        raise SystemExit(
            "Could not find DATABASE_URL. Set it in .streamlit/secrets.toml "
            f"or the environment. ({exc})"
        )

import pandas as pd  # noqa: E402

from core import db, ingest_csv, matching  # noqa: E402
from core.normalize import normalize_name  # noqa: E402

SAMPLE_DIR = _PROJECT / "sample_data"
SAMPLE_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# 1. Sample CSVs (realistic headers so the column-mapping guesser has work to do)
# ---------------------------------------------------------------------------

def _matchforce() -> pd.DataFrame:
    return pd.DataFrame([
        # first ask: current volunteer, no gift
        ["Rebecca", "Stern", "Newton", "1988-05-14", "2023-03-01", ""],
        # common-name #1: David Cohen of NEWTON (former, deep dormant tie)
        ["David", "Cohen", "Newton", "1979-02-20", "2016-01-10", "2019-06-01"],
        # near match: volunteer "Sara" vs report "Sarah"
        ["Sara", "Levine", "Brookline", "1991-09-02", "2022-06-15", ""],
        # upgrade (also a donor below): former volunteer
        ["Miriam", "Roth", "Newton", "1950-11-30", "2010-01-01", "2014-01-01"],
    ], columns=["First Name", "Last Name", "City", "Birthday",
                "Match Date", "Match Closure Date"])


def _salesforce() -> pd.DataFrame:
    return pd.DataFrame([
        ["Aaron", "Goldberg", "Sharon", "1985-07-19", "2024-02-01", ""],
    ], columns=["First Name", "Last Name", "City", "Birthday",
                "Match Date", "Match Closure Date"])


def _donors() -> pd.DataFrame:
    return pd.DataFrame([
        # upgrade: Miriam Roth is also a volunteer -> Tier 1
        ["Miriam", "Roth", "Roth Family Foundation", "Newton", 5000, 15000, 10000],
        # common-name #2: David Cohen of SHARON (donor) -> conflicts with Newton vol
        ["David", "Cohen", "Cohen LLC", "Sharon", 2000, 6000, 4000],
        # existing donor, not a volunteer
        ["Nathan", "Blum", "", "Brookline", 500, 1500, 1000],
    ], columns=["First Name", "Last Name", "Organization", "City",
                "First Gift", "Last Gift", "Average Gift"])


def _attendees() -> pd.DataFrame:
    return pd.DataFrame([
        # connection-only, and ALSO in LinkedIn below -> multi-source
        ["Ellen", "Fisher", "Fisher & Co", "Newton", "Spring Gala 2024"],
    ], columns=["First Name", "Last Name", "Organization", "City",
                "Event Attended"])


def _linkedin() -> pd.DataFrame:
    return pd.DataFrame([
        ["Ellen", "Fisher", "Fisher & Co", "Partner", "2021-04-10"],
        # connection-only, single source
        ["Paul", "Adler", "Adler Group", "Director", "2020-08-22"],
    ], columns=["First Name", "Last Name", "Company", "Position", "Connected On"])


def _board() -> pd.DataFrame:
    return pd.DataFrame([
        # connection-only via board introduction
        ["George", "Klein", "Sam Katz", "Newton"],
    ], columns=["First Name", "Last Name", "Board Member", "City"])


CSV_SOURCES = {
    "matchforce": _matchforce, "salesforce": _salesforce, "donors": _donors,
    "attendees": _attendees, "linkedin": _linkedin, "board": _board,
}


def write_and_import_csvs() -> None:
    for source_key, builder in CSV_SOURCES.items():
        df = builder()
        path = SAMPLE_DIR / f"sample_{source_key}.csv"
        df.to_csv(path, index=False)
        mapping = ingest_csv.guess_mapping(source_key, list(df.columns))
        count = ingest_csv.import_csv(source_key, df, mapping)
        print(f"  {source_key:11s} -> {count} rows  ({path.name})")


# ---------------------------------------------------------------------------
# 2. A committed report (simulating one Dayna already reviewed) + near match
# ---------------------------------------------------------------------------

def seed_committed_report() -> None:
    db.execute("DELETE FROM near_matches")
    db.execute("DELETE FROM report_names")
    db.execute("DELETE FROM reports")

    report_id = db.insert_report(
        "2024 Federation Honor Roll", "Jewish Federation", "seed@local", False,
    )
    names = [
        ("Sarah Levine", "$1,000 - $4,999"),   # near match with volunteer Sara Levine
        ("Miriam Roth", "$10,000+"),            # confident match -> enriches upgrade
        ("Jonah Pearl", "$5,000 - $9,999"),     # REPORT ONLY -> must stay off ranked list
    ]
    db.insert_report_names(report_id, [
        {"raw_name": n, "normalized_name": normalize_name(n), "gift_range": g}
        for n, g in names
    ])
    db.execute("UPDATE report_names SET confirmed = TRUE WHERE report_id = :id",
               {"id": report_id})
    db.commit_report(report_id)
    print(f"  committed report #{report_id} with {len(names)} confirmed names")


# ---------------------------------------------------------------------------
# 3. Two sample PDFs for practising the Upload screen by hand
# ---------------------------------------------------------------------------

def make_pdfs() -> None:
    _make_clean_pdf(SAMPLE_DIR / "sample_clean_report.pdf")
    _make_scanned_pdf(SAMPLE_DIR / "sample_scanned_report.pdf")
    print("  wrote sample_clean_report.pdf and sample_scanned_report.pdf")


def _make_clean_pdf(path: pathlib.Path) -> None:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=letter)
    lines = [
        ("2024 Community Federation Honor Roll", 20),
        ("", 12),
        ("$10,000+", 14),
        ("Hannah Weiss", 12),
        ("", 6),
        ("$5,000 - $9,999", 14),
        ("D. Cohen", 12),          # near match vs David Cohen
        ("", 6),
        ("$1,000 - $4,999", 14),
        ("Talia Green", 12),
    ]
    y = 720
    for text, size in lines:
        c.setFont("Helvetica", size)
        c.drawString(72, y, text)
        y -= size + 8
    c.save()


def _make_scanned_pdf(path: pathlib.Path) -> None:
    """Render text to an IMAGE-only PDF so there is no text layer -> forces OCR."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1000, 1300), "white")
    draw = ImageDraw.Draw(img)
    try:
        title_font = ImageFont.truetype("arial.ttf", 40)
        font = ImageFont.truetype("arial.ttf", 32)
    except Exception:
        title_font = ImageFont.load_default()
        font = ImageFont.load_default()

    lines = [
        ("Temple Beth Annual Donors", title_font),
        ("", font),
        ("$1,000 - $4,999", font),
        ("Rachel Simon", font),
        ("Benjamin Katz", font),
    ]
    y = 80
    for text, f in lines:
        draw.text((80, y), text, fill="black", font=f)
        y += 70
    img.save(str(path), "PDF", resolution=200.0)


# ---------------------------------------------------------------------------

def main() -> None:
    print("Initialising schema…")
    db.init_schema()
    print("Writing + importing sample CSVs…")
    write_and_import_csvs()
    print("Seeding committed report…")
    seed_committed_report()
    print("Writing sample PDFs…")
    make_pdfs()
    print("Scanning for near matches + common-name conflicts…")
    counts = matching.refresh_review_queue(db.load_all_tables())
    print(f"  review queue -> near: {counts['near']}, common_name: {counts['common_name']}")
    print("\nDone. Start the app and open the Ranked List.")


if __name__ == "__main__":
    main()
