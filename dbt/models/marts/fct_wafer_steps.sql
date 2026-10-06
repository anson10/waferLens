{{
    config(indexes=[
        {'columns': ['wafer_id', 'route_step_id', 'pass_no'], 'unique': True},
        {'columns': ['chamber_id', 'track_in_at']},
    ])
}}

-- Grain: one row per wafer x route step x pass: where the wafer was processed (chamber,
-- recipe, lot), when, how long it queued and how long the step took. The basis for
-- commonality analysis (phase 3) and cycle-time reporting.
select
    h.wafer_id,
    h.route_step_id,
    h.pass_no,
    h.lot_id,
    h.chamber_id,
    h.recipe_id,
    to_char(h.track_in_at at time zone 'UTC', 'YYYYMMDD')::int as date_key,
    h.track_in_at,
    h.track_out_at,
    h.queue_hours,
    h.process_minutes,
    h.is_final_pass,
    h.pass_no > 1 as is_rework
from {{ ref('int_wafer_route_history') }} as h
