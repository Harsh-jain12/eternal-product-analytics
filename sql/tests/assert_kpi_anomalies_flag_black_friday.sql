/*
  INDEPENDENT VALIDATION OF THE MONITORING RULE.

  handoff -> black_friday_cohort records a discount spike spanning 2019-11-21 to
  2019-11-30, detected by a completely different rule: 02 looked at per-line PRICE
  against each product's own median, with no calendar input and no volume input.
  mart_kpi_anomalies looks at daily VOLUME and VALUE series -- orders, sessions,
  conversion, revenue, new buyers -- and knows nothing about price dispersion.

  If the monitoring rule works, the two must land on the same week. A trading event that
  moves conversion from ~3.5% to ~5.8% and orders from ~1,100 to ~2,400 is the largest
  thing in this five-month window; a daily-KPI monitor that does not see it is not
  monitoring anything.

  The test fails if the rule flags NO day in that span. It deliberately does not assert
  WHICH days or HOW MANY: the assertion is that the detector fires on the known event,
  not that it reproduces a hand-picked list.
*/

with flagged as (
    select count(*) as n_flagged_days
    from (
        select distinct activity_date
        from {{ ref('mart_kpi_anomalies') }}
        where is_anomaly
          and activity_date between date '2019-11-21' and date '2019-11-30'
    )
)

select 'monitoring rule flags no day in the 2019-11-21..2019-11-30 Black Friday span' as failure,
       n_flagged_days
from flagged
where n_flagged_days < 1
