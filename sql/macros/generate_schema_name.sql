{#- Use the schema name as configured, not <target>_<schema>. Keeps the DuckDB file
    readable: staging.stg_events, marts.fct_orders. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
