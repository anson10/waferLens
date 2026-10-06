{{ config(indexes=[{'columns': ['wafer_id'], 'unique': True}, {'columns': ['tested_at']}]) }}

-- Grain: one row per sorted wafer. Yield is good dies / tested dies, pass/fail from the sort
-- bins (so a new fail bin needs no change here). Cycle time runs from the wafer's first
-- track-in to its last track-out.
with bins as (
    select
        b.wafer_id,
        sum(b.die_count) as tested_dies,
        coalesce(sum(b.die_count) filter (where s.is_pass), 0) as good_dies
    from {{ ref('stg_wafer_bin_summary') }} as b
    inner join {{ ref('stg_sort_bins') }} as s on b.bin_code = s.bin_code
    group by b.wafer_id
),

route as (
    select
        wafer_id,
        min(track_in_at) as started_at,
        max(track_out_at) as finished_at
    from {{ ref('stg_wafer_step_history') }}
    group by wafer_id
)

select
    m.wafer_id,
    w.current_lot_id as lot_id,
    l.product_id,
    m.tested_at,
    to_char(m.tested_at at time zone 'UTC', 'YYYYMMDD')::int as tested_date_key,
    r.started_at,
    r.finished_at,
    (extract(epoch from r.finished_at - r.started_at) / 86400.0)::double precision
        as cycle_time_days,
    b.tested_dies,
    b.good_dies,
    b.tested_dies - b.good_dies as failed_dies,
    round(100.0 * b.good_dies / nullif(b.tested_dies, 0), 2) as yield_pct
from {{ ref('stg_wafer_maps') }} as m
inner join bins as b on m.wafer_id = b.wafer_id
inner join route as r on m.wafer_id = r.wafer_id
inner join {{ ref('stg_wafers') }} as w on m.wafer_id = w.wafer_id
inner join {{ ref('stg_lots') }} as l on w.current_lot_id = l.lot_id
