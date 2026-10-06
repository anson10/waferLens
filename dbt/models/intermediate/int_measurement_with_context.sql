-- One measurement stream for reporting: tool sensor readings and inline metrology at the
-- same grain (wafer x route step x pass x parameter), each tied to the chamber, recipe and
-- lot that processed the wafer at that step.
--
-- * Sensors: one value per wafer-step-pass. The reading's time is the pass's track-in, which
--   is how it is matched to its genealogy row.
-- * Metrology: the 9 sites are averaged per wafer (the value an X-bar chart plots); the
--   within-wafer standard deviation and site count are kept. It measures the final pass.
-- * Spec limits come from the metrology plan. Limits sit at target +/- 4 sigma, so the
--   process sigma is (usl - lsl) / 8 and z_from_target is in sigma units.
with history as (
    select * from {{ ref('stg_wafer_step_history') }}
),

sensor as (
    select
        'sensor' as source,
        r.measured_at,
        r.wafer_id,
        r.route_step_id,
        h.pass_no,
        r.parameter_id,
        h.lot_id,
        h.chamber_id,
        h.recipe_id,
        r.value,
        null::double precision as site_sd,
        1 as n_sites
    from {{ ref('stg_tool_sensor_readings') }} as r
    inner join history as h
        on r.wafer_id = h.wafer_id
        and r.route_step_id = h.route_step_id
        and r.measured_at = h.track_in_at
),

final_pass as (
    select *
    from history
    where (wafer_id, route_step_id, pass_no) in (
        select wafer_id, route_step_id, max(pass_no)
        from history
        group by wafer_id, route_step_id
    )
),

metrology as (
    select
        'metrology' as source,
        min(m.measured_at) as measured_at,
        m.wafer_id,
        m.route_step_id,
        h.pass_no,
        m.parameter_id,
        h.lot_id,
        h.chamber_id,
        h.recipe_id,
        avg(m.value) as value,
        stddev_samp(m.value) as site_sd,
        count(*) as n_sites
    from {{ ref('stg_metrology_measurements') }} as m
    inner join final_pass as h
        on m.wafer_id = h.wafer_id
        and m.route_step_id = h.route_step_id
    group by m.wafer_id, m.route_step_id, h.pass_no, m.parameter_id, h.lot_id, h.chamber_id,
        h.recipe_id
),

unioned as (
    select * from sensor
    union all
    select * from metrology
)

select
    md5(
        u.source || '|' || u.wafer_id || '|' || u.route_step_id || '|' || u.pass_no || '|'
        || u.parameter_id
    ) as measurement_key,
    u.*,
    p.target,
    p.lsl,
    p.usl,
    case when p.target is not null then (u.value - p.target) / ((p.usl - p.lsl) / 8.0) end
        as z_from_target,
    coalesce(u.value < p.lsl or u.value > p.usl, false) as is_out_of_spec
from unioned as u
left join {{ ref('stg_metrology_plans') }} as p
    on u.source = 'metrology'
    and u.route_step_id = p.route_step_id
    and u.parameter_id = p.parameter_id
