select
    wafer_id,
    route_step_id,
    pass_no,
    lot_id,
    chamber_id,
    recipe_id,
    track_in as track_in_at,
    track_out as track_out_at,
    (extract(epoch from track_out - track_in) / 60.0)::double precision as process_minutes
from {{ source('waferlens', 'wafer_step_history') }}
