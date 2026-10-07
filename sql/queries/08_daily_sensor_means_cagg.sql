-- Same panel as 02, served by the sensor_daily continuous aggregate (migration 0006):
-- one pre-computed row per day, chamber and parameter instead of every raw reading.
SELECT d.day, d.chamber_id, d.mean_value, d.n AS readings
FROM sensor_daily AS d
WHERE d.parameter_id = (SELECT parameter_id FROM parameters WHERE name = 'rf_power_w')
ORDER BY d.day, d.chamber_id;
