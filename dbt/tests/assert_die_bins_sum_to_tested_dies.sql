-- Every die of a sorted wafer lands in exactly one bin: the bins must add up to the dies
-- tested, and the shares to 1.
select y.wafer_id, y.tested_dies, sum(b.die_count) as binned_dies
from {{ ref('fct_wafer_yield') }} as y
inner join {{ ref('fct_die_bins') }} as b on y.wafer_id = b.wafer_id
group by y.wafer_id, y.tested_dies
having sum(b.die_count) <> y.tested_dies or abs(sum(b.share_of_wafer) - 1) > 0.001
