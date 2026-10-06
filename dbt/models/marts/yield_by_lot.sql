-- Average yield and defect density per lot.
-- dbt port of analysis/queries.py::yield_by_lot.

select
    l.lot_id,
    l.product,
    l.technology_node,
    l.start_date,
    l.status,
    count(yr.record_id)              as wafer_count,
    round(avg(yr.yield_pct)::numeric, 2)      as avg_yield_pct,
    round(avg(yr.defect_density)::numeric, 4) as avg_defect_density
from {{ ref('stg_lots') }} l
join {{ ref('stg_wafers') }} w on w.lot_id = l.lot_id
join {{ ref('stg_yield_records') }} yr on yr.wafer_id = w.wafer_id
group by l.lot_id, l.product, l.technology_node, l.start_date, l.status
order by l.lot_id
