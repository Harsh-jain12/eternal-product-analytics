/*
  05's leakage verification method 1, at row level rather than in prose: the feature
  window and the outcome window must not overlap.

  FEATURE window  event_time <= t0   (strictly before t0, plus the first order's own
                                      purchase lines at exactly t0)
  OUTCOME window  order_ts   >  t0   in a session other than the first-order session

  05 measured max feature-block offset 0s against min outcome offset 70s. This test
  fails if any row lands on the wrong side, or if the first-order line set and the
  certified order it is supposed to be do not agree on how many items that order had.
*/

with violations as (

    -- M2/M3 must read nothing at or after t0
    select 'int_pre_t0_events reads at or after t0' as violation, count(*) as n_rows
    from {{ ref('int_pre_t0_events') }}
    where event_time >= first_ts

    union all
    -- M1 must read exactly the first order, and nothing else. If the line set and
    -- fct_orders disagree on the item count, one of the two windows has moved.
    select 'first-order lines disagree with the certified order n_items', count(*)
    from (
        select l.user_id, count(*) as n_lines, max(u.first_order_n_items) as n_items
        from {{ ref('int_first_order_lines') }} l
        join {{ ref('dim_users') }} u on u.user_id = l.user_id
        group by 1
    )
    where n_lines <> n_items

    union all
    -- every purchaser must have a first-order line set
    select 'a purchaser has no first-order lines', count(*)
    from {{ ref('dim_users') }} u
    left join (select distinct user_id from {{ ref('int_first_order_lines') }}) l
           on l.user_id = u.user_id
    where u.is_purchaser and l.user_id is null

    union all
    -- the outcome must never count a return inside the first-order session
    select 'a repeat order counted inside the first-order session', count(*)
    from {{ ref('mart_user_features') }} f
    join {{ ref('dim_users') }} u on u.user_id = f.user_id
    join {{ ref('fct_orders') }} o on o.user_id = f.user_id
    where f.days_to_next_order is not null
      and o.user_session = u.first_order_session
      and o.order_ts > u.first_order_ts
      and {{ sig_round("date_diff('second', u.first_order_ts, o.order_ts) / 86400.0") }} = f.days_to_next_order
      -- ... and no order in a DIFFERENT session explains that same gap
      and not exists (
          select 1 from {{ ref('fct_orders') }} o2
          where o2.user_id = f.user_id
            and o2.user_session <> u.first_order_session
            and o2.order_ts > u.first_order_ts
            and {{ sig_round("date_diff('second', u.first_order_ts, o2.order_ts) / 86400.0") }} = f.days_to_next_order
      )
)

select * from violations where n_rows > 0
