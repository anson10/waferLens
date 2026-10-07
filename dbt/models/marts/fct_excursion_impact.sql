-- Grain: one row per injected excursion. What it cost: the wafers it touched, and how their
-- yield compares with comparable wafers that escaped it.
--
-- affected  chamber excursions and spatial patterns: wafers processed in the chamber inside
--           the window; recipe changes: wafers processed with the bad recipe version
-- control   wafers of the same product processed (any step) inside the same window that the
--           excursion did not touch. Comparing within the window cancels whatever else
--           happened to the fab at the time, e.g. another excursion overlapping this one.
-- dies_lost (control mean yield - wafer yield) x tested dies, summed over affected wafers
with excursions as (
    select excursion_id, excursion_type, chamber_id, recipe_id, started_at, ended_at
    from {{ ref('stg_excursions_ground_truth') }}
),

steps as (
    select wafer_id, chamber_id, recipe_id, track_in_at from {{ ref('fct_wafer_steps') }}
),

population as (
    select distinct e.excursion_id, s.wafer_id
    from excursions as e
    inner join steps as s on s.track_in_at >= e.started_at and s.track_in_at < e.ended_at
),

affected as (
    select distinct e.excursion_id, s.wafer_id
    from excursions as e
    inner join steps as s
        on s.chamber_id = e.chamber_id
        and s.track_in_at >= e.started_at
        and s.track_in_at < e.ended_at
    where e.recipe_id is null
    union
    select distinct e.excursion_id, s.wafer_id
    from excursions as e
    inner join steps as s on s.recipe_id = e.recipe_id
    where e.recipe_id is not null
),

labelled as (
    select
        p.excursion_id,
        y.wafer_id,
        y.product_id,
        y.yield_pct,
        y.tested_dies,
        a.wafer_id is not null as is_affected
    from population as p
    inner join {{ ref('fct_wafer_yield') }} as y on p.wafer_id = y.wafer_id
    left join affected as a on p.excursion_id = a.excursion_id and p.wafer_id = a.wafer_id
),

control as (
    select excursion_id, product_id, avg(yield_pct) as control_yield_pct
    from labelled
    where not is_affected
    group by excursion_id, product_id
)

select
    e.excursion_id,
    e.excursion_type,
    e.started_at,
    e.ended_at,
    count(l.wafer_id) as affected_wafers,
    round(avg(l.yield_pct)::numeric, 2) as affected_yield_pct,
    round(avg(c.control_yield_pct)::numeric, 2) as control_yield_pct,
    round(avg(l.yield_pct - c.control_yield_pct)::numeric, 2) as yield_delta_pct,
    round(coalesce(sum((c.control_yield_pct - l.yield_pct) / 100.0 * l.tested_dies), 0)::numeric)
        as dies_lost
from excursions as e
left join labelled as l on e.excursion_id = l.excursion_id and l.is_affected
left join control as c on l.excursion_id = c.excursion_id and l.product_id = c.product_id
group by e.excursion_id, e.excursion_type, e.started_at, e.ended_at
