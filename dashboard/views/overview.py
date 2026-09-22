"""Overview -- the project in one screen."""

from __future__ import annotations

import streamlit as st
from matplotlib.ticker import FuncFormatter

from lib.load import H, extract, scope_value
from lib.style import BLUE, ORANGE, RED, chart, frame, page_header, thousands

page_header(
    "Which first-time buyers come back, and who should actually be contacted?",
    "Five months of a cosmetics retailer's event log, rebuilt into orders, cohorts, segments and a "
    "repeat-purchase model &mdash; then a real randomised experiment borrowed from Criteo to answer the "
    "part the observational data cannot.",
    "notebooks 00-09, the dbt metrics layer in sql/, and outputs/handoff_params.json",
)

pooled = extract("retention_pooled")
d90 = pooled.loc[pooled.bucket_day == 90].iloc[0]
d14 = pooled.loc[pooled.bucket_day == 14].iloc[0]

# ----------------------------------------------------------------------------------
st.header("The headline: returning and buying are two different problems")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Come back at all, by day 90", f"{d90.activity_retention_pct:.0f}%",
          help="Any event, in a session other than the first-order session.")
c2.metric("Buy again by day 90", f"{d90.purchase_retention_pct:.0f}%",
          help="A further order, same window and same session rule.")
c3.metric("The gap", f"{d90.gap_pp:.0f} pp",
          help="Stable from day 14 onward -- it opens early and never closes.")
c4.metric("Eligible cohorts at D90", f"{int(d90.eligible_n):,}",
          help="Only cohorts whose last joiner has 90 trailing days contribute. "
               "Ineligible cohorts are excluded, never zero-filled.")

fig, ax = frame(figsize=(10, 4.6))
ax.plot(pooled.bucket_day, pooled.activity_retention_pct, marker="o", color=ORANGE,
        lw=2, label="Came back (any event)")
ax.plot(pooled.bucket_day, pooled.purchase_retention_pct, marker="o", color=BLUE,
        lw=2, label="Bought again")
ax.fill_between(pooled.bucket_day, pooled.purchase_retention_pct,
                pooled.activity_retention_pct, color=ORANGE, alpha=0.10)
ax.annotate(f"{d90.gap_pp:.0f} pp", xy=(90, (d90.activity_retention_pct + d90.purchase_retention_pct) / 2),
            xytext=(72, 44), fontsize=10, color="#8a6d3b", fontweight="bold")
ax.set_xlabel("Days since first order")
ax.set_ylabel("% of cohort")
ax.set_xticks(list(pooled.bucket_day))
ax.set_ylim(0, 70)
ax.grid(axis="y", lw=0.6)
ax.legend(loc="upper left")
chart(
    fig,
    title="They come back. They do not buy.",
    subtitle="Purchase cohorts, pooled additively over the cohorts eligible at each bucket. "
             "Cookie-scoped user_id, so both curves are lower bounds.",
    takeaway=f"By day 90, {d90.activity_retention_pct:.0f}% of first-time buyers return to the site but only "
             f"{d90.purchase_retention_pct:.0f}% place a second order -- a {d90.gap_pp:.0f} pp gap that is "
             f"already {d14.gap_pp:.0f} pp at day 14 and never closes. Re-engagement is not the binding "
             f"constraint; conversion of the already-engaged is.",
    source="retention_pooled.parquet, from marts.mart_cohort_retention "
           "(reconciled against handoff retention_measured)",
)

# ----------------------------------------------------------------------------------
st.header("What the data covers")

scope = extract("scope")
cols = st.columns(4)
for col, mid in zip(cols, ["analysis_event_rows", "users_any_event", "purchasers", "orders"]):
    row = scope.loc[scope.id == mid].iloc[0]
    col.metric(row.label, f"{int(row.value):,}", help=row.note)

st.caption(
    f"{scope.date_min.iloc[0][:10]} to {scope.date_max.iloc[0][:10]} "
    f"&nbsp;·&nbsp; {int(scope_value('raw_event_rows')):,} raw event rows before bot exclusion "
    f"&nbsp;·&nbsp; {int(scope_value('bot_users_excluded')):,} bot-like users removed "
    f"&nbsp;·&nbsp; no order_id in the source, so orders are reconstructed"
)

