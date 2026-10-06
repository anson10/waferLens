-- A metrology value is measured after the step it measures finished.
select f.measurement_key
from {{ ref('fct_measurements') }} as f
inner join {{ ref('int_wafer_route_history') }} as h
    on f.wafer_id = h.wafer_id and f.route_step_id = h.route_step_id and f.pass_no = h.pass_no
where f.source = 'metrology' and f.measured_at <= h.track_out_at
