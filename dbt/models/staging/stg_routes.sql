select
    route_id,
    product_id,
    version as route_version
from {{ source('waferlens', 'routes') }}
