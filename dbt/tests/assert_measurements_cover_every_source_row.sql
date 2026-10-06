-- No measurement lost in the union: every sensor reading is one fact row, and every
-- measured wafer x step x parameter is one metrology fact row.
with expected as (
    select 'sensor' as source, count(*) as n
    from {{ source('waferlens', 'tool_sensor_readings') }}
    union all
    select 'metrology', count(*)
    from (
        select distinct wafer_id, route_step_id, parameter_id
        from {{ source('waferlens', 'metrology_measurements') }}
    ) as m
),

actual as (
    select source, count(*) as n from {{ ref('fct_measurements') }} group by source
)

select e.source, e.n as expected, a.n as actual
from expected as e
left join actual as a on e.source = a.source
where a.n is distinct from e.n
