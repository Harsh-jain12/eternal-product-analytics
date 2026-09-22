# `dashboard/` — the reading surface

A seven-page Streamlit app over the finished analysis. It is deliberately **not** a
second analysis: it reads committed parquet extracts built from the dbt marts, plus the
copy of `handoff_params.json` that carries every constant notebooks 00–09 certified, and
recomputes nothing analytical.

```bash
pip install -r dashboard/requirements.txt
streamlit run dashboard/app.py
```

That works from a fresh clone. No DuckDB warehouse, no raw CSVs, no dbt, no
scikit-learn — `dashboard/data/` is 0.35 MB and is checked in.

---

## The three design rules, and how each one is enforced

**1. The app reads only marts and handoff, and recomputes nothing analytical.**

`lib/load.py` exposes exactly two accessors — `extract(name)` for a committed parquet and
`H("dotted.json.path")` for a handoff constant — and there is no database connection
anywhere in the app. Every rate, gap, cohort cell and anomaly flag was computed upstream
in SQL. The one place the app does arithmetic is the break-even calculator on the last
page, which is a formula over a labelled ledger and says so on screen, line by line.

**2. Nothing user-level, and under 25 MB.**

`build_extracts.py` refuses to write a frame carrying a `user_id` or `user_session`
column, and refuses to write one larger than a stated aggregate ceiling. Current total:

| | |
|---|---|
| parquet extracts | 23 files, 0.19 MB |
| `handoff_params.json` | 0.15 MB, verbatim copy |
| **total committed** | **0.35 MB** against a 25 MB budget |

The largest single file is `kpi_anomalies.parquet` at 1,216 rows (8 KPIs × 152 days).

**3. Every number traces to a mart or a handoff key.**

Every chart carries a `Source:` caption naming the extract and the mart behind it.
`extract_manifest.parquet` carries one row per file with its grain and source, and the
sidebar renders it. DATA and ASSUMPTION are tagged with the same colours 09 uses, and on
the calculator page only the ASSUMPTION rows and the SCENARIO lift get sliders — the DATA
rows are fixed and shown with the file they came from.

---

## Rebuilding the extracts

Only needed when a mart or the handoff document changes.

```bash
cd sql && DBT_PROFILES_DIR=. dbt build      # ~4 min, 17 models + 103 tests
cd .. && python dashboard/build_extracts.py # ~10 s
```

The builder does not trust the warehouse it reads. Before it writes anything it
**reconciles**, and a mismatch fails the build rather than reaching a page:

- all 50 checks in `mart_reconciliation` must pass;
- the pooled retention curve must equal `handoff.retention_measured` at every one of the
  21 published cells;
- the Black Friday gap it recomputes from `dim_users` × `fct_orders` must equal
  `handoff.black_friday_cohort.gap_pp` at every bucket;
- the funnel's three scopes must reproduce 01's published counts;
- the anomaly mart must flag at least one day in the Black Friday span.

It is deterministic: DuckDB at `threads=1` for the fetch, `quantile_cont` only, and every
extract sorted on a key it asserts is unique before writing. Two clean runs produce
identical files.

### What is in `dashboard/data/`

| file | grain | from |
|---|---|---|
| `scope.parquet` | one scope metric | `dim_users`, `fct_orders`, `stg_events`, `stg_bot_users` |
| `funnel_scopes.parquet` | funnel stage | `fct_sessions`, rolled up to user grain |
| `funnel_first_time_vs_returning.parquet` | user type | `fct_sessions` |
| `funnel_by_session_depth.parquet` | depth bucket | `fct_sessions` |
| `cohort_retention.parquet` | (cohort, bucket) | `mart_cohort_retention` |
| `retention_pooled.parquet` | bucket | `mart_cohort_retention`, pooled |
| `black_friday_retention.parquet` | bucket | `dim_users` × `fct_orders` |
| `orders_per_user.parquet` | lifetime-order bucket | `fct_orders` |
| `churn_candidates / _validation / _population` | candidate / spec / quantity | handoff `churn_definition` |
| `segments / _stability / _k_selection / _disagreement` | segment / test / k / cell | handoff `segmentation` |
| `daily_kpis.parquet` | calendar day | `mart_daily_kpis` |
| `kpi_anomalies.parquet` | (kpi, day) | `mart_kpi_anomalies` |
| `model_baselines / model_headline` | model / metric | handoff `modelling` |
| `impact_ledger / impact_sensitivity` | input | handoff `experiment_design`, `impact` |
| `reconciliation.parquet` | certified number | `mart_reconciliation` |
| `extract_manifest.parquet` | file | this script |
| `handoff_params.json` | one document | verbatim copy of `outputs/handoff_params.json` |

