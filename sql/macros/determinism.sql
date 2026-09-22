{#-
  The two rounding guards from src/data.py, ported to SQL so this layer carries the
  same determinism contract as the notebooks.

  sig_round(col, sig)  -- src.data.round_sig. For a float that is REPORTED or PERSISTED.
                          Significant figures, not decimals: these features span 1e-3 to
                          1e3, so a fixed decimal count would over-round the small ones
                          and under-round the large ones. Bit-identical to the Python
                          implementation (verified on the sig=6 grid).

  key_round(col, dp)   -- src.data.key_round. For a float that is used as an ORDERING,
                          RANK or BUCKETING key, applied BEFORE it is used as one. This
                          is connect()'s failure mode 4, the one that AMPLIFIES: a 1e-13
                          wobble in a sort key comes back out as a whole rank step, and
                          the declared tie-break never fires because the values are no
                          longer tied.
-#}

{% macro sig_round(col, sig=none) -%}
    {%- set s = sig if sig is not none else var('sig_figures') -%}
    case
        when ({{ col }}) is null or ({{ col }}) = 0 or not isfinite(({{ col }})::DOUBLE)
            then ({{ col }})::DOUBLE
        else round_even(({{ col }})::DOUBLE * pow(10.0, {{ s - 1 }} - floor(log10(abs(({{ col }})::DOUBLE)))), 0)
             / pow(10.0, {{ s - 1 }} - floor(log10(abs(({{ col }})::DOUBLE))))
    end
{%- endmacro %}

{% macro key_round(col, dp=none) -%}
    {%- set d = dp if dp is not none else var('key_decimals') -%}
    round(({{ col }})::DOUBLE, {{ d }})
{%- endmacro %}

{#- The certified handoff document, as a single JSON text value. Every constant this
    layer inherits is pulled out of it by json path -- nothing is hardcoded. -#}
{% macro handoff_doc() -%}
    (select content from read_text('{{ var("handoff_path") }}'))
{%- endmacro %}

{% macro handoff_num(json_path) -%}
    (select try_cast(json_extract_string(content, '{{ json_path }}') as DOUBLE)
     from read_text('{{ var("handoff_path") }}'))
{%- endmacro %}

{% macro handoff_text(json_path) -%}
    (select json_extract_string(content, '{{ json_path }}')
     from read_text('{{ var("handoff_path") }}'))
{%- endmacro %}
