"""Overview -- the project in one screen."""

from __future__ import annotations

import streamlit as st
from matplotlib.ticker import FuncFormatter

from lib.load import H, extract, scope_value
from lib.style import BLUE, ORANGE, RED, chart, frame, page_header, thousands

page_header(
    "Which first-time buyers come back, and who is worth contacting?",
    "Five months of clickstream from a cosmetics shop &mdash; every view, cart and purchase &mdash; rebuilt "
    "into orders, cohorts, segments and a repeat-purchase model. Then a real randomised experiment from "
    "Criteo, because who would <em>respond</em> to being contacted is a question this kind of data cannot "
    "answer at all. The one thing to carry away: buyers come back to browse and then don't buy again, and "
    "nothing here picks out which ones will accurately enough to target on.",
    "notebooks 00-09, the dbt metrics layer in sql/, and outputs/handoff_params.json",
)

pooled = extract("retention_pooled")
d90 = pooled.loc[pooled.bucket_day == 90].iloc[0]
d14 = pooled.loc[pooled.bucket_day == 14].iloc[0]

# ----------------------------------------------------------------------------------
st.header("The headline: coming back and buying again are different problems")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Come back at all, by day 90", f"{d90.activity_retention_pct:.0f}%",
          help="Any activity at all, in some session other than the one the first order happened in.")
c2.metric("Buy again by day 90", f"{d90.purchase_retention_pct:.0f}%",
          help="A second order. Same window, same session rule.")
c3.metric("The gap", f"{d90.gap_pp:.0f} pp",
          help="It opens by day 14 and stays open.")
c4.metric("First-time buyers measured", f"{int(d90.eligible_n):,}",
          help="A cohort only counts at day 90 if its last joiner has been watched that long. "
               "Cohorts that have not are left out, not filled in with zeroes.")

fig, ax = frame(figsize=(10, 4.6))
ax.plot(pooled.bucket_day, pooled.activity_retention_pct, marker="o", color=ORANGE,
        lw=2, label="Came back (any activity)")
ax.plot(pooled.bucket_day, pooled.purchase_retention_pct, marker="o", color=BLUE,
        lw=2, label="Bought again")
ax.fill_between(pooled.bucket_day, pooled.purchase_retention_pct,
                pooled.activity_retention_pct, color=ORANGE, alpha=0.10)
ax.annotate(f"{d90.gap_pp:.0f} pp", xy=(90, (d90.activity_retention_pct + d90.purchase_retention_pct) / 2),
            xytext=(72, 44), fontsize=10, color="#8a6d3b", fontweight="bold")
ax.set_xlabel("Days since first order")
ax.set_ylabel("% of the cohort")
ax.set_xticks(list(pooled.bucket_day))
ax.set_ylim(0, 70)
ax.grid(axis="y", lw=0.6)
ax.legend(loc="upper left")
chart(
    fig,
    title="They come back. They don't buy.",
    subtitle="Cohorts of first-time buyers, pooled over the ones old enough to measure at each point. These "
             "are cookie IDs, so one person on two devices counts twice -- both curves are floors.",
    takeaway=f"Getting people back is not the problem. {d90.activity_retention_pct:.0f}% of first-time "
             f"buyers are on the site again by day 90 and {d90.purchase_retention_pct:.0f}% have bought "
             f"again. The {d90.gap_pp:.0f} pp gap is already {d14.gap_pp:.0f} pp at day 14, so whatever "
             f"stops the second order, it is not that these people went away.",
    source="retention_pooled.parquet, from marts.mart_cohort_retention "
           "(reconciled against handoff retention_measured)",
)

