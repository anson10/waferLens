# WaferLens

Semiconductor process data analysis pipeline. Simulates realistic fab wafer
data, ingests it into a SQL database, and exposes analytical dashboards via
Streamlit. Portfolio project demonstrating SQL, data engineering, and
semiconductor domain knowledge (SPC, yield, defect density).

## Status

Scaffold only (Step 1 of 9). Directory skeleton and dependencies are in place;
domain logic lands in later feature pushes.

- [x] Step 1 — Project scaffold, `db/session.py`, dependencies
- [ ] Step 2 — SQLAlchemy models + Alembic migrations
- [ ] Step 3 — Simulation layer (wafers, process steps, yield)
- [ ] Step 4 — CSV → DB ingest
- [ ] Step 5 — SPC engine (Western Electric / Nelson rules)
- [ ] Step 6 — Raw-SQL queries + yield aggregations
- [ ] Step 7 — Streamlit dashboard (Overview, Yield, SPC Monitor)
- [ ] Step 8 — Additional dashboard pages
- [ ] Step 9 — README, screenshots, CV framing

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## How to run (target, not yet wired)

```bash
# Init DB + run migrations                    (Step 2)
alembic upgrade head

# Simulate data                               (Step 3)
python -m simulate.wafer
python -m simulate.process

# Ingest to DB                                (Step 4)
python -m ingest.loader

# Launch dashboard                            (Step 7)
streamlit run dashboard/app.py
```

## Project layout

```
db/           SQLAlchemy models + session factory (+ Alembic migrations)
simulate/    Wafer, process, and yield data generators
ingest/       CSV → DB loader
analysis/     SPC rules, yield aggregations, raw SQL query helpers
dashboard/    Streamlit UI
tests/        pytest suite (in-memory SQLite)
```

## Archive

The previous `schemaforge` project (XML layout generator/validator) is
preserved on the `schemaforge-archive` branch.