with st.expander("The full scope register, with a source per row"):
    st.dataframe(
        scope[["label", "value", "source_kind", "source_ref", "note"]].rename(columns={
            "label": "Metric", "value": "Value", "source_kind": "From",
            "source_ref": "Mart or handoff key", "note": "Note"}),
        hide_index=True, width="stretch",
        column_config={"Value": st.column_config.NumberColumn(format="%d")},
    )

# ----------------------------------------------------------------------------------
st.header("What the project found")

# Two handoff keys whose names contain quotes and pipes; pulled out so the f-strings
# below stay readable.
QINI_RISK = H("criteo_experiment.uplift.qini.conversion | mu0 REVERSED = 'at risk'.qini_ratio")
QINI_RANDOM = H("criteo_experiment.uplift.qini.conversion | random ranking.qini_ratio")

FINDINGS = [
    {
        "page": "Retention & churn",
        "nb": "02_cohorts_retention",
        "claim": f"Returning and re-buying separate early and stay separated: "
                 f"{d90.activity_retention_pct:.0f}% vs {d90.purchase_retention_pct:.0f}% at D90, "
                 f"a {d90.gap_pp:.0f} pp gap that is already {d14.gap_pp:.0f} pp at D14.",
        "caveat": "Cookie-scoped ids, so both numbers are lower bounds on true customer behaviour.",
        "tone": "neutral",
    },
    {
        "page": "Retention & churn",
        "nb": "06_modelling",
        "claim": f"Every signal for repeat purchase is weak. The shipped model reaches "
                 f"AP {H('modelling.shipped_model.test_AP'):.4f} and ROC "
                 f"{H('modelling.shipped_model.test_ROC_AUC'):.4f}; one raw feature on its own recovers "
                 f"{H('modelling.baselines.NAIVE pre_n_products alone (1 feature).pct_of_shipped_excess_AP'):.0f}% "
                 f"of the model's excess average precision over prevalence.",
        "caveat": "Reported as a negative result. A 62-feature model that a single count nearly matches "
                  "is not a targeting engine.",
        "tone": "negative",
    },
    {
        "page": "Retention & churn",
        "nb": "02 + 06",
        "claim": "\"Behaviour beats value\" survives in a corrected form. The one proxy 02 tested "
                 "&mdash; first-session depth &mdash; never beats first-order value. A broader "
                 f"pre-purchase browsing block does: standalone ROC "
                 f"{H('modelling.ladder.standalone.M3 pre-t0 browsing.test_ROC'):.4f} against "
                 f"{H('modelling.ladder.standalone.M1 first order.test_ROC'):.4f}, and it wins entering "
                 "the nested ladder either first or last.",
        "caveat": "This was labelled FALSIFIED until it was revised on 2026-09-21; the over-claim and the "
                  "correction are both recorded in handoff, not quietly replaced.",
        "tone": "revised",
    },
    {
        "page": "Retention & churn",
        "nb": "03_churn_definition",
        "claim": f"The churn threshold is not identified by five months of data. "
                 f"{H('churn_definition.certified_threshold_days')} days is the operating value at the "
                 f"centre of a {H('churn_definition.certified_region_days.0'):g}-"
                 f"{H('churn_definition.certified_region_days.1'):g} day region, validated at recall "
                 f"{H('churn_definition.validation.specB.recall_pct')}% and a false-positive rate of "
                 f"{H('churn_definition.validation.specB.fp_rate_pct')}%.",
        "caveat": "Recall of 53% means the flagged list is not the at-risk population. Nothing downstream "
                  "sizes a campaign on the flag.",
        "tone": "negative",
    },
    {
        "page": "Segments",
        "nb": "04_segmentation",
        "claim": f"Four behavioural segments separate repeat rate {H('segmentation.clustering.segments.Broad Deliberators.repeat_pct'):.1f}% "
                 f"to {H('segmentation.clustering.segments.Single-Mission Buyers.repeat_pct'):.1f}% on a variable "
                 f"never fitted on &mdash; but only "
                 f"{H('segmentation.stability.same_cluster_pct')}% of users stay in the same segment two "
                 f"months later (kappa {H('segmentation.stability.cohens_kappa')}).",
        "caveat": "The structure reproduces; the membership does not. A stored segment label is not a "
                  "durable customer attribute.",
        "tone": "negative",
    },
    {
        "page": "Acquisition & cohorts",
        "nb": "02_cohorts_retention",
        "claim": f"Black Friday buyers retain worse than everyone else, and the gap widens: "
                 f"{H('black_friday_cohort.gap_pp.d7')} pp at D7 to "
                 f"{H('black_friday_cohort.gap_pp.d60')} pp at D60, on one population held fixed.",
        "caveat": "Associational, and about one trading week. It is not a finding about discounting.",
        "tone": "negative",
    },
    {
        "page": "Experiment & impact",
        "nb": "07_criteo_experiment",
        "claim": "On a genuine randomised experiment, targeting by risk is worse than random. Ranking by "
                 "reversed baseline response &mdash; the &ldquo;most at risk first&rdquo; rule &mdash; "
                 f"scores a Qini ratio of {QINI_RISK:.2f} against {QINI_RANDOM:.2f} for a random list.",
        "caveat": "Criteo is a different business and a different outcome. What transfers is the shape of "
                  "the argument, not the coefficient.",
        "tone": "positive",
    },
    {
        "page": "Experiment & impact",
        "nb": "08 + 09",
        "claim": f"The recommended test is a day-14 activation nudge. It breaks even at "
                 f"{H('experiment_design.economics.break_even_lift_pp'):.2f} pp "
                 f"({H('experiment_design.economics.break_even_lift_rel_pct'):.1f}% relative), and the "
                 f"design can reliably detect only "
                 f"{H('experiment_design.economics.mde_pp'):.2f} pp &mdash; "
                 f"{H('experiment_design.economics.mde_over_breakeven'):.1f}x the break-even.",
        "caveat": "So the decision rule is three-way against break-even, not a significance test against "
                  "zero, and \"inconclusive\" is a pre-registered outcome rather than a failure.",
        "tone": "neutral",
    },
]

