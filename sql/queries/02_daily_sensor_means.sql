-- Dashboard panel: daily mean of one sensor per chamber over the whole period.
-- Touches every reading of that sensor; the candidate for a continuous aggregate (phase 4).
SELECT time_bucket('1 day', r.time) AS day, r.chamber_id, avg(r.value) AS mean_value,
       count(*) AS readings
FROM tool_sensor_readings AS r
WHERE r.parameter_id = (SELECT parameter_id FROM parameters WHERE name = 'rf_power_w')
GROUP BY day, r.chamber_id
ORDER BY day, r.chamber_id;