---

## The pages

| page | what it answers |
|---|---|
| **Overview** | The 60% return / 27% buy gap, the data's scope, and eight findings each tied to the notebook that produced it. |
| **Acquisition & cohorts** | The cohort triangle with ineligible cells grey and never zero, and Black Friday week against everyone else on one fixed population. |
| **Funnel health** | The same funnel at three scopes side by side — 1.8x apart at the purchase step — labelled as lower bounds, split first-time vs returning. |
| **Retention & churn** | Purchase and activity curves with `eligible_n` under each point; the 30–45 day churn region with 42.2d as the operating value; recall, false-positive rate, and why flagged ≠ at-risk. |
| **Segments** | Four aggregated profiles with kappa 0.309 stated on the page, not in a footnote, and the RFM × behaviour disagreement cells. |
| **Monitoring** | Daily KPIs against a trailing robust baseline, per series and as a heatmap, plus the days the rule declines to score and why. |
| **Experiment & impact** | Design B in one screen, the Criteo policy comparison that justifies not targeting the churn tail, and the break-even calculator. |

### The break-even calculator

Sliders: **cost per contact** and **contribution margin** (both ASSUMPTION), and the
**scenario lift** (SCENARIO). Fixed and shown with sources: base rate, second-order AOV,
downstream multiplier, first-buyer inflow, day-14 survival (all DATA), plus the holdback
and `n` per arm (DESIGN).

It outputs the break-even lift in pp and relative terms, net €/year, and whether design B
can adjudicate the scenario — `P(ship)` being the chance the 95% interval's lower bound
clears break-even, computed from the design's own unpooled arm-difference standard error.
At the defaults it reproduces 09 exactly: €12.757 per incremental second order, 0.3919 pp
break-even, €16,256 net per year at 1.00 pp, and 80% P(ship) for design B against 39.9%
for design A.

---

## Deploying to Streamlit Community Cloud

1. Push to GitHub (this repo, public or with the app given access).
2. **New app** → pick the repo and branch.
3. **Main file path**: `dashboard/app.py`.
4. Leave the Python version at 3.11+ and let it install `dashboard/requirements.txt`.

Nothing else is needed. There are no secrets, no environment variables and no external
services — `dashboard/data/` and `dashboard/.streamlit/config.toml` are checked in, and
`config.toml` pins the light theme the matplotlib figures are drawn for.

Two things that break a deploy if changed:

- **Moving `dashboard/data/`.** Paths resolve from `lib/load.py`'s own location, so the
  folder has to stay beside it.
- **Adding `duckdb` to `dashboard/requirements.txt`.** It is not needed at serve time and
  is deliberately absent; the extract builder is a local pre-deploy step and takes its
  `duckdb` from the repo-root `requirements.txt`.

---

## Layout

```
dashboard/
  app.py                 entry point: navigation, sidebar, provenance panel
  build_extracts.py      local pre-deploy step; reads the warehouse, writes data/
  requirements.txt       what Community Cloud installs (no duckdb, no dbt, no sklearn)
  .streamlit/config.toml light theme, pinned
  lib/
    load.py              extract() and H() -- the only two data accessors
    style.py             palette, frame()/add_title()/add_takeaway(), DATA/ASSUMPTION chips
  views/                 one file per page
  data/                  the committed extracts
```

`lib/style.py` restates `src/plotting.py`'s figure convention rather than importing it:
every figure has a title via `fig.text`, a one-line subtitle giving scope and caveats, and
a bottom-anchored TAKEAWAY box. The deployed app is a clone of `dashboard/` alone and must
not reach back into the repo's analysis package. Two differences from the notebook
helpers, both deliberate: the space reserved outside the axes is measured in **inches**
rather than as a figure fraction, because these figures range from 3.2 to 5.2 inches tall
and a fixed fraction puts the x-axis label under the takeaway box on the short ones; and
titles and takeaways are passed through `html.unescape`, because the same strings are
written for `st.markdown` and for matplotlib, which draws text rather than HTML.

Colours mean the same thing on every page: **blue** is purchase retention and the primary
metric, **orange** is activity retention and the superset, **red** is a flag or a negative
result, **grey** is ineligible, censored or not evaluable.
