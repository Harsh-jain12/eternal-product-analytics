{{ config(materialized='table') }}

/*
  Daily KPI monitoring with a robust baseline. This is the model the dashboard's
  Monitoring page reads; nothing there recomputes it.

  Grain / PK: (kpi, activity_date). Long format, one row per series per day, so a
  consumer adds a KPI by adding a row rather than a column.

  THE RULE, and it is deliberately the same family as 02's discount-spike detector
  (stg_discount_spike_days): a day is anomalous when its value sits more than
  3 * 1.4826 * MAD from the median of a TRAILING baseline window. 1.4826 is the
  normal-consistency constant, so the cut is "3 sigma" if the series were normal and
  a robust equivalent when it is not -- which matters here, because the thing being
  detected (Black Friday) is exactly the kind of outlier that would inflate a
  mean-and-sd baseline enough to hide itself.

  WHAT MAKES THIS A MONITORING RULE RATHER THAN A DESCRIPTION. The window is
  TRAILING and EXCLUSIVE: days d-28 .. d-1, never day d itself and never a future day.
  A day cannot contribute to its own baseline, so the flag is computable on the morning
  after -- which is the only version of it that could ever run in production. 02's rule
  is two-sided over the whole window because 02 is describing a closed period; this one
  is not, because it is not.

  NOT EVALUABLE IS NOT NORMAL. A day with fewer than 14 prior days in its window, or
  one whose baseline MAD is zero (a constant window has no scale, so every deviation
  would be infinite), gets is_anomaly = NULL and a stated reason -- never false. The
  first 14 days of the series are therefore unmonitored, and the table says so rather
  than showing them as clean.

  Determinism (CLAUDE.md, src/data.py connect()):
    - quantile_cont for both the median and the MAD, never approx_quantile (note 2).
    - robust_z is a float that is used as a BUCKETING KEY -- it is compared against the
      3.0 cut -- so it is key_round()ed BEFORE that comparison (note 4, the one that
      amplifies). The Black Friday days sit at |z| of 8-40 against a cut of 3, so no
      membership turns on the rounding; it is applied because the rule requires it.
    - Every ORDER BY here is on the unique (kpi, activity_date) key.
    - The baseline is built by an explicit self-join on the day offset rather than a
      windowed quantile, because MAD is a median OF a deviation FROM a median and the
      two passes have to be separable to stay exact.
*/

{% set baseline_window_days = 28 %}
{% set min_baseline_days    = 14 %}
{% set mad_multiplier       = 3.0 %}

with kpis as (
    select
        activity_date,
        n_sessions,
        n_active_users,
        n_orders,
        conversion_rate_session_scope_pct,
        aov_median_eur,
        n_new_first_time_buyers,
        gross_revenue_eur,
        day14_trigger_pool_n
    from {{ ref('mart_daily_kpis') }}
),

-- Long format. The label and the unit travel with the value so the dashboard does not
-- have to carry a lookup of its own.
series as (
    {% set kpi_specs = [
        ('n_sessions',                        'Sessions',                    'count',   'fct_sessions'),
        ('n_active_users',                    'Active users',                'count',   'stg_events'),
        ('n_orders',                          'Orders',                      'count',   'fct_orders'),
        ('conversion_rate_session_scope_pct', 'Conversion (session scope)',  'percent', 'fct_sessions'),
        ('aov_median_eur',                    'AOV (median)',                'eur',     'fct_orders'),
        ('n_new_first_time_buyers',           'New first-time buyers',       'count',   'dim_users'),
        ('gross_revenue_eur',                 'Gross revenue',               'eur',     'fct_orders'),
        ('day14_trigger_pool_n',              'Day-14 trigger pool',         'count',   'mart_user_features'),
    ] %}
    {% for col, label, unit, source in kpi_specs %}
    select
        '{{ col }}'    as kpi,
        '{{ label }}'  as kpi_label,
        '{{ unit }}'   as kpi_unit,
        '{{ source }}' as kpi_source_model,
        activity_date,
        cast({{ col }} as DOUBLE) as kpi_value
    from kpis
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
),

