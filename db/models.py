"""SQLAlchemy ORM models.

Schema:
    lots ── wafers ──┬── measurements ── spc_flags
                     │         │
                     │   process_steps
                     │
                     └── yield_records
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Lot(Base):
    __tablename__ = "lots"

    lot_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product: Mapped[str] = mapped_column(String(64), nullable=False)
    technology_node: Mapped[str] = mapped_column(String(16), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    wafers: Mapped[list["Wafer"]] = relationship(back_populates="lot")

    def __repr__(self) -> str:
        return f"<Lot {self.lot_id} {self.product} {self.technology_node}>"


class Wafer(Base):
    __tablename__ = "wafers"

    wafer_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.lot_id"), nullable=False, index=True)
    wafer_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    lot: Mapped["Lot"] = relationship(back_populates="wafers")
    measurements: Mapped[list["Measurement"]] = relationship(back_populates="wafer")
    yield_records: Mapped[list["YieldRecord"]] = relationship(back_populates="wafer")

    def __repr__(self) -> str:
        return f"<Wafer lot={self.lot_id} n={self.wafer_number}>"


class ProcessStep(Base):
    __tablename__ = "process_steps"

    step_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    step_name: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    layer: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False)

    measurements: Mapped[list["Measurement"]] = relationship(back_populates="step")

    def __repr__(self) -> str:
        return f"<ProcessStep {self.sequence_order}:{self.step_name} tool={self.tool_id}>"


class Measurement(Base):
    __tablename__ = "measurements"

    measurement_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wafer_id: Mapped[int] = mapped_column(ForeignKey("wafers.wafer_id"), nullable=False, index=True)
    step_id: Mapped[int] = mapped_column(ForeignKey("process_steps.step_id"), nullable=False, index=True)
    parameter: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    wafer: Mapped["Wafer"] = relationship(back_populates="measurements")
    step: Mapped["ProcessStep"] = relationship(back_populates="measurements")
    spc_flags: Mapped[list["SpcFlag"]] = relationship(back_populates="measurement")


class YieldRecord(Base):
    __tablename__ = "yield_records"

    record_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wafer_id: Mapped[int] = mapped_column(ForeignKey("wafers.wafer_id"), nullable=False, index=True)
    die_count: Mapped[int] = mapped_column(Integer, nullable=False)
    pass_count: Mapped[int] = mapped_column(Integer, nullable=False)
    yield_pct: Mapped[float] = mapped_column(Float, nullable=False)
    defect_density: Mapped[float] = mapped_column(Float, nullable=False)

    wafer: Mapped["Wafer"] = relationship(back_populates="yield_records")


class SpcFlag(Base):
    __tablename__ = "spc_flags"

    flag_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    measurement_id: Mapped[int] = mapped_column(
        ForeignKey("measurements.measurement_id"), nullable=False, index=True
    )
    rule_violated: Mapped[str] = mapped_column(String(32), nullable=False)
    flagged_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    measurement: Mapped["Measurement"] = relationship(back_populates="spc_flags")
