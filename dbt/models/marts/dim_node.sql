select
    node_id,
    node_name,
    feature_size_nm
from {{ ref('stg_technology_nodes') }}
