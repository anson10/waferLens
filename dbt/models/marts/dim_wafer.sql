select
    w.wafer_id,
    w.wafer_code,
    w.current_lot_id as lot_id,
    l.product_id,
    w.slot,
    w.wafer_status
from {{ ref('stg_wafers') }} as w
inner join {{ ref('stg_lots') }} as l on w.current_lot_id = l.lot_id
