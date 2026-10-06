select
    time as measured_at,
    wafer_id,
    route_step_id,
    parameter_id,
    chamber_id,
    value
from {{ source('waferlens', 'tool_sensor_readings') }}
