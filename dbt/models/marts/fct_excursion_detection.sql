-- Grain: one row per injected excursion x SPC chart x scope (chamber | tool).
-- Scores Phase II SPC against the simulator's ground truth:
--
--   monitored            does this chart watch a series the excursion moves at all?
--                        Sensor excursions move the chamber's primary sensor; a recipe change
--                        moves a metrology parameter at its route step (and T²); spatial
--                        patterns move neither, by design: only the wafer map shows them.
--   detected             first alarm on an affected point inside [start, end)
--   delay_hours/points   time and number of affected measurements until that alarm
--   placebo_*            the same measures over the equal-length window right before the
--                        excursion, where there is nothing to detect. Windows run for days, so
--                        some false alarm there is likely; what separates a real detection is
--                        how much sooner it comes: delay_points vs placebo_delay_points is an
--                        empirical ARL1 vs ARL0 on the fab's own data
--   started_in_baseline  the excursion began before the series' limits were frozen, so the
--                        limits may have learned the shift as normal
--
-- "Affected points" = the excursion chamber's points for sensor excursions (also at tool
-- scope, where the chart pools all chambers of the tool), and every point at the recipe's
-- route step for recipe changes.
with excursions as (
    select
        e.excursion_id,
        e.excursion_type,
        e.magnitude_sigma,
        e.chamber_id,
        c.tool_id,
        e.parameter_id,
        r.route_step_id as recipe_route_step_id,
        e.started_at,
        e.ended_at,
        e.ended_at - e.started_at as duration,
        e.excursion_type in ('step_shift', 'drift', 'chamber_offset') as is_sensor
    from {{ ref('stg_excursions_ground_truth') }} as e
    left join {{ ref('dim_chamber') }} as c on e.chamber_id = c.chamber_id
    left join {{ ref('dim_recipe') }} as r on e.recipe_id = r.recipe_id
),

charts as (
    select chart from {{ ref('spc_charts') }}
),

grid as (
    select
        e.*,
        ch.chart,
        s.scope,
        case
            when e.is_sensor then ch.chart <> 't2'
            when e.excursion_type = 'recipe_change' then ch.chart <> 't2' or s.scope = 'chamber'
            else false
        end as applicable
    from excursions as e
    cross join charts as ch
    cross join (values ('chamber'), ('tool')) as s (scope)
),

-- Alarms on affected points, matched with equality joins (one branch per excursion kind).
affected_alarms as (
    select e.excursion_id, a.chart, a.scope, a.measured_at
    from excursions as e
    inner join {{ ref('fct_spc_alarms') }} as a
        on a.source = 'sensor'
        and a.chamber_id = e.chamber_id
        and a.parameter_id = e.parameter_id
    where e.is_sensor
    union all
    select e.excursion_id, a.chart, a.scope, a.measured_at
    from excursions as e
    inner join {{ ref('fct_spc_alarms') }} as a
        on a.source = 'metrology'
        and a.route_step_id = e.recipe_route_step_id
        and (a.parameter_id = e.parameter_id or a.chart = 't2')
    where e.excursion_type = 'recipe_change'
),

-- Affected measurements from the start of the placebo window to the end of the excursion,
-- to count how many points went by before the first alarm.
affected_points as (
    select e.excursion_id, f.measured_at
    from excursions as e
    inner join {{ ref('fct_measurements') }} as f
        on f.source = 'sensor'
        and f.chamber_id = e.chamber_id
        and f.parameter_id = e.parameter_id
        and f.measured_at >= e.started_at - e.duration
        and f.measured_at < e.ended_at
    where e.is_sensor
    union all
    select e.excursion_id, f.measured_at
    from excursions as e
    inner join {{ ref('fct_measurements') }} as f
        on f.source = 'metrology'
        and f.route_step_id = e.recipe_route_step_id
        and f.parameter_id = e.parameter_id
        and f.measured_at >= e.started_at - e.duration
        and f.measured_at < e.ended_at
    where e.excursion_type = 'recipe_change'
),

-- When the limits of the series watching each excursion were frozen.
baselines as (
    select e.excursion_id, l.scope, max(l.baseline_end_at) as baseline_end_at
    from excursions as e
    inner join {{ ref('stg_spc_control_limits') }} as l
        on (
            e.is_sensor
            and l.source = 'sensor'
            and l.parameter_id = e.parameter_id
            and (l.chamber_id = e.chamber_id or (l.scope = 'tool' and l.tool_id = e.tool_id))
        )
        or (
            e.excursion_type = 'recipe_change'
            and l.source = 'metrology'
            and l.route_step_id = e.recipe_route_step_id
        )
    group by e.excursion_id, l.scope
),

scored as (
    select
        g.excursion_id,
        g.chart,
        g.scope,
        min(a.measured_at) filter (
            where a.measured_at >= g.started_at and a.measured_at < g.ended_at
        ) as first_alarm_at,
        min(a.measured_at) filter (
            where a.measured_at >= g.started_at - g.duration and a.measured_at < g.started_at
        ) as placebo_first_alarm_at
    from grid as g
    left join affected_alarms as a
        on g.excursion_id = a.excursion_id and g.chart = a.chart and g.scope = a.scope
    group by g.excursion_id, g.chart, g.scope
)

select
    g.excursion_id,
    g.excursion_type,
    g.magnitude_sigma,
    abs(g.magnitude_sigma) as abs_magnitude_sigma,
    g.chart,
    g.scope,
    g.applicable and b.baseline_end_at is not null as monitored,
    coalesce(g.started_at < b.baseline_end_at, false) as started_in_baseline,
    s.first_alarm_at is not null as detected,
    s.first_alarm_at,
    (extract(epoch from s.first_alarm_at - g.started_at) / 3600.0)::double precision
        as delay_hours,
    (
        select count(*)
        from affected_points as p
        where p.excursion_id = g.excursion_id
            and p.measured_at >= g.started_at
            and p.measured_at <= s.first_alarm_at
    ) as delay_points,
    s.placebo_first_alarm_at is not null as placebo_alarm,
    (
        select count(*)
        from affected_points as p
        where p.excursion_id = g.excursion_id
            and p.measured_at >= g.started_at - g.duration
            and p.measured_at <= s.placebo_first_alarm_at
    ) as placebo_delay_points,
    (
        select count(*)
        from affected_points as p
        where p.excursion_id = g.excursion_id and p.measured_at < g.started_at
    ) as placebo_window_points,
    g.started_at,
    g.ended_at
from grid as g
inner join scored as s
    on g.excursion_id = s.excursion_id and g.chart = s.chart and g.scope = s.scope
left join baselines as b on g.excursion_id = b.excursion_id and g.scope = b.scope
