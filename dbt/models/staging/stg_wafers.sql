select
    wafer_id,
    lot_id,
    wafer_number,
    status
from {{ source('waferlens', 'wafers') }}
