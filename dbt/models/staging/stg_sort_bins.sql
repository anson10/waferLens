select
    bin_code,
    name as bin_name,
    is_pass
from {{ source('waferlens', 'sort_bins') }}
