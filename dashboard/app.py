"""Streamlit entry point — sidebar navigation across all dashboard pages."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

st.set_page_config(page_title="WaferLens", layout="wide")


@st.cache_resource(show_spinner="Initialising database…")
def _bootstrap() -> None:
    """Create tables and seed from CSVs if the DB is empty (Streamlit Cloud first run)."""
    from sqlalchemy import text
    from db.models import Base
    from db.session import engine, get_session
    from ingest.loader import run as ingest_run
    from analysis.spc import run_spc

    Base.metadata.create_all(engine)

    with get_session() as session:
        count = session.execute(text("SELECT COUNT(*) FROM lots")).scalar()

    if count == 0:
        ingest_run()
        with get_session() as session:
            run_spc(session)


_bootstrap()

from dashboard.views.overview import render as render_overview
from dashboard.views.yield_analysis import render as render_yield
from dashboard.views.spc_monitor import render as render_spc
from dashboard.views.process_explorer import render as render_process
from dashboard.views.defect_trends import render as render_defect

PAGES = {
    "Overview": render_overview,
    "Yield Analysis": render_yield,
    "SPC Monitor": render_spc,
    "Process Explorer": render_process,
    "Defect Trends": render_defect,
}

st.sidebar.title("WaferLens")
selection = st.sidebar.radio("Navigate", list(PAGES.keys()))
PAGES[selection]()
