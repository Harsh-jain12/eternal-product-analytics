/*
  05's forbidden list, enforced as a test rather than as prose.

  mart_user_features must not carry a column from the F2 (lifetime / recency / RFM),
  F4 (static cluster label) or F5 (cart-abandonment TYPE) families, nor the four columns
  05 persisted for diagnostics and explicitly forbade fitting on. A name check cannot
  prove a feature is leakage-free -- the load-bearing guarantees are window disjointness
  and the provenance audit -- but it does stop the known-bad names from reappearing.
*/

select column_name as forbidden_column
from information_schema.columns
where table_name = 'mart_user_features'
  and (
        column_name in (
            -- 05's diagnostic-only columns: "must not be fitted on"
            't0_calendar_day', 'is_bulk_buyer_fullhistory', 'pre_segment', 'cluster_name',
            -- F2: lifetime / recency / RFM
            'lifetime_order_value', 'lifetime_items', 'n_orders', 'recency_days',
            'rfm_score', 'r_score', 'f_score', 'm_score', 'last_event_ts', 'last_order_ts',
            -- F5: abandonment TYPE, the 02 Section 0E leak
            'abandonment_type', 'deferred_intent', 'substitution', 'price_driven',
            'comparison_browse', 'other_inconclusive',
            -- the churn label: D30 cannot carry one under the certified 42.2d rule
            'is_churned', 'churn_flag'
        )
        or column_name like 'post_t0%'
        or column_name like '%_fullhistory'
      )
