"""SPC Monitor — control charts per step/parameter, flag history."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analysis.queries import measurements_for_step, spc_flags_detail
from db.session import get_session


@st.cache_data(ttl=60)
def _load_flags():
    with get_session() as s:
        return pd.DataFrame(spc_flags_detail(s))


@st.cache_data(ttl=60)
def _load_series(step_id: int, parameter: str):
    with get_session() as s:
        return pd.DataFrame(measurements_for_step(s, step_id, parameter))


def render():
    st.header("SPC Monitor")

    flags_df = _load_flags()
    if flags_df.empty:
        st.warning("No SPC flags — run analysis/spc.py first.")
        return

    # --- Selectors ---
    steps = flags_df[["step_name", "tool_id"]].drop_duplicates().sort_values("step_name")
    step_labels = {f"{r.step_name} ({r.tool_id})": r.step_name for r in steps.itertuples()}
    step_choice = st.sidebar.selectbox("Process Step", list(step_labels.keys()))
    selected_step = step_choice  # used for flag filter

    step_flags = flags_df[flags_df["step_name"] == step_labels[step_choice]]
    params = sorted(step_flags["parameter"].unique())
    parameter = st.sidebar.selectbox("Parameter", params)

    # --- Resolve step_id ---
    with get_session() as s:
        from sqlalchemy import text
        row = s.execute(
            text("SELECT step_id FROM process_steps WHERE step_name = :n"),
            {"n": step_labels[step_choice]},
        ).fetchone()
    if row is None:
        st.error("Step not found.")
        return
    step_id = row[0]

    series = _load_series(step_id, parameter)
    if series.empty:
        st.info("No measurements for this selection.")
        return

    values = series["value"].to_numpy(dtype=float)
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1))
    ucl, lcl = mean + 3 * std, mean - 3 * std

    # KPIs
    flagged_ids = set(step_flags[step_flags["parameter"] == parameter]["measurement_id"])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Mean", f"{mean:.3f}")
    c2.metric("Std Dev", f"{std:.3f}")
    c3.metric("UCL / LCL", f"{ucl:.2f} / {lcl:.2f}")
    c4.metric("Flags", len(flagged_ids))

    # --- Control chart ---
    st.subheader(f"Control Chart — {parameter}")
    flag_mask = series["measurement_id"].isin(flagged_ids)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=series.index, y=series["value"],
        mode="lines+markers", name="Value",
        marker=dict(color=["red" if f else "steelblue" for f in flag_mask], size=6),
        line=dict(color="steelblue", width=1),
    ))
    for y, label, color in [
        (ucl, "UCL (+3σ)", "red"),
        (mean, "Mean", "green"),
        (lcl, "LCL (-3σ)", "red"),
    ]:
        fig.add_hline(y=y, line_dash="dash", line_color=color,
                      annotation_text=label, annotation_position="right")
    fig.update_layout(xaxis_title="Sample", yaxis_title=parameter,
                      margin=dict(t=20, b=20), height=380)
    st.plotly_chart(fig, use_container_width=True)

    # --- Flag history table ---
    st.subheader("Flag History (this step)")
    step_flag_table = step_flags[
        ["flag_id", "rule_violated", "parameter", "value", "wafer_id", "lot_id", "product", "measured_at"]
    ].reset_index(drop=True)
    st.dataframe(step_flag_table, use_container_width=True, hide_index=True)
