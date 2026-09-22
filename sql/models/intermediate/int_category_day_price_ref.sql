{{ config(materialized='table') }}

/*
  LEAKAGE-SAFE category price reference, 05 Section 4, reproduced verbatim.

  Grain: (category_id, event_date), prior days only, same .shift().expanding() shape as
  int_product_day_price_ref. Carries the mean and sd of log price so a first-order line
  can be scored as a z-score within its own category as the category looked BEFORE the
  order.

  Two admission rules, both from 05, both deliberately NULLing rather than clipping:
    - at least 50 prior priced observations;
    - prior sd(log price) >= 0.05.
  A thin or single-price category produces a divide-by-almost-zero z-score. Those
  categories get no reference at all and fo_price_z_in_category stays NULL, with
  fo_catz_coverage recording how much of the order was scorable.

  RC-1 class: cat_sd_lp is compared against the 0.05 cut, so a last-bit wobble at the
  boundary would move a category in or out of the reference set. key_round() first.
*/

with category_day as (
    select
        category_id,
        event_date as d,
        count(*)                 as n,
        sum(ln(price))           as sum_log_price,
        sum(ln(price) * ln(price)) as sum_log_price_sq
    from {{ ref('stg_events') }}
    where price > 0 and category_id is not null
    group by 1, 2
),

expanding_prior as (
    select
        category_id,
        d,
        sum(n)                over w as prior_n,
        sum(sum_log_price)    over w as prior_sum_lp,
        sum(sum_log_price_sq) over w as prior_sum_lp_sq
    from category_day
    window w as (
        partition by category_id
        order by d
        rows between unbounded preceding and 1 preceding
    )
)

select
    category_id,
    d,
    prior_n,
    {{ key_round('prior_sum_lp / prior_n') }} as cat_mean_lp,
    {{ key_round('sqrt(greatest(prior_sum_lp_sq / prior_n - (prior_sum_lp / prior_n) * (prior_sum_lp / prior_n), 0))') }} as cat_sd_lp
from expanding_prior
where prior_n >= 50
  and {{ key_round('sqrt(greatest(prior_sum_lp_sq / prior_n - (prior_sum_lp / prior_n) * (prior_sum_lp / prior_n), 0))') }} >= 0.05
