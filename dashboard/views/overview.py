"""Overview page — lot status, wafer counts, SPC flag summary."""

import pandas as pd
import plotly.express as px
import streamlit as st

from analysis.queries import spc_flag_counts, yield_by_lot
from db.session import get_session


@st.cache_data(ttl=60)
def _load():
    with get_session() as s:
        lots = pd.DataFrame(yield_by_lot(s))
        flags = pd.DataFrame(spc_flag_counts(s))
    return lots, flags


def render():
    st.header("Overview")

    lots, flags = _load()

    if lots.empty:
        st.warning("No data — run the ingest pipeline first.")
        return

    # --- KPI row ---
    total_wafers = int(lots["wafer_count"].sum())
    avg_yield = lots["avg_yield_pct"].mean()
    total_flags = int(flags["flag_count"].sum()) if not flags.empty else 0
    active_lots = int((lots["status"] == "active").sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Lots", len(lots))
    c2.metric("Wafers", total_wafers)
    c3.metric("Avg Yield", f"{avg_yield:.1f}%")
    c4.metric("SPC Flags", total_flags)

    st.divider()

    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Lot Status")
        status_counts = lots["status"].value_counts().reset_index()
        status_counts.columns = ["status", "count"]
        fig = px.pie(status_counts, names="status", values="count",
                     color_discrete_sequence=px.colors.qualitative.Set2)
        fig.update_layout(margin=dict(t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.subheader("SPC Flags by Rule")
        if flags.empty:
            st.info("No SPC flags found.")
        else:
            fig = px.bar(flags, x="rule_violated", y="flag_count",
                         labels={"rule_violated": "Rule", "flag_count": "Flags"},
                         color="rule_violated",
                         color_discrete_sequence=px.colors.qualitative.Set2)
            fig.update_layout(showlegend=False, margin=dict(t=20, b=20))
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Lot Table")
    st.dataframe(
        lots[["lot_id", "product", "technology_node", "start_date",
              "status", "wafer_count", "avg_yield_pct", "avg_defect_density"]],
        use_container_width=True,
        hide_index=True,
    )
