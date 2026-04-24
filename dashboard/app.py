"""Streamlit entry point — sidebar navigation across all dashboard pages."""

import streamlit as st

st.set_page_config(page_title="WaferLens", layout="wide")

from dashboard.views.overview import render as render_overview
from dashboard.views.yield_analysis import render as render_yield

PAGES = {
    "Overview": render_overview,
    "Yield Analysis": render_yield,
}

st.sidebar.title("WaferLens")
selection = st.sidebar.radio("Navigate", list(PAGES.keys()))
PAGES[selection]()
