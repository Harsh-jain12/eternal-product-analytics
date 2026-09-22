{{ config(materialized='table') }}

/*
  THE LEAKAGE-SAFE MODELLING TABLE -- 05's features.parquet, model-eligible columns only.

  Grain / PK: user_id. One row per bot-excluded purchaser (109,732). NOT pre-filtered to
  one horizon: D30, D60 and D90 have three different eligible populations, so a single
  pre-filtered table would force a horizon choice on the consumer. The eligibility flags
  are here and the consumer subsets.

  ANCHOR       t0 = the user's first order timestamp, certified reconstruction rule.
  FEATURES     event_time < t0, plus the first order's own purchase lines at exactly t0.
  OUTCOME      orders with order_ts > t0, in a session other than the first-order session.
  The two windows are disjoint by construction.

  ELIGIBILITY IS IN EXACT ELAPSED SECONDS, not date_diff('day'). date_diff counts
  calendar-boundary crossings, so it promotes users whose window has not closed: at D30
  it admits users the exact rule excludes. A censored user is EXCLUDED, never zero-filled
  -- an unobserved window is not a negative.

  WHAT IS DELIBERATELY NOT HERE (05's forbidden list, handoff -> features.forbidden_list):
    F1  any feature computed from events after t0
    F2  lifetime orders/spend, last-event recency, R/F/M, tenure-to-DATA_END
    F3  product/category popularity or price stats over the full window -- the price
        references this model joins are prior-days-only (int_*_day_price_ref)
    F4  a static cluster label joined from segment_assignments
    F5  any cart-abandonment TYPE label. 02 Section 0E: under the leaky spec
        `deferred_intent` scored OR 10.81; with disjoint classification and outcome
        windows the same type scores BELOW baseline and the ranking inverts. Only
        abandonment VOLUME survives, and that is what pre_cart_not_in_first_order_rate is.
  Also absent, and absent on purpose: t0_calendar_day, is_bulk_buyer_fullhistory and
  pre_segment. 05 persisted those for diagnostics and forbade fitting on them; this table
  is model-eligible columns only, so they are not carried. is_bulk_buyer_fullhistory's
  leakage-safe twin, first_order_is_bulk, IS carried -- 05 found 33 of the 143 bulk
  buyers are flagged on an order placed after t0.

  NOTHING IS IMPUTED. Every NULL is a real absence and every absence has a named
  indicator: fs_has_pre_purchase_events, has_pre_t0_history, has_prior_sessions,
  has_day_cadence, has_session_cadence. A user with one visit has no rhythm; imputing the
  median would assert one.

  DETERMINISM. Every float column is sig_round()ed to 6 significant figures (src.data
  round_sig) and the whole build runs single-threaded (profiles.yml). 05 measured that
  the rounding alone is necessary but NOT sufficient -- a value whose 7th significant
  digit sits within 1e-15 of a rounding boundary flips across the grid, which converts a
  reproducible failure into an intermittent one -- and settled on both guards together.
*/

with data_end as (
    select max(event_time) as data_end_ts from {{ ref('stg_events') }}
),

purchasers as (
    select user_id, first_order_ts as first_ts, first_order_session as first_session,
           first_order_cohort_month as cohort_month
    from {{ ref('dim_users') }}
    where is_purchaser
),

-- ---- target and censoring -----------------------------------------------------------
target as (
    select
        p.user_id,
        p.first_ts,
        p.cohort_month,
        min(date_diff('second', p.first_ts, o.order_ts) / 86400.0) as days_to_next_order,
        date_diff('second', p.first_ts, (select data_end_ts from data_end)) as trailing_seconds
    from purchasers p
    left join {{ ref('fct_orders') }} o
           on o.user_id = p.user_id
          and o.order_ts > p.first_ts
          and o.user_session <> p.first_session
    group by 1, 2, 3
),

-- ---- M1: the first order, at t0 -----------------------------------------------------
m1_primary_brand as (
    select user_id, b as fo_primary_brand
    from (
        select user_id, coalesce(brand, '__NULL__') as b,
               row_number() over (partition by user_id
                                  order by count(*) desc, coalesce(brand, '__NULL__')) as rn
        from {{ ref('int_first_order_lines') }}
        group by 1, 2
    ) where rn = 1
),

