-- Grain: one row per injected excursion. Where commonality ranked the true cause, next to
-- what the excursion cost. An excursion "measurably cost yield" when its affected wafers
-- yielded at least 1 point below same-product, same-window controls: a yield-based method
-- can only be expected to find those. Ranks are from the yield signal (phase 3);
-- pattern_true_rank is the pattern-led ranking for spatial excursions (phase 5a).
with truth as (
    select excursion_id, min(suspect_rank) as true_rank
    from {{ ref('fct_root_cause_candidates') }}
    where is_true_cause and signal = 'yield'
    group by excursion_id
),

pattern_truth as (
    select excursion_id, min(suspect_rank) as pattern_true_rank
    from {{ ref('fct_root_cause_candidates') }}
    where is_true_cause and signal = 'pattern'
    group by excursion_id
),

sizes as (
    select excursion_id, count(*) as candidates
    from {{ ref('fct_root_cause_candidates') }}
    where signal = 'yield'
    group by excursion_id
)

select
    e.excursion_id,
    e.excursion_type,
    abs(e.magnitude_sigma) as abs_magnitude_sigma,
    e.spatial_pattern,
    t.true_rank,
    coalesce(s.candidates, 0) as candidates,
    coalesce(t.true_rank = 1, false) as top1,
    coalesce(t.true_rank <= 3, false) as top3,
    pt.pattern_true_rank,
    i.affected_wafers,
    i.yield_delta_pct,
    i.dies_lost,
    coalesce(i.yield_delta_pct <= -1.0, false) as cost_yield
from {{ ref('stg_excursions_ground_truth') }} as e
left join truth as t on e.excursion_id = t.excursion_id
left join pattern_truth as pt on e.excursion_id = pt.excursion_id
left join sizes as s on e.excursion_id = s.excursion_id
left join {{ ref('fct_excursion_impact') }} as i on e.excursion_id = i.excursion_id
