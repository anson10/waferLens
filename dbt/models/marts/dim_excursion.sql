-- Grain: one row per injected excursion. The dimension the excursion-grain facts
-- (fct_excursion_impact, fct_excursion_detection, fct_root_cause_eval, fct_pattern_detection)
-- and fct_root_cause_candidates share, so a BI model can filter them all from one table.
select
    e.excursion_id,
    e.excursion_id::text || ' · ' || e.excursion_type as excursion_label,
    e.excursion_type,
    e.description,
    e.chamber_id,
    c.chamber_label,
    c.tool_id,
    e.recipe_id,
    r.recipe_name || ' v' || r.recipe_version as recipe_label,
    p.parameter_name,
    pc.pattern as spatial_pattern,
    e.magnitude_sigma,
    abs(e.magnitude_sigma) as abs_magnitude_sigma,
    e.started_at,
    e.ended_at,
    to_char(e.started_at at time zone 'UTC', 'YYYYMMDD')::int as start_date_key,
    extract(epoch from e.ended_at - e.started_at) / 3600.0 as duration_hours
from {{ ref('stg_excursions_ground_truth') }} as e
left join {{ ref('dim_chamber') }} as c on e.chamber_id = c.chamber_id
left join {{ ref('dim_recipe') }} as r on e.recipe_id = r.recipe_id
left join {{ ref('dim_parameter') }} as p on e.parameter_id = p.parameter_id
left join {{ ref('wafer_pattern_classes') }} as pc on e.spatial_pattern = pc.simulator_pattern