m1_primary_category as (
    select user_id, category_id as fo_primary_category
    from (
        select user_id, category_id,
               row_number() over (partition by user_id
                                  order by count(*) desc, category_id) as rn
        from {{ ref('int_first_order_lines') }}
        where category_id is not null
        group by 1, 2
    ) where rn = 1
),

m1_price_ref as (
    select
        l.user_id,
        avg(case when r.prior_max_price > 0 then greatest(1.0 - l.price / r.prior_max_price, 0.0) end) as fo_discount_vs_prior_max,
        avg(case when r.prior_mean_price > 0 then l.price / r.prior_mean_price end)                    as fo_price_vs_prior_mean,
        avg(r.prior_price_pct)                                                                         as fo_product_price_pct_prior,
        count(r.product_id) * 1.0 / count(*)                                                           as fo_price_ref_coverage
    from {{ ref('int_first_order_lines') }} l
    left join {{ ref('int_product_day_price_ref') }} r
           on r.product_id = l.product_id and r.d = l.d
    group by 1
),

m1_cat_z as (
    select
        l.user_id,
        avg(greatest(least((ln(l.price) - c.cat_mean_lp) / c.cat_sd_lp, 5.0), -5.0)) as fo_price_z_in_category,
        count(c.category_id) * 1.0 / count(*)                                        as fo_catz_coverage
    from {{ ref('int_first_order_lines') }} l
    left join {{ ref('int_category_day_price_ref') }} c
           on c.category_id = l.category_id and c.d = l.d
    where l.price > 0
    group by 1
),

m1_agg as (
    select
        user_id,
        max(first_ts)                as ft,
        count(*)                     as fo_n_items,
        count(distinct product_id)   as fo_n_products,
        count(distinct category_id)  as fo_n_categories,
        count(distinct brand)        as fo_n_brands,
        sum(case when price > 0 then price else 0 end) as fo_value,
        max(price)                   as fo_max_price,
        min(price)                   as fo_min_price,
        quantile_cont(price, 0.5)    as fo_median_price,
        avg(case when brand is null then 1.0 else 0.0 end) as fo_brand_null_share
    from {{ ref('int_first_order_lines') }}
    group by 1
),

-- fo_value_w: the winsorised monetary twin. 02's constraint 6 forbids a MEAN-based
-- monetary feature that the 143 bulk buyers can move. The raw value is kept (a tree does
-- not care); this is what any mean or linear term should use. quantile_cont, not
-- approx_quantile -- connect() note 2 measured the sketch at 4.0754 vs 4.0705 for the
-- same median across two runs.
fo_value_p99 as (
    select quantile_cont({{ sig_round('fo_value') }}, 0.99) as v99 from m1_agg
),

bulk_threshold as (
    select param_value as bulk_items_threshold
    from {{ ref('stg_handoff_params') }}
    where json_path = '$.bulk_buyer_segment.threshold_items_per_order'
),

m1 as (
    select
        a.user_id,
        a.fo_n_items, a.fo_n_products, a.fo_n_categories, a.fo_n_brands,
        a.fo_value,
        least({{ sig_round('a.fo_value') }}, (select v99 from fo_value_p99)) as fo_value_w,
        a.fo_max_price, a.fo_min_price, a.fo_median_price,
        a.fo_max_price - a.fo_min_price as fo_price_range,
        a.fo_brand_null_share,
        pb.fo_primary_brand,
        pc.fo_primary_category,
        hour(a.ft)       as fo_hour,
        dayofweek(a.ft)  as fo_dow,
        case when dayofweek(a.ft) in (0, 6) then 1 else 0 end as fo_is_weekend,
        px.fo_discount_vs_prior_max,
        px.fo_price_vs_prior_mean,
        px.fo_product_price_pct_prior,
        px.fo_price_ref_coverage,
        cz.fo_price_z_in_category,
        cz.fo_catz_coverage,
        case when coalesce(px.fo_discount_vs_prior_max, 0) > 1e-9 then 1 else 0 end as fo_has_discount,
        case when a.fo_n_items >= (select bulk_items_threshold from bulk_threshold) then 1 else 0 end as first_order_is_bulk
    from m1_agg a
    left join m1_primary_brand    pb on pb.user_id = a.user_id
    left join m1_primary_category pc on pc.user_id = a.user_id
    left join m1_price_ref        px on px.user_id = a.user_id
    left join m1_cat_z            cz on cz.user_id = a.user_id
),

