select
    wafer_id,
    bin_code,
    die_count
from {{ source('waferlens', 'wafer_bin_summary') }}
