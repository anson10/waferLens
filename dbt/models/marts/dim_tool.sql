select
    t.tool_id,
    t.tool_type,
    tt.tool_type_description,
    count(c.chamber_id) as chamber_count
from {{ ref('stg_tools') }} as t
inner join {{ ref('stg_tool_types') }} as tt on t.tool_type = tt.tool_type
left join {{ ref('stg_chambers') }} as c on t.tool_id = c.tool_id
group by t.tool_id, t.tool_type, tt.tool_type_description
