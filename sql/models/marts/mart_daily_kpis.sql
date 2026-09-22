{{ config(materialized='table') }}

/*
  The daily monitoring table -- the one model here that is a reporting surface rather
  than a reproduction of a notebook figure.

  Grain / PK: activity_date. One row per calendar day in the observation window.

  CONVERSION IS REPORTED AT TWO SCOPES AND THEY ARE LABELLED, because they are different
  quantities with different denominators and 01 found them 1.8x apart:
    conversion_rate_session_scope_pct   sessions that contained a purchase / all sessions
    conversion_rate_user_scope_pct      users who purchased that day / users active that day
  A user browsing across five sessions and buying in one is 20% at session scope and 100%
  at user scope. Never quote one as the other.

  AOV IS REPORTED AS A MEDIAN AND A WINSORISED MEAN, never as a raw mean. 02 Section 0C
  identified 143 bulk buyers -- a reseller / B2B signature, kept and flagged, not dropped
  -- who place 0.19% of orders but take 1.4% of revenue, and a raw daily mean is theirs
  to move. The winsorising cap is the P99 of the whole order-value distribution, computed
  once with quantile_cont (never approx_quantile, connect() note 2) so every day is
  capped on the same bar. n_orders_from_bulk_buyers keeps the caveat visible on the row.

  THE DAY-14 TRIGGER POOL is 08's activation population, counted on the day the rule
  would fire: t0 + 14 days, for a user with no second order yet. Three columns, because
  an operational count and a measurable one are not the same thing:
    day14_trigger_pool_n             everyone the rule would enrol that day. The
                                     operational number -- how many sends to budget for.
    day14_trigger_pool_observable_n  of those, the ones whose 30-day outcome window
                                     closes inside the data (trailing >= 44 days). This
                                     is 08's historical analogue, and it is the only one
                                     a base rate may be computed on. NULL, never 0, once
                                     the window runs past the end of the data -- an
                                     unobserved window is not an empty one.
    day14_trigger_pool_repeaters_n   of the observable, those who ordered again in
                                     (t0+14d, t0+44d].
  The pool's base rate is sum(repeaters) / sum(observable) -- 10.25%, NOT 05/06's 13.73%.
  Those are different populations over different windows and must never be substituted
  for one another (08's naming rule).
*/

with data_end as (
    select max(event_time) as data_end_ts from {{ ref('stg_events') }}
),

trigger_days as (
    select param_value as trigger_days
    from {{ ref('stg_handoff_params') }}
    where json_path = '$.experiment_design.trigger.days_since_first_order'
),

outcome_horizon as (
    select param_value as horizon_days
    from {{ ref('stg_handoff_params') }}
    where json_path = '$.retention_horizon.primary_days'
),

calendar as (
    select distinct event_date as activity_date from {{ ref('stg_events') }}
),

order_value_cap as (
    select quantile_cont(order_value, 0.99) as p99_order_value from {{ ref('fct_orders') }}
),

daily_events as (
    select
        event_date as activity_date,
        count(*)                                                as n_events,
        count(*) filter (where event_type = 'view')             as n_view_events,
        count(*) filter (where event_type = 'cart')             as n_cart_events,
        count(*) filter (where event_type = 'remove_from_cart') as n_removal_events,
        count(*) filter (where event_type = 'purchase')         as n_purchase_events,
        count(distinct user_id)                                 as n_active_users,
        count(distinct user_id) filter (where event_type = 'purchase') as n_purchasing_users
    from {{ ref('stg_events') }}
    group by 1
),

daily_sessions as (
    select
        session_date as activity_date,
        count(*)                            as n_sessions,
        count(*) filter (where converted)   as n_sessions_converted,
        count(distinct user_id)             as n_users_starting_a_session,
        count(*) filter (where is_first_time_session) as n_first_time_sessions
    from {{ ref('fct_sessions') }}
    group by 1
),

daily_orders as (
    select
        o.order_date as activity_date,
        count(*)                                     as n_orders,
        sum(o.n_items)                               as n_items,
        {{ key_round('sum(o.order_value)') }}        as gross_revenue_eur,
        quantile_cont(o.order_value, 0.5)            as aov_median_eur,
        avg(least(o.order_value, (select p99_order_value from order_value_cap))) as aov_mean_winsorised_eur,
        count(*) filter (where u.is_bulk_buyer)      as n_orders_from_bulk_buyers
    from {{ ref('fct_orders') }} o
    join {{ ref('dim_users') }} u on u.user_id = o.user_id
    group by 1
),

