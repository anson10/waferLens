select
    lot_id,
    product,
    technology_node,
    start_date,
    status
from {{ source('waferlens', 'lots') }}
