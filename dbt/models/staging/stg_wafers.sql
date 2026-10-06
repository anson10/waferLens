select
    wafer_id,
    wafer_code,
    lot_id as current_lot_id,
    slot,
    status as wafer_status
from {{ source('waferlens', 'wafers') }}
