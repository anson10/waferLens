select
    lot_id,
    lot_code,
    parent_lot_id,
    product_id,
    route_id,
    priority,
    start_time as started_at,
    status as lot_status
from {{ source('waferlens', 'lots') }}
