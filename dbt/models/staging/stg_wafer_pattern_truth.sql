select
    wafer_id,
    excursion_id
from {{ source('waferlens', 'wafer_pattern_truth') }}