-- ---- M2: the first-order session, TRUNCATED AT t0 -----------------------------------
-- fs_ended_in_purchase is not here: it is TRUE for 100% of purchasers by the definition
-- of t0, so it carries zero information and would consume a degree of freedom in a
-- nested LR test. Same for fs_purchase_before_t0, constant at 0. 05 dropped both.
m2_entry as (
    select user_id, event_type as fs_entry_event_type
    from (
        select user_id, event_type,
               row_number() over (
                   partition by user_id
                   order by event_time, event_type, product_id,
                            {{ key_round('price') }}, category_id
               ) as rn
        from {{ ref('int_pre_t0_events') }}
        where is_first_order_session
    ) where rn = 1
),

m2_agg as (
    select
        user_id,
        min(event_time) as fs_start,
        max(first_ts)   as ft,
        count(*)                                                as fs_n_events,
        count(*) filter (where event_type = 'view')             as fs_n_view_ev,
        count(*) filter (where event_type = 'cart')             as fs_n_cart_ev,
        count(*) filter (where event_type = 'remove_from_cart') as fs_n_removals,
        count(distinct product_id) filter (where event_type = 'view') as fs_p_viewed,
        count(distinct product_id)  as fs_p_touched,
        count(distinct category_id) as fs_n_categories,
        count(distinct brand)       as fs_n_brands,
        max(price) filter (where event_type = 'view' and price > 0) as fs_max_price_viewed,
        quantile_cont(price, 0.9) filter (where event_type = 'view' and price > 0)
          - quantile_cont(price, 0.1) filter (where event_type = 'view' and price > 0) as fs_price_range_viewed
    from {{ ref('int_pre_t0_events') }}
    where is_first_order_session
    group by 1
),

m2 as (
    select
        a.user_id,
        a.fs_n_events, a.fs_n_view_ev, a.fs_n_cart_ev, a.fs_n_removals,
        a.fs_p_viewed, a.fs_p_touched, a.fs_n_categories, a.fs_n_brands,
        a.fs_max_price_viewed,
        greatest(a.fs_price_range_viewed, 0) as fs_price_range_viewed,
        date_diff('second', a.fs_start, a.ft) / 60.0 as fs_duration_min,
        hour(a.fs_start)      as fs_start_hour,
        dayofweek(a.fs_start) as fs_start_dow,
        e.fs_entry_event_type
    from m2_agg a
    left join m2_entry e on e.user_id = a.user_id
),

-- ---- M3: everything known before t0 -------------------------------------------------
-- Defined over ALL pre-t0 events, not over PRIOR SESSIONS only: 05 found 33.6% of
-- purchasers have no session before the one they bought in, so the disjoint definition
-- would leave a third of the population with an empty M3 block.
m3_counts as (
    select
        user_id,
        count(*)                                                as pre_n_events,
        count(*) filter (where event_type = 'view')             as pre_n_view_ev,
        count(*) filter (where event_type = 'cart')             as pre_n_cart_ev,
        count(*) filter (where event_type = 'remove_from_cart') as pre_n_removals,
        count(distinct product_id)                              as pre_n_products,
        count(distinct product_id) filter (where event_type = 'view') as pre_p_viewed,
        count(distinct product_id) filter (where event_type = 'cart') as pre_p_carted,
        count(distinct category_id) as pre_n_categories,
        count(distinct brand)       as pre_n_brands,
        count(distinct event_date)  as pre_n_active_days,
        min(event_time) as first_event_ts,
        max(event_time) as last_pre_event_ts,
        max(first_ts)   as ft
    from {{ ref('int_pre_t0_events') }}
    group by 1
),

m3_sessions as (
    select
        user_id,
        count(*) as pre_n_sessions,
        sum(case when is_first_order_session = 0 then 1 else 0 end) as pre_n_prior_sessions,
        avg(n_ev) as pre_mean_session_depth
    from {{ ref('int_pre_t0_sessions') }}
    group by 1
),

