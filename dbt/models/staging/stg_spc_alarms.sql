select
    alarm_id,
    limit_id,
    chart,
    wafer_id,
    route_step_id,
    pass_no,
    measured_at,
    statistic,
    direction
from {{ source('waferlens', 'spc_alarms') }}
