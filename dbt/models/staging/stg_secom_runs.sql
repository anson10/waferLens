select
    run_id,
    run_time as run_at,
    failed
from {{ source('waferlens', 'secom_runs') }}
