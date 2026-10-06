{#
  Grain: one value per wafer x route step x pass x parameter, sensors and metrology together
  (int_measurement_with_context). ~3M rows on the demo fab, so it is incremental:

  * New rows: only measurements newer than the table's latest, minus a 3-day look-back for
    late metrology. delete+insert on measurement_key makes re-processed rows replace, not
    duplicate.
  * Reloads: the loader replaces the whole fab, so rows from an earlier load would linger.
    The pre-hook deletes rows whose load differs from the current one; the incremental filter
    then finds an empty table and inserts everything.
#}
{{
    config(
        materialized='incremental',
        unique_key='measurement_key',
        incremental_strategy='delete+insert',
        on_schema_change='fail',
        indexes=[
            {'columns': ['measurement_key'], 'unique': True},
            {'columns': ['wafer_id']},
            {'columns': ['parameter_id', 'measured_at']},
        ],
        pre_hook="
            {% if is_incremental() %}
            delete from {{ this }}
            where loaded_from_run_at is distinct from (
                select max(created_at) from {{ source('waferlens', 'simulation_runs') }}
            )
            {% endif %}
        ",
    )
}}

select
    m.measurement_key,
    m.source,
    m.measured_at,
    to_char(m.measured_at at time zone 'UTC', 'YYYYMMDD')::int as date_key,
    m.wafer_id,
    m.lot_id,
    m.route_step_id,
    m.pass_no,
    m.parameter_id,
    m.chamber_id,
    m.recipe_id,
    m.value,
    m.site_sd,
    m.n_sites,
    m.target,
    m.lsl,
    m.usl,
    m.z_from_target,
    m.is_out_of_spec,
    (select max(created_at) from {{ source('waferlens', 'simulation_runs') }})
        as loaded_from_run_at
from {{ ref('int_measurement_with_context') }} as m
{% if is_incremental() %}
where m.measured_at > (
    select coalesce(max(measured_at), '-infinity'::timestamptz) - interval '3 days'
    from {{ this }}
)
{% endif %}
