-- Genealogy with full context: one row per wafer x route step x pass, in route order.
-- Adds the step, chamber, tool and recipe version, plus two window-function columns:
--   queue_hours   how long the wafer waited since leaving its previous step
--   is_final_pass the pass that metrology measures (a reworked step has pass 1 and 2)
with history as (
    select * from {{ ref('stg_wafer_step_history') }}
),

steps as (
    select * from {{ ref('stg_route_steps') }}
),

chambers as (
    select * from {{ ref('stg_chambers') }}
),

tools as (
    select * from {{ ref('stg_tools') }}
),

recipes as (
    select * from {{ ref('stg_recipes') }}
)

select
    h.wafer_id,
    h.route_step_id,
    h.pass_no,
    h.lot_id,
    s.sequence_no,
    s.step_name,
    s.layer,
    t.tool_type,
    c.tool_id,
    h.chamber_id,
    c.chamber_label,
    h.recipe_id,
    r.recipe_version,
    h.track_in_at,
    h.track_out_at,
    h.process_minutes,
    (extract(epoch from h.track_in_at - lag(h.track_out_at) over route_order) / 3600.0)
        ::double precision as queue_hours,
    row_number() over (
        partition by h.wafer_id, h.route_step_id order by h.pass_no desc
    ) = 1 as is_final_pass
from history as h
inner join steps as s on h.route_step_id = s.route_step_id
inner join chambers as c on h.chamber_id = c.chamber_id
inner join tools as t on c.tool_id = t.tool_id
inner join recipes as r on h.recipe_id = r.recipe_id
window route_order as (partition by h.wafer_id order by s.sequence_no, h.pass_no)
