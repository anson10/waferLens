-- Reporting: weekly mean yield per product (what Power BI's summary page shows).
SELECT date_trunc('week', m.tested_at) AS week, p.code AS product,
       round(avg(y.yield_pct), 2) AS mean_yield, count(*) AS wafers
FROM wafer_yield AS y
JOIN wafer_maps AS m USING (wafer_id)
JOIN wafers AS w USING (wafer_id)
JOIN lots AS l ON l.lot_id = w.lot_id
JOIN products AS p ON p.product_id = l.product_id
GROUP BY week, p.code
ORDER BY week, p.code;
