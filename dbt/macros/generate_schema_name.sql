{#
  Use the folder's schema name as-is (staging, intermediate, marts) instead of dbt's default
  "<target schema>_<custom schema>". Power BI and Grafana then read a stable `marts` schema.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}{{ target.schema }}{%- else -%}{{ custom_schema_name | trim }}{%- endif -%}
{%- endmacro %}
