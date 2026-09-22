{{ config(materialized='table') }}

/*
  The project-wide bot exclusion, certified in 01 and recorded in
  handoff_params.json -> bot_exclusion.

  Rule: sessions per ACTIVE DAY (a rate, not a raw count) above the exact 99.9th
  percentile of the real distribution. A generic Tukey far-outlier fence on raw session
  count was tested in 01 and rejected -- it over-flagged ordinary repeat shoppers.

  The threshold is READ from the handoff, not re-derived and not hardcoded.

  This model keeps what the rule removes, rather than only who: the per-user event,
  purchase-line and order counts here are what mart_reconciliation adds back to recover
  00's pre-exclusion totals and to check the three published exclusion shares.
*/

with threshold as (
    select param_value as sess_per_active_day_threshold
    from {{ ref('stg_handoff_params') }}
    where json_path = '$.bot_exclusion.threshold'
),

-- The null_user_session rule from 00's audit is applied first and only here: every
-- session-scoped join in this project keys on (user_id, user_session), so a row without
-- a session cannot participate. It is excluded once, at the source.
session_valid_events as (
    select
        user_id,
        user_session,
        event_time,
        event_type,
        price
    from read_csv_auto('{{ var("raw_events_glob") }}')
    where user_session is not null
),

per_user as (
    select
        user_id,
        count(*)                                                   as n_events,
        count(distinct user_session)                               as n_sessions,
        count(distinct date_trunc('day', event_time))              as n_active_days,
        count(*) filter (where event_type = 'purchase')            as n_purchase_rows
    from session_valid_events
    group by 1
),

-- RC-1 / connect() note 4: sess_per_active_day is a BUCKETING KEY -- it is compared to
-- the certified threshold, and a last-bit wobble at the boundary would move a user in or
-- out of the exclusion list. Round the key BEFORE it is used as one.
rated as (
    select
        user_id,
        n_events,
        n_sessions,
        n_active_days,
        n_purchase_rows,
        {{ key_round('n_sessions * 1.0 / n_active_days') }} as sess_per_active_day
    from per_user
),

flagged as (
    select r.*
    from rated r
    cross join threshold t
    where r.sess_per_active_day > t.sess_per_active_day_threshold
),

-- Orders under the CERTIFIED rule, counted for the excluded users only, so the
-- pre-exclusion order total can be reconstructed without materialising a second
-- bot-inclusive event table.
bot_orders as (
    select user_id, count(*) as n_orders
    from (
        select e.user_id
        from session_valid_events e
        join flagged f on f.user_id = e.user_id
        where e.event_type = 'purchase'
        group by e.user_id, e.user_session, e.event_time
    )
    group by 1
)

select
    f.user_id,
    f.n_events,
    f.n_sessions,
    f.n_active_days,
    f.sess_per_active_day,
    f.n_purchase_rows,
    coalesce(o.n_orders, 0) as n_orders
from flagged f
left join bot_orders o on o.user_id = f.user_id
