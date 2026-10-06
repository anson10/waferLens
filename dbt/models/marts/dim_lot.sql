-- Lots with their split lineage. The recursive CTE walks parent_lot_id up to the root lot,
-- so a split child (and any child of a child) reports under the lot it started as.
with recursive lineage as (
    select
        lot_id,
        lot_id as root_lot_id,
        0 as split_depth
    from {{ ref('stg_lots') }}
    where parent_lot_id is null

    union all

    select
        child.lot_id,
        parent.root_lot_id,
        parent.split_depth + 1
    from {{ ref('stg_lots') }} as child
    inner join lineage as parent on child.parent_lot_id = parent.lot_id
),

wafer_counts as (
    select current_lot_id as lot_id, count(*) as wafer_count
    from {{ ref('stg_wafers') }}
    group by current_lot_id
)

select
    l.lot_id,
    l.lot_code,
    l.parent_lot_id,
    lineage.root_lot_id,
    lineage.split_depth,
    l.product_id,
    l.priority,
    l.started_at,
    to_char(l.started_at at time zone 'UTC', 'YYYYMMDD')::int as start_date_key,
    l.lot_status,
    coalesce(wc.wafer_count, 0) as wafer_count
from {{ ref('stg_lots') }} as l
inner join lineage on l.lot_id = lineage.lot_id
left join wafer_counts as wc on l.lot_id = wc.lot_id
