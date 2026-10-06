select
    excursion_id,
    run_id,
    excursion_type,
    chamber_id,
    recipe_id,
    parameter_id,
    spatial_pattern,
    start_time as started_at,
    end_time as ended_at,
    magnitude_sigma,
    description
from {{ source('waferlens', 'excursions_ground_truth') }}
