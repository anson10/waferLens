select
    route_step_id,
    parameter_id,
    wafers_per_lot,
    sites_per_wafer,
    target,
    lsl,
    usl
from {{ source('waferlens', 'metrology_plans') }}
