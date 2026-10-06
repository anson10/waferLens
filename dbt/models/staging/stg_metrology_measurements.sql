select
    time as measured_at,
    wafer_id,
    route_step_id,
    parameter_id,
    site_no,
    site_x_mm,
    site_y_mm,
    sqrt(site_x_mm ^ 2 + site_y_mm ^ 2) as site_radius_mm,
    value
from {{ source('waferlens', 'metrology_measurements') }}
