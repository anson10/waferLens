select
    route_step_id,
    route_id,
    sequence_no,
    step_name,
    layer,
    tool_type
from {{ source('waferlens', 'route_steps') }}
