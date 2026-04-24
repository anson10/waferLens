"""Defect Trends — defect density over time and correlation with yield."""

import pandas as pd
import plotly.express as px
import streamlit as st

from analysis.yield_analysis import defect_density_trend
from analysis.queries import yield_by_lot
from db.session import get_session


@st.cache_data(ttl=60)
def _load():
    with get_session() as s:
        lots = pd.DataFrame(yield_by_lot(s))
        trend = defect_density_trend(s)
    return lots, trend


def render():
    st.header("Defect Trends")

    lots, trend = _load()
    if lots.empty:
        st.warning("No data — run the ingest pipeline first.")
        return

    # --- Defect density over time ---
    st.subheader("Defect Density Over Time (by Lot)")
    fig = px.line(
        trend, x="start_date", y="avg_defect_density", markers=True,
        labels={"start_date": "Lot Start Date", "avg_defect_density": "Avg Defect Density"},
        color_discrete_sequence=["tomato"],
    )
    fig.update_layout(margin=dict(t=20, b=20))
    st.plotly_chart(fig, use_container_width=True)

    st.divider()
    col_left, col_right = st.columns(2)

    with col_left:
        # --- Defect density vs yield scatter ---
        st.subheader("Defect Density vs Yield")
        fig = px.scatter(
            lots, x="avg_defect_density", y="avg_yield_pct",
            color="technology_node", hover_data=["lot_id", "product"],
            trendline="ols",
            labels={
                "avg_defect_density": "Avg Defect Density",
                "avg_yield_pct": "Avg Yield (%)",
                "technology_node": "Node",
            },
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig.update_layout(margin=dict(t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)

    with col_right:
        # --- Defect density by technology node box plot ---
        st.subheader("Defect Density by Technology Node")
        fig = px.box(
            lots, x="technology_node", y="avg_defect_density",
            color="technology_node",
            labels={
                "technology_node": "Node",
                "avg_defect_density": "Avg Defect Density",
            },
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig.update_layout(showlegend=False, margin=dict(t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)

    # --- Defect density by product ---
    st.subheader("Avg Defect Density by Product")
    product_stats = (
        lots.groupby("product")["avg_defect_density"]
        .mean()
        .reset_index()
        .sort_values("avg_defect_density", ascending=False)
    )
    fig = px.bar(
        product_stats, x="product", y="avg_defect_density",
        color="product",
        labels={"product": "Product", "avg_defect_density": "Avg Defect Density"},
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig.update_layout(showlegend=False, margin=dict(t=20, b=20))
    st.plotly_chart(fig, use_container_width=True)
