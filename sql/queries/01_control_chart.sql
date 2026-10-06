-- Control chart (SPC / Grafana): one chamber's primary sensor from a week before its first
-- drift excursion to a week after. Reads a narrow time range of one chamber + parameter.
SELECT r.time, r.value
FROM tool_sensor_readings AS r
JOIN excursions_ground_truth AS e
  ON r.chamber_id = e.chamber_id
 AND r.parameter_id = e.parameter_id
 AND r.time BETWEEN e.start_time - INTERVAL '7 days' AND e.end_time + INTERVAL '7 days'
WHERE e.excursion_id = (SELECT min(excursion_id) FROM excursions_ground_truth
                        WHERE excursion_type = 'drift')
ORDER BY r.time;
