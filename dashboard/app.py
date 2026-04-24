"""Streamlit entry point — sidebar navigation across all dashboard pages."""

import streamlit as st

st.set_page_config(page_title="WaferLens", layout="wide")

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
