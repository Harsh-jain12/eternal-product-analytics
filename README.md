# Eternal Product Analyst Portfolio — REES46 Cosmetics + Criteo

**Central question.** Which user behaviours and first-purchase characteristics drive repeat
purchase and long-term retention, which customer segments are most valuable and most at
risk, and who should actually be targeted with a retention intervention?

**Status.** Notebooks 00–08 built and committed; 09 not yet built. The chain is reproducible end-to-end — see [Reproducibility](#reproducibility).

**Data.** REES46 *eCommerce Events History in Cosmetics Shop* — 5 monthly CSVs
(2019-10 → 2020-02), 20.7M events, 1.64M users, 159,382 reconstructed orders (no `order_id`
in the source; the reconstruction rule is derived and certified in nb00). Plus the Criteo
Uplift Prediction dataset (13.98M rows, a genuine randomised incrementality test) reserved
for nb07.

**Engine.** DuckDB over the raw CSVs. Seed 42 everywhere. matplotlib, every figure carrying
a stated takeaway.

---

## Leakage: the forbidden-feature list

`05_features.ipynb` builds the modelling table and is organised **by leakage risk rather
than by data source**, because a leaky feature does not raise an error — it just makes the
model look good. The anchor is `t0`, each user's first order timestamp. Features may read
events strictly before `t0`, plus the first order's own purchase lines at `t0`. The outcome
is measured strictly after `t0`.

Nothing in `data/processed/features.parquet` may be built from any of the following. The
list is mirrored verbatim as a code comment in nb05 §2, and nb05 §9 audits the built table
against it.

| | forbidden | why | enforcement in nb05 |
|---|---|---|---|
| **F1** | any aggregate over the outcome window (`event_time > t0`) | it *is* the answer | every feature query filters to `event_time < t0` or to the first-order purchase lines; §9A asserts it at row level |
| **F2** | lifetime orders / lifetime spend / last-event recency | each is a function of the whole window, therefore of the outcome | no join to 03's `churn_flags` or 04's R/F/M columns; tenure is measured **to `t0`**, not to `DATA_END` |
| **F3** | product or category statistics over the full dataset | a February price cut would inform an October order | price references built with `.shift().expanding()` — window frame `UNBOUNDED PRECEDING .. 1 PRECEDING` over prior days only |
| **F4** | static `cluster_name` from 04 | membership is not durable (56.9% same-cluster, κ = 0.309) **and** the labels were fitted on full history | `segment_assignments.parquet` loaded for comparison only; §8 re-scores from `segment_model.json` on pre-`t0` data and reports coverage |
| **F5** | cart-abandonment **type** features | 02 §0E: under a leaky spec `deferred_intent` scored OR 10.81; with disjoint windows the same type scores 0.78 and the ranking inverts | abandonment **volume** is kept and is predictive; type labels are loaded, reported, never joined |

### Three leaks that were live in the inherited definitions

Each was caught by a structural check, not by noticing an implausible score — which is the
argument for doing the window arithmetic before building anything.

1. **02's `first_session_events` is untruncated.** 241,536 events — including 24,625
   purchase rows — sit inside the first-order session *after* the order, for 11,704 users
   (10.7% of purchasers), the furthest 151 days later via session-ID reuse. Correct for 02's
   descriptive use; a leak as a feature. Holding coverage constant on the 81,626 users where
   both versions are defined, the untruncated count scores univariate AUC 0.5790 against
   0.5525 truncated at `t0`.
2. **02's `is_bulk_buyer` is a full-history flag.** It fires on any order over 90.6 items
   across the whole window, so for 33 of the 143 flagged users the evidence post-dates `t0`.
   Carried as a population flag with `model_eligible = False`; `first_order_is_bulk`
   replaces it.
3. **04's `cart_abandonment_rate` cannot exist before the first order.** There are exactly
   zero purchases before `t0`, so every carted product is abandoned and the rate is a
   constant 1.0. 04 computed it over full history. The consequence reaches past the one
   feature: `segment_model.json` cannot be applied faithfully to a pre-`t0` window, because
   one of its eight fitted inputs is degenerate there.

### How leakage is verified, not just claimed

- **§9A window disjointness** — row-level SQL: every feature-block event is at or before
  `t0`, every outcome order strictly after it. The four windows are asserted to partition
  all 11,354,272 purchaser events.
- **§9B provenance audit** — every column declares the window it reads; the built-column set
  and the declared set are asserted equal, so a feature cannot be added without declaring a
  window.
- **§9C univariate screen with planted positive controls** — a pure outcome-window aggregate
  (AUC 0.9386) and 02's untruncated first-session depth are pushed through the same screen,
  so its power is demonstrated before anything is cleared by it. Its blind spot is stated
  rather than glossed: univariate AUC cannot see a weak leak or an interaction leak, so §9A
  and §9B are the load-bearing checks.

---

## Building the feature frame: three guards, all mandatory

DuckDB's parallel float `avg`/`sum` reduce in physical scan order, and `fetchdf()` returns
rows in scan order. nb04 established two guards. **nb05 found they are not sufficient.**

1. `SET threads=1` **for the fetch** (materialisations stay parallel — that is where the wall
   clock is; the guard costs about 8 seconds).
2. `src.data.round_sig(df, cols, sig=6)` — stabilises the values.
3. `.sort_values('user_id')` — stabilises the row order.

Guards 2 and 3 alone leave the frame *intermittently* non-reproducible: the wobble is ~1e-15
relative and `round_sig` snaps to a 1e-6 grid, so a value sitting within 1e-15 of a boundary
flips across it. It broke nb05's first execution on **one cell out of 109,732**. Rounding
makes the non-determinism rare rather than absent, which is the worse failure mode. Use
`fetch_block()`.

These three are about one frame. The project-wide rules, and the fourth failure mode that
made them necessary, are in [Reproducibility](#reproducibility).

---

## Repository layout

```
notebooks/   00 data quality · 01 funnel · 02 cohorts + retention · 03 churn definition
             04 segmentation · 05 features · 06 modelling · 07 Criteo experiment
             08 experiment design · 09 business impact + recommendations
src/         data.py    DuckDB layer, certified order rule, determinism guards
             plotting.py frame / add_title / add_takeaway / save / show_df
outputs/     handoff_params.json   the contract between notebooks — read it first
             tables/   one CSV per reported figure
             figures/  every figure, each with a stated takeaway
data/        raw/ (REES46 CSVs + criteo/)   processed/ (parquet artefacts)
```

`outputs/handoff_params.json` carries the certified order-reconstruction rule, the primary
retention horizon, the certified churn threshold, the bot exclusion, the segmentation model
and the nb05 feature contract forward between notebooks. Every notebook after 00 reads it
rather than re-deriving.

## Standing limitations

- `user_id` is **cookie-scoped, not account-scoped**. Every retention and repeat-purchase
  figure in this project is a **lower bound** on true customer-level behaviour.
- REES46 contains **no randomised experiment**. Nothing here is an A/B test; nb08 is a
  design, not a result. Criteo (nb07) is the genuine randomised experiment, and is what lets
  the project show that risk-targeting is not uplift-targeting.
- **SPINE-1: the depth proxy failed, the hypothesis did not** (nb02 §5, reconciled with
  nb06 on 2026-09-21). First-session depth — the one behavioural proxy nb02 tested — never
  beats first-order value: D30 and D60 are ties on a bootstrap CI for ΔV that spans zero,
  value leads at D90. But nb06 finds that a *broader* behavioural block, pre-purchase
  browsing volume (M3), beats first-order information (M1) in both ladder orders — standalone
  test ROC 0.6192 vs 0.5852. So "behaviour beats value" is **not** falsified in general; the
  narrow proxy failed and the broader measure succeeded, and every signal is weak. The
  earlier "FALSIFIED" label over-claimed and is corrected, not deleted.
- The churn threshold (42.2 days) is **not identified** by this dataset — it is the centre of
  a 30–45 day region. Quote the region; use 42.2d as the operating value so 04/05/06 stay
  comparable.
- The certified churn rule's **recall is 53%**. The flagged population is not the at-risk
  population; any reach or ROI denominator built on the flagged count is wrong by roughly a
  factor of two.
- **D30 cannot carry a churn label.** Under the 42.2d rule no user is churned before day
  42.2, so nb06's target is `repeat_purchase_30d` and must never be called churn.
- One **named, bounded residual** survives in the reproducibility check — a single measured
  cell, quantified in [Reproducibility](#reproducibility).

---

## Reproducibility

**Established 2026-09-21.** The chain was executed end-to-end, `00 → 08`, from an empty
`data/processed/` and no `.duckdb`, **five times**, and the runs were diffed against each other over every
`handoff_params.json` leaf and every cell of all 211 CSVs — 20,909 values.

| | run A | run B | run C | run D | run E |
|---|---|---|---|---|---|
| wall clock | 9,245 s | 2,976 s | 3,102 s | 3,156 s | 3,038 s |
| notebooks | 9/9 clean | 9/9 clean | 9/9 clean | 9/9 clean | 9/9 clean |

A and B are the determinism pair. C, D and E regenerated the artefacts after corrections to
the limitation text itself — each correction had to be executed to land in
`handoff_params.json`, and the committed artefacts come from the last of them.

Run A took three times as long because the machine was under heavy external load
(load average 14 against 8 cores; nb06 took 2,580 s in A and 359 s in B).
That is the point of the exercise: **the results do not depend on how the machine was
scheduled.** Under normal load the chain takes roughly 30–35 minutes, of which nb07 —
hashing and modelling 14M Criteo rows — is about two thirds.

**Result: 3 differing values out of 20,909 between A and B, all three the same number.**
Runs C–E regenerated the artefacts after corrections to the limitation text, and diffing
them traced that number's full propagation — reported below, because it reaches further than
the A-vs-B diff alone revealed. Across all five runs these are identical: the shipped model,
the spine measurement, `churn_definition`, and every Criteo result.

**One residual survives every guard**, and it is not a new fault: it is the `round_sig`
boundary flip that nb05 §11 already describes, in `fo_price_vs_prior_mean`, observed.

Measured spread across all five runs:

| | magnitude |
|---|---|
| at source, `features.parquet` | 0–2 cells of 10,534,272 (≤ 1.9e-07), float diff ~1e-15 |
| `L2_diff_sorted_and_rounded` | `0, 1, 0, 0, 0` across the five runs |
| nb06 `loglik` | ≤ 1.2e-10 relative |
| nb06 `LR_chi2` | ≤ 8.1e-09 relative (≤ 1e-06 absolute on values of 500–1700) |
| extreme-tail `p` | ≤ 3.1e-06 relative, on p-values of 1e-20 to 1e-226 |
| `min_predicted_probability` | ≤ 8.3e-09 relative |
| `nb06_predictions_d30.parquet` | every row, all below reported precision |

`LR_chi2` amplifies because it is a difference of two large, nearly equal log-likelihoods;
the p-values amplify again because they sit in the far tail. Both remain five to eight
orders of magnitude below anything the project reports — nb06 quotes χ² to 1 dp and never
compares a p-value of 1e-94 against anything but zero.

These are **cross-run** quantities. No single execution can compute them, which is why they
live here and not in a `known_limitations` entry: a notebook should not assert a number it
cannot verify. The notebook states the mechanism and the order of magnitude and points here.

**What does not move, across all three runs:** the shipped model's test AP, ROC, Brier and
decile-1 lift; the decile table; the nb06 ladder χ² at the 1 dp it is reported to; the spine
measurement; `churn_definition`; `orders.parquet`; `churn_flags.parquet`; every cluster
label; and every reported figure in all 211 CSVs.

**Why it is accepted rather than fixed:** it measures the *two-guard* configuration that
nb05 §11 already declares insufficient — "rounding makes the non-determinism rare rather
than absent, which is the worse failure mode". The shipped frame uses all three guards via
`fetch_block()`, and `L3_diff_threads1_raw` is `0` for every block in every run. Removing
the last 1e-15 would mean giving up parallel aggregation, which costs more than the residual
is worth; the honest move is to bound it and say so.

The self-measurement columns of `nb04_float_determinism_audit.csv` and
`nb05_determinism_audit.csv` are exempt by design — their job is to measure the float
wobble, so they move — and their after-guard columns match.

### What it took

Four distinct determinism defects, each found by a clean re-run rather than by reading the
code. All four are documented in `src/data.py → connect()`:

1. `row_number()` through a **lazy view** — re-assigned on every reference, so joins landed
   on the wrong rows.
2. **`approx_quantile`** — a sketch, not an exact quantile; 4.0754 vs 4.0705 for one median.
3. Raw parallel **`sum`/`avg`** — last-bit differences, cosmetic as a value.
4. **Any of the above used *as an ordering or bucketing key*** — the one that amplifies, and
   the reason (3) is not merely cosmetic. A 1e-13 wobble in a `percent_rank` sort key becomes
   a whole rank step: measured at **597,236 of 3,113,627 ranks moving between two processes,
   max |diff| 0.0423**, going to **zero** once the key is rounded. A tie-break column does not
   save you — the values are no longer tied. Guard: `key_round()` / `sig_round()`.

Two supporting rules fall out of the same work: every `ORDER BY` / `sort_values` / rank key
must be **unique** (the orders key is `user_id, user_session, order_ts` — never just the
first two), and nothing that is a wall-clock time or a measurement *of* non-determinism may
be written into a CSV or a handoff leaf.
