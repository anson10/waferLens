"""Process Explorer — drill down by step: parameter distributions and stats."""

import math

import pandas as pd
import plotly.express as px
import streamlit as st

from analysis.queries import measurements_for_step, process_step_stats
from db.session import get_session


@st.cache_data(ttl=60)
def _load_stats():
    with get_session() as s:
        return pd.DataFrame(process_step_stats(s))


@st.cache_data(ttl=60)
def _load_all_measurements(step_id: int):
    """Load all parameters for a step in one query."""
    with get_session() as s:
        from sqlalchemy import text
        rows = s.execute(
            text(
                """
                SELECT m.measurement_id, m.parameter, m.value, m.wafer_id
                FROM measurements m
                WHERE m.step_id = :sid
                ORDER BY m.parameter
                """
            ),
            {"sid": step_id},
        ).mappings().all()
    return pd.DataFrame([dict(r) for r in rows])


def render():
    st.header("Process Explorer")

    stats = _load_stats()
    if stats.empty:
        st.warning("No data — run the ingest pipeline first.")
        return

    steps = stats[["step_id", "step_name", "tool_id"]].drop_duplicates().sort_values("step_name")
    step_labels = {f"{r.step_name} ({r.tool_id})": int(r.step_id) for r in steps.itertuples()}
    choice = st.sidebar.selectbox("Process Step", list(step_labels.keys()))
    step_id = step_labels[choice]

    step_stats = stats[stats["step_id"] == step_id].copy()
    step_stats["std"] = step_stats["variance"].apply(lambda v: math.sqrt(max(v, 0)))

    st.subheader(f"Parameter Statistics — {choice}")
    display_cols = ["parameter", "measurement_count", "mean_value", "std"]
    st.dataframe(
        step_stats[display_cols].rename(columns={
            "measurement_count": "count",
            "mean_value": "mean",
        }),
        use_container_width=True,
        hide_index=True,
    )

    st.divider()
    st.subheader("Parameter Distributions")

    meas = _load_all_measurements(step_id)
    if meas.empty:
        return

    params = sorted(meas["parameter"].unique())
    cols_per_row = 2
    rows = [params[i:i + cols_per_row] for i in range(0, len(params), cols_per_row)]

    for row_params in rows:
        cols = st.columns(len(row_params))
        for col, param in zip(cols, row_params):
            with col:
                subset = meas[meas["parameter"] == param]
                fig = px.histogram(
                    subset, x="value", nbins=30,
                    title=param,
                    labels={"value": param},
                    color_discrete_sequence=["steelblue"],
                )
                fig.update_layout(margin=dict(t=40, b=20), height=260, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
