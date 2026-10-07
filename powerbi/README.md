# WaferLens · Power BI

Yield reporting on the dbt star schema (`marts`), in progress (phase 7). Power BI connects
read-only as `powerbi_reader` (migration 0011) in Import mode; see
[ADR-011](../docs/adr/0011-power-bi-import-on-marts-pbip.md). `make powerbi-check` lists
what it can see.
