{{ config(materialized='table') }}

/*
  LEAKAGE-SAFE product price reference, 05 Section 4, reproduced verbatim.

  Grain: (product_id, event_date). For each product-day it carries statistics computed
  over STRICTLY EARLIER days only -- the SQL equivalent of .shift().expanding()
  (CLAUDE.md principle 9). A full-dataset product median would let a first-order feature
  see price cuts that had not happened yet: 05 measured mean discount 0.1394 against the
  safe 0.0161, 8.7x larger, purely from that leak.

  RC-1, and this is where the project measured it: `prior_price_pct` is a percent_rank
  whose ORDER BY is a float built from a parallel sum. Two processes on the same data:
  raw key -> 597,236 of 3,113,627 ranks differ, max |diff| 0.0423; key_round()ed key ->
  0 differ. The product_id tie-break does NOT save you -- two products at the same price
  stop comparing equal once their accumulated sums differ by one bit, so the tie-break
  never fires. Rounding restores the tie, and only then does product_id decide it.

  prior_mean_price is rounded too, not just the rank key: it is persisted and feeds
  fo_price_vs_prior_mean, the one feature 05 Section 11 caught flipping.
*/

with product_day as (
    select
        product_id,
        event_date as d,
        count(*)   as n,
        sum(price) as sum_price,
        max(price) as max_price
    from {{ ref('stg_events') }}
    where price > 0
    group by 1, 2
),

expanding_prior as (
    select
        product_id,
        d,
        sum(n)         over w as prior_n,
        sum(sum_price) over w as prior_sum_price,
        max(max_price) over w as prior_max_price
    from product_day
    window w as (
        partition by product_id
        order by d
        rows between unbounded preceding and 1 preceding
    )
)

select
    product_id,
    d,
    {{ key_round('prior_sum_price / prior_n') }} as prior_mean_price,
    prior_max_price,
    percent_rank() over (
        partition by d
        order by {{ key_round('prior_sum_price / prior_n') }}, product_id
    ) as prior_price_pct
from expanding_prior
where prior_n is not null and prior_n > 0
