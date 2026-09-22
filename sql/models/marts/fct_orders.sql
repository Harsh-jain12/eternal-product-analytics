{{ config(materialized='table') }}

/*
  THE CERTIFIED ORDER-RECONSTRUCTION RULE. REES46 has no order_id; orders are
  reconstructed, and this is the rule 00 certified and every notebook from 01 onward
  uses. It is reproduced verbatim from src/data.py CERTIFIED_ORDER_RULE_SQL.

      GROUP BY (user_id, user_session, event_time) on event_type = 'purchase' rows

  Certified because 98.1% of multi-purchase-row sessions share one identical purchase
  timestamp across all their purchase rows. The rejected alternative -- one order per
  user_session -- produces implausible order spans (up to the full dataset window)
  because session ids are reused; 00's audit records sessions_over_24h at 2.16%.

  Grain / PK: (user_id, user_session, order_ts). NOT (user_id, order_ts): 5 user+timestamp
  pairs carry two orders in different sessions, and 08 measured the consequence of
  dropping user_session from the key -- user 423015615 has two orders at the same second
  worth EUR 378.35 and EUR 401.45, and which one counted as "the second order" moved the
  AOV that the sample-size calculation was built on. Every "Nth order" in this layer is
  chosen on the FULL certified key.

  round(sum(price), 6): sum() is a parallel float reduction, so order_value differed in
  its last bit on 10 of 158,399 orders between two clean runs. Cosmetic as a value, not
  cosmetic the moment anything sorts or buckets on it. Rounded here, once, at the same
  precision as the notebooks, so this table and data/processed/orders.parquet cannot
  disagree.

  count(*), not count(DISTINCT product_id), for n_items: 00's audit records that REES46
  logs one row per unit, so a repeated purchase line is quantity, not noise.
*/

with orders as (
    select
        user_id,
        user_session,
        event_time                    as order_ts,
        count(*)                      as n_items,
        {{ key_round('sum(price)') }} as order_value
    from {{ ref('stg_events') }}
    where event_type = 'purchase'
    group by user_id, user_session, event_time
)

select
    user_id,
    user_session,
    order_ts,
    cast(date_trunc('day', order_ts) as DATE) as order_date,
    n_items,
    order_value,
    -- The ORDER BY is the full certified key, so it is a TOTAL order within a user and
    -- order_seq is a function of the data alone.
    row_number() over (partition by user_id order by order_ts, user_session) as order_seq
from orders
