{{ config(materialized='table') }}

/*
  The one typed, cleaned event table every other model reads. Equivalent to the `ev`
  relation that 01-05 build (src/data.py: load_raw_events -> drop_null_sessions ->
  exclude_users).

  APPLIED HERE, and nowhere else:
    - null_user_session   (00 audit, 0.0222% of rows) -- dropped. Every session-scoped
      join in this project keys on (user_id, user_session), so these rows cannot
      participate in a session, order or funnel figure.
    - bot exclusion       (01, handoff -> bot_exclusion) -- 1,605 users removed.

  DELIBERATELY NOT APPLIED -- row-level deduplication:
    00's audit rule `exact_duplicate_rows_all_events` covers 10.41% of rows and its
    certified implication is "Kept as-is. Do not dedupe view/cart/remove_from_cart rows
    -- would silently drop real repeated user actions logged at 1-second resolution."
    `duplicate_purchase_line_items` (0.07%) is likewise kept: REES46 logs one row per
    unit, so a repeated purchase line is most plausibly quantity > 1, and dropping it
    would silently discard quantity from basket size and revenue.

    Deduplication in this project is a GRAIN, not a cleaning step: the deduplicated
    funnel counts distinct (user_id, user_session, product_id) per stage. fct_sessions
    carries those counts. Dedupe there, not here.

  Nothing else is filtered. Negative-price and zero-price rows are kept as events and
  excluded inside the monetary aggregates that must not see them (00 audit).
*/

select
    cast(user_id      as BIGINT)    as user_id,
    cast(user_session as VARCHAR)   as user_session,
    cast(event_time   as TIMESTAMP) as event_time,
    cast(event_type   as VARCHAR)   as event_type,
    cast(product_id   as BIGINT)    as product_id,
    cast(category_id  as BIGINT)    as category_id,
    cast(category_code as VARCHAR)  as category_code,
    cast(brand        as VARCHAR)   as brand,
    cast(price        as DOUBLE)    as price,
    cast(date_trunc('day', event_time) as DATE) as event_date
from read_csv_auto('{{ var("raw_events_glob") }}')
where user_session is not null
  and user_id not in (select user_id from {{ ref('stg_bot_users') }})
