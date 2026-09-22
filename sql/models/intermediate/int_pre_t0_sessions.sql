{{ config(materialized='table') }}

/*
  Session-level roll-up of the pre-t0 window -- 05's `pre_sess`. Carries the session
  starts that M4's visit cadence is measured between, and the session counts M3 uses.

  Grain: (user_id, user_session), restricted to sessions with at least one pre-t0 event.
*/

select
    user_id,
    user_session,
    min(event_time) as s_start,
    max(event_time) as s_end,
    count(*)        as n_ev,
    max(case when is_first_order_session then 1 else 0 end) as is_first_order_session
from {{ ref('int_pre_t0_events') }}
group by 1, 2
