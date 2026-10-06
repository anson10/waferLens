select
    chamber_id,
    tool_id,
    chamber_code,
    tool_id || '/' || chamber_code as chamber_label
from {{ source('waferlens', 'chambers') }}