daily_new_buyers as (
    select first_order_date as activity_date, count(*) as n_new_first_time_buyers
    from {{ ref('dim_users') }}
    where is_purchaser
    group by 1
),

-- One row per user, on the day the day-14 rule would fire for them.
trigger_pool as (
    select
        cast(date_trunc('day', f.first_ts + to_days(cast(t.trigger_days as INTEGER))) as DATE) as activity_date,
        -- enrollable: no second order by the trigger day
        count(*) filter (
            where f.days_to_next_order is null or f.days_to_next_order > t.trigger_days
        ) as day14_trigger_pool_n,
        -- observable: the trigger's own 30-day outcome window closes inside the data
        count(*) filter (
            where (f.days_to_next_order is null or f.days_to_next_order > t.trigger_days)
              and f.trailing_days >= t.trigger_days + h.horizon_days
        ) as day14_trigger_pool_observable_n,
        count(*) filter (
            where f.trailing_days >= t.trigger_days + h.horizon_days
              and f.days_to_next_order >  t.trigger_days
              and f.days_to_next_order <= t.trigger_days + h.horizon_days
        ) as day14_trigger_pool_repeaters_n
    from {{ ref('mart_user_features') }} f
    cross join trigger_days t
    cross join outcome_horizon h
    group by 1
)

select
    c.activity_date,

    -- volume
    coalesce(e.n_events, 0)           as n_events,
    coalesce(e.n_view_events, 0)      as n_view_events,
    coalesce(e.n_cart_events, 0)      as n_cart_events,
    coalesce(e.n_removal_events, 0)   as n_removal_events,
    coalesce(e.n_purchase_events, 0)  as n_purchase_events,
    coalesce(s.n_sessions, 0)         as n_sessions,
    coalesce(s.n_first_time_sessions, 0) as n_first_time_sessions,
    coalesce(e.n_active_users, 0)     as n_active_users,

    -- conversion, at two labelled scopes
    coalesce(s.n_sessions_converted, 0) as n_sessions_converted,
    coalesce(e.n_purchasing_users, 0)   as n_purchasing_users,
    {{ key_round('100.0 * s.n_sessions_converted / nullif(s.n_sessions, 0)') }}  as conversion_rate_session_scope_pct,
    {{ key_round('100.0 * e.n_purchasing_users / nullif(e.n_active_users, 0)') }} as conversion_rate_user_scope_pct,

    -- orders and basket value
    coalesce(o.n_orders, 0)  as n_orders,
    coalesce(o.n_items, 0)   as n_items,
    o.gross_revenue_eur,
    {{ key_round('o.aov_median_eur', 2) }}           as aov_median_eur,
    {{ key_round('o.aov_mean_winsorised_eur', 2) }}  as aov_mean_winsorised_eur,
    coalesce(o.n_orders_from_bulk_buyers, 0) as n_orders_from_bulk_buyers,

    -- acquisition
    coalesce(nb.n_new_first_time_buyers, 0) as n_new_first_time_buyers,

    -- 08's activation trigger, counted on the day it fires
    coalesce(tp.day14_trigger_pool_n, 0) as day14_trigger_pool_n,
    -- NULL, not 0, once the 30-day outcome window runs past the end of the data
    case when c.activity_date + to_days(cast((select horizon_days from outcome_horizon) as INTEGER))
              <= cast((select data_end_ts from data_end) as DATE)
         then coalesce(tp.day14_trigger_pool_observable_n, 0) end as day14_trigger_pool_observable_n,
    case when c.activity_date + to_days(cast((select horizon_days from outcome_horizon) as INTEGER))
              <= cast((select data_end_ts from data_end) as DATE)
         then coalesce(tp.day14_trigger_pool_repeaters_n, 0) end as day14_trigger_pool_repeaters_n,
    c.activity_date + to_days(cast((select horizon_days from outcome_horizon) as INTEGER))
        <= cast((select data_end_ts from data_end) as DATE) as trigger_outcome_window_closed

from calendar c
left join daily_events   e  on e.activity_date  = c.activity_date
left join daily_sessions s  on s.activity_date  = c.activity_date
left join daily_orders   o  on o.activity_date  = c.activity_date
left join daily_new_buyers nb on nb.activity_date = c.activity_date
left join trigger_pool   tp on tp.activity_date = c.activity_date
