{{ config(indexes=[{'columns': ['wafer_id'], 'unique': True}, {'columns': ['tested_at']}]) }}

-- Grain: one row per sorted wafer FabEye classified. The true pattern comes from the
-- simulator's ground truth (the excursion whose pattern the map shows), translated to
-- FabEye's WM-811K class names; wafers with no injected pattern are 'none'.
with truth as (
    select
        t.wafer_id,
        t.excursion_id,
        c.pattern as true_pattern,
        e.magnitude_sigma
    from {{ ref('stg_wafer_pattern_truth') }} as t
    inner join {{ ref('stg_excursions_ground_truth') }} as e on t.excursion_id = e.excursion_id
    inner join {{ ref('wafer_pattern_classes') }} as c on e.spatial_pattern = c.simulator_pattern
)

select
    p.wafer_id,
    w.current_lot_id as lot_id,
    l.product_id,
    m.tested_at,
    to_char(m.tested_at at time zone 'UTC', 'YYYYMMDD')::int as tested_date_key,
    p.predicted_pattern,
    p.confidence,
    p.auto_accept,
    not p.auto_accept as needs_review,
    cardinality(p.prediction_set) as prediction_set_size,
    p.classifier,
    coalesce(t.true_pattern, 'none') as true_pattern,
    t.excursion_id,
    t.magnitude_sigma as true_pattern_magnitude_sigma,
    p.predicted_pattern = coalesce(t.true_pattern, 'none') as is_correct,
    coalesce(t.true_pattern, 'none') = any(p.prediction_set) as truth_in_prediction_set
from {{ ref('stg_wafer_patterns') }} as p
inner join {{ ref('stg_wafer_maps') }} as m on p.wafer_id = m.wafer_id
inner join {{ ref('stg_wafers') }} as w on p.wafer_id = w.wafer_id
inner join {{ ref('stg_lots') }} as l on w.current_lot_id = l.lot_id
left join truth as t on p.wafer_id = t.wafer_id
