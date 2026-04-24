"""Raw SQL query functions for reuse in the dashboard and analysis layers."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def yield_by_lot(session: Session) -> list[dict]:
    """Average yield and defect density per lot, ordered by lot_id."""
    rows = session.execute(
        text(
            """
            SELECT
                l.lot_id,
                l.product,
                l.technology_node,
                l.start_date,
                l.status,
                COUNT(yr.record_id)              AS wafer_count,
                ROUND(AVG(yr.yield_pct), 2)      AS avg_yield_pct,
                ROUND(AVG(yr.defect_density), 4) AS avg_defect_density
            FROM lots l
            JOIN wafers       w  ON w.lot_id    = l.lot_id
            JOIN yield_records yr ON yr.wafer_id = w.wafer_id
            GROUP BY l.lot_id, l.product, l.technology_node, l.start_date, l.status
            ORDER BY l.lot_id
            """
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def yield_by_product(session: Session) -> list[dict]:
    """Average yield grouped by product, ordered descending by yield."""
    rows = session.execute(
        text(
            """
            SELECT
                l.product,
                COUNT(yr.record_id)              AS wafer_count,
                ROUND(AVG(yr.yield_pct), 2)      AS avg_yield_pct,
                ROUND(AVG(yr.defect_density), 4) AS avg_defect_density
            FROM lots l
            JOIN wafers       w  ON w.lot_id    = l.lot_id
            JOIN yield_records yr ON yr.wafer_id = w.wafer_id
            GROUP BY l.product
            ORDER BY avg_yield_pct DESC
            """
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def yield_by_node(session: Session) -> list[dict]:
    """Average yield grouped by technology node."""
    rows = session.execute(
        text(
            """
            SELECT
                l.technology_node,
                COUNT(yr.record_id)              AS wafer_count,
                ROUND(AVG(yr.yield_pct), 2)      AS avg_yield_pct,
                ROUND(AVG(yr.defect_density), 4) AS avg_defect_density
            FROM lots l
            JOIN wafers       w  ON w.lot_id    = l.lot_id
            JOIN yield_records yr ON yr.wafer_id = w.wafer_id
            GROUP BY l.technology_node
            ORDER BY avg_yield_pct DESC
            """
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def spc_flag_counts(session: Session) -> list[dict]:
    """Total SPC flags per rule, ordered by count descending."""
    rows = session.execute(
        text(
            """
            SELECT
                sf.rule_violated,
                COUNT(*) AS flag_count
            FROM spc_flags sf
            GROUP BY sf.rule_violated
            ORDER BY flag_count DESC
            """
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def measurements_for_step(
    session: Session, step_id: int, parameter: str
) -> list[dict]:
    """Ordered measurements for a (step, parameter) pair — used for control charts."""
    rows = session.execute(
        text(
            """
            SELECT
                m.measurement_id,
                m.wafer_id,
                m.value,
                m.timestamp
            FROM measurements m
            WHERE m.step_id   = :step_id
              AND m.parameter = :parameter
            ORDER BY m.timestamp
            """
        ),
        {"step_id": step_id, "parameter": parameter},
    ).mappings().all()
    return [dict(r) for r in rows]


def spc_flags_detail(session: Session) -> list[dict]:
    """SPC flags joined with measurement and step context — used for flag history table."""
    rows = session.execute(
        text(
            """
            SELECT
                sf.flag_id,
                sf.rule_violated,
                sf.flagged_at,
                m.measurement_id,
                m.parameter,
                m.value,
                m.timestamp  AS measured_at,
                ps.step_name,
                ps.tool_id,
                w.wafer_id,
                l.lot_id,
                l.product
            FROM spc_flags sf
            JOIN measurements  m  ON m.measurement_id = sf.measurement_id
            JOIN process_steps ps ON ps.step_id        = m.step_id
            JOIN wafers        w  ON w.wafer_id         = m.wafer_id
            JOIN lots          l  ON l.lot_id            = w.lot_id
            ORDER BY sf.flagged_at DESC
            """
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def process_step_stats(session: Session) -> list[dict]:
    """Mean, std, and count per (step, parameter) — used for Process Explorer."""
    rows = session.execute(
        text(
            """
            SELECT
                ps.step_id,
                ps.step_name,
                ps.tool_id,
                ps.layer,
                m.parameter,
                COUNT(*)                         AS measurement_count,
                ROUND(AVG(m.value), 4)           AS mean_value,
                ROUND(AVG(m.value * m.value) - AVG(m.value) * AVG(m.value), 6) AS variance
            FROM measurements m
            JOIN process_steps ps ON ps.step_id = m.step_id
            GROUP BY ps.step_id, ps.step_name, ps.tool_id, ps.layer, m.parameter
            ORDER BY ps.sequence_order, m.parameter
            """
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def low_yield_wafers(session: Session, threshold: float = 80.0) -> list[dict]:
    """Wafers below a yield threshold, joined with lot context."""
    rows = session.execute(
        text(
            """
            SELECT
                w.wafer_id,
                w.wafer_number,
                l.lot_id,
                l.product,
                yr.yield_pct,
                yr.defect_density
            FROM yield_records yr
            JOIN wafers w ON w.wafer_id = yr.wafer_id
            JOIN lots   l ON l.lot_id   = w.lot_id
            WHERE yr.yield_pct < :threshold
            ORDER BY yr.yield_pct ASC
            """
        ),
        {"threshold": threshold},
    ).mappings().all()
    return [dict(r) for r in rows]
