-- The read-only roles (grafana_reader, migration 0006; powerbi_reader, migration 0011) need
-- USAGE on the marts schema as well as SELECT on its tables. +grants re-grants the tables
-- on every build, but if the schema itself is dropped and dbt recreates it, the schema-level
-- grant is gone and both roles lose access. Re-granting it after every run closes that gap.
{% macro grant_reader_usage(schemas) %}
    {% if 'marts' in schemas %}
        grant usage on schema marts to grafana_reader, powerbi_reader
    {% else %}
        select 1
    {% endif %}
{% endmacro %}
