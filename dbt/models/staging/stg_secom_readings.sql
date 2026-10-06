select
    run_id,
    sensor_no,
    value
from {{ source('waferlens', 'secom_readings') }}
