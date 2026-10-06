-- Average yield and defect density per technology node.
-- dbt port of analysis/queries.py::yield_by_node.

select
    l.technology_node,
    count(yr.record_id)              as wafer_count,
    round(avg(yr.yield_pct)::numeric, 2)      as avg_yield_pct,
    round(avg(yr.defect_density)::numeric, 4) as avg_defect_density
from {{ ref('stg_lots') }} l
join {{ ref('stg_wafers') }} w on w.lot_id = l.lot_id
join {{ ref('stg_yield_records') }} yr on yr.wafer_id = w.wafer_id
group by l.technology_node
order by avg_yield_pct desc
