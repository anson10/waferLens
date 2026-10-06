select
    s.route_step_id,
    s.route_id,
    r.product_id,
    s.sequence_no,
    s.step_name,
    s.layer,
    s.tool_type,
    s.route_step_id in (select route_step_id from {{ ref('stg_metrology_plans') }})
        as has_metrology
from {{ ref('stg_route_steps') }} as s
inner join {{ ref('stg_routes') }} as r on s.route_id = r.route_id
