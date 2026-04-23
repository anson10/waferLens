# CLAUDE.md — WaferLens

## Project Overview
WaferLens is a semiconductor process data analysis pipeline that simulates
realistic fab wafer data, ingests it into a SQL database, and exposes
analytical dashboards via Streamlit. It is a portfolio project demonstrating
SQL, data engineering, and semiconductor domain knowledge.

## Stack
- Python 3.11+
- SQLite (dev) / PostgreSQL (prod-ready)
- SQLAlchemy 2.0 (ORM + Core)
- Alembic (migrations)
- pandas
- Streamlit
- Plotly Express
- Faker + numpy (data simulation)

## Project Structure
waferlens/
├── CLAUDE.md
├── README.md
├── requirements.txt
├── .env.example
│
├── db/
│   ├── models.py          # SQLAlchemy ORM models
│   ├── session.py         # DB engine + session factory
│   └── migrations/        # Alembic migration scripts
│
├── simulate/
│   ├── wafer.py           # Wafer + lot data generator
│   ├── process.py         # Process step + parameter generator
│   └── yield_model.py     # Yield and defect simulation logic
│
├── ingest/
│   └── loader.py          # Parses simulated data → inserts to DB
│
├── analysis/
│   ├── spc.py             # SPC logic (control limits, violations)
│   ├── yield_analysis.py  # Yield queries and aggregations
│   └── queries.py         # Reusable SQL/ORM query functions
│
├── dashboard/
│   └── app.py             # Streamlit UI
│
└── tests/
└── test_queries.py

## Database Schema

### Core Tables
- `lots` — lot_id, product, technology_node, start_date, status
- `wafers` — wafer_id, lot_id, wafer_number, status
- `process_steps` — step_id, step_name, tool_id, layer, sequence_order
- `measurements` — measurement_id, wafer_id, step_id, parameter,
                    value, unit, timestamp
- `yield_records` — record_id, wafer_id, die_count, pass_count,
                    yield_pct, defect_density
- `spc_flags` — flag_id, measurement_id, rule_violated, flagged_at

### Key Relationships
- lot → wafers (1:many)
- wafer → measurements (1:many)
- measurement → spc_flags (1:many)
- process_step → measurements (1:many)

## Domain Concepts
- **Lot**: batch of wafers processed together (typically 25 wafers)
- **Technology node**: e.g. 28nm, 65nm, 130nm — defines design rules
- **Process step**: a single fab operation (e.g. lithography, etch, CVD)
- **SPC (Statistical Process Control)**: monitoring process parameters
  against control limits to detect drift before yield loss occurs
- **Yield**: percentage of functional dies per wafer
- **Defect density**: defects per cm², key fab quality metric

## SPC Rules to Implement
- Rule 1 (Western Electric): 1 point beyond 3σ
- Rule 2: 8 consecutive points on same side of mean
- Rule 3: 6 points continuously increasing or decreasing
- Rule 4: 2 of 3 points beyond 2σ on same side

## Dashboard Pages
1. **Overview** — lot status, wafer counts, recent SPC flags
2. **Yield Analysis** — yield % by lot, product, technology node
3. **SPC Monitor** — control charts per parameter/tool, flag history
4. **Process Explorer** — drill down by step, layer, tool
5. **Defect Trends** — defect density over time, correlation with yield

## Simulation Parameters
- Generate ~500 wafers across ~20 lots
- 8–12 process steps per lot
- 3–5 measured parameters per step (e.g. thickness_nm, cd_nm,
  resistivity, etch_rate)
- Inject realistic drift and outliers to trigger SPC rules
- Yield range: 70–98% with gaussian noise + defect correlation

## Development Notes
- Always use SQLAlchemy sessions via `db/session.py`, never raw sqlite3
- All complex aggregations should be written as raw SQL in `queries.py`
  with comments explaining the business logic — this is intentional
  for SQL portfolio visibility
- Streamlit app imports only from `analysis/` — no direct DB calls in UI
- Keep simulate/ and ingest/ decoupled — simulation writes CSVs,
  ingest reads them

## How to Run
```bash
# Install deps
pip install -r requirements.txt

# Init DB + run migrations
alembic upgrade head

# Simulate data
python -m simulate.wafer
python -m simulate.process

# Ingest to DB
python -m ingest.loader

# Launch dashboard
streamlit run dashboard/app.py
```

## CV Framing
"Simulated and analysed semiconductor fab process data across 500+ wafers
and 20 lots. Built SQL schema modelling wafer lots, process steps,
measurements, and SPC flags. Implemented Western Electric SPC rules,
yield analysis, and defect density trends via a Streamlit dashboard."

## Testing

### Stack
- `pytest` — test runner
- `pytest-cov` — coverage reporting
- In-memory SQLite (`sqlite:///:memory:`) for all DB tests — fast, no cleanup needed

### Test Structure
tests/
├── conftest.py           # Shared fixtures (in-memory DB session, sample data)
├── test_models.py        # ORM models create correctly, relationships resolve
├── test_simulate.py      # Simulation output shape, value ranges, no nulls
├── test_ingest.py        # CSV rows land in correct DB tables with correct types
├── test_queries.py       # SQL queries return expected aggregations and filters
└── test_spc.py           # Each Western Electric rule flags correctly

### Key Fixtures (conftest.py)
- `db_session` — spins up in-memory SQLite, creates all tables, yields session,
  tears down after each test
- `sample_lot` — inserts one lot + 3 wafers for query tests
- `sample_measurements` — inserts controlled measurement series for SPC tests

### SPC Test Cases (test_spc.py)
Each rule must have a passing case and a non-flagging case:
- Rule 1: series with one point at mean + 4σ → should flag
- Rule 1: series within ±2σ → should not flag
- Rule 2: 8 points all above mean → should flag
- Rule 2: alternating above/below → should not flag
- Rule 3: strictly increasing sequence of 6 → should flag
- Rule 4: 2 of 3 points beyond 2σ same side → should flag

### SQL Query Test Cases (test_queries.py)
- Yield aggregation returns correct average across known wafers
- SPC flag count matches manually injected violations
- Process step filter returns only measurements for that step
- Lot status filter excludes completed lots correctly

### Running Tests
```bash
# Run all tests
pytest

# With coverage report
pytest --cov=waferlens --cov-report=term-missing

# Single file
pytest tests/test_spc.py -v
```

### Coverage Target
Aim for 70%+ overall, with 90%+ on `analysis/spc.py` and `analysis/queries.py`
since these are the most logic-heavy and CV-visible modules.
