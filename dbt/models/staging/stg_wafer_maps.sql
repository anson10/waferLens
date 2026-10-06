-- The bin grid itself (bin_map) stays in the source table: marts use the bin counts.
select
    wafer_id,
    tested_at
from {{ source('waferlens', 'wafer_maps') }}
