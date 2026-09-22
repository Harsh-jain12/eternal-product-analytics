# `sql/` — the metrics layer

The notebooks are the analysis. This is the production-shaped version of it: a
**dbt-duckdb** project that rebuilds every certified number from the raw CSVs on a
schedule, and fails the build if any of them drifts.

It does not re-derive anything. Every constant it needs — the bot threshold, the bulk
bar, the retention buckets, the primary horizon, the day-14 trigger — is **read from
`outputs/handoff_params.json` at build time**, and every published figure is compared
back to it. There is no hardcoded target anywhere in the project.

```
dbt build     # 16 models + 94 tests, from the raw CSVs, in about 4 minutes
```

---

## How to run it

```bash
cd sql
pip install dbt-duckdb==1.10.1          # already in ../requirements.txt
DBT_PROFILES_DIR=. dbt build            # build every model, then run every test
DBT_PROFILES_DIR=. dbt docs generate --static   # regenerate docs/index.html
```

The generated docs are checked in at **`sql/docs/index.html`** — a single self-contained
file, so the lineage graph opens with a double-click, no server. `sql/docs/graph_summary.json`
is the same graph in machine-readable form, with dbt's per-run invocation id stripped so
the published file is a pure function of the models rather than of the run that produced
it. `sql/target/` (compiled SQL, run timings) is gitignored.

Inputs, both relative to `sql/` and both overridable with `--vars`:

| var | default | what it is |
|---|---|---|
| `raw_events_glob` | `../data/raw/*.csv` | the five REES46 monthly files |
| `handoff_path` | `../outputs/handoff_params.json` | what 00–08 certified |

Output: `../data/eternal.duckdb` (gitignored), with schemas `staging`, `intermediate`
and `marts`.

`profiles.yml` is checked in on purpose — there are no credentials here and no remote
warehouse. Swap the `duckdb` output for a `snowflake`/`bigquery` one and the models move
with it; only `read_csv_auto` and `read_text` would need a source table and a seed.

---

## The models

Grain is what the table is one row of. PK is what is tested `unique`.

### staging — clean the input, inherit the constants

| model | grain / PK | purpose |
|---|---|---|
| `stg_handoff_params` | `json_path` | Every certified constant, read from `handoff_params.json`. `json_path` is the audit trail: a failing check names the notebook figure it disagrees with. |
| `stg_bot_users` | `user_id` | The 1,605 users the bot rule removes, **with** their event / purchase-line / order counts, so the pre-exclusion totals can be reconstructed without a second pass. |
| `stg_events` | one row per logged event (no PK — duplicates are expected) | Typed, null-session rows dropped, bot users excluded. Equivalent to `ev` in 01–05. |
| `stg_discount_spike_days` | `spike_date` | 02's discount detector. No calendar input; it isolates Black Friday week on price dispersion alone. |

### intermediate — the windows the feature table is built from

| model | grain / PK | purpose |
|---|---|---|
| `int_product_day_price_ref` | `(product_id, d)` | Prior-days-only product price reference. The SQL form of `.shift().expanding()`. |
| `int_category_day_price_ref` | `(category_id, d)` | Prior-days-only category log-price mean and sd, admitted only above 50 prior observations and sd ≥ 0.05. |
| `int_first_order_lines` | one row per first-order purchase line | The whole M1 feature window. |
| `int_pre_t0_events` | one row per pre-`t0` purchaser event | The whole M2 + M3 feature window. |
| `int_pre_t0_sessions` | `(user_id, user_session)` | Session roll-up of that window; the basis for M4's visit cadence. |

### marts — what a consumer reads

| model | grain / PK | purpose |
|---|---|---|
| `dim_users` | `user_id` | `first_event_ts`, `first_order_ts` (t0), `first_order_session`, both cohort columns, `is_black_friday_cohort`, `is_bulk_buyer`. One row per bot-excluded user, purchaser or not. |
| `fct_sessions` | `(user_id, user_session)` | Funnel flags at two grains — raw event counts and distinct-product counts, which is 01's raw-vs-deduplicated comparison. |
| `fct_orders` | `(user_id, user_session, order_ts)` | The certified order-reconstruction rule, verbatim. |
| `mart_cohort_retention` | `(cohort_month, bucket_day)` | Purchase **and** activity retention, `eligible_n` per cell, ineligible cells absent rather than zero. |
| `mart_user_features` | `user_id` | 05's leakage-safe M1–M4 table, the 81 model-eligible columns plus keys, targets and eligibility flags. |
| `mart_daily_kpis` | `activity_date` | Sessions, conversion at two labelled scopes, orders, AOV (median + winsorised mean), new first-time buyers, day-14 trigger pool. |
| `mart_reconciliation` | `check_name` | One row per certified number: what the handoff says, what this layer computes, the tolerance, pass/fail. |

