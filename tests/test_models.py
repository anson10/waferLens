"""Smoke tests for ORM models and relationships."""

from datetime import date, datetime

from db.models import Lot, Measurement, ProcessStep, SpcFlag, Wafer, YieldRecord


def test_full_chain_round_trip(db_session):
    lot = Lot(
        product="FooChip",
        technology_node="28nm",
        start_date=date(2026, 1, 1),
        status="active",
    )
    wafer = Wafer(wafer_number=1, status="in_progress", lot=lot)
    step = ProcessStep(
        step_name="lithography", tool_id="LITHO-01", layer="M1", sequence_order=1
    )
    measurement = Measurement(
        wafer=wafer,
        step=step,
        parameter="thickness_nm",
        value=42.0,
        unit="nm",
        timestamp=datetime(2026, 1, 2, 12, 0),
    )
    flag = SpcFlag(
        measurement=measurement,
        rule_violated="WE1",
        flagged_at=datetime(2026, 1, 2, 12, 5),
    )
    yrec = YieldRecord(
        wafer=wafer, die_count=100, pass_count=92, yield_pct=92.0, defect_density=0.3
    )

    db_session.add_all([lot, wafer, step, measurement, flag, yrec])
    db_session.commit()

    reloaded = db_session.get(Lot, lot.lot_id)
    assert reloaded is not None
    assert len(reloaded.wafers) == 1
    w = reloaded.wafers[0]
    assert w.lot is reloaded
    assert w.measurements[0].parameter == "thickness_nm"
    assert w.measurements[0].step.step_name == "lithography"
    assert w.measurements[0].spc_flags[0].rule_violated == "WE1"
    assert w.yield_records[0].yield_pct == 92.0


def test_process_step_backref(db_session):
    step = ProcessStep(step_name="etch", tool_id="ETCH-02", layer="V1", sequence_order=5)
    lot = Lot(product="BarChip", technology_node="65nm", start_date=date(2026, 1, 1), status="active")
    wafer = Wafer(wafer_number=2, status="active", lot=lot)
    m1 = Measurement(
        wafer=wafer, step=step, parameter="etch_rate", value=10.5,
        unit="nm/s", timestamp=datetime(2026, 1, 2, 9, 0),
    )
    m2 = Measurement(
        wafer=wafer, step=step, parameter="etch_rate", value=10.7,
        unit="nm/s", timestamp=datetime(2026, 1, 2, 9, 30),
    )
    db_session.add_all([lot, wafer, step, m1, m2])
    db_session.commit()

    assert len(step.measurements) == 2
