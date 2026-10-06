select
    parameter_id,
    name as parameter_name,
    unit,
    kind as parameter_kind
from {{ source('waferlens', 'parameters') }}
