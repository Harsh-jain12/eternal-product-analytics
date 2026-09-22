/*
  A reconciliation suite that silently stops checking something still passes. This test
  fails if any handoff key the brief requires is not actually exercised by a row in
  mart_reconciliation -- so deleting a check is a test failure, not a quiet regression.

  Required coverage: the purchaser count, the order count, the bot-excluded user count,
  purchase AND activity retention at EVERY bucket, eligible_n at every bucket, and the
  feature table's eligible_n and positive rate at every horizon.
*/

with required(json_path) as (
    values
    ('$.row_counts.n_purchasing_users'),
    ('$.row_counts.n_orders'),
    ('$.row_counts.n_users_any_event'),
    ('$.row_counts.total_events'),
    ('$.bot_exclusion.n_users_excluded'),
    ('$.features.n_rows'),
    ('$.retention_measured.purchase_retention_pct.d1'),
    ('$.retention_measured.purchase_retention_pct.d3'),
    ('$.retention_measured.purchase_retention_pct.d7'),
    ('$.retention_measured.purchase_retention_pct.d14'),
    ('$.retention_measured.purchase_retention_pct.d30'),
    ('$.retention_measured.purchase_retention_pct.d60'),
    ('$.retention_measured.purchase_retention_pct.d90'),
    ('$.retention_measured.activity_retention_pct.d1'),
    ('$.retention_measured.activity_retention_pct.d3'),
    ('$.retention_measured.activity_retention_pct.d7'),
    ('$.retention_measured.activity_retention_pct.d14'),
    ('$.retention_measured.activity_retention_pct.d30'),
    ('$.retention_measured.activity_retention_pct.d60'),
    ('$.retention_measured.activity_retention_pct.d90'),
    ('$.retention_measured.eligible_n.d1'),
    ('$.retention_measured.eligible_n.d3'),
    ('$.retention_measured.eligible_n.d7'),
    ('$.retention_measured.eligible_n.d14'),
    ('$.retention_measured.eligible_n.d30'),
    ('$.retention_measured.eligible_n.d60'),
    ('$.retention_measured.eligible_n.d90'),
    ('$.features.eligible_n.d30'),
    ('$.features.eligible_n.d60'),
    ('$.features.eligible_n.d90'),
    ('$.features.positive_rate_pct.d30'),
    ('$.features.positive_rate_pct.d60'),
    ('$.features.positive_rate_pct.d90')
)

select r.json_path as uncovered_handoff_key
from required r
left join {{ ref('mart_reconciliation') }} m on m.handoff_json_path = r.json_path
where m.handoff_json_path is null
