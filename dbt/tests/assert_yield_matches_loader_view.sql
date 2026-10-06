-- The mart computes yield itself; it must agree with the loader's wafer_yield materialized
-- view for every wafer, in both directions.
select coalesce(f.wafer_id, v.wafer_id) as wafer_id, f.yield_pct as mart, v.yield_pct as view
from {{ ref('fct_wafer_yield') }} as f
full outer join {{ source('waferlens', 'wafer_yield') }} as v on f.wafer_id = v.wafer_id
where f.wafer_id is null or v.wafer_id is null or f.yield_pct <> v.yield_pct
