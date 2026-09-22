{{ config(materialized='table') }}

/*
  User grain. PK: user_id. One row for EVERY bot-excluded user with at least one
  session-valid event, purchaser or not -- so a conversion denominator can be taken from
  this table without a second pass over the events.

  user_id IS COOKIE-SCOPED, NOT ACCOUNT-SCOPED. One person on two devices is two rows.
  Every repeat-purchase and retention figure built on this table is therefore a LOWER
  BOUND, and must be reported as one (handoff -> known_limitations).

  t0 = first_order_ts, chosen on the FULL certified orders key (order_ts, user_session),
  never on order_ts alone -- see fct_orders.

  Two cohort columns, because this project uses two and they are not the same thing:
    - acquisition_cohort_month  month of the user's first EVENT. Defined for everyone.
    - first_order_cohort_month  month of t0. This is the cohort 02's retention curves and
                                05's feature table are built on, and it is NULL for a
                                non-purchaser.

  is_black_friday_cohort: t0 falls on a day the 02 discount detector flagged. Renamed
  from `is_promo` in 02 -- every detected spike day falls inside one trading week, so the
  flag identifies the Black Friday cohort, not promotional acquisition generally. False,
  not NULL, for a user with no first order: they are not in that cohort.

  is_bulk_buyer: the user has ever placed an order at or above the certified P99.9 order
  size. FULL-HISTORY, and therefore LEAKY as a model feature -- 05 found 33 of the 143
  are flagged on an order placed AFTER t0. It is a POPULATION flag for reporting and
  for excluding B2B-looking users from mean-based monetary metrics (02's decision:
  keep and flag, never drop). mart_user_features carries the leakage-safe twin,
  first_order_is_bulk, instead.
*/

with bulk_threshold as (
    select param_value as bulk_items_threshold
    from {{ ref('stg_handoff_params') }}
    where json_path = '$.bulk_buyer_segment.threshold_items_per_order'
),

spike_days as (
    select spike_date from {{ ref('stg_discount_spike_days') }} where is_spike
),

user_events as (
    select
        user_id,
        min(event_time) as first_event_ts,
        max(event_time) as last_event_ts,
        count(*)        as n_events,
        count(distinct user_session)  as n_sessions,
        count(distinct event_date)    as n_active_days
    from {{ ref('stg_events') }}
    group by 1
),

user_orders as (
    select
        user_id,
        count(*)         as n_orders,
        min(order_ts)    as first_order_ts_min,
        max(order_ts)    as last_order_ts,
        {{ key_round('sum(order_value)') }} as lifetime_order_value,
        sum(n_items)     as lifetime_items,
        max(n_items)     as max_order_items
    from {{ ref('fct_orders') }}
    group by 1
),

first_order as (
    select user_id, user_session as first_order_session, order_ts as first_order_ts,
           n_items as first_order_n_items, order_value as first_order_value
    from {{ ref('fct_orders') }}
    where order_seq = 1
)

select
    e.user_id,
    e.first_event_ts,
    e.last_event_ts,
    e.n_events,
    e.n_sessions,
    e.n_active_days,
    cast(date_trunc('month', e.first_event_ts) as DATE) as acquisition_cohort_month,

    f.first_order_ts,
    f.first_order_session,
    f.first_order_n_items,
    f.first_order_value,
    cast(date_trunc('month', f.first_order_ts) as DATE) as first_order_cohort_month,
    cast(date_trunc('day',   f.first_order_ts) as DATE) as first_order_date,

    coalesce(o.n_orders, 0)            as n_orders,
    o.last_order_ts,
    o.lifetime_order_value,
    o.lifetime_items,
    coalesce(o.n_orders, 0) > 0        as is_purchaser,
    coalesce(o.n_orders, 0) >= 2       as is_repeat_purchaser,

    coalesce(f.first_order_date_is_spike, false) as is_black_friday_cohort,
    coalesce(o.max_order_items >= b.bulk_items_threshold, false) as is_bulk_buyer
from user_events e
left join user_orders o on o.user_id = e.user_id
left join (
    select fo.*, (sd.spike_date is not null) as first_order_date_is_spike
    from first_order fo
    left join spike_days sd on sd.spike_date = cast(date_trunc('day', fo.first_order_ts) as DATE)
) f on f.user_id = e.user_id
cross join bulk_threshold b