-- (day, prior day) pairs inside the trailing exclusive window. ~28 rows per day per
-- KPI: 152 days x 8 KPIs x 28 = ~34k rows, so the join is cheap and exact.
baseline_pairs as (
    select
        d.kpi,
        d.activity_date,
        p.kpi_value as prior_value
    from series d
    join series p
      on p.kpi = d.kpi
     and p.activity_date <  d.activity_date
     and p.activity_date >= d.activity_date - {{ baseline_window_days }}
    where p.kpi_value is not null
),

-- Pass 1: the baseline median.
baseline_median as (
    select
        kpi,
        activity_date,
        count(*)                            as baseline_n_days,
        quantile_cont(prior_value, 0.5)     as baseline_median
    from baseline_pairs
    group by 1, 2
),

-- Pass 2: the median absolute deviation FROM that median. Separable only because the
-- median is materialised first, which is why this is not a single window function.
baseline_mad as (
    select
        p.kpi,
        p.activity_date,
        m.baseline_n_days,
        m.baseline_median,
        quantile_cont(abs(p.prior_value - m.baseline_median), 0.5) as baseline_mad
    from baseline_pairs p
    join baseline_median m
      on m.kpi = p.kpi and m.activity_date = p.activity_date
    group by 1, 2, 3, 4
),

scored as (
    select
        s.kpi,
        s.kpi_label,
        s.kpi_unit,
        s.kpi_source_model,
        s.activity_date,
        {{ sig_round('s.kpi_value') }}                                as kpi_value,
        coalesce(b.baseline_n_days, 0)                                as baseline_n_days,
        {{ sig_round('b.baseline_median') }}                          as baseline_median,
        {{ sig_round('b.baseline_mad') }}                             as baseline_mad,
        {{ sig_round('1.4826 * b.baseline_mad') }}                    as baseline_scaled_mad,
        {{ sig_round('b.baseline_median - ' ~ mad_multiplier ~ ' * 1.4826 * b.baseline_mad') }} as baseline_lower,
        {{ sig_round('b.baseline_median + ' ~ mad_multiplier ~ ' * 1.4826 * b.baseline_mad') }} as baseline_upper,
        -- BUCKETING KEY. key_round() before the comparison below, not after.
        case when b.baseline_mad > 0
             then {{ key_round('(s.kpi_value - b.baseline_median) / (1.4826 * b.baseline_mad)') }}
        end as robust_z,
        case
            when b.baseline_n_days is null or b.baseline_n_days < {{ min_baseline_days }}
                then 'baseline shorter than {{ min_baseline_days }} days'
            when b.baseline_mad = 0
                then 'baseline MAD is zero -- no scale to test against'
        end as not_evaluable_reason
    from series s
    left join baseline_mad b
           on b.kpi = s.kpi and b.activity_date = s.activity_date
)

select
    kpi,
    kpi_label,
    kpi_unit,
    kpi_source_model,
    activity_date,
    kpi_value,
    baseline_n_days,
    baseline_median,
    baseline_mad,
    baseline_scaled_mad,
    baseline_lower,
    baseline_upper,
    robust_z,
    {{ mad_multiplier }}     as mad_multiplier,
    {{ baseline_window_days }} as baseline_window_days,
    {{ min_baseline_days }}    as min_baseline_days,
    not_evaluable_reason,
    -- NULL, never false, when the day cannot be scored.
    case when not_evaluable_reason is null
         then abs(robust_z) > {{ mad_multiplier }} end as is_anomaly,
    case when not_evaluable_reason is null and abs(robust_z) > {{ mad_multiplier }}
         then case when robust_z > 0 then 'high' else 'low' end end as anomaly_direction
from scored
