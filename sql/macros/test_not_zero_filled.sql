{#- Principle: an unobserved window is not a zero. A retention or eligibility cell that
    exists must have a real denominator behind it; a cell with no denominator must not
    exist at all (CLAUDE.md non-negotiable 1, 05's eligibility rule). -#}
{% test not_zero_filled(model, column_name, denominator_column) %}

select *
from {{ model }}
where {{ denominator_column }} is null
   or {{ denominator_column }} <= 0
   or {{ column_name }} is null

{% endtest %}
