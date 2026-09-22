{{ config(materialized='table') }}

/*
  THE TEST THAT MAKES THIS LAYER A REPRODUCTION RATHER THAN A REWRITE.

  Every row is one certified number, computed from the models above and compared to the
  value 00-08 published in outputs/handoff_params.json. NO TARGET IS HARDCODED: every
  expected value is read through stg_handoff_params, and `handoff_json_path` carries the
  key that was read into the output, so a failure names the notebook figure it disagrees
  with rather than an anonymous constant.

  `tolerance` is half of the last digit the handoff itself publishes, plus a float
  epsilon. A count reconciles EXACTLY (tolerance 0). A percentage published to 2dp
  reconciles to 2dp. Nothing is given slack it was not published with.

  Any row with passed = false is a FAILING TEST, not a warning -- see
  tests/assert_reconciles_with_handoff.sql. A drift here means the SQL layer and the
  notebooks have diverged, and one of them is wrong.
*/

with h as (
    select json_path, param_value, param_text from {{ ref('stg_handoff_params') }}
),

-- ---- inputs ---------------------------------------------------------------------------
totals as (
    select
        (select count(*) from {{ ref('stg_events') }})                              as stg_events_rows,
        (select count(distinct user_id) from {{ ref('stg_events') }})               as stg_users,
        (select count(*) from {{ ref('stg_events') }} where event_type = 'purchase') as stg_purchase_rows,
        (select count(*) from {{ ref('fct_orders') }})                              as n_orders,
        (select count(*) from {{ ref('dim_users') }} where is_purchaser)            as n_purchasers,
        (select count(*) from {{ ref('dim_users') }} where is_bulk_buyer)           as n_bulk_users,
        (select count(*) from {{ ref('stg_bot_users') }})                           as n_bot_users,
        (select coalesce(sum(n_events), 0)        from {{ ref('stg_bot_users') }})  as bot_events,
        (select coalesce(sum(n_purchase_rows), 0) from {{ ref('stg_bot_users') }})  as bot_purchase_rows,
        (select coalesce(sum(n_orders), 0)        from {{ ref('stg_bot_users') }})  as bot_orders,
        (select count(*) from {{ ref('stg_bot_users') }} where n_orders > 0)        as bot_purchasers,
        -- rows the null_user_session rule removes, recovered from the raw file so the
        -- raw totals can be reconstructed without a second bot-inclusive event table
        (select count(*) from read_csv_auto('{{ var("raw_events_glob") }}') where user_session is null) as null_session_rows,
        (select count(distinct user_id) from read_csv_auto('{{ var("raw_events_glob") }}'))             as raw_users,
        (select min(event_time) from {{ ref('stg_events') }}) as data_min_ts,
        (select max(event_time) from {{ ref('stg_events') }}) as data_max_ts
),

bulk_shares as (
    select
        {{ key_round('100.0 * count(*) filter (where u.is_bulk_buyer) / count(*)') }} as pct_of_orders,
        {{ key_round('100.0 * sum(o.order_value) filter (where u.is_bulk_buyer) / sum(o.order_value)') }} as pct_of_revenue
    from {{ ref('fct_orders') }} o
    join {{ ref('dim_users') }} u on u.user_id = o.user_id
),

order_size_p999 as (
    select quantile_cont(n_items, 0.999) as p999 from {{ ref('fct_orders') }}
),

spikes as (
    select
        count(*) filter (where is_spike)      as n_spike_days,
        min(spike_date) filter (where is_spike) as first_spike_date,
        max(spike_date) filter (where is_spike) as last_spike_date,
        max(spike_cut)                          as spike_cut
    from {{ ref('stg_discount_spike_days') }}
),

retention_pooled as (
    select
        bucket_day,
        sum(eligible_n)          as eligible_n,
        {{ key_round('100.0 * sum(purchase_returners) / sum(eligible_n)') }} as purchase_pct,
        {{ key_round('100.0 * sum(activity_returners) / sum(eligible_n)') }} as activity_pct
    from {{ ref('mart_cohort_retention') }}
    group by 1
),

features_by_horizon as (
    select 30 as horizon,
           count(*) filter (where eligible_30d) as eligible_n,
           {{ key_round('100.0 * count(*) filter (where eligible_30d and repeat_purchase_30d) / count(*) filter (where eligible_30d)') }} as positive_rate_pct
    from {{ ref('mart_user_features') }}
    union all
    select 60,
           count(*) filter (where eligible_60d),
           {{ key_round('100.0 * count(*) filter (where eligible_60d and repeat_purchase_60d) / count(*) filter (where eligible_60d)') }}
    from {{ ref('mart_user_features') }}
    union all
    select 90,
           count(*) filter (where eligible_90d),
           {{ key_round('100.0 * count(*) filter (where eligible_90d and repeat_purchase_90d) / count(*) filter (where eligible_90d)') }}
    from {{ ref('mart_user_features') }}
),

