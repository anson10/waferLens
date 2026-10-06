select
    product_id,
    code as product_code,
    node_id,
    die_area_cm2::double precision as die_area_cm2,
    map_rows,
    map_cols,
    gross_dies
from {{ source('waferlens', 'products') }}
