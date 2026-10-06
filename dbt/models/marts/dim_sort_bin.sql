select
    bin_code,
    bin_name,
    is_pass
from {{ ref('stg_sort_bins') }}
