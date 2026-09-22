{{ config(materialized='table') }}

/*
  02's retention curves, at cohort grain.

  Grain / PK: (cohort_month, bucket_day). cohort_month is the month of t0 (the first
  order), so this is a PURCHASE cohort -- CLAUDE.md non-negotiable 1: the primary
  retention metric is purchase retention. Activity retention is reported alongside, as a
  superset, never as the headline.

  DEFINITIONS, both certified in 02 and carried in handoff -> retention_measured:
    purchase retention  share of the cohort placing >= 1 FURTHER ORDER within x days,
                        in a session OTHER THAN the first-order session
    activity retention  same window and same session rule, any event type

  The "different session" rule matters and is audited in 02: repeat orders placed inside
  the first-order session are excluded, because a second checkout in the same session is
  not a return visit.

  CENSORING -- THE RULE THIS TABLE EXISTS TO ENFORCE:
    A cohort contributes to bucket x only if its LAST joiner has at least x trailing days
    of observation. An ineligible (cohort, bucket) cell produces NO ROW. It is never
    zero-filled, and it is never given a partial denominator. That is why eligible_n
    falls as the horizon lengthens: D1-D14 admit four cohorts, D30/D60 three, D90 two.

  The table is ADDITIVE, and deliberately so. The pooled curve 02 publishes is
      sum(purchase_returners) / sum(eligible_n)
  over the rows present at a bucket -- not an average of the cohort rates. Pool that way,
  or the small cohorts get the same weight as the large ones.

  Buckets are READ from handoff -> retention_measured.buckets, not hardcoded.
*/

with data_end as (
    select max(event_time) as data_end_ts from {{ ref('stg_events') }}
),

buckets as (
    select cast(unnest(from_json(json_extract(content, '$.retention_measured.buckets'), '["BIGINT"]')) as INTEGER) as bucket_day
    from read_text('{{ var("handoff_path") }}')
),

base as (
    select
        u.user_id,
        u.first_order_ts,
        u.first_order_session,
        u.first_order_cohort_month as cohort_month
    from {{ ref('dim_users') }} u
    where u.is_purchaser
),

-- Time to the first QUALIFYING return order: a later order, in a different session.
next_order as (
    select
        b.user_id,
        min(date_diff('second', b.first_order_ts, o.order_ts) / 86400.0) as days_to_next_order
    from base b
    join {{ ref('fct_orders') }} o on o.user_id = b.user_id
    where o.order_ts > b.first_order_ts
      and o.user_session <> b.first_order_session
    group by 1
),

-- Time to the first qualifying return EVENT: same window, same session rule, any type.
next_event as (
    select
        b.user_id,
        min(date_diff('second', b.first_order_ts, e.event_time) / 86400.0) as days_to_next_event
    from base b
    join {{ ref('stg_events') }} e on e.user_id = b.user_id
    where e.event_time > b.first_order_ts
      and e.user_session <> b.first_order_session
    group by 1
),

-- Trailing window available to the LAST joiner in each cohort. This, not the average
-- user's window, is what makes a cohort eligible: if the last joiner's window has not
-- closed, the cohort's rate at that bucket is not yet measurable.
cohort_eligibility as (
    select
        b.cohort_month,
        count(*) as cohort_n_users,
        max(b.first_order_ts) as last_joiner_ts,
        date_diff('day', max(b.first_order_ts), (select data_end_ts from data_end)) as min_trailing_days
    from base b
    group by 1
),

user_outcomes as (
    select
        b.cohort_month,
        b.user_id,
        n.days_to_next_order,
        a.days_to_next_event
    from base b
    left join next_order n on n.user_id = b.user_id
    left join next_event a on a.user_id = b.user_id
)

select
    c.cohort_month,
    k.bucket_day,
    c.cohort_n_users,
    c.min_trailing_days,
    count(*)                                                        as eligible_n,
    count(*) filter (where u.days_to_next_order <= k.bucket_day)    as purchase_returners,
    count(*) filter (where u.days_to_next_event <= k.bucket_day)    as activity_returners,
    {{ key_round('100.0 * count(*) filter (where u.days_to_next_order <= k.bucket_day) / count(*)') }} as purchase_retention_pct,
    {{ key_round('100.0 * count(*) filter (where u.days_to_next_event <= k.bucket_day) / count(*)') }} as activity_retention_pct
from cohort_eligibility c
cross join buckets k
join user_outcomes u on u.cohort_month = c.cohort_month
-- THE CENSORING RULE. An ineligible cohort produces no row at this bucket.
where c.min_trailing_days >= k.bucket_day
group by 1, 2, 3, 4
