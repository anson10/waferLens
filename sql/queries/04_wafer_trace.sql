-- Drill-down: everything one wafer went through (chamber, recipe, sensor values per step).
SELECT h.route_step_id, h.pass_no, h.chamber_id, h.recipe_id, h.track_in,
       r.parameter_id, r.value
FROM wafer_step_history AS h
LEFT JOIN tool_sensor_readings AS r
  ON r.wafer_id = h.wafer_id AND r.route_step_id = h.route_step_id AND r.time = h.track_in
WHERE h.wafer_id = (SELECT max(wafer_id) FROM wafers WHERE status = 'complete')
ORDER BY h.track_in, r.parameter_id;