-- Abandonment VOLUME, the only abandonment signal 02 Section 0E left standing.
-- NOT the abandonment TYPE, which is the F5 violation.
-- 05 also replaced 04's cart_abandonment_rate here: there are ZERO purchases before t0,
-- so that feature is a constant 1.0 in a strictly-pre-t0 window. This one is not
-- degenerate -- it asks which pre-t0 carted products did NOT make the first order.
m3_first_order_products as (
    select distinct user_id, product_id from {{ ref('int_first_order_lines') }}
),
m3_pre_cart_products as (
    select distinct user_id, product_id from {{ ref('int_pre_t0_events') }} where event_type = 'cart'
),
m3_abandonment as (
    select
        c.user_id,
        1.0 - count(f.product_id) * 1.0 / count(*) as pre_cart_not_in_first_order_rate
    from m3_pre_cart_products c
    left join m3_first_order_products f on f.user_id = c.user_id and f.product_id = c.product_id
    group by 1
),

m3_brand_entropy as (
    select
        user_id,
        -sum(pr * log2(pr)) as pre_brand_entropy,
        coalesce(sum(c) filter (where lvl <> '__NULL__'), 0) * 1.0 / sum(c) as pre_brand_coverage
    from (
        select user_id, lvl, c, c * 1.0 / sum(c) over (partition by user_id) as pr
        from (
            select user_id, coalesce(brand, '__NULL__') as lvl, count(*) as c
            from {{ ref('int_pre_t0_events') }} where event_type = 'view' group by 1, 2
        )
    ) group by 1
),

m3_category_entropy as (
    select user_id, -sum(pr * log2(pr)) as pre_category_entropy
    from (
        select user_id, lvl, c, c * 1.0 / sum(c) over (partition by user_id) as pr
        from (
            select user_id, category_id as lvl, count(*) as c
            from {{ ref('int_pre_t0_events') }}
            where event_type = 'view' and category_id is not null group by 1, 2
        )
    ) group by 1
),

m3_price_pct as (
    select
        p.user_id,
        avg(r.prior_price_pct) as pre_mean_price_pct_viewed,
        quantile_cont(r.prior_price_pct, 0.9) - quantile_cont(r.prior_price_pct, 0.1) as pre_price_range_viewed
    from {{ ref('int_pre_t0_events') }} p
    join {{ ref('int_product_day_price_ref') }} r
      on r.product_id = p.product_id and r.d = p.event_date
    where p.event_type = 'view'
    group by 1
),

m3 as (
    select
        cn.user_id,
        cn.pre_n_events, cn.pre_n_view_ev, cn.pre_n_cart_ev, cn.pre_n_removals,
        ln(1 + cn.pre_n_removals) as log1p_pre_n_removals,
        cn.pre_n_products, cn.pre_p_viewed, cn.pre_p_carted,
        cn.pre_n_categories, cn.pre_n_brands, cn.pre_n_active_days,
        date_diff('second', cn.first_event_ts,    cn.ft) / 86400.0 as tenure_d,
        date_diff('second', cn.last_pre_event_ts, cn.ft) / 86400.0 as pre_days_since_last_event,
        ss.pre_n_sessions,
        ss.pre_n_prior_sessions,
        case when coalesce(ss.pre_n_prior_sessions, 0) > 0 then 1 else 0 end as has_prior_sessions,
        ss.pre_mean_session_depth,
        cn.pre_p_carted * 1.0 / nullif(cn.pre_p_viewed, 0)    as pre_view_to_cart,
        cn.pre_n_removals * 1.0 / nullif(cn.pre_n_cart_ev, 0) as pre_removal_per_cart,
        ab.pre_cart_not_in_first_order_rate,
        be.pre_brand_entropy, be.pre_brand_coverage, ce.pre_category_entropy,
        pp.pre_mean_price_pct_viewed, pp.pre_price_range_viewed,
        -- 04 Section 9C's confound, carried explicitly instead of left implicit: every
        -- raw pre-t0 count is strongly tenure-driven, so each gets a per-tenure-day twin
        -- and BOTH forms are in the table. The floor is one minute, so a same-minute
        -- first order cannot divide by zero.
        cn.pre_n_view_ev  / greatest({{ sig_round("date_diff('second', cn.first_event_ts, cn.ft) / 86400.0") }}, 1.0/1440.0) as pre_views_per_tenure_day,
        ss.pre_n_sessions / greatest({{ sig_round("date_diff('second', cn.first_event_ts, cn.ft) / 86400.0") }}, 1.0/1440.0) as pre_sessions_per_tenure_day,
        cn.pre_n_events   / greatest({{ sig_round("date_diff('second', cn.first_event_ts, cn.ft) / 86400.0") }}, 1.0/1440.0) as pre_events_per_tenure_day,
        cn.pre_n_products / greatest({{ sig_round("date_diff('second', cn.first_event_ts, cn.ft) / 86400.0") }}, 1.0/1440.0) as pre_products_per_tenure_day
    from m3_counts cn
    left join m3_sessions         ss on ss.user_id = cn.user_id
    left join m3_abandonment      ab on ab.user_id = cn.user_id
    left join m3_brand_entropy    be on be.user_id = cn.user_id
    left join m3_category_entropy ce on ce.user_id = cn.user_id
    left join m3_price_pct        pp on pp.user_id = cn.user_id
),

