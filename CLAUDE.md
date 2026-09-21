# Eternal Product Analyst Portfolio — REES46 Cosmetics + Criteo

## Central business question
Which user behaviors and first-purchase characteristics drive repeat purchase and
long-term retention, which customer segments are most valuable and at risk, and who
should actually be targeted with a retention intervention?

## Spine hypothesis (REVISED in 02, RECONCILED with 06 — read SPINE-1 before using this)
Repeat purchase and repeat engagement are separable problems at this retailer: by D90,
60% of purchasers return but only 27% buy again, a 33pp gap stable from D14 onward.
Every signal this project has found for repeat purchase is weak, so the targeting
question cannot be answered by propensity alone — it requires estimating who would
RESPOND to an intervention, which observational data cannot do (nb07/nb08).

The second clause of the original spine still stands and is still to be tested: the
users most likely to churn are not necessarily the users who would respond to an
intervention. Negative results are acceptable and must be reported honestly, not hidden.

### SPINE-1 — the depth proxy failed, the hypothesis did not
Original first clause: *"Repeat purchase is driven more by user behavior and
category/journey characteristics than by simple first-order value."*

**Status: REVISED 2026-09-21. Labelled FALSIFIED on 2026-09-14; that over-claimed.**
Both the label and the numbers under it are corrected below, and the correction is
recorded rather than silently applied.

**What 02 §5 tested** — one behavioural proxy (first-session event count) against one
monetary proxy (first-order value), as value-boundary quintiles, by Cramér's V, with a
2,000-resample bootstrap CI on ΔV = V(depth) − V(value):

| horizon | value | depth | category | ΔV (depth − value) | 95% CI | verdict |
|---|---|---|---|---|---|---|
| D30 | 0.0895 | 0.0897 | 0.0616 | +0.0002 | [−0.0078, +0.0080] | **tie** |
| D60 | 0.1154 | 0.1110 | 0.0775 | −0.0044 | [−0.0123, +0.0036] | **tie** |
| D90 | 0.1310 | 0.1194 | 0.0872 | −0.0116 | [−0.0217, −0.0023] | value ahead |

Depth is **never** ahead. D30 and D60 are ties — the CI spans zero, so the data does not
order them and nothing may quote an ordering from those horizons. Only D90 separates,
and narrowly.

*Two corrections to the 2026-09-14 table, both from the same cause.* It read
`D30 0.0895 / 0.0894`, `D60 0.1154 / 0.1108`, `D90 0.1310 / 0.1197` and called D30 a
"dead heat" off a 0.0001 gap. The quintile cut was `pd.qcut(x.rank(method="first"), 5)`,
which breaks ties by row position — and row position came from a DuckDB `fetchdf()`, so
the numbers moved between runs. The cut is now on value boundaries, and "tie" is a
bootstrap CI rather than an eyeball.

**What 06 found on the same outcome** — a broader behavioural block beats first-order
information, in both ladder orders:

| | standalone test ROC | χ² entering first | χ² entering last |
|---|---|---|---|
| M3 pre-t0 browsing | **0.6192** | 1598.1 (df 25) | 926.7 (df 25, after M1+M2) |
| M1 first order | 0.5852 | 1118.8 (df 18) | 496.9 (df 18, after M3) |

M3 is ahead both ways round: it buys more entering first, and it still buys more
entering after M1 than M1 buys entering after it.

**The accurate statement.** First-session depth — the proxy 02 tested — does not beat
first-order value. But pre-purchase browsing volume does. So *"behaviour beats value"* is
**not falsified in general**: the specific proxy failed and a broader behavioural measure
succeeded. All signals are weak (V ≈ 0.09–0.13; standalone ROC 0.57–0.62; the shipped
model 0.6278). Do not quote "SPINE-1 FALSIFIED". Full record, including why the two
results do not contradict each other, in `handoff_params.json → spine_hypothesis_status`
and its `reconciliation_with_06`.

### Leakage rule arising from 02 §0E (binding on nb05)
No feature may be derived from a cart-abandonment type whose definition references the
outcome window. Under the leaky spec `deferred_intent` scored OR=10.81; with disjoint
classification/outcome windows the same type scores below the baseline and the ranking
inverts. Only abandonment *volume* survives as a predictor. See
`handoff_params.json → leakage_rules_for_05`.

## Datasets
- Primary: REES46 "eCommerce Events History in Cosmetics Shop" — 5 monthly CSVs
  (2019-Oct through 2020-Feb) in data/raw/. Schema: event_time, event_type
  (view/cart/remove_from_cart/purchase), product_id, category_id, category_code,
  brand, price, user_id, user_session. No order_id — must be reconstructed.
  user_id is cookie-scoped, not account-scoped — treat every retention/repeat
  number as a LOWER BOUND and say so.
- Experimentation module: Criteo Uplift Prediction dataset (real randomized
  incrementality test, ~14M rows) in data/raw/criteo/. Used ONLY in 07 to validate
  experiment-analysis methodology and the risk-vs-uplift targeting argument.

