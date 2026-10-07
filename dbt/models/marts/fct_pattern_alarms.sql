{{ config(indexes=[{'columns': ['pattern', 'alarmed_at']}]) }}

-- Grain: one row per wafer whose sort result raised a wafer-map pattern alarm.
--
-- Rule, fixed before any evaluation: for each pattern, count the wafers FabEye auto-accepted
-- with that pattern among those sorted in the last 24 hours. Alarm when the count reaches
-- greatest(3, 3 x the pattern's background rate per day), the background learned on the
-- first 30 days of sort data, like SPC's Phase I. 'none' never alarms.
with scored as (
    select wafer_id, tested_at, predicted_pattern as pattern
    from {{ ref('fct_wafer_pattern') }}
    where predicted_pattern <> 'none' and auto_accept
),

first_sort as (
    select min(tested_at) as at from {{ ref('fct_wafer_pattern') }}
),

background as (
    select s.pattern, count(*) / 30.0 as per_day
    from scored as s
    cross join first_sort as f
    where s.tested_at < f.at + interval '30 days'
    group by s.pattern
),

rolling as (
    select
        s.wafer_id,
        s.tested_at,
        s.pattern,
        count(*) over (
            partition by s.pattern order by s.tested_at
            range between interval '24 hours' preceding and current row
        ) as wafers_24h
    from scored as s
)

select
    r.wafer_id,
    r.tested_at as alarmed_at,
    r.pattern,
    r.wafers_24h,
    greatest(3, ceil(3 * coalesce(b.per_day, 0)))::int as threshold
from rolling as r
left join background as b on r.pattern = b.pattern
where r.wafers_24h >= greatest(3, ceil(3 * coalesce(b.per_day, 0)))
