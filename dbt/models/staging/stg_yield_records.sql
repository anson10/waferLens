select
    record_id,
    wafer_id,
    die_count,
    pass_count,
    yield_pct,
    defect_density
from {{ source('waferlens', 'yield_records') }}
