/*
  THE RULE THIS WHOLE LAYER IS BUILT AROUND: an unobserved window is not a negative.

  A user is eligible at horizon h only if h days have elapsed since t0 in EXACT SECONDS.
  This test fails if any user is flagged eligible without the elapsed time to back it up,
  or is flagged a repeater at a horizon their return falls outside of.
*/

select user_id, trailing_days, days_to_next_order,
       eligible_30d, eligible_60d, eligible_90d,
       repeat_purchase_30d, repeat_purchase_60d, repeat_purchase_90d
from {{ ref('mart_user_features') }}
where (eligible_30d and trailing_days < 30)
   or (eligible_60d and trailing_days < 60)
   or (eligible_90d and trailing_days < 90)
   or (repeat_purchase_30d and (days_to_next_order is null or days_to_next_order > 30))
   or (repeat_purchase_60d and (days_to_next_order is null or days_to_next_order > 60))
   or (repeat_purchase_90d and (days_to_next_order is null or days_to_next_order > 90))
   -- a 30-day repeat is also a 60- and a 90-day repeat
   or (repeat_purchase_30d and not repeat_purchase_60d)
   or (repeat_purchase_60d and not repeat_purchase_90d)
