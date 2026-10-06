select
    parameter_id,
    parameter_name,
    unit,
    parameter_kind
from {{ ref('stg_parameters') }}
