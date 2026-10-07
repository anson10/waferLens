"""The event contract between tool agents (producers) and real-time SPC (consumers).

One event per sensor summary a chamber reports for a wafer step, as JSON on the
``sensor-readings`` topic, keyed by chamber so each chamber's events stay in order (Kafka
orders within a partition, and the key picks the partition).

``schema`` names the contract and its version. A consumer accepts the versions it knows and
rejects the rest loudly instead of misreading them; a breaking change gets a new version
(and, in production, a schema registry).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TOPIC = "sensor-readings"
SCHEMA = "waferlens.sensor_reading/v1"


class SensorReading(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_: Literal["waferlens.sensor_reading/v1"] = Field(default=SCHEMA, alias="schema")
    measured_at: datetime  # event time: when the tool reported it
    wafer_id: int
    route_step_id: int
    parameter_id: int
    chamber_id: int
    value: float
    produced_at: datetime  # wall clock when published; latency is measured from here

    @property
    def event_id(self) -> str:
        """The reading's identity (the table's primary key): replays carry the same id."""
        return (f"{self.wafer_id}-{self.route_step_id}-{self.parameter_id}-"
                f"{self.measured_at.isoformat()}")  # fmt: skip

    @property
    def key(self) -> bytes:
        return str(self.chamber_id).encode()

    def to_bytes(self) -> bytes:
        return self.model_dump_json(by_alias=True).encode()

    @classmethod
    def from_bytes(cls, raw: bytes) -> SensorReading:
        return cls.model_validate_json(raw)
