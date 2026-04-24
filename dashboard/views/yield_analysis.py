"""Yield Analysis page — yield by lot, product, technology node, low-yield wafers."""

import pandas as pd
import plotly.express as px
import streamlit as st

from analysis.yield_analysis import defect_density_trend, low_yield_summary, yield_summary
from db.session import get_session


@st.cache_data(ttl=60)
def _load():
    with get_session() as s:
        summary = yield_summary(s)
        trend = defect_density_trend(s)
    return summary, trend


def render():
    st.header("Yield Analysis")

    summary, trend = _load()
    by_lot: pd.DataFrame = summary["by_lot"]

    if by_lot.empty:
        st.warning("No data — run the ingest pipeline first.")
        return

    threshold = st.sidebar.slider("Low-yield threshold (%)", 60, 95, 80)

    # --- Yield by lot ---
    st.subheader("Yield % by Lot")
    fig = px.bar(
        by_lot, x="lot_id", y="avg_yield_pct",
        color="product",
        labels={"lot_id": "Lot ID", "avg_yield_pct": "Avg Yield (%)"},
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig.add_hline(y=threshold, line_dash="dash", line_color="red",
                  annotation_text=f"Threshold {threshold}%")
    fig.update_layout(margin=dict(t=20, b=20))
    st.plotly_chart(fig, use_container_width=True)

    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Yield by Product")
        fig = px.bar(
            summary["by_product"], x="product", y="avg_yield_pct",
            labels={"product": "Product", "avg_yield_pct": "Avg Yield (%)"},
            color="product",
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig.update_layout(showlegend=False, margin=dict(t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.subheader("Yield by Technology Node")
        fig = px.bar(
            summary["by_node"], x="technology_node", y="avg_yield_pct",
            labels={"technology_node": "Node", "avg_yield_pct": "Avg Yield (%)"},
            color="technology_node",
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig.update_layout(showlegend=False, margin=dict(t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)

    # --- Defect density trend ---
    st.subheader("Defect Density Trend (by Lot Start Date)")
    if not trend.empty:
        fig = px.line(
            trend, x="start_date", y="avg_defect_density", markers=True,
            labels={"start_date": "Start Date", "avg_defect_density": "Avg Defect Density"},
        )
        fig.update_layout(margin=dict(t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)

    # --- Low yield wafers ---
    st.subheader(f"Wafers Below {threshold}% Yield")
    with get_session() as s:
        low_df = low_yield_summary(s, threshold=threshold)
    if low_df.empty:
        st.success(f"No wafers below {threshold}%.")
    else:
        st.dataframe(low_df, use_container_width=True, hide_index=True)
