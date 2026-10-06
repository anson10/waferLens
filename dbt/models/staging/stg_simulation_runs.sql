select
    run_id,
    profile,
    seed,
    created_at
from {{ source('waferlens', 'simulation_runs') }}