trigger_pool as (
    select
        sum(day14_trigger_pool_observable_n) as pool_n,
        {{ key_round('100.0 * sum(day14_trigger_pool_repeaters_n) / sum(day14_trigger_pool_observable_n)') }} as base_rate_pct
    from {{ ref('mart_daily_kpis') }}
),

n_model_eligible as (
    select count(*) as n_cols
    from (
        select column_name
        from information_schema.columns
        where table_name = 'mart_user_features'
          and column_name not in ('user_id', 'first_ts', 'cohort_month', 'trailing_days',
                                  'days_to_next_order',
                                  'eligible_30d', 'eligible_60d', 'eligible_90d',
                                  'repeat_purchase_30d', 'repeat_purchase_60d', 'repeat_purchase_90d')
    )
),

-- ---- the checks -----------------------------------------------------------------------
checks as (

    -- 00: shape of the raw data, reconstructed from what this layer removed
    select '00 raw event rows'                as check_name, 'stg_events'      as model,
           '$.row_counts.total_events'        as handoff_json_path,
           (t.stg_events_rows + t.bot_events + t.null_session_rows)::DOUBLE as model_value, 0.0 as tolerance,
           'stg_events + the events of the 1,605 excluded users + the null-session rows' as how
    from totals t
    union all
    select '00 distinct users in the raw CSVs', 'stg_events', '$.row_counts.n_users_any_event',
           t.raw_users::DOUBLE, 0.0,
           'counted on the raw file; stg_events holds 1,605 fewer for the bot rule and 207 fewer whose only events had no session'
    from totals t
    union all
    select '00 orders under the certified rule, before bot exclusion', 'fct_orders', '$.row_counts.n_orders',
           (t.n_orders + t.bot_orders)::DOUBLE, 0.0, 'fct_orders + the orders of the excluded users'
    from totals t
    union all
    select '00 purchasers, before bot exclusion', 'dim_users', '$.row_counts.n_purchasing_users',
           (t.n_purchasers + t.bot_purchasers)::DOUBLE, 0.0, 'dim_users purchasers + excluded users who had an order'
    from totals t
    union all
    -- 00 reports the span as elapsed whole days between the first and last event
    -- (2019-10-01 00:00:00 -> 2020-02-29 23:59:59 = 151 days and change), NOT as a count
    -- of calendar days touched, which is 152.
    select '00 observation window length in days', 'stg_events', '$.data_date_range.span_days',
           date_diff('day', t.data_min_ts, t.data_max_ts)::DOUBLE, 0.0,
           'elapsed whole days between the first and last event in stg_events' from totals t

    -- 01: the bot exclusion
    union all
    select '01 users excluded by the bot rule', 'stg_bot_users', '$.bot_exclusion.n_users_excluded',
           t.n_bot_users::DOUBLE, 0.0, 'row count of stg_bot_users' from totals t
    union all
    select '01 share of session-valid events excluded', 'stg_bot_users', '$.bot_exclusion.share_of_events_pct',
           {{ key_round('100.0 * t.bot_events / (t.stg_events_rows + t.bot_events)') }}, 0.0005,
           'denominator is session-valid events, not raw rows' from totals t
    union all
    select '01 share of purchase LINES excluded', 'stg_bot_users', '$.bot_exclusion.share_of_purchase_rows_pct',
           {{ key_round('100.0 * t.bot_purchase_rows / (t.stg_purchase_rows + t.bot_purchase_rows)') }}, 0.00005,
           'purchase rows, not orders' from totals t
    union all
    select '01 share of ORDERS excluded', 'stg_bot_users', '$.bot_exclusion.share_of_orders_pct',
           {{ key_round('100.0 * t.bot_orders / (t.n_orders + t.bot_orders)') }}, 0.00005,
           'certified-rule orders, not purchase rows' from totals t

    -- 02: bulk buyers
    union all
    select '02 bulk-buyer bar (P99.9 of order size)', 'fct_orders', '$.bulk_buyer_segment.threshold_items_per_order',
           p.p999, 1e-9, 're-derived with quantile_cont on fct_orders; dim_users READS the handoff value'
    from order_size_p999 p
    union all
    select '02 bulk buyers flagged', 'dim_users', '$.bulk_buyer_segment.n_users',
           t.n_bulk_users::DOUBLE, 0.0, 'dim_users.is_bulk_buyer' from totals t
    union all
    select '02 bulk share of orders', 'dim_users', '$.bulk_buyer_segment.share_of_orders_pct',
           b.pct_of_orders, 0.0005, 'orders placed by is_bulk_buyer users' from bulk_shares b
    union all
    select '02 bulk share of revenue', 'dim_users', '$.bulk_buyer_segment.share_of_revenue_pct',
           b.pct_of_revenue, 0.0005, 'order_value from is_bulk_buyer users' from bulk_shares b

    -- 02: the Black Friday detector
    union all
    select '02 discount-spike cut (median + 3*1.4826*MAD)', 'stg_discount_spike_days', '$.black_friday_cohort.spike_threshold',
           s.spike_cut, 0.000005, 'recomputed from price dispersion, no calendar input' from spikes s
    union all
    select '02 days flagged as discount spikes', 'stg_discount_spike_days', '$.black_friday_cohort.n_spike_days',
           s.n_spike_days::DOUBLE, 0.0, 'is_spike rows' from spikes s

    -- 02: retention, at every bucket
    union all
    select '02 purchase retention D' || r.bucket_day, 'mart_cohort_retention',
           '$.retention_measured.purchase_retention_pct.d' || r.bucket_day,
           r.purchase_pct, 0.005, 'pooled over eligible cohorts: sum(returners)/sum(eligible_n)'
    from retention_pooled r
    union all
    select '02 activity retention D' || r.bucket_day, 'mart_cohort_retention',
           '$.retention_measured.activity_retention_pct.d' || r.bucket_day,
           r.activity_pct, 0.005, 'same window and session rule, any event type'
    from retention_pooled r
    union all
    select '02 eligible denominator D' || r.bucket_day, 'mart_cohort_retention',
           '$.retention_measured.eligible_n.d' || r.bucket_day,
           r.eligible_n::DOUBLE, 0.0, 'ineligible cohorts contribute no row, so this falls with the horizon'
    from retention_pooled r

    -- 05: the modelling frame
    union all
    select '05 purchasers in the feature table', 'mart_user_features', '$.features.n_rows',
           t.n_purchasers::DOUBLE, 0.0, 'one row per bot-excluded purchaser' from totals t
    union all
    select '05 model-eligible feature columns', 'mart_user_features', '$.features.n_model_eligible',
           c.n_cols::DOUBLE, 0.0, 'columns excluding the key, the targets and the eligibility flags'
    from n_model_eligible c
    union all
    select '05 eligible_n D' || f.horizon, 'mart_user_features', '$.features.eligible_n.d' || f.horizon,
           f.eligible_n::DOUBLE, 0.0, 'exact elapsed seconds, censored users excluded'
    from features_by_horizon f
    union all
    select '05 positive rate D' || f.horizon, 'mart_user_features', '$.features.positive_rate_pct.d' || f.horizon,
           f.positive_rate_pct, 0.005, 'repeat_purchase_{h}d over the eligible frame'
    from features_by_horizon f

    -- 08: the activation trigger
    union all
    select '08 day-14 trigger pool, historical analogue', 'mart_daily_kpis',
           '$.experiment_design.population.n_historical_analogue',
           p.pool_n::DOUBLE, 0.0, 'sum of the observable pool over every day the trigger fires'
    from trigger_pool p
    union all
    select '08 day-14 trigger pool base rate', 'mart_daily_kpis',
           '$.experiment_design.population.base_rate_pct',
           p.base_rate_pct, 0.00005,
           'NOT 05/06''s 13.73%: different population, different window' from trigger_pool p
),

