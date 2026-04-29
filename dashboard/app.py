"""Streamlit entry point — sidebar navigation across all dashboard pages."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

st.set_page_config(page_title="WaferLens", layout="wide")


@st.cache_resource
def _db_ready() -> bool:
    """Return True once tables exist and are seeded. Cached so this runs once per process."""
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

    return True


def _bootstrap_with_ui() -> None:
    """Show a stepped loading UI on first cold start, then rerun into the normal app."""
    from sqlalchemy import text
    from db.models import Base
    from db.session import engine, get_session
    from ingest.loader import run as ingest_run
    from analysis.spc import run_spc

    st.title("WaferLens")
    st.caption("Semiconductor process analytics")

    with st.status("Starting up…", expanded=True) as status:
        st.write("Creating database schema…")
        Base.metadata.create_all(engine)

        st.write("Loading wafer lots and measurements…")
        ingest_run()

        st.write("Running SPC analysis…")
        with get_session() as session:
            run_spc(session)

        status.update(label="Ready!", state="complete", expanded=False)

    st.cache_resource.clear()
    st.rerun()


# On the very first request the cache is cold — peek cheaply without importing
# heavy modules, then decide whether to show the loading UI.
def _needs_seed() -> bool:
    from sqlalchemy import text, inspect
    from db.session import engine

    insp = inspect(engine)
    if not insp.has_table("lots"):
        return True
    from db.session import get_session
    with get_session() as session:
        return session.execute(text("SELECT COUNT(*) FROM lots")).scalar() == 0


if _needs_seed():
    _bootstrap_with_ui()
    st.stop()

_db_ready()

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
