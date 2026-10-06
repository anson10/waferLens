-- One row per calendar day (UTC) from the first lot start to the last wafer sort.
-- date_key (yyyymmdd) is what every fact joins on; Power BI marks this as its date table.
with bounds as (
    select
        (select min(started_at) from {{ ref('stg_lots') }}) as first_at,
        greatest(
            (select max(tested_at) from {{ ref('stg_wafer_maps') }}),
            (select max(track_out_at) from {{ ref('stg_wafer_step_history') }})
        ) as last_at
),

days as (
    select generate_series(
        (first_at at time zone 'UTC')::date,
        (coalesce(last_at, first_at) at time zone 'UTC')::date,
        interval '1 day'
    )::date as calendar_date
    from bounds
)

select
    to_char(calendar_date, 'YYYYMMDD')::int as date_key,
    calendar_date,
    extract(year from calendar_date)::int as year,
    extract(quarter from calendar_date)::int as quarter,
    extract(month from calendar_date)::int as month,
    to_char(calendar_date, 'Mon') as month_name,
    extract(isoyear from calendar_date)::int as iso_year,
    extract(week from calendar_date)::int as iso_week,
    date_trunc('week', calendar_date)::date as week_start,
    extract(isodow from calendar_date)::int as day_of_week,
    extract(isodow from calendar_date) >= 6 as is_weekend
from days
