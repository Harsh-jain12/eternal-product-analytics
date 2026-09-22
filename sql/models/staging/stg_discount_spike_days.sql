{{ config(materialized='table') }}

/*
  02 Section 4's discount-spike detector, reproduced verbatim.

  Grain: one row per calendar day in the observation window.

  The rule is given NO calendar input. It compares each purchased line's price to that
  product's own median price across the window, averages the resulting shortfall per day,
  and flags days above median + 3 * 1.4826 * MAD of that daily series. It independently
  isolates Black Friday week -- which is why 02 renamed the flag from `is_promo`: every
  detected day falls inside one trading week, so this identifies the BLACK FRIDAY COHORT,
  not promotional acquisition in general.

  Determinism: quantile_cont, never approx_quantile (connect() note 2). `intensity` is an
  avg() -- a parallel float reduction -- AND it is a bucketing key here, compared against
  the MAD cut, so it is key_round()ed before the comparison (connect() note 4). The
  separation is wide (0.066 at the bottom of the spike set against 0.0086 for the next
  day), so rounding changes no membership; it is applied because the rule requires it,
  not because this case is close.
*/

with product_ref_price as (
    select
        product_id,
        quantile_cont(price, 0.5) as ref_price
    from {{ ref('stg_events') }}
    where price > 0
    group by 1
),

purchase_lines as (
    select product_id, price, event_date
    from {{ ref('stg_events') }}
    where event_type = 'purchase' and price > 0
),

daily as (
    select
        p.event_date as spike_date,
        {{ key_round('avg(greatest(0.0, (r.ref_price - p.price) / r.ref_price))') }} as intensity,
        count(*) as n_lines
    from purchase_lines p
    join product_ref_price r using (product_id)
    where r.ref_price > 0
    group by 1
),

cut as (
    select
        quantile_cont(intensity, 0.5) as med,
        quantile_cont(abs(intensity - (select quantile_cont(intensity, 0.5) from daily)), 0.5) as mad
    from daily
),

threshold as (
    select med, mad, {{ key_round('med + 3 * 1.4826 * mad') }} as spike_cut
    from cut
)

select
    d.spike_date,
    d.intensity,
    d.n_lines,
    t.spike_cut,
    d.intensity > t.spike_cut as is_spike
from daily d
cross join threshold t
