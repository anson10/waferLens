select
    flag_id,
    measurement_id,
    rule_violated,
    flagged_at
from {{ source('waferlens', 'spc_flags') }}
