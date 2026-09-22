{{ config(materialized='table') }}

/*
  Every certified constant this layer inherits, READ from outputs/handoff_params.json at
  build time -- never hardcoded, and never re-derived (CLAUDE.md working conventions:
  "use what 00 certified, or explicitly say why you're overriding it").

  Grain: one row per json path. `json_path` IS the audit trail -- any test or model that
  reads a constant names the path it read, and mart_reconciliation carries that path into
  its output so a failing check says which handoff key it disagreed with.
*/

with doc as (
    select content as j from read_text('{{ var("handoff_path") }}')
),

paths(json_path, purpose) as (
    values
    -- ---- 00: shape of the raw data -------------------------------------------------
    ('$.row_counts.total_events',                        'raw event rows, before any cleaning rule'),
    ('$.row_counts.n_orders',                            'orders under the certified rule, BEFORE bot exclusion'),
    ('$.row_counts.n_purchasing_users',                  'purchasers BEFORE bot exclusion'),
    ('$.row_counts.n_users_any_event',                   'distinct user_id in the raw CSVs'),
    ('$.data_date_range.span_days',                      'observation window length in days'),
    -- ---- 01: bot exclusion, applied project-wide -----------------------------------
    ('$.bot_exclusion.threshold',                        'sessions per active day above which a user is excluded'),
    ('$.bot_exclusion.n_users_excluded',                 'users the rule removes'),
    ('$.bot_exclusion.share_of_events_pct',              'share of session-valid events removed'),
    ('$.bot_exclusion.share_of_purchase_rows_pct',       'share of purchase LINES removed'),
    ('$.bot_exclusion.share_of_orders_pct',              'share of ORDERS removed'),
    -- ---- 02: retention, cohorts, bulk buyers, Black Friday -------------------------
    ('$.retention_measured.purchase_retention_pct.d1',   'pooled purchase retention, D1'),
    ('$.retention_measured.purchase_retention_pct.d3',   'pooled purchase retention, D3'),
    ('$.retention_measured.purchase_retention_pct.d7',   'pooled purchase retention, D7'),
    ('$.retention_measured.purchase_retention_pct.d14',  'pooled purchase retention, D14'),
    ('$.retention_measured.purchase_retention_pct.d30',  'pooled purchase retention, D30'),
    ('$.retention_measured.purchase_retention_pct.d60',  'pooled purchase retention, D60'),
    ('$.retention_measured.purchase_retention_pct.d90',  'pooled purchase retention, D90'),
    ('$.retention_measured.activity_retention_pct.d1',   'pooled activity retention, D1'),
    ('$.retention_measured.activity_retention_pct.d3',   'pooled activity retention, D3'),
    ('$.retention_measured.activity_retention_pct.d7',   'pooled activity retention, D7'),
    ('$.retention_measured.activity_retention_pct.d14',  'pooled activity retention, D14'),
    ('$.retention_measured.activity_retention_pct.d30',  'pooled activity retention, D30'),
    ('$.retention_measured.activity_retention_pct.d60',  'pooled activity retention, D60'),
    ('$.retention_measured.activity_retention_pct.d90',  'pooled activity retention, D90'),
    ('$.retention_measured.eligible_n.d1',               'eligible denominator, D1'),
    ('$.retention_measured.eligible_n.d3',               'eligible denominator, D3'),
    ('$.retention_measured.eligible_n.d7',               'eligible denominator, D7'),
    ('$.retention_measured.eligible_n.d14',              'eligible denominator, D14'),
    ('$.retention_measured.eligible_n.d30',              'eligible denominator, D30'),
    ('$.retention_measured.eligible_n.d60',              'eligible denominator, D60'),
    ('$.retention_measured.eligible_n.d90',              'eligible denominator, D90'),
    ('$.retention_horizon.primary_days',                 'primary retention horizon -- D30'),
    ('$.bulk_buyer_segment.threshold_items_per_order',   'P99.9 of order size, the is_bulk_buyer bar'),
    ('$.bulk_buyer_segment.n_users',                     'users flagged is_bulk_buyer'),
    ('$.bulk_buyer_segment.share_of_orders_pct',         'share of orders placed by bulk buyers'),
    ('$.bulk_buyer_segment.share_of_revenue_pct',        'share of revenue from bulk buyers'),
    ('$.black_friday_cohort.spike_threshold',            'median + 3*1.4826*MAD cut on daily discount intensity'),
    ('$.black_friday_cohort.n_spike_days',               'days the detector flags'),
    -- ---- 05: leakage-safe feature table --------------------------------------------
    ('$.features.n_rows',                                'purchasers in the feature table, bot-excluded'),
    ('$.features.n_model_eligible',                      'columns a model may be fitted on'),
    ('$.features.eligible_n.d30',                        'D30 modelling frame size'),
    ('$.features.eligible_n.d60',                        'D60 modelling frame size'),
    ('$.features.eligible_n.d90',                        'D90 modelling frame size'),
    ('$.features.positive_rate_pct.d30',                 'repeat_purchase_30d base rate'),
    ('$.features.positive_rate_pct.d60',                 'repeat_purchase_60d base rate'),
    ('$.features.positive_rate_pct.d90',                 'repeat_purchase_90d base rate'),
    -- ---- 08: the day-14 activation trigger -----------------------------------------
    ('$.experiment_design.trigger.days_since_first_order','trigger fires this many days after t0'),
    ('$.experiment_design.population.n_historical_analogue','users the day-14 rule would have enrolled'),
    ('$.experiment_design.population.base_rate_pct',      'repeat rate of the day-14 pool in the next 30 days')
),

text_paths(json_path, purpose) as (
    values
    ('$.data_date_range.min',                            'first event timestamp in the raw data'),
    ('$.data_date_range.max',                            'last event timestamp -- DATA_END, the censoring boundary'),
    ('$.black_friday_cohort.spike_day_span[0]',          'first detected discount-spike day'),
    ('$.black_friday_cohort.spike_day_span[1]',          'last detected discount-spike day'),
    ('$.order_reconstruction_rule.rule',                 'the certified order-reconstruction rule, as prose'),
    ('$.retention_measured.definition_purchase',         'the certified purchase-retention definition'),
    ('$.retention_measured.definition_activity',         'the certified activity-retention definition')
)

select
    p.json_path,
    p.purpose,
    json_extract_string(d.j, p.json_path)                      as param_text,
    try_cast(json_extract_string(d.j, p.json_path) as DOUBLE)  as param_value
from doc d
cross join (
    select json_path, purpose from paths
    union all
    select json_path, purpose from text_paths
) p
