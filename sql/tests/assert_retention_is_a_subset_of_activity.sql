/*
  A purchase return is also an activity return, by the definitions in
  handoff -> retention_measured: same window, same session rule, purchase is one event
  type among four. So purchase retention must be <= activity retention in EVERY cell.
  If it is not, the two definitions have drifted apart. 02 asserts this; so does this
  layer, at cohort grain rather than only on the pooled curve.
*/

select cohort_month, bucket_day, purchase_retention_pct, activity_retention_pct
from {{ ref('mart_cohort_retention') }}
where purchase_returners > activity_returners
