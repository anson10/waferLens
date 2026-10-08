# WaferLens · Power BI

Yield reporting on the dbt star schema (`marts`), saved as a Power BI Project (PBIP): the
semantic model is TMDL and the report is PBIR, so every measure, relationship, page and
bookmark is a text file that diffs in git. Power BI connects read-only as `powerbi_reader`
(migration 0011, SELECT on `marts` only) in Import mode; see
[ADR-011](../docs/adr/0011-power-bi-import-on-marts-pbip.md). `make powerbi-check` lists what
the role can see.

Open `WaferLens.pbip` in Power BI Desktop with `make up` running, then **Refresh**.

## Model

- **21 tables**: 9 facts at a stated grain (wafer, wafer × bin, wafer × step, alarm,
  excursion, excursion × suspect, …) and their dimensions, imported from the dbt marts.
- **28 relationships**, all many-to-one and single-direction, from facts to dimensions.
  Filters flow one way, so no visual is ambiguous about which path a filter takes.
- **Date table**: `dim_date` is marked as the date table; auto date/time is off, so there are
  no hidden date tables and time intelligence uses one calendar.
- **Role-playing pattern dimension**: `fct_wafer_pattern` relates to `wafer_pattern_classes`
  twice, by the predicted pattern (active) and by the true pattern (inactive). `Wafers (true)`
  switches with `USERELATIONSHIP`, so predicted and true counts sit side by side.
- **Hidden keys**: surrogate keys are hidden; report authors see names and measures only.
- **39 measures** in `_Measures`, in display folders (Yield, Loss, Process Control, Root
  Cause, Wafer Patterns, Tooltip), each with a description and a format string.

## Pages

| Page | Question |
|---|---|
| [Executive Summary](images/executive-summary.png) | How is yield doing, and is it getting worse? |
| [Yield loss](images/yield-loss.png) | Where are dies lost? |
| [Root cause](images/root-cause.png) | Which chamber did the bad wafers share? |
| [Excursions](images/excursions.png) | What did each excursion cost, and how fast was it caught? |
| Process control | Where are alarms and patterns concentrating? |
| [Wafer](images/wafer.png) (drillthrough, hidden) | What happened to this wafer? |

Bookmarks jump to the two stories: **Excursion 10** (commonality ranks the true chamber 10th
while SPC raised 3,740 alarms on it) and **Excursion 12** (a spatial pattern: rank 1, but only
67 SPC alarms), plus **Reset**.

## DAX highlights

**Die-weighted yield, not a wafer average.** `Die Yield % = DIVIDE ( [Good Dies], [Tested
Dies] )`. Averaging wafer yields (`Avg Wafer Yield %`) weights a 432-die SENS130 wafer like a
1,176-die MCU28 one: 87.13% against the die-weighted 87.64% over the whole fab. The die-weighted number is
the one a fab reports.

**A Pareto line that stays right under any filter.**

```dax
Cumulative Loss % =
VAR ThisBin = [Failed Dies]
VAR Bins = ADDCOLUMNS ( ALLSELECTED ( dim_sort_bin[bin_name] ), "@lost", [Failed Dies] )
RETURN DIVIDE ( SUMX ( FILTER ( Bins, [@lost] >= ThisBin ), [@lost] ), SUMX ( Bins, [@lost] ) )
```

`ALLSELECTED` keeps the slicers and cross-filters (a product, a month) but removes the bar's
own bin, so the line always ends at 100% of what is on screen.

**A relationship that exists only inside a measure.** The root-cause table is filtered on
`fct_root_cause_candidates`, and filters don't flow from a fact up to `dim_chamber`. `TREATAS`
applies the row's `chamber_id` to `dim_chamber`, from where it reaches the SPC alarms; the
window comes from the selected excursion when there is exactly one (`HASONEVALUE`):

```dax
Tip Alarms =
VAR OneExcursion = HASONEVALUE ( dim_excursion[excursion_id] )
VAR FromTime = MIN ( dim_excursion[started_at] )
VAR ToTime = MAX ( dim_excursion[ended_at] )
RETURN
    CALCULATE (
        [Chamber Alarms],
        TREATAS ( VALUES ( fct_root_cause_candidates[chamber_id] ), dim_chamber[chamber_id] ),
        FILTER (
            ALL ( fct_spc_alarms[measured_at] ),
            NOT OneExcursion
                || ( fct_spc_alarms[measured_at] >= FromTime && fct_spc_alarms[measured_at] < ToTime )
        )
    )
```

The alternative, a bidirectional relationship, would make every other page's filter paths
ambiguous.

**Single values for a drillthrough.** The Wafer page's cards use `SELECTEDVALUE` (`Predicted
Pattern`, `Pattern Confidence`, `Wafer Title`): one wafer gives its value; anything else gives
blank instead of a meaningless sum.

**A baseline next to every detection number.** `Detection Delay (points)` and `Placebo Delay
(points)` are medians over the same charts: the placebo is the same-length window with no
excursion. EWMA alarms after 8 points against 145 by chance; WE1 (33 against 29.5) is no
better than chance, and the chart shows it.

## Row-level security

One role per product (`Product MCU28`, `Product PMIC65`, `Product SENS130`). Each filters
`dim_product` and also `dim_wafer` (by the product's id), because `fct_wafer_steps` reaches
products only through the wafer; the other facts carry `product_id` themselves. Excursions
and root cause stay fab-wide on purpose: a chamber excursion hits every product that runs
through it. Test with **Modeling → View as**; as PMIC65, June shows 1,353 wafers at 88.72%
instead of 4,458 at 89.87% ([screenshot](images/rls.png)).

## Performance

Performance Analyzer, all five pages refreshed (37 visuals, 29 DAX queries, Import mode on the
demo fab): every DAX query ran in 50 ms or less, median 12 ms. The slowest is the root-cause
table's `Tip Alarms` column (50 ms), which filters 156,612 alarm timestamps per suspect row;
next is the lowest-yield wafers table (27 ms), a Bottom-20 over 25,000 wafers. A visual takes
400–470 ms end to end on a page load, almost all of it rendering and waiting for the other
visuals, so the model is not the bottleneck and nothing was changed.

## Limitations

- Desktop only, against the local warehouse; not published to the Power BI service.
- The chamber tooltip page is configured but this Desktop build shows the default tooltip
  instead, so the SPC alarms per suspect are a column in the root-cause table.
- Import mode: numbers are as of the last refresh.
