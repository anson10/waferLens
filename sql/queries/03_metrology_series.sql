-- Metrology SPC series: one measured step + parameter over the last 30 days, site mean per
-- wafer (the value an X-bar chart plots).
SELECT m.wafer_id, min(m.time) AS measured_at, avg(m.value) AS wafer_mean,
       stddev_samp(m.value) AS within_wafer_sd
FROM metrology_measurements AS m
WHERE m.route_step_id = (SELECT min(route_step_id) FROM metrology_plans)
  AND m.parameter_id = (SELECT min(parameter_id) FROM metrology_plans
                        WHERE route_step_id = (SELECT min(route_step_id) FROM metrology_plans))
  AND m.time > (SELECT max(time) FROM metrology_measurements) - INTERVAL '30 days'
GROUP BY m.wafer_id
ORDER BY measured_at;