text_checks as (
    select '00 observation window, first event' as check_name, 'stg_events' as model,
           '$.data_date_range.min' as handoff_json_path,
           strftime(t.data_min_ts, '%Y-%m-%d %H:%M:%S') as model_text from totals t
    union all
    select '00 observation window, last event', 'stg_events', '$.data_date_range.max',
           strftime(t.data_max_ts, '%Y-%m-%d %H:%M:%S') from totals t
    union all
    select '02 first discount-spike day', 'stg_discount_spike_days', '$.black_friday_cohort.spike_day_span[0]',
           strftime(s.first_spike_date, '%Y-%m-%d') from spikes s
    union all
    select '02 last discount-spike day', 'stg_discount_spike_days', '$.black_friday_cohort.spike_day_span[1]',
           strftime(s.last_spike_date, '%Y-%m-%d') from spikes s
),

numeric_result as (
    select
        c.check_name,
        c.model,
        c.handoff_json_path,
        'numeric' as compare_as,
        h.param_value as handoff_value,
        c.model_value,
        abs(c.model_value - h.param_value) as abs_diff,
        c.tolerance,
        c.how,
        (h.param_value is not null and c.model_value is not null
         and abs(c.model_value - h.param_value) <= c.tolerance + 1e-9) as passed
    from checks c
    join h on h.json_path = c.handoff_json_path
    where c.model_value is not null
),

text_result as (
    select
        t.check_name,
        t.model,
        t.handoff_json_path,
        'text' as compare_as,
        null::DOUBLE as handoff_value,
        null::DOUBLE as model_value,
        null::DOUBLE as abs_diff,
        null::DOUBLE as tolerance,
        'compared as text: model "' || t.model_text || '" vs handoff "' || coalesce(h.param_text, '<missing>') || '"' as how,
        (h.param_text is not null and t.model_text = h.param_text) as passed
    from text_checks t
    join h on h.json_path = t.handoff_json_path
)

select * from numeric_result
union all
select * from text_result