st.markdown("##### Where the rest of it is")
st.markdown(
    "- **Acquisition & cohorts** &mdash; who joined when, and why the Black Friday week bought worse "
    "customers than every other week.\n"
    "- **Funnel health** &mdash; how far browsers get, counted three ways that disagree by 1.8x.\n"
    "- **Retention & churn** &mdash; both curves in full, and the 42.2-day rule that decides who counts "
    "as lost.\n"
    "- **Segments** &mdash; four behavioural groups, and why saving which group a user is in goes stale.\n"
    "- **Monitoring** &mdash; daily KPIs against a trailing baseline, and the days it refuses to score.\n"
    "- **Experiment & impact** &mdash; the test worth running, the Criteo evidence behind who it should "
    "target, and what it has to earn to pay for itself."
)

# ----------------------------------------------------------------------------------
st.header("What the data is")

scope = extract("scope")
cols = st.columns(4)
for col, mid in zip(cols, ["analysis_event_rows", "users_any_event", "purchasers", "orders"]):
    row = scope.loc[scope.id == mid].iloc[0]
    col.metric(row.label, f"{int(row.value):,}", help=row.note)

st.caption(
    f"{scope.date_min.iloc[0][:10]} to {scope.date_max.iloc[0][:10]} "
    f"&nbsp;·&nbsp; {int(scope_value('raw_event_rows')):,} event rows before bots were dropped "
    f"&nbsp;·&nbsp; {int(scope_value('bot_users_excluded')):,} bot-like users dropped "
    f"&nbsp;·&nbsp; the log carries no order id, so orders had to be rebuilt from what each session bought"
)