## Notebook architecture (build ONE at a time, in order, only when told to)
00_data_quality.ipynb      — already built, in notebooks/. RUN IT, don't rebuild it.
01_funnel.ipynb            — session+user funnel, first-time vs returning, cart-abandonment typing
02_cohorts_retention.ipynb — activity + purchase retention curves, cohort triangle, promo vs organic
03_churn_definition.ipynb  — empirical threshold from inter-purchase intervals, FP/recall validation
04_segmentation.ipynb      — RFM + behavioral clustering, cluster stability check, RFM x cluster cross-tab
05_features.ipynb          — leakage-safe feature table, forbidden-feature list documented
06_modelling.ipynb         — logistic baseline, nested LR-test comparison, LightGBM, calibration, SHAP
07_criteo_experiment.ipynb — SRM, balance, ATE, ITT vs TOT, uplift/CATE, Qini, policy comparison
08_experiment_design.ipynb — REES46 intervention DESIGN only (no randomized data exists for it)
09_impact.ipynb            — ROI chain with DATA-DERIVED values vs ASSUMPTIONS kept visually separate

Plus: sql/ (versioned .sql per model), dashboard/, README.md

## Non-negotiable principles
1. Primary retention metric = PURCHASE retention, not activity retention (report both, primary is purchase).
2. Churn threshold is DERIVED from inter-purchase interval percentiles, never picked as a round number.
   Validate false-positive rate and recall against future behavior. Test P75/P85/P95 sensitivity.
3. Lifecycle: 1st->2nd->3rd purchase rates, time-to-second-purchase, all censoring-aware.
4. Segmentation = RFM (interpretable baseline) + behavioral clustering (engagement/funnel/price/category).
   Validate cluster stability across time periods. Report instability as a negative result if found.
5. Explicitly find and discuss RFM/cluster DISAGREEMENT cells — especially high-value-but-at-risk users.
6. ML target: repeat_purchase_30d (or whatever horizon nb00 certified as viable). Chronological split,
   never random. Nested model comparison (M0 baseline -> M1 first-order -> M2 first-session behavior ->
   M3 pre-purchase behavior) with likelihood-ratio tests between each step.
7. Evaluate with PR-AUC, Average Precision, calibration/Brier, decile lift. ROC-AUC secondary only.
8. SHAP is supporting evidence, never the main analysis.
9. Leakage: document every forbidden feature explicitly (no outcome-window aggregates, use
   .shift().expanding() for any rolling category/product stat).
10. REES46 has NO randomized experiment. Never call it an A/B test. Nb08 is a DESIGN, not a result.
11. Criteo IS the genuine randomized experiment. Use it to show risk-targeting != uplift-targeting.
12. Every stat test: report EFFECT SIZE + CI, not just p-value. Datasets are large — p-values alone
    are close to meaningless at this n.
13. Business impact: separate DATA-DERIVED values from ASSUMPTIONS in every calculation, visually.
14. Every final recommendation answers: what should the business DO, why, expected impact, cost,
    risk, how to test it.

## Working conventions
- SQL engine: DuckDB, local, over the raw CSVs (no BigQuery needed for this project — data is local).
- Visualization style: matplotlib. Every figure has a title via fig.text, a one-line subtitle stating
  scope/caveats, and a bottom-anchored TAKEAWAY box stating the point in one sentence. No figure
  without a takeaway. Reuse the frame()/save()/show_df()/thousands() helpers already defined in
  00_data_quality.ipynb — keep them in src/plotting.py and import them in every later notebook
  instead of redefining.
- Random seed fixed at 42 everywhere.
- DETERMINISM IS A CORRECTNESS PROPERTY, not a nicety. Two clean runs must agree at reported
  precision. Four failure modes, all documented in src/data.py connect(): (1) `row_number()`
  through a lazy view, (2) `approx_quantile`, (3) raw parallel `sum`/`avg`, (4) any of those
  used AS AN ORDERING OR BUCKETING KEY — the one that amplifies, turning a 1e-13 wobble into a
  whole rank step. Rules: `quantile_cont` not `approx_quantile`; materialise anything carrying a
  synthetic row id; every `ORDER BY`/`sort_values`/rank key must be UNIQUE (the orders key is
  `user_id, user_session, order_ts` — never just the first two); `key_round()`/`sig_round()`
  before a float is used as a rank, cut or digitize key; canonical row order before any
  positional resampling. Never write a wall-clock time or a measurement-of-non-determinism into
  a CSV or a handoff leaf — the audit tables are the one place those belong.
- Never silently drop rows. Every cleaning rule goes in outputs/tables/data_quality_audit.csv with
  rows affected, %, reason, implication (00 already does this — extend the same pattern).
- Read outputs/handoff_params.json at the start of every notebook after 00 — it carries the
  certified order-reconstruction rule, primary retention horizon, and churn threshold candidates
  forward. Do not re-derive these; use what 00 certified, or explicitly say why you're overriding it.
- One notebook per session unless told otherwise. Do not build ahead of what's been asked for.
- Commit after each notebook passes: `git add -A && git commit -m "nb0X: <one line>"`.

## Tone in generated markdown/READMEs
Plain, direct, interview-ready. State the finding, then the evidence, then the caveat. No filler,
no consulting jargon, no hedging language. If a hypothesis fails, say it failed and say why that's
still a useful result.