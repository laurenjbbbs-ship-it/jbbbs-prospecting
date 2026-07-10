# JBBBS Prospecting Tool

Surfaces people worth a fundraising conversation and ranks them **by relationship
first, not wealth**. It finds and ranks prospects; it does not steward them
(Salesforce owns the donor cycle). Capacity from outside reports is only a
tiebreaker, never a reason a name surfaces.

## Who does what

| Person | Role | Can |
|--------|------|-----|
| Dayna | **Manager** | Everything: upload reports, clear the review queue, refresh source exports, read the list |
| Amy, Casey, Zack Roe | **Reader** | Read the Ranked List and Lookup |
| Lauren | Manager | Builds and maintains the tool |

Readers never see Upload or Review, and cannot reach those pages even by typing
the URL.

## The four pages

1. **Ranked List** (all users) — the ranked table, with filters (segment,
   program, tier, priority), column sort, and export to Excel/CSV.
2. **Upload Reports** (manager) — upload a PDF honor roll. The tool extracts
   names + gift ranges into an editable table. **Nothing is added until you
   confirm** (review-before-commit). Scanned PDFs are flagged and read via OCR.
3. **Review Matches** (manager) — the near-match queue. Each row shows both
   candidate records side by side. Approve to link, or reject to keep apart.
   **The tool never merges two people on its own.**
4. **Lookup** (all users) — one search box; returns everything across every
   source for a name, including report-only names. Zack Roe's screen for checking
   a new volunteer.

## How ranking works — the four gates

1. **Volunteer?** → on the list.
2. **Donor?** → volunteer+donor = *upgrade*; volunteer only = *first ask*;
   donor only = *existing donor*. All high priority.
3. **Connection only** (board / LinkedIn / attendee) → on the list, low priority.
4. **No connection** → off the list. A report-only appearance is **not** a
   connection: it enriches ranked names and shows in Lookup, but never surfaces a
   name on its own.

Default order: first ask → upgrade → existing donor (high) → connection only
(low). Within a tier: more outside sources first, then capacity.

## Safeguards

- **Review before commit** — every uploaded report's names are reviewed before
  they count.
- **Confident vs. near** — identical normalized names link automatically; a
  Sara/Sarah near match goes to review.
- **Common-name safeguard** — same name but different town → routed to review,
  never fused. Protects against merging two different people.

---

## Running it locally (Lauren)

The app is a [Streamlit](https://streamlit.io) app backed by Neon Postgres.

**Start the app** — double-click one of:
- `run_manager.bat` — opens the app as a **manager** (all four pages).
- `run_reader.bat` — opens the app as a **reader** (to see what Amy/Casey/Zack
  see). Uses the local `DEV_ROLE` toggle; this override does not exist in the
  deployed app, where real Google sign-in decides the role.

**Reload the sample data** — double-click `reseed_sample_data.bat`. This rewrites
the synthetic sample CSVs/PDFs into `sample_data/` and reloads them into the
database.

**Secrets** live in `.streamlit/secrets.toml` (git-ignored — never uploaded):
the Neon connection string, the Google sign-in keys, and the email→role
allowlist.

### Environment (already set up)

- Python 3.12 virtual environment at `C:\Users\LaurenKorn\jvenv`
  (kept outside the OneDrive folder to avoid the Windows long-path limit).
- Dependencies: see `requirements.txt`.
- OCR (`Tesseract`) runs on the host after deployment; a local install is
  optional. Without it, digital PDFs still work and scanned PDFs show a clear
  message instead of failing.

## Deploying (later)

Streamlit Community Cloud (private) + Neon + Google sign-in. Add the same secrets
in the Cloud UI, add the `streamlit.app` redirect URI to the Google OAuth client,
and confirm the app is private with the five-email allowlist **before loading any
real donor data**.
