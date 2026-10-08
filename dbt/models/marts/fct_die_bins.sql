{{ config(indexes=[{'columns': ['wafer_id', 'bin_code'], 'unique': True}]) }}

-- Grain: one row per sorted wafer x bin: how many dies landed in each bin, and that bin's
-- share of the wafer (a window over the wafer's rows). Feeds the yield Pareto. Carries the
-- wafer's lot and product keys like the other wafer facts, so a BI model can filter losses
-- by product without going through another fact.
select
    b.wafer_id,
    w.current_lot_id as lot_id,
    l.product_id,
    b.bin_code,
    to_char(m.tested_at at time zone 'UTC', 'YYYYMMDD')::int as tested_date_key,
    b.die_count,
    round(b.die_count::numeric / sum(b.die_count) over (partition by b.wafer_id), 4)
        as share_of_wafer
from {{ ref('stg_wafer_bin_summary') }} as b
inner join {{ ref('stg_wafer_maps') }} as m on b.wafer_id = m.wafer_id
inner join {{ ref('stg_wafers') }} as w on b.wafer_id = w.wafer_id
inner join {{ ref('stg_lots') }} as l on w.current_lot_id = l.lot_id
