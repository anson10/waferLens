select
    tool_type,
    description as tool_type_description
from {{ source('waferlens', 'tool_types') }}