Nine models beyond the seven the brief names. `stg_handoff_params` and `stg_bot_users`
exist so nothing is hardcoded and so the pre-exclusion totals stay reconstructable;
`stg_discount_spike_days` and the five `int_*` models are the notebooks' own
materialisations (`prod_ref`, `cat_ref`, `fo_lines`, `pre_ev`, `pre_sess`), kept as
models so the lineage graph shows where each feature block's window comes from;
`mart_reconciliation` is the test surface.

---

## Tests — 94, all `error` severity

```
dbt test
```

**Structural (88 generic).** 65 `not_null`, 7 `unique`, 7 `unique_combination` for the
composite PKs (a local test, so there is no `dbt_utils` dependency and `dbt build` needs
no network), 5 `relationships` from `fct_orders`, `fct_sessions`, `mart_user_features`,
`int_first_order_lines` and `int_pre_t0_events` back to `dim_users`, 2
`accepted_values` on `event_type` and `stage_code`, and 2 `not_zero_filled` — a local
test on both retention columns, asserting no cell exists without a real denominator
behind it.

**Reconciliation (6 singular tests, 50 checks).** All targets read from
`handoff_params.json` at build time.

| test | what fails it |
|---|---|
| `assert_reconciles_with_handoff` | any of the 50 checks in `mart_reconciliation` |
| `assert_reconciliation_covers_every_required_key` | a required handoff key stops being checked — deleting a check is a failure, not a quiet regression |
| `assert_no_forbidden_feature_columns` | an F2/F4/F5 column, or one of 05's four diagnostic-only columns, appears in `mart_user_features` |
| `assert_feature_and_outcome_windows_are_disjoint` | a feature reads at or after `t0`, or a repeat order is counted inside the first-order session |
| `assert_censored_users_are_never_zero_filled` | a user is eligible without the elapsed seconds, or a repeat flag contradicts `days_to_next_order` |
| `assert_retention_is_a_subset_of_activity` | purchase returners exceed activity returners in any cohort × bucket cell |

### The handoff keys the reconciliation reads

Every one of these appears as a `handoff_json_path` on a row of `mart_reconciliation`.

| block | keys |
|---|---|
| 00 shape | `row_counts.total_events`, `row_counts.n_orders`, `row_counts.n_purchasing_users`, `row_counts.n_users_any_event`, `data_date_range.min` / `.max` / `.span_days` |
| 01 bot rule | `bot_exclusion.n_users_excluded`, `.share_of_events_pct`, `.share_of_purchase_rows_pct`, `.share_of_orders_pct` |
| 02 bulk | `bulk_buyer_segment.threshold_items_per_order`, `.n_users`, `.share_of_orders_pct`, `.share_of_revenue_pct` |
| 02 Black Friday | `black_friday_cohort.spike_threshold`, `.n_spike_days`, `.spike_day_span[0]` / `[1]` |
| 02 retention | `retention_measured.purchase_retention_pct.d{1,3,7,14,30,60,90}`, `.activity_retention_pct.d{…}`, `.eligible_n.d{…}` — 21 checks |
| 05 features | `features.n_rows`, `.n_model_eligible`, `.eligible_n.d{30,60,90}`, `.positive_rate_pct.d{30,60,90}` |
| 08 trigger | `experiment_design.population.n_historical_analogue`, `.base_rate_pct`, `experiment_design.trigger.days_since_first_order` |

`tolerance` is half of the last digit the handoff itself publishes, plus a float epsilon.
A count reconciles **exactly**. A percentage published to 2dp reconciles to 2dp. Nothing
is given slack it was not published with.

---

## What this layer carries over from the notebooks

**Determinism is a correctness property, not a nicety.** All four failure modes from
`src/data.py connect()` are handled in SQL:

