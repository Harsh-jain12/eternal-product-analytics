# Eternal Product Analyst Portfolio — REES46 Cosmetics + Criteo

**Central question.** Which user behaviours and first-purchase characteristics drive repeat
purchase and long-term retention, which customer segments are most valuable and most at
risk, and who should actually be targeted with a retention intervention?

**Status.** Notebooks 00–05 built and committed. 06–09 not yet built.

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

## Reproducibility: three determinism guards, all mandatory

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

---

## Repository layout

```
notebooks/   00 data quality · 01 funnel · 02 cohorts + retention · 03 churn definition
             04 segmentation · 05 features              (06–09 not yet built)
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
- **SPINE-1 is falsified** (nb02 §5): behaviour does not beat first-order value for
  predicting repeat purchase, and both are weak (Cramér's V 0.09–0.13). Recorded and dated
  rather than deleted.
- The churn threshold (42.2 days) is **not identified** by this dataset — it is the centre of
  a 30–45 day region. Quote the region; use 42.2d as the operating value so 04/05/06 stay
  comparable.
- The certified churn rule's **recall is 53%**. The flagged population is not the at-risk
  population; any reach or ROI denominator built on the flagged count is wrong by roughly a
  factor of two.
- **D30 cannot carry a churn label.** Under the 42.2d rule no user is churned before day
  42.2, so nb06's target is `repeat_purchase_30d` and must never be called churn.
- A clean end-to-end re-execution of 00→05 in one continuous session has **not** been done.
  Every number reconciles on re-read, but the reproducibility claim is not yet earned.
