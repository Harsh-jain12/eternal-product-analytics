# Eternal Product Analyst Portfolio — REES46 Cosmetics + Criteo

## Central business question
Which user behaviors and first-purchase characteristics drive repeat purchase and
long-term retention, which customer segments are most valuable and at risk, and who
should actually be targeted with a retention intervention?

## Spine hypothesis (test it, do not force it)
Repeat purchase is driven more by user behavior and category/journey characteristics
than by simple first-order value, and the users most likely to churn are not
necessarily the users who would respond to an intervention. Negative results are
acceptable and must be reported honestly, not hidden.

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