1. *`row_number()` through a lazy view.* Every model is `materialized: table`. Nothing
   carrying a synthetic row id is a view.
2. *`approx_quantile`.* Never used. `quantile_cont` everywhere — the sketch was measured
   at 4.0754 vs 4.0705 for the same median across two runs.
3. *Raw parallel float `sum`/`avg`.* DuckDB runs at `threads: 1` (`profiles.yml`), and
   every reported float is rounded — `sig_round()` to 6 significant figures for a
   persisted value, `key_round()` to 6 decimals for a key.
4. *Any of those used as an ordering or bucketing key* — the one that amplifies.
   `key_round()` is applied **before** the value is used as one: the `percent_rank` key
   in `int_product_day_price_ref` (where an unrounded key moved 597,236 of 3,113,627
   ranks between two processes), the `sd(log price)` cut in
   `int_category_day_price_ref`, the bot rate in `stg_bot_users`, the MAD cut in
   `stg_discount_spike_days`, and every session/entry-row tie-break.

Every `ORDER BY` and window frame uses a **unique** key. `fct_orders.order_seq` is
ordered on `(order_ts, user_session)` — the full certified key — never on `order_ts`
alone: 5 user+timestamp pairs carry two orders in different sessions, and 08 measured
that dropping `user_session` moved the AOV the sample-size calculation was built on.

**Verified, not asserted.** The project was built twice from scratch — `rm
data/eternal.duckdb && dbt build` — and the two warehouses were diffed on a per-row
content digest of all 16 tables, 36,483,549 rows: **0 tables differ**. Two clean runs
agree exactly, not merely at reported precision.

`sig_round()` uses DuckDB's `round_even`, not `round`. numpy rounds half to **even** and
SQL rounds half **away from zero**, so an exact tie on the 6-significant-figure grid
lands one step apart. Before that fix, 233 of 109,732 `tenure_d` values, 190
`trailing_days` and 168 `gap_before_purchase_visit` differed from the notebook's — each
by exactly one grid step, invisible in a mean and exactly the kind of difference that
becomes a whole rank step once something buckets on it.

**Other rules carried in:**

- Purchase retention is the primary metric; activity retention is reported alongside as
  a superset, never as the headline.
- Censored users are excluded, never zero-filled — in `mart_cohort_retention` (no row),
  in `mart_user_features` (eligibility in exact elapsed seconds), and in
  `mart_daily_kpis` (`day14_trigger_pool_observable_n` is NULL once its window is open).
- Nothing is imputed in the feature table. Every NULL has a named indicator.
- `stg_events` does **not** deduplicate rows. 00's audit is explicit that the 10.4%
  exact-duplicate rows are real repeated actions at 1-second resolution and the 0.07%
  repeated purchase lines are quantity. Deduplication in this project is a **grain** —
  the distinct-product counts in `fct_sessions` — not a cleaning step.
- `user_id` is cookie-scoped. Every retention and repeat figure here is a lower bound.

---

## Known limits

**11 cells in 10,095,344 do not match `features.parquet` exactly.** A cell-by-cell
comparison of `mart_user_features` against 05's output over all 92 shared columns and
109,732 rows leaves 8 cells of `fo_price_vs_prior_mean`, 2 of
`pre_mean_price_pct_viewed` and 1 of `pre_price_range_viewed`. Each differs by exactly
one step of the 6-significant-figure grid. This is the residual 05 Section 11 documented
and did not claim to have eliminated: a value whose 7th significant digit sits within
1e-15 of a rounding boundary flips across the grid. It moves no reported figure — every
one of the 50 reconciliation checks passes — and it is recorded here rather than papered
over.

**`fct_sessions` does not carry 01's top-20 brand and category buckets.** Those are a
presentation cut, and they depend on a top-20 list that shifts with the data. The
underlying `first_brand` / `first_category_id` columns are here; bucket them in the
consumer.

**This layer covers 00–02, 05 and 08.** The churn threshold (03), the segmentation (04),
the fitted models (06) and the Criteo experiment (07) are not reproduced here: a k-means
fit, a LightGBM model and an uplift estimator do not belong in a SQL metrics layer.
`mart_user_features` is the handoff point — it is the table 06 would train on.
