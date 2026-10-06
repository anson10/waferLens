-- Ground-truth check: for each chamber excursion, the wafers it touched and their yield.
SELECT e.excursion_id, e.excursion_type, count(DISTINCT h.wafer_id) AS wafers,
       round(avg(y.yield_pct), 2) AS mean_yield
FROM excursions_ground_truth AS e
JOIN wafer_step_history AS h
  ON h.chamber_id = e.chamber_id AND h.track_in >= e.start_time AND h.track_in < e.end_time
JOIN wafer_yield AS y ON y.wafer_id = h.wafer_id
GROUP BY e.excursion_id, e.excursion_type
ORDER BY e.excursion_id;
