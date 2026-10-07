{{ config(indexes=[{'columns': ['alarm_id'], 'unique': True}, {'columns': ['measured_at']}]) }}

-- Grain: one row per alarm (a point that signalled on one chart of one series). Carries the
-- series context reports filter by: chamber or tool scope, parameter (null for T²), the
-- chamber that processed the wafer (for tool-scope series too), and its lot and product.
select
    a.alarm_id,
    a.chart,
    c.chart_name,
    c.chart_family,
    l.source,
    l.scope,
    l.limit_id,
    l.limit_version,
    l.tool_id,
    coalesce(l.chamber_id, s.chamber_id) as chamber_id,
    l.parameter_id,
    a.route_step_id,
    a.wafer_id,
    a.pass_no,
    s.lot_id,
    w.product_id,
    a.measured_at,
    to_char(a.measured_at at time zone 'UTC', 'YYYYMMDD')::int as date_key,
    a.statistic,
    a.direction,
    l.baseline_end_at
from {{ ref('stg_spc_alarms') }} as a
inner join {{ ref('stg_spc_control_limits') }} as l on a.limit_id = l.limit_id
inner join {{ ref('stg_wafer_step_history') }} as s
    on a.wafer_id = s.wafer_id and a.route_step_id = s.route_step_id and a.pass_no = s.pass_no
inner join {{ ref('dim_wafer') }} as w on a.wafer_id = w.wafer_id
-- The seed names each chart; the inner join also guarantees every chart code is known.
inner join {{ ref('spc_charts') }} as c on a.chart = c.chart
