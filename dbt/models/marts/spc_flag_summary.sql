-- Total SPC flags per Western Electric rule.
-- dbt port of analysis/queries.py::spc_flag_counts.

select
    rule_violated,
    count(*) as flag_count
from {{ ref('stg_spc_flags') }}
group by rule_violated
order by flag_count desc