-- ---- M4: cadence, and its honest limit ----------------------------------------------
-- PURCHASE cadence is NOT here, and cannot be: at a first-order anchor every user has
-- exactly one order, so the quantity does not exist for 100% of users. That is not
-- missingness. 04 Section 9B asked for a personalised purchase-cadence threshold; the
-- test that would settle it is a re-anchor on the SECOND order predicting the third.
-- What is measurable before t0 is VISIT cadence, and that is what this block carries.
m4_session_gaps as (
    select
        user_id, user_session, s_start,
        date_diff('second',
                  lag(s_start) over (partition by user_id order by s_start, user_session),
                  s_start) / 86400.0 as gap_d,
        row_number() over (partition by user_id order by s_start desc, user_session desc) as rn_desc
    from {{ ref('int_pre_t0_sessions') }}
),

m4_session_hist as (
    select
        user_id,
        count(*) as cad_n_hist_gaps,
        quantile_cont(gap_d, 0.5) as cad_median_gap_d,
        quantile_cont(gap_d, 0.75) - quantile_cont(gap_d, 0.25) as cad_iqr_gap_d
    from m4_session_gaps
    where gap_d is not null and rn_desc > 1
    group by 1
),

m4_last_gap as (
    select user_id, gap_d as gap_before_purchase_visit
    from m4_session_gaps where rn_desc = 1
),

m4_day_gaps as (
    select
        user_id, dday,
        date_diff('day', lag(dday) over (partition by user_id order by dday), dday) as gap,
        row_number() over (partition by user_id order by dday desc) as rn_desc
    from (select distinct user_id, event_date as dday from {{ ref('int_pre_t0_events') }})
),

m4_day_hist as (
    select
        user_id,
        count(*) filter (where gap is not null and rn_desc > 1) as cad_day_n_hist_gaps,
        quantile_cont(gap, 0.5) filter (where gap is not null and rn_desc > 1) as cad_day_median_gap_d,
        max(gap) filter (where rn_desc = 1) as gap_before_purchase_day
    from m4_day_gaps
    group by 1
),

