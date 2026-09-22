{{ config(materialized='table') }}

/*
  Every purchaser event STRICTLY BEFORE t0 -- 05's `pre_ev`. This is the whole of the
  M2 and M3 feature window, and the reason the leakage rule is checkable at row level
  rather than only in prose: 05 asserts max feature-block offset 0s vs t0 against min
  outcome offset 70s.

  THE TRAP THIS MODEL EXISTS TO AVOID (05 Section 1A). 02's certified
  `first_session_events` is UNTRUNCATED -- it counts the whole first session, which for
  10.67% of purchasers (11,704 users, 241,536 events) extends PAST t0 and includes
  purchase rows. Every M2 feature in this project is cut at t0 instead. Measured cost of
  not truncating: univariate AUC 0.5737 against its truncated twin's 0.5525 -- the
  difference is leakage, not signal.

  `is_first_order_session` marks the rows M2 reads; M3 reads all of them.
*/

select
    e.user_id,
    e.user_session,
    e.event_time,
    e.event_date,
    e.event_type,
    e.product_id,
    e.category_id,
    e.brand,
    e.price,
    u.first_order_ts      as first_ts,
    u.first_order_session as first_session,
    e.user_session = u.first_order_session as is_first_order_session
from {{ ref('stg_events') }} e
join {{ ref('dim_users') }} u on u.user_id = e.user_id
where u.is_purchaser
  and e.event_time < u.first_order_ts
