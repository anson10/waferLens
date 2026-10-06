-- Commonality (phase 3): which chambers are over-represented among the worst 10% of wafers
-- sorted in the last 28 days?
WITH recent AS (
    SELECT y.wafer_id, y.yield_pct
    FROM wafer_yield AS y
    JOIN wafer_maps AS m USING (wafer_id)
    WHERE m.tested_at > (SELECT max(tested_at) FROM wafer_maps) - INTERVAL '28 days'
), cut AS (
    SELECT percentile_cont(0.1) WITHIN GROUP (ORDER BY yield_pct) AS p10 FROM recent
)
SELECT h.chamber_id,
       count(*) FILTER (WHERE r.yield_pct < cut.p10) AS low_yield_passes,
       count(*) AS passes,
       round(100.0 * avg((r.yield_pct < cut.p10)::int), 1) AS low_yield_pct
FROM recent AS r
CROSS JOIN cut
JOIN wafer_step_history AS h USING (wafer_id)
GROUP BY h.chamber_id
ORDER BY low_yield_pct DESC
LIMIT 10;