m4 as (
    select
        coalesce(h.user_id, dh.user_id) as user_id,
        h.cad_n_hist_gaps, h.cad_median_gap_d, h.cad_iqr_gap_d,
        l.gap_before_purchase_visit,
        dh.cad_day_n_hist_gaps, dh.cad_day_median_gap_d, dh.gap_before_purchase_day,
        case when h.cad_median_gap_d is not null then 1 else 0 end          as has_session_cadence,
        case when coalesce(dh.cad_day_n_hist_gaps, 0) > 0 then 1 else 0 end as has_day_cadence,
        -- The floor is a floor, not a fallback: SQL's greatest() ignores NULLs, so a
        -- bare greatest(median, EPS) would hand a user with NO cadence a denominator of
        -- EPS and invent a lapse ratio for them. 11,718 users have a gap before the
        -- purchase visit but no day cadence to measure it against; their ratio stays
        -- NULL, and has_day_cadence / has_session_cadence say why.
        {{ sig_round('l.gap_before_purchase_visit') }}
            / (case when h.cad_median_gap_d is null then null
                    else greatest({{ sig_round('h.cad_median_gap_d') }}, 1.0/1440.0) end) as cad_lapse_ratio,
        {{ sig_round('dh.gap_before_purchase_day') }}
            / (case when dh.cad_day_median_gap_d is null then null
                    else greatest({{ sig_round('dh.cad_day_median_gap_d') }}, 1.0) end)   as cad_day_lapse_ratio,
        {{ sig_round('h.cad_iqr_gap_d') }}
            / (case when h.cad_median_gap_d is null then null
                    else greatest({{ sig_round('h.cad_median_gap_d') }}, 1.0/1440.0) end) as cad_regularity
    from m4_day_hist dh
    full outer join m4_session_hist h on h.user_id = dh.user_id
    left join m4_last_gap l on l.user_id = coalesce(h.user_id, dh.user_id)
    where h.user_id is not null or dh.cad_day_n_hist_gaps > 0
)