with st.expander("Every scope number, and where each one came from"):
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
        "claim": f"Coming back and buying again split apart inside two weeks and never converge: "
                 f"{d90.activity_retention_pct:.0f}% are back on the site by day 90 and "
                 f"{d90.purchase_retention_pct:.0f}% have bought, a {d90.gap_pp:.0f} pp gap that is "
                 f"already {d14.gap_pp:.0f} pp at day 14.",
        "caveat": "These are cookie IDs, not accounts. One person on two devices counts twice, so both "
                  "numbers are floors.",
        "tone": "neutral",
    },
    {
        "page": "Retention & churn",
        "nb": "06_modelling",
        "claim": f"Nothing predicts a second purchase well. The model that shipped reaches "
                 f"AP {H('modelling.shipped_model.test_AP'):.4f} and ROC "
                 f"{H('modelling.shipped_model.test_ROC_AUC'):.4f}, and one plain count &mdash; how many "
                 f"different products someone browsed before their first order &mdash; recovers "
                 f"{H('modelling.baselines.NAIVE pre_n_products alone (1 feature).pct_of_shipped_excess_AP'):.0f}% "
                 f"of everything the full model adds over the base rate.",
        "caveat": "A negative result, reported as one. A 62-feature model that one count nearly matches is "
                  "not a targeting engine.",
        "tone": "negative",
    },
    {
        "page": "Retention & churn",
        "nb": "02 + 06",
        "claim": "\"Behaviour beats value\" holds, but not in the form it was first tested. How deep the "
                 "first session went never beats what the first order was worth. How much someone browsed "
                 f"before buying does: standalone ROC "
                 f"{H('modelling.ladder.standalone.M3 pre-t0 browsing.test_ROC'):.4f} against "
                 f"{H('modelling.ladder.standalone.M1 first order.test_ROC'):.4f}, and it wins whether it "
                 "enters the model first or last.",
        "caveat": "This was labelled FALSIFIED until 2026-09-21. Both the over-claim and the correction "
                  "stay on the record rather than being quietly swapped.",
        "tone": "revised",
    },
    {
        "page": "Retention & churn",
        "nb": "03_churn_definition",
        "claim": f"Five months of data cannot pin down when a customer is gone. "
                 f"{H('churn_definition.certified_threshold_days')} days is what the project operates on, "
                 f"taken from the middle of a {H('churn_definition.certified_region_days.0'):g}-"
                 f"{H('churn_definition.certified_region_days.1'):g} day band, and it catches "
                 f"{H('churn_definition.validation.specB.recall_pct')}% of the users who really do go quiet "
                 f"while wrongly flagging {H('churn_definition.validation.specB.fp_rate_pct')}% of the ones "
                 f"who do not.",
        "caveat": "Catching 53% of them means the flagged list is not the at-risk list. Nothing "
                  "downstream sizes a campaign off the flag.",
        "tone": "negative",
    },
    {
        "page": "Segments",
        "nb": "04_segmentation",
        "claim": f"Four behavioural segments spread repeat rate from "
                 f"{H('segmentation.clustering.segments.Broad Deliberators.repeat_pct'):.1f}% to "
                 f"{H('segmentation.clustering.segments.Single-Mission Buyers.repeat_pct'):.1f}% on an "
                 f"outcome they were never fitted on &mdash; but only "
                 f"{H('segmentation.stability.same_cluster_pct')}% of users are still in the same segment "
                 f"two months later (kappa {H('segmentation.stability.cohens_kappa')}).",
        "caveat": "The groups come back; the people move between them. A saved segment label goes stale, "
                  "so it has to be recomputed when it is used.",
        "tone": "negative",
    },
    {
        "page": "Acquisition & cohorts",
        "nb": "02_cohorts_retention",
        "claim": f"Black Friday bought worse customers, and the gap got wider rather than closing: "
                 f"{H('black_friday_cohort.gap_pp.d7')} pp behind at day 7, "
                 f"{H('black_friday_cohort.gap_pp.d60')} pp behind at day 60, on one population held fixed.",
        "caveat": "One trading week, and a correlation. It says nothing about discounting in general.",
        "tone": "negative",
    },
    {
        "page": "Experiment & impact",
        "nb": "07_criteo_experiment",
        "claim": "On a real randomised experiment, contacting the people most likely to leave does worse "
                 "than contacting people at random. The &ldquo;most at risk first&rdquo; ranking scores a "
                 f"Qini ratio of {QINI_RISK:.2f} against {QINI_RANDOM:.2f} for a random list.",
        "caveat": "Criteo is a different business with a different outcome. The argument transfers; the "
                  "coefficient does not.",
        "tone": "positive",
    },
    {
        "page": "Experiment & impact",
        "nb": "08 + 09",
        "claim": f"The test worth running is a nudge on day 14. It pays for itself above "
                 f"{H('experiment_design.economics.break_even_lift_pp'):.2f} pp "
                 f"({H('experiment_design.economics.break_even_lift_rel_pct'):.1f}% relative), and the "
                 f"design can only reliably see "
                 f"{H('experiment_design.economics.mde_pp'):.2f} pp &mdash; "
                 f"{H('experiment_design.economics.mde_over_breakeven'):.1f}x that.",
        "caveat": "So the read-out is a three-way call against break-even rather than a significance test "
                  "against zero, and \"inconclusive\" is written into the plan in advance instead of "
                  "counting as a failure.",
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
st.header("How many browsers ever buy anything")

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
ax.set_xlabel("People reaching the step")
ax.grid(axis="x", lw=0.6)
chart(
    fig,
    title="One in fifteen browsers ever buys",
    subtitle="Counted per person, so someone who buys on their fourth visit counts once. Counted per "
             "session the bottom bar reads 3.8% instead of 6.9% -- a different question with a different "
             "answer. See Funnel health.",
    takeaway=f"{keep.iloc[-1].users_reaching_pct_of_view:.1f}% of the people who looked at anything ever "
             f"bought anything. Read that as a floor: a cookie ID splits one person across their devices, "
             f"and every extra device pushes a per-person rate down.",
    source="funnel_scopes.parquet, from marts.fct_sessions rolled up to user grain",
)

st.caption(
    "Every page says what it is counting in its subtitle. Per-person and per-session rates sit 1.8x apart "
    "at the purchase step, and mixing them up is the easiest mistake to make with this data."
)
