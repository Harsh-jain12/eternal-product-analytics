"""Retention & churn -- the two curves, and the rule that decides who is at risk."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st
from matplotlib.ticker import FuncFormatter

from lib.load import H, extract
from lib.style import (BLUE, FAINT, GREEN, GREY, ORANGE, PURPLE, RED, chart,
                       frame, page_header, thousands)

page_header(
    "Retention & churn",
    "Purchase retention is the primary metric here and activity retention is reported beside it as the "
    "superset it is. Then the churn rule: where it came from, what it catches, and the 47% of at-risk "
    "users it does not.",
    "02_cohorts_retention and 03_churn_definition, via marts.mart_cohort_retention and handoff churn_definition",
)

pooled = extract("retention_pooled")
d90 = pooled.loc[pooled.bucket_day == 90].iloc[0]
d30 = pooled.loc[pooled.bucket_day == 30].iloc[0]
d14 = pooled.loc[pooled.bucket_day == 14].iloc[0]

# ----------------------------------------------------------------------------------
st.header("The two curves, and the denominator behind each point")

fig, ax = frame(figsize=(10, 4.8))
ax.plot(pooled.bucket_day, pooled.activity_retention_pct, marker="o", color=ORANGE, lw=2,
        label="Activity retention (any event)")
ax.plot(pooled.bucket_day, pooled.purchase_retention_pct, marker="o", color=BLUE, lw=2,
        label="Purchase retention (PRIMARY)")
ax.fill_between(pooled.bucket_day, pooled.purchase_retention_pct,
                pooled.activity_retention_pct, color=ORANGE, alpha=0.09)
for r in pooled.itertuples():
    ax.annotate(f"{r.gap_pp:.0f}pp", xy=(r.bucket_day, (r.activity_retention_pct + r.purchase_retention_pct) / 2),
                ha="center", fontsize=8, color="#8a6d3b")
ax.set_xticks(list(pooled.bucket_day))
ax.set_xlabel("Days since first order")
ax.set_ylabel("% of the eligible cohort")
ax.set_ylim(0, 68)
ax.grid(axis="y", lw=0.6)
ax.legend(loc="upper left")

axn = ax.twinx()
axn.bar(pooled.bucket_day, pooled.eligible_n, width=2.4, color=FAINT, zorder=0)
axn.set_ylim(0, pooled.eligible_n.max() * 4.2)
axn.set_yticks([0, 50000, 100000])
axn.yaxis.set_major_formatter(FuncFormatter(thousands))
axn.set_ylabel("eligible_n (grey bars)", color="#9aa3ad", fontsize=8.5)
axn.tick_params(labelsize=8, colors="#9aa3ad")
ax.set_zorder(axn.get_zorder() + 1)
ax.patch.set_visible(False)

chart(
    fig,
    title="The gap opens by day 14 and never closes",
    subtitle="Pooled additively over the cohorts eligible at each bucket. The grey bars are eligible_n -- "
             "it FALLS at D30 and again at D90 because cohorts drop out of the denominator rather than "
             "being zero-filled.",
    takeaway=f"At D14 the gap is already {d14.gap_pp:.0f} pp ({d14.activity_retention_pct:.1f}% return, "
             f"{d14.purchase_retention_pct:.1f}% buy) and by D90 it is {d90.gap_pp:.0f} pp. Whatever stops "
             f"the second purchase is not an attention problem &mdash; these users are on the site.",
    source="retention_pooled.parquet, from marts.mart_cohort_retention; every cell reconciled against "
           "handoff retention_measured before the extract was written",
)

t = pooled.copy()
t["denominator_note"] = np.where(
    t.n_cohorts == t.n_cohorts.max(), "all eligible cohorts",
    t.n_cohorts.astype(str) + " cohorts -- the rest have no trailing window")
show = t[["bucket_day", "eligible_n", "purchase_returners", "purchase_retention_pct",
          "activity_returners", "activity_retention_pct", "gap_pp", "denominator_note"]]
show.columns = ["Bucket (days)", "eligible_n", "Bought again", "Purchase %",
                "Came back", "Activity %", "Gap (pp)", "Denominator"]
st.dataframe(show, hide_index=True, width="stretch",
             column_config={c: st.column_config.NumberColumn(format="%.2f")
                            for c in ["Purchase %", "Activity %", "Gap (pp)"]})

orders_per_user = extract("orders_per_user")
one = orders_per_user.loc[orders_per_user.order_seq == 1].iloc[0]
st.caption(
    f"For context on the size of the problem: {100 * one.n_users / orders_per_user.n_users.sum():.1f}% of "
    f"purchasers placed exactly one order inside the window "
    f"({int(one.n_users):,} of {int(orders_per_user.n_users.sum()):,}). Right-censored by construction "
    f"&mdash; a five-month window cannot see an order placed in month six."
)

# ----------------------------------------------------------------------------------
st.header("The churn rule")

thr = float(H("churn_definition.certified_threshold_days"))
lo_region = H("churn_definition.certified_region_days.0")
hi_region = H("churn_definition.certified_region_days.1")
specs = extract("churn_validation")
specB = specs.loc[specs.spec.str.startswith("Spec B")].iloc[0]
specA = specs.loc[specs.spec.str.startswith("Spec A")].iloc[0]

st.error(
    f"**The threshold is not identified by this dataset.** {H('churn_definition.identification_status.claim')}"
    f" &nbsp;It is quoted as the **{lo_region}&ndash;{hi_region} day region** with **{thr} days as the "
    f"operating value**, because 04, 05 and 06 have to cut at one number or their results stop being "
    f"comparable &mdash; not because the data resolves it to a decimal.",
    icon=":material/error:",
)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Operating value", f"{thr} days",
          help=H("churn_definition.derivation.backward_method"))
k2.metric("Certified region", f"{lo_region:g}-{hi_region:g} days",
          help=H("churn_definition.identification_status.what_survives"))
k3.metric("Recall", f"{specB.recall_pct:.2f}%",
          help=f"95% CI [{specB.recall_ci_lo:.2f}%, {specB.recall_ci_hi:.2f}%]. "
               f"Just over half the truly at-risk users are flagged.")
k4.metric("False-positive rate", f"{specB.fp_rate_pct:.2f}%",
          help=f"95% CI [{specB.fp_ci_lo:.2f}%, {specB.fp_ci_hi:.2f}%]. Precision {specB.precision_pct:.2f}%.")

left, right = st.columns([0.52, 0.48])

with left:
    st.subheader("Where the number came from")
    st.markdown(
        f"Two methods that share no inputs land **{H('churn_definition.derivation.agreement_days')} days "
        f"apart**, and that agreement &mdash; not either method alone &mdash; is the certification:\n\n"
        f"- **Backward:** {H('churn_definition.derivation.backward_method')}\n"
        f"- **Forward:** {H('churn_definition.derivation.forward_method')}\n\n"
        f"{H('churn_definition.derivation.why_this_is_the_certification')}"
    )
    cand = extract("churn_candidates")
    cshow = cand[["candidate", "threshold_days", "status"]]
    cshow.columns = ["Candidate", "Days", "What 03 did with it"]
    st.dataframe(cshow, hide_index=True, width="stretch")

with right:
    st.subheader("What moves it")
    st.markdown(
        f"- **Flag-date position.** {H('churn_definition.identification_status.evidence_against_precision.flag_date_drift')}\n"
        f"- **Cost asymmetry.** {H('churn_definition.identification_status.evidence_against_precision.cost_asymmetry_band')}\n\n"
        f"{H('churn_definition.identification_status.evidence_against_precision.taken_together')}"
    )
    st.info(f"**What would settle it.** {H('churn_definition.identification_status.what_would_identify_it')}",
            icon=":material/schedule:")

fig, ax = frame(figsize=(10, 3.8))
cand = extract("churn_candidates").sort_values("threshold_days")
colours = [GREEN if c == "p75" else GREY for c in cand.candidate]
ax.barh(np.arange(len(cand)), cand.threshold_days, color=colours, height=0.5)
ax.set_ylim(-0.75, len(cand) - 0.25)
ax.axvspan(lo_region, hi_region, color=GREEN, alpha=0.10, zorder=0)
ax.axvline(thr, color=GREEN, ls="--", lw=1.4)
ax.text(thr + 1.5, len(cand) - 0.55, f"operating value {thr}d", fontsize=8.5, color="#2F6B45")
ax.text((lo_region + hi_region) / 2, -0.62, f"certified region {lo_region:g}-{hi_region:g}d",
        ha="center", fontsize=8.5, color="#2F6B45")
for i, r in enumerate(cand.itertuples()):
    ax.text(r.threshold_days + 1.2, i, f"{r.candidate}  ({r.threshold_days}d)", va="center", fontsize=9)
ax.set_yticks([])
ax.set_xlim(0, 100)
ax.set_xlabel("Days of purchase silence before a user is called churned")
ax.grid(axis="x", lw=0.6)
chart(
    fig,
    title="Four candidates, one validated, one never scorable at all",
    subtitle="Candidates are percentiles of per-user median inter-purchase gaps. The green band is the "
             "region every method tried lands inside.",
    takeaway=f"P75 ({thr}d) is the only candidate that both validates and separates: the median flags 77% "
             f"of the base, P85 recalls only 36%, and P95 (87.3d) needs 174.6 days of span against the "
             f"152 available, so it was never scored on a single user. A threshold that cannot be tested "
             f"is not a conservative choice.",
    source="churn_candidates.parquet, from handoff churn_threshold_candidates_days",
)

# ----------------------------------------------------------------------------------
st.header("Flagged is not at risk")

pop = extract("churn_population").sort_values("order")
flagged = pop.loc[pop.quantity == "Flagged by the rule"].iloc[0]
at_risk = pop.loc[pop.quantity == "Truly at risk"].iloc[0]
correct = pop.loc[pop.quantity == "Correctly flagged"].iloc[0]
missed = pop.loc[pop.quantity == "At risk and missed"].iloc[0]

fig, ax = frame(figsize=(10, 3.9))
order = ["Evaluable base", "Truly at risk", "Flagged by the rule", "Correctly flagged", "At risk and missed"]
pop = pop.set_index("quantity").loc[order].reset_index()
colour = {"Evaluable base": GREY, "Truly at risk": RED, "Flagged by the rule": BLUE,
          "Correctly flagged": GREEN, "At risk and missed": PURPLE}
y = np.arange(len(pop))
ax.barh(y, pop.n, color=[colour[q] for q in pop.quantity], height=0.55)
for i, r in enumerate(pop.itertuples()):
    ax.text(r.n * 1.012, i, f"  {int(r.n):,}", va="center", fontsize=9.5)
ax.set_yticks(y)
ax.set_yticklabels(pop.quantity)
ax.invert_yaxis()
ax.set_xlim(0, pop.n.max() * 1.22)
ax.xaxis.set_major_formatter(FuncFormatter(thousands))
ax.set_xlabel("Users at the 2020-01-04 flag date")
ax.grid(axis="x", lw=0.6)
chart(
    fig,
    title="The flag returns 59% of the at-risk base, and 10% of what it returns is wrong",
    subtitle=f"Validated at flag date {H('churn_definition.validation.flag_date')[:10]} on "
             f"{int(H('churn_definition.validation.evaluable_n')):,} scorable users.",
    takeaway=f"The rule flags {int(flagged.n):,} users. {int(correct.n):,} of them are genuinely at risk "
             f"(precision {specB.precision_pct:.1f}%), and another {int(missed.n):,} at-risk users are not "
             f"flagged at all. Sizing a campaign on the flagged count understates the addressable "
             f"population by {100 * (1 - flagged.n / at_risk.n):.0f}% &mdash; which is why 08 and 09 size "
             f"on the trigger FLOW instead.",
    source="churn_population.parquet, from handoff churn_definition.addressable_population",
)

c1, c2 = st.columns([0.5, 0.5])
with c1:
    st.markdown(
        f"**The arithmetic that is easy to get wrong.** The at-risk base is "
        f"`correctly_flagged / recall` = {int(correct.n):,} / {specB.recall_pct / 100:.4f} = "
        f"**{int(at_risk.n):,}**. Dividing the *flagged* count by recall instead gives "
        f"{int(flagged.n / (specB.recall_pct / 100)):,} and double-counts the false positives. "
        f"04 applied that version inside cells and had to withdraw it."
    )
with c2:
    st.markdown(
        f"**Where the missed half sits.** {H('churn_definition.addressable_population.where_the_missed_half_sits')}"
    )

st.dataframe(
    pop[["quantity", "n", "note"]].rename(columns={"quantity": "Population", "n": "Users", "note": "What it is"}),
    hide_index=True, width="stretch",
)

with st.expander("The two validation specifications, side by side"):
    vs = specs[["spec", "forward_window_days", "n_flagged", "recall_pct", "recall_ci_lo", "recall_ci_hi",
                "fp_rate_pct", "fp_ci_lo", "fp_ci_hi", "precision_pct", "youden_j"]]
    vs.columns = ["Spec", "Forward window (d)", "Flagged", "Recall %", "Recall lo", "Recall hi",
                  "FP rate %", "FP lo", "FP hi", "Precision %", "Youden J"]
    st.dataframe(vs, hide_index=True, width="stretch")
    st.markdown(
        f"Spec B is the certified one. {H('churn_definition.reasoning')}"
    )

st.warning(
    f"**A churn label needs at least 43 days.** Under a {thr}-day rule no user can be called churned "
    f"before day {thr}, so the D30 repeat-purchase target the model is trained on is a "
    f"**repeat-purchase** target and is never labelled churn. "
    f"{H('modelling.target_naming')}",
    icon=":material/label_off:",
)

# ----------------------------------------------------------------------------------
st.header("How well repeat purchase can be predicted at all")

mb = extract("model_baselines").sort_values("ap")
head = extract("model_headline")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Shipped model AP", f"{H('modelling.shipped_model.test_AP'):.4f}",
          delta=f"{H('modelling.shipped_model.test_AP_lift_vs_base'):.2f}x prevalence")
m2.metric("Shipped model ROC", f"{H('modelling.shipped_model.test_ROC_AUC'):.4f}",
          delta=f"ceiling for one feature was {H('features.univariate_ceiling.max_auc'):.4f}")
m3.metric("Top decile lift", f"{H('modelling.shipped_model.decile1_lift'):.2f}x",
          help=f"Top 3 deciles capture {H('modelling.shipped_model.top3_decile_capture_pct')}% of repeats.")
m4.metric("Recovered by ONE raw feature",
          f"{H('modelling.baselines.NAIVE pre_n_products alone (1 feature).pct_of_shipped_excess_AP'):.0f}%",
          help="Share of the shipped model's excess average precision over prevalence that a single "
               "count of distinct products browsed before the first order recovers on its own.")

fig, ax = frame(figsize=(10, 4.2))
y = np.arange(len(mb))
colours = [GREEN if s else GREY for s in mb.is_shipped]
ax.barh(y, mb.ap, color=colours, height=0.55)
base_ap = float(mb.ap.min())
ax.axvline(base_ap, color=RED, ls="--", lw=1.2)
ax.text(base_ap + 0.002, len(mb) - 0.4, "prevalence", fontsize=8.5, color=RED)
for i, r in enumerate(mb.itertuples()):
    ax.text(r.ap + 0.003, i, f"AP {r.ap:.4f}   ROC {r.roc:.4f}", va="center", fontsize=9)
ax.set_yticks(y)
ax.set_yticklabels([m.replace("NAIVE ", "").replace("SHIPPED  ", "") for m in mb.model])
ax.set_xlim(0, mb.ap.max() * 1.55)
ax.set_xlabel("Average precision on repeat_purchase_30d (PRIMARY metric)")
ax.grid(axis="x", lw=0.6)
chart(
    fig,
    title="A 62-feature model that one count nearly matches",
    subtitle="Chronological split, test fold only. AP is the primary metric; ROC is reported beside it and "
             "is secondary, because the positive rate is 11.7% in the test fold.",
    takeaway=f"The shipped logistic model reaches AP {H('modelling.shipped_model.test_AP'):.4f} against "
             f"{base_ap:.4f} for prevalence &mdash; and a single raw feature, the count of distinct products "
             f"browsed before the first order, recovers "
             f"{H('modelling.baselines.NAIVE pre_n_products alone (1 feature).pct_of_shipped_excess_AP'):.0f}% "
             f"of that gain. The signal is real, reproducible and small, and it is reported as small.",
    source="model_baselines.parquet, from handoff modelling.baselines",
)

st.markdown(
    f"**Why this matters for targeting.** {H('modelling.operating_point.uplift_caveat')} "
    f"At the operating point 06 shipped, the rule flags {H('modelling.operating_point.flagged_pct')}% of "
    f"users at precision {H('modelling.operating_point.precision_pct')}% "
    f"({H('modelling.operating_point.precision_lift')}x the base rate) and recall "
    f"{H('modelling.operating_point.recall_pct')}%. That is a propensity ranking, and the Experiment & "
    f"impact page is about why a propensity ranking is not a targeting rule."
)

with st.expander("The SPINE-1 hypothesis, and the correction it went through"):
    st.markdown(
        f"**Original claim.** {H('spine_hypothesis_status.original_claim')}\n\n"
        f"**Status.** {H('spine_hypothesis_status.status')}\n\n"
        f"**Verdict on the proxy 02 tested.** {H('spine_hypothesis_status.verdict')}"
    )
    meas = H("spine_hypothesis_status.measurement")
    sp = pd.DataFrame([{
        "Horizon": h,
        "First-order value (Cramer's V)": m["value_V"],
        "First-session depth (V)": m["depth_V"],
        "Delta V": m["delta_V_depth_minus_value"],
        "95% CI lo": m["delta_V_ci"][0],
        "95% CI hi": m["delta_V_ci"][1],
        "Verdict": "tie" if m["tie"] else "value ahead",
    } for h, m in meas.items()])
    st.dataframe(sp, hide_index=True, width="stretch")
    st.markdown(
        f"**How it reconciles with 06.** "
        f"{H('spine_hypothesis_status.reconciliation_with_06.statement')}\n\n"
        f"{H('spine_hypothesis_status.reconciliation_with_06.evidence.reading')}\n\n"
        f"**Binding.** {H('spine_hypothesis_status.reconciliation_with_06.binding')}"
    )