select
    t.user_id,
    t.first_ts,
    t.cohort_month,
    {{ sig_round('t.trailing_seconds / 86400.0') }} as trailing_days,
    {{ sig_round('t.days_to_next_order') }}         as days_to_next_order,

    -- eligibility in EXACT ELAPSED SECONDS; censored users are excluded by the consumer,
    -- never zero-filled
    t.trailing_seconds >= 30 * 86400 as eligible_30d,
    t.trailing_seconds >= 60 * 86400 as eligible_60d,
    t.trailing_seconds >= 90 * 86400 as eligible_90d,
    coalesce(t.days_to_next_order <= 30, false) as repeat_purchase_30d,
    coalesce(t.days_to_next_order <= 60, false) as repeat_purchase_60d,
    coalesce(t.days_to_next_order <= 90, false) as repeat_purchase_90d,

    -- ---- M1 first order (24) --------------------------------------------------------
    {{ sig_round('m1.fo_value') }}                   as fo_value,
    {{ sig_round('m1.fo_value_w') }}                 as fo_value_w,
    m1.fo_n_items, m1.fo_n_products, m1.fo_n_categories, m1.fo_n_brands,
    {{ sig_round('m1.fo_brand_null_share') }}        as fo_brand_null_share,
    {{ sig_round('m1.fo_max_price') }}               as fo_max_price,
    {{ sig_round('m1.fo_min_price') }}               as fo_min_price,
    {{ sig_round('m1.fo_median_price') }}            as fo_median_price,
    {{ sig_round('m1.fo_price_range') }}             as fo_price_range,
    m1.fo_hour, m1.fo_dow, m1.fo_is_weekend,
    {{ sig_round('m1.fo_discount_vs_prior_max') }}   as fo_discount_vs_prior_max,
    {{ sig_round('m1.fo_price_vs_prior_mean') }}     as fo_price_vs_prior_mean,
    {{ sig_round('m1.fo_product_price_pct_prior') }} as fo_product_price_pct_prior,
    {{ sig_round('m1.fo_price_ref_coverage') }}      as fo_price_ref_coverage,
    {{ sig_round('m1.fo_price_z_in_category') }}     as fo_price_z_in_category,
    {{ sig_round('m1.fo_catz_coverage') }}           as fo_catz_coverage,
    m1.fo_has_discount,
    m1.first_order_is_bulk,
    -- HIGH-CARDINALITY. Target- or frequency-encode INSIDE the training fold; a
    -- full-table encoding is an F3 violation.
    m1.fo_primary_brand,
    m1.fo_primary_category,

    -- ---- M2 first-order session, truncated at t0 (15) -------------------------------
    m2.fs_n_events, m2.fs_n_view_ev, m2.fs_n_cart_ev, m2.fs_n_removals,
    m2.fs_p_viewed, m2.fs_p_touched, m2.fs_n_categories, m2.fs_n_brands,
    {{ sig_round('m2.fs_max_price_viewed') }}   as fs_max_price_viewed,
    {{ sig_round('m2.fs_price_range_viewed') }} as fs_price_range_viewed,
    {{ sig_round('m2.fs_duration_min') }}       as fs_duration_min,
    m2.fs_start_hour, m2.fs_start_dow,
    m2.fs_entry_event_type,
    case when m2.fs_n_events is not null then 1 else 0 end as fs_has_pre_purchase_events,

    -- ---- M3 pre-t0 browsing (30) ----------------------------------------------------
    m3.pre_n_events, m3.pre_n_view_ev, m3.pre_n_cart_ev, m3.pre_n_removals,
    {{ sig_round('m3.log1p_pre_n_removals') }} as log1p_pre_n_removals,
    m3.pre_n_products, m3.pre_p_viewed, m3.pre_p_carted,
    m3.pre_n_categories, m3.pre_n_brands, m3.pre_n_active_days,
    m3.pre_n_sessions, m3.pre_n_prior_sessions, coalesce(m3.has_prior_sessions, 0) as has_prior_sessions,
    {{ sig_round('m3.pre_mean_session_depth') }}             as pre_mean_session_depth,
    {{ sig_round('m3.pre_view_to_cart') }}                   as pre_view_to_cart,
    {{ sig_round('m3.pre_removal_per_cart') }}               as pre_removal_per_cart,
    {{ sig_round('m3.pre_cart_not_in_first_order_rate') }}   as pre_cart_not_in_first_order_rate,
    {{ sig_round('m3.pre_brand_entropy') }}                  as pre_brand_entropy,
    {{ sig_round('m3.pre_brand_coverage') }}                 as pre_brand_coverage,
    {{ sig_round('m3.pre_category_entropy') }}               as pre_category_entropy,
    {{ sig_round('m3.pre_mean_price_pct_viewed') }}          as pre_mean_price_pct_viewed,
    {{ sig_round('m3.pre_price_range_viewed') }}             as pre_price_range_viewed,
    {{ sig_round('m3.tenure_d') }}                           as tenure_d,
    -- NOT a recency feature: 05 measured the median at ~1 minute, because almost every
    -- user's last pre-t0 event is a click in the buying session seconds before the order.
    -- It measures checkout speed. gap_before_purchase_visit carries real pre-purchase recency.
    {{ sig_round('m3.pre_days_since_last_event') }}          as pre_days_since_last_event,
    {{ sig_round('m3.pre_views_per_tenure_day') }}           as pre_views_per_tenure_day,
    {{ sig_round('m3.pre_sessions_per_tenure_day') }}        as pre_sessions_per_tenure_day,
    {{ sig_round('m3.pre_events_per_tenure_day') }}          as pre_events_per_tenure_day,
    {{ sig_round('m3.pre_products_per_tenure_day') }}        as pre_products_per_tenure_day,
    case when m3.pre_n_events is not null then 1 else 0 end  as has_pre_t0_history,

    -- ---- M4 cadence (12) ------------------------------------------------------------
    m4.cad_n_hist_gaps,
    {{ sig_round('m4.cad_median_gap_d') }}          as cad_median_gap_d,
    {{ sig_round('m4.cad_iqr_gap_d') }}             as cad_iqr_gap_d,
    {{ sig_round('m4.cad_regularity') }}            as cad_regularity,
    {{ sig_round('m4.gap_before_purchase_visit') }} as gap_before_purchase_visit,
    {{ sig_round('m4.cad_lapse_ratio') }}           as cad_lapse_ratio,
    coalesce(m4.has_session_cadence, 0)             as has_session_cadence,
    m4.cad_day_n_hist_gaps,
    {{ sig_round('m4.cad_day_median_gap_d') }}      as cad_day_median_gap_d,
    {{ sig_round('m4.gap_before_purchase_day') }}   as gap_before_purchase_day,
    {{ sig_round('m4.cad_day_lapse_ratio') }}       as cad_day_lapse_ratio,
    coalesce(m4.has_day_cadence, 0)                 as has_day_cadence

from target t
left join m1 on m1.user_id = t.user_id
left join m2 on m2.user_id = t.user_id
left join m3 on m3.user_id = t.user_id
left join m4 on m4.user_id = t.user_id
