/*
  THE RECONCILIATION TEST. Fails if ANY certified number in mart_reconciliation
  disagrees with outputs/handoff_params.json. Error severity, not warn: a drift here
  means the SQL layer and the notebooks have diverged and one of them is wrong.

  The failing rows name the check, the handoff key that was read, both values and the
  tolerance, so `dbt test` output is enough to diagnose without opening the warehouse.
*/

select
    check_name,
    model,
    handoff_json_path,
    handoff_value,
    model_value,
    abs_diff,
    tolerance,
    how
from {{ ref('mart_reconciliation') }}
where not passed