TONE_COLOUR = {"negative": RED, "positive": "#2F6B45", "revised": "#8a6d3b", "neutral": BLUE}

for f in FINDINGS:
    with st.container(border=True):
        left, right = st.columns([0.80, 0.20])
        left.markdown(
            f'<span style="color:{TONE_COLOUR[f["tone"]]};font-weight:600">&#9632;</span> {f["claim"]}',
            unsafe_allow_html=True,
        )
        left.caption(f"Caveat: {f['caveat']}")
        right.markdown(f"`{f['nb']}`")
        right.caption(f"See: {f['page']}")

# ----------------------------------------------------------------------------------
st.header("How far the funnel actually narrows")

funnel = extract("funnel_scopes").copy()
labels = {"view": "Viewed", "cart": "Added to cart", "remove_from_cart": "Removed from cart",
          "purchase": "Purchased"}
funnel["nice"] = funnel.stage.map(labels)
keep = funnel[funnel.stage != "remove_from_cart"]

fig, ax = frame(figsize=(10, 4.0))
y = range(len(keep))
ax.barh(list(y), keep.users_reaching, color=BLUE, height=0.55)
for i, r in enumerate(keep.itertuples()):
    ax.text(r.users_reaching * 1.01, i, f"  {int(r.users_reaching):,}  ({r.users_reaching_pct_of_view:.1f}%)",
            va="center", fontsize=9.5, color="#333333")
ax.set_yticks(list(y))
ax.set_yticklabels(keep.nice)
ax.invert_yaxis()
ax.set_xlim(0, keep.users_reaching.max() * 1.30)
ax.xaxis.set_major_formatter(FuncFormatter(thousands))
ax.set_xlabel("Users reaching the stage (USER SCOPE)")
ax.grid(axis="x", lw=0.6)
chart(
    fig,
    title="One in fifteen browsers ever buys",
    subtitle="USER scope -- a user counts once. The session-scope version of this chart reads 3.8% at the "
             "bottom instead of 6.9%; the two are not interchangeable. See Funnel health.",
    takeaway=f"{keep.iloc[-1].users_reaching_pct_of_view:.1f}% of users who viewed anything ever placed an "
             f"order. Every figure here is a lower bound: a cookie-scoped id splits one person across "
             f"devices, which can only push a per-user conversion rate down.",
    source="funnel_scopes.parquet, from marts.fct_sessions rolled up to user grain",
)

st.caption(
    "Every page states the scope of its denominator in the subtitle, because the two scopes differ by "
    "1.8x at the purchase stage and quoting one as the other is the easiest mistake in this dataset."
)
