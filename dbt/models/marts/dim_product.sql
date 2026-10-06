-- Product with its node flattened in, so reports filter by node without a second hop.
select
    p.product_id,
    p.product_code,
    p.node_id,
    n.node_name,
    n.feature_size_nm,
    p.die_area_cm2,
    p.map_rows,
    p.map_cols,
    p.gross_dies
from {{ ref('stg_products') }} as p
inner join {{ ref('stg_technology_nodes') }} as n on p.node_id = n.node_id
