select
    tool_id,
    tool_type
from {{ source('waferlens', 'tools') }}
