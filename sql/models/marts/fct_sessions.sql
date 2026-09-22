{{ config(materialized='table') }}

/*
  Session grain, from 01's session_table.

  Grain / PK: (user_id, user_session). The composite key is the point -- user_session is
  NOT unique on its own in this data (00's audit: session-ID reuse, sessions_over_24h at
  2.16%, max span the entire five-month window), so every session-scoped join in this
  project keys on both columns.

  FUNNEL FLAGS AT TWO GRAINS, which is what 01's "raw vs deduplicated" comparison is:
    - n_*_events        raw event rows per stage
    - n_products_*      DISTINCT products per stage, session-scoped
  The second is the deduplicated funnel. 00's audit forbids dropping the duplicate rows
  themselves (they are real repeated actions at 1-second resolution), so deduplication
  lives here, as a grain, rather than in stg_events as a filter.

  stage_code is the furthest stage the session reached: 0 view, 1 remove_from_cart,
  2 cart, 3 purchase -- 01's encoding, kept so the funnel is orderable.

  first_* carries the session's entry item. The row_number ORDER BY covers every column
  projected, so the winning row is a function of the data only: ORDER BY event_time alone
  is NOT a total order inside a session (a session logs many events in the same second),
  and the float in the key is key_round()ed before it is used as one (RC-1).

  session_seq / is_first_time_session: ordered by (session_start, user_session), a total
  order, so "the user's first session" cannot move between runs.
*/

with events as (
    select * from {{ ref('stg_events') }}
),

session_agg as (
    select
        user_id,
        user_session,
        min(event_time) as session_start,
        max(event_time) as session_end,
        count(*)                                                      as n_events,
        count(*) filter (where event_type = 'view')                   as n_view_events,
        count(*) filter (where event_type = 'cart')                   as n_cart_events,
        count(*) filter (where event_type = 'remove_from_cart')       as n_removal_events,
        count(*) filter (where event_type = 'purchase')               as n_purchase_events,
        count(distinct product_id) filter (where event_type = 'view')     as n_products_viewed,
        count(distinct product_id) filter (where event_type = 'cart')     as n_products_carted,
        count(distinct product_id) filter (where event_type = 'remove_from_cart') as n_products_removed,
        count(distinct product_id) filter (where event_type = 'purchase') as n_products_purchased,
        count(distinct product_id)                                    as n_products_touched,
        count(distinct category_id)                                   as n_categories,
        count(distinct brand)                                         as n_brands,
        max(case event_type
                when 'purchase'         then 3
                when 'cart'             then 2
                when 'remove_from_cart' then 1
                else 0 end)                                           as stage_code,
        bool_or(event_type = 'purchase')                              as converted,
        {{ key_round("sum(case when event_type = 'purchase' and price > 0 then price else 0 end)") }} as purchase_revenue
    from events
    group by 1, 2
),

session_first_item as (
    select user_id, user_session, product_id, price, brand, category_id
    from (
        select
            user_id, user_session, product_id, price, brand, category_id,
            row_number() over (
                partition by user_id, user_session
                order by event_time, product_id, event_type,
                         {{ key_round('price') }}, category_id,
                         coalesce(brand, '~~NULL~~')
            ) as rn
        from events
    )
    where rn = 1
)

select
    a.user_id,
    a.user_session,
    a.session_start,
    a.session_end,
    cast(date_trunc('day', a.session_start) as DATE) as session_date,
    row_number() over (partition by a.user_id order by a.session_start, a.user_session) as session_seq,
    row_number() over (partition by a.user_id order by a.session_start, a.user_session) = 1 as is_first_time_session,
    case when row_number() over (partition by a.user_id order by a.session_start, a.user_session) = 1
         then 'first_time' else 'returning' end as user_type,
    a.n_events,
    a.n_view_events,
    a.n_cart_events,
    a.n_removal_events,
    a.n_purchase_events,
    a.n_products_viewed,
    a.n_products_carted,
    a.n_products_removed,
    a.n_products_purchased,
    a.n_products_touched,
    a.n_categories,
    a.n_brands,
    a.n_view_events    > 0 as has_view,
    a.n_cart_events    > 0 as has_cart,
    a.n_removal_events > 0 as has_removal,
    a.converted,
    a.stage_code,
    a.purchase_revenue,
    case when a.n_events = 1              then '1'
         when a.n_events between 2 and 3  then '2-3'
         when a.n_events between 4 and 6  then '4-6'
         when a.n_events between 7 and 10 then '7-10'
         else '11+' end as session_depth_bucket,
    {{ key_round("date_diff('second', a.session_start, a.session_end) / 60.0") }} as session_duration_min,
    -- 00's sessions_over_24h rule, carried as a flag rather than a filter: these are
    -- session-ID reuse, not one continuous visit, and anything that treats a session as
    -- a visit should be able to see them.
    date_diff('second', a.session_start, a.session_end) > 86400 as is_over_24h,
    f.product_id  as first_product_id,
    f.price       as first_price,
    f.brand       as first_brand,
    f.category_id as first_category_id
from session_agg a
left join session_first_item f
       on f.user_id = a.user_id and f.user_session = a.user_session
