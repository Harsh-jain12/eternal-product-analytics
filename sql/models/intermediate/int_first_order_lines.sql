{{ config(materialized='table') }}

/*
  The purchase lines that make up each purchaser's FIRST order -- 05's `fo_lines`.

  Window: event_time = t0 exactly, AND user_session = the first-order session. Both
  conditions, not just the timestamp: 05 Section 1 shows the four windows (before t0,
  the first order's own lines at t0, simultaneous-but-other-session at t0, after t0)
  PARTITION the purchaser event set, and the third of those -- 41 rows across 32 users
  logged at exactly t0 in a different session -- belongs to neither the feature window
  nor the outcome window, so it is excluded rather than quietly folded into M1.

  This is the whole of the M1 feature window.
*/

select
    e.user_id,
    e.product_id,
    e.category_id,
    e.brand,
    e.price,
    u.first_order_ts as first_ts,
    e.event_date     as d
from {{ ref('stg_events') }} e
join {{ ref('dim_users') }} u
  on u.user_id      = e.user_id
 and u.first_order_session = e.user_session
 and u.first_order_ts      = e.event_time
where e.event_type = 'purchase'
