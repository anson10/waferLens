select
    node_id,
    name as node_name,
    feature_size_nm
from {{ source('waferlens', 'technology_nodes') }}
