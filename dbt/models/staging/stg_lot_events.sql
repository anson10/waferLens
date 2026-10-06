select
    event_id,
    lot_id,
    event_type,
    event_time as event_at,
    related_lot_id
from {{ source('waferlens', 'lot_events') }}
