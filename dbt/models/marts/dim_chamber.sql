-- Chamber with its tool and tool type flattened in: commonality results are read by
-- chamber label (e.g. ETCH-02/B) and grouped by tool type.
select
    c.chamber_id,
    c.chamber_label,
    c.chamber_code,
    c.tool_id,
    t.tool_type
from {{ ref('stg_chambers') }} as c
inner join {{ ref('stg_tools') }} as t on c.tool_id = t.tool_id
