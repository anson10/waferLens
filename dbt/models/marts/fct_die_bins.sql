{{ config(indexes=[{'columns': ['wafer_id', 'bin_code'], 'unique': True}]) }}

-- Grain: one row per sorted wafer x bin: how many dies landed in each bin, and that bin's
-- share of the wafer (a window over the wafer's rows). Feeds the yield Pareto.
select
    b.wafer_id,
    b.bin_code,
    to_char(m.tested_at at time zone 'UTC', 'YYYYMMDD')::int as tested_date_key,
    b.die_count,
    round(b.die_count::numeric / sum(b.die_count) over (partition by b.wafer_id), 4)
        as share_of_wafer
from {{ ref('stg_wafer_bin_summary') }} as b
inner join {{ ref('stg_wafer_maps') }} as m on b.wafer_id = m.wafer_id
