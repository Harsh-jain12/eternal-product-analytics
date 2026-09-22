{#- Composite-key uniqueness. Written here rather than pulled from dbt_utils so this
    project has no package dependency and `dbt build` works with no network. -#}
{% test unique_combination(model, combination_of_columns) %}

with grouped as (
    select {{ combination_of_columns | join(', ') }}, count(*) as n_rows
    from {{ model }}
    group by {{ range(1, combination_of_columns | length + 1) | join(', ') }}
)
select * from grouped where n_rows > 1

{% endtest %}
