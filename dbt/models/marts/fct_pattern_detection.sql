-- Grain: one row per injected spatial-pattern excursion. Does the wafer-map pattern alarm
-- (fct_pattern_alarms) catch it, how long after the excursion started, and how does that
-- compare with SPC and with chance?
--
--   first_sorted_at     when the first wafer showing the pattern reached wafer sort: no
--                       sort-based signal can be earlier, so sort_lag_hours is the floor
--   detected            an alarm for the excursion's pattern in [start, end + 14 days); the
--                       14 days let wafers processed during the excursion reach sort
--   placebo_alarm       an alarm for the same pattern in the equal-length window right before
--                       the excursion, where there is nothing to detect
--   spc_detected        chamber-scope EWMA caught it (it can't: no sensor moves)
with excursions as (
    select
        e.excursion_id,
        e.chamber_id,
        e.started_at,
        e.ended_at,
        e.magnitude_sigma,
        c.pattern,
        e.ended_at + interval '14 days' - e.started_at as credit_window
    from {{ ref('stg_excursions_ground_truth') }} as e
    inner join {{ ref('wafer_pattern_classes') }} as c on e.spatial_pattern = c.simulator_pattern
    where e.excursion_type = 'spatial_pattern'
),

first_sorted as (
    select excursion_id, min(m.tested_at) as first_sorted_at, count(*) as pattern_wafers
    from {{ ref('stg_wafer_pattern_truth') }} as t
    inner join {{ ref('stg_wafer_maps') }} as m on t.wafer_id = m.wafer_id
    group by excursion_id
),

hits as (
    select
        x.excursion_id,
        min(a.alarmed_at) filter (
            where a.alarmed_at >= x.started_at and a.alarmed_at < x.started_at + x.credit_window
        ) as first_alarm_at,
        min(a.alarmed_at) filter (
            where a.alarmed_at >= x.started_at - x.credit_window and a.alarmed_at < x.started_at
        ) as placebo_alarm_at
    from excursions as x
    left join {{ ref('fct_pattern_alarms') }} as a on x.pattern = a.pattern
    group by x.excursion_id
)

select
    x.excursion_id,
    x.chamber_id,
    x.pattern,
    abs(x.magnitude_sigma) as abs_magnitude_sigma,
    x.started_at,
    x.ended_at,
    f.pattern_wafers,
    f.first_sorted_at,
    extract(epoch from f.first_sorted_at - x.started_at) / 3600.0 as sort_lag_hours,
    h.first_alarm_at is not null as detected,
    h.first_alarm_at,
    extract(epoch from h.first_alarm_at - x.started_at) / 3600.0 as delay_hours,
    h.placebo_alarm_at is not null as placebo_alarm,
    extract(epoch from h.placebo_alarm_at - (x.started_at - x.credit_window)) / 3600.0
        as placebo_delay_hours,
    coalesce(d.detected, false) as spc_detected
from excursions as x
left join first_sorted as f on x.excursion_id = f.excursion_id
left join hits as h on x.excursion_id = h.excursion_id
left join {{ ref('fct_excursion_detection') }} as d
    on x.excursion_id = d.excursion_id and d.chart = 'ewma' and d.scope = 'chamber'
