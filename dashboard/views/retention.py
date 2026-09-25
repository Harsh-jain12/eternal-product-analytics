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
    "Two curves: how many first-time buyers come back at all, and how many buy again. Buying again is the "
    "one that counts here, and it is always the lower of the two. Then the rule this project uses to call "
    "a customer lost &mdash; 42.2 days without a purchase &mdash; where that number came from, what it "
    "catches, and the 47% of at-risk users it walks straight past.",
    "02_cohorts_retention and 03_churn_definition, via marts.mart_cohort_retention and handoff churn_definition",
)

pooled = extract("retention_pooled")
d90 = pooled.loc[pooled.bucket_day == 90].iloc[0]
d30 = pooled.loc[pooled.bucket_day == 30].iloc[0]
d14 = pooled.loc[pooled.bucket_day == 14].iloc[0]

# ----------------------------------------------------------------------------------
st.header("Both curves, and how many people are behind each point")

fig, ax = frame(figsize=(10, 4.8))
ax.plot(pooled.bucket_day, pooled.activity_retention_pct, marker="o", color=ORANGE, lw=2,
        label="Came back (any activity)")
ax.plot(pooled.bucket_day, pooled.purchase_retention_pct, marker="o", color=BLUE, lw=2,
        label="Bought again (the primary metric)")
ax.fill_between(pooled.bucket_day, pooled.purchase_retention_pct,
                pooled.activity_retention_pct, color=ORANGE, alpha=0.09)
for r in pooled.itertuples():
    ax.annotate(f"{r.gap_pp:.0f}pp", xy=(r.bucket_day, (r.activity_retention_pct + r.purchase_retention_pct) / 2),
                ha="center", fontsize=8, color="#8a6d3b")
ax.set_xticks(list(pooled.bucket_day))
ax.set_xlabel("Days since first order")
ax.set_ylabel("% of the cohort measured")
ax.set_ylim(0, 68)
ax.grid(axis="y", lw=0.6)
ax.legend(loc="upper left")

axn = ax.twinx()
axn.bar(pooled.bucket_day, pooled.eligible_n, width=2.4, color=FAINT, zorder=0)
axn.set_ylim(0, pooled.eligible_n.max() * 4.2)
axn.set_yticks([0, 50000, 100000])
axn.yaxis.set_major_formatter(FuncFormatter(thousands))
axn.set_ylabel("People measured (grey bars)", color="#9aa3ad", fontsize=8.5)
axn.tick_params(labelsize=8, colors="#9aa3ad")
ax.set_zorder(axn.get_zorder() + 1)
ax.patch.set_visible(False)

chart(
    fig,
    title="The gap opens by day 14 and never closes",
    subtitle="Pooled over the cohorts old enough to measure at each point. The grey bars are how many "
             "people sit behind each point -- they FALL at day 30 and again at day 90, because young "
             "cohorts leave the count rather than being filled in with zeroes.",
    takeaway=f"The gap is already {d14.gap_pp:.0f} pp at day 14 &mdash; {d14.activity_retention_pct:.1f}% "
             f"back on the site, {d14.purchase_retention_pct:.1f}% buying &mdash; and "
             f"{d90.gap_pp:.0f} pp by day 90. These people are not ignoring the shop. They are in it and "
             f"not buying.",
    source="retention_pooled.parquet, from marts.mart_cohort_retention; every cell reconciled against "
           "handoff retention_measured before the extract was written",
)

t = pooled.copy()
t["denominator_note"] = np.where(
    t.n_cohorts == t.n_cohorts.max(), "every cohort old enough to measure",
    t.n_cohorts.astype(str) + " cohorts -- the rest have not been watched this long")
show = t[["bucket_day", "eligible_n", "purchase_returners", "purchase_retention_pct",
          "activity_returners", "activity_retention_pct", "gap_pp", "denominator_note"]]
show.columns = ["Days since first order", "People measured", "Bought again", "Purchase %",
                "Came back", "Activity %", "Gap (pp)", "Who is in the count"]
st.dataframe(show, hide_index=True, width="stretch",
             column_config={c: st.column_config.NumberColumn(format="%.2f")
                            for c in ["Purchase %", "Activity %", "Gap (pp)"]})

orders_per_user = extract("orders_per_user")
one = orders_per_user.loc[orders_per_user.order_seq == 1].iloc[0]
st.caption(
    f"For scale: {100 * one.n_users / orders_per_user.n_users.sum():.1f}% of everyone who bought placed "
    f"exactly one order inside the window "
    f"({int(one.n_users):,} of {int(orders_per_user.n_users.sum()):,}). Some of them bought again in month "
    f"six. Five months of data cannot see that, so this share is an overstatement of one-and-done."
)

# ----------------------------------------------------------------------------------
st.header("When is a customer actually lost?")

thr = float(H("churn_definition.certified_threshold_days"))
lo_region = H("churn_definition.certified_region_days.0")
hi_region = H("churn_definition.certified_region_days.1")
specs = extract("churn_validation")
specB = specs.loc[specs.spec.str.startswith("Spec B")].iloc[0]
specA = specs.loc[specs.spec.str.startswith("Spec A")].iloc[0]

st.error(
    f"**Why {thr} days and not 30.** 30 is a round number somebody picked. {thr} days is the 75th "
    f"percentile of how long these customers actually leave between orders: three repeat buyers in four "
    f"have a typical gap shorter than that, so a buyer who has been quiet longer is behaving unlike three "
    f"quarters of the base. **Why a range and not a number.** Two methods that share no inputs both land "
    f"inside **{lo_region}&ndash;{hi_region} days**, and nothing in five months of data tells the days "
    f"inside that band apart &mdash; move the date you flag on and the number moves with it. So the band "
    f"is the honest answer and **{thr} days** is the single value everything downstream cuts at, because "
    f"04, 05 and 06 have to cut at one number to stay comparable with each other. "
    f"{H('churn_definition.identification_status.claim')}",
    icon=":material/error:",
)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Called lost after", f"{thr} days",
          help=H("churn_definition.derivation.backward_method"))
k2.metric("Defensible range", f"{lo_region:g}-{hi_region:g} days",
          help=H("churn_definition.identification_status.what_survives"))
k3.metric("At-risk users it catches", f"{specB.recall_pct:.2f}%",
          help=f"Recall, 95% CI [{specB.recall_ci_lo:.2f}%, {specB.recall_ci_hi:.2f}%]. Just over half of "
               f"the users who really do stop buying get flagged.")
k4.metric("Safe users it flags anyway", f"{specB.fp_rate_pct:.2f}%",
          help=f"False-positive rate, 95% CI [{specB.fp_ci_lo:.2f}%, {specB.fp_ci_hi:.2f}%]. Of the flags "
               f"the rule does raise, {specB.precision_pct:.2f}% are right.")

left, right = st.columns([0.52, 0.48])

with left:
    st.subheader("Where the number came from")
    st.markdown(
        f"Two methods that share no inputs land **{H('churn_definition.derivation.agreement_days')} days "
        f"apart**. That agreement is what makes the number usable; neither method alone would:\n\n"
        f"- **Backward:** {H('churn_definition.derivation.backward_method')}\n"
        f"- **Forward:** {H('churn_definition.derivation.forward_method')}\n\n"
        f"{H('churn_definition.derivation.why_this_is_the_certification')}"
    )
    cand = extract("churn_candidates")
    cshow = cand[["candidate", "threshold_days", "status"]]
    cshow.columns = ["Candidate", "Days", "What happened to it"]
    st.dataframe(cshow, hide_index=True, width="stretch")

with right:
    st.subheader("What moves the number")
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
ax.set_xlabel("Days without a purchase before a customer is called lost")
ax.grid(axis="x", lw=0.6)
chart(
    fig,
    title="Four candidates, one that works, one that cannot be tested at all",
    subtitle="Each candidate is a percentile of how long buyers typically leave between orders. The green "
             "band is where every method tried lands.",
    takeaway=f"P75 ({thr}d) is the only candidate that both works and can be checked. Cutting at the "
             f"median flags 77% of everybody, P85 catches only 36% of the at-risk users, and P95 (87.3d) "
             f"needs 174.6 days of history where 152 exist &mdash; so it was never tested on a single "
             f"user. A threshold nobody can test is not the cautious choice.",
    source="churn_candidates.parquet, from handoff churn_threshold_candidates_days",
)

# ----------------------------------------------------------------------------------
st.header("Being flagged is not the same as being at risk")

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
ax.set_xlabel("Users on the 2020-01-04 flag date")
ax.grid(axis="x", lw=0.6)
chart(
    fig,
    title="The rule flags 59% as many users as are at risk, and 10% of those flags are wrong",
    subtitle=f"Checked at the {H('churn_definition.validation.flag_date')[:10]} flag date against what "
             f"those {int(H('churn_definition.validation.evaluable_n')):,} users went on to do.",
    takeaway=f"The rule flags {int(flagged.n):,} users. {int(correct.n):,} of them really are at risk "
             f"({specB.precision_pct:.1f}% of the flags are right), and a further {int(missed.n):,} at-risk "
             f"users are never flagged. Size a campaign off the flagged list and you understate who you "
             f"could reach by {100 * (1 - flagged.n / at_risk.n):.0f}%, which is why the design in 08 and "
             f"09 sizes on the flow of users hitting day 14 instead.",
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
    pop[["quantity", "n", "note"]].rename(columns={"quantity": "Group", "n": "Users", "note": "What it is"}),
    hide_index=True, width="stretch",
)

with st.expander("The two ways the rule was checked, side by side"):
    vs = specs[["spec", "forward_window_days", "n_flagged", "recall_pct", "recall_ci_lo", "recall_ci_hi",
                "fp_rate_pct", "fp_ci_lo", "fp_ci_hi", "precision_pct", "youden_j"]]
    vs.columns = ["Check", "Days watched after", "Flagged", "Caught %", "Caught lo", "Caught hi",
                  "Wrongly flagged %", "Wrong lo", "Wrong hi", "Flags that were right %", "Youden J"]
    st.dataframe(vs, hide_index=True, width="stretch")
    st.markdown(
        f"Spec B is the one this project uses. {H('churn_definition.reasoning')}"
    )

st.warning(
    f"**The model below does not predict churn.** Under a {thr}-day rule nobody can be called lost before "
    f"day 43, and the model is trained on a 30-day window. What it predicts is whether a second order "
    f"arrives within 30 days &mdash; a different question, and it is never labelled as churn anywhere in "
    f"this project. {H('modelling.target_naming')}",
    icon=":material/label_off:",
)

# ----------------------------------------------------------------------------------
st.header("How well a second purchase can be predicted at all")

mb = extract("model_baselines").sort_values("ap")
head = extract("model_headline")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Shipped model AP", f"{H('modelling.shipped_model.test_AP'):.4f}",
          delta=f"{H('modelling.shipped_model.test_AP_lift_vs_base'):.2f}x prevalence")
m2.metric("Shipped model ROC", f"{H('modelling.shipped_model.test_ROC_AUC'):.4f}",
          delta=f"ceiling for one feature was {H('features.univariate_ceiling.max_auc'):.4f}")
m3.metric("Top decile lift", f"{H('modelling.shipped_model.decile1_lift'):.2f}x",
          help=f"Top 3 deciles capture {H('modelling.shipped_model.top3_decile_capture_pct')}% of repeats.")
m4.metric("What ONE plain count recovers",
          f"{H('modelling.baselines.NAIVE pre_n_products alone (1 feature).pct_of_shipped_excess_AP'):.0f}%",
          help="How much of everything the 62-feature model adds over the base rate is recovered by a "
               "single number: how many different products someone browsed before their first order.")

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
ax.set_xlabel("Average precision on a second order within 30 days (the primary metric)")
ax.grid(axis="x", lw=0.6)
chart(
    fig,
    title="A 62-feature model that one count nearly matches",
    subtitle="Trained on earlier users and scored on later ones, never a random split. Average precision "
             "leads because only 11.7% of the test users buy again; ROC sits beside it as the secondary "
             "number.",
    takeaway=f"The model reaches AP {H('modelling.shipped_model.test_AP'):.4f} where guessing the base "
             f"rate gives {base_ap:.4f}. One plain count &mdash; how many different products someone "
             f"browsed before their first order &mdash; recovers "
             f"{H('modelling.baselines.NAIVE pre_n_products alone (1 feature).pct_of_shipped_excess_AP'):.0f}% "
             f"of the difference. The signal is real and it is small, and saying so is the finding.",
    source="model_baselines.parquet, from handoff modelling.baselines",
)

st.markdown(
    f"**Why this matters for targeting.** {H('modelling.operating_point.uplift_caveat')} "
    f"At the cut-off 06 settled on, the model flags {H('modelling.operating_point.flagged_pct')}% of users; "
    f"{H('modelling.operating_point.precision_pct')}% of those flags are right "
    f"({H('modelling.operating_point.precision_lift')}x the base rate), and it catches "
    f"{H('modelling.operating_point.recall_pct')}% of the users who do buy again. That ranks people by how "
    f"likely they are to buy anyway. The Experiment & impact page is about why that is not the same as "
    f"knowing who to contact."
)

with st.expander("The hypothesis this started from, and the correction it went through"):
    st.markdown(
        f"**What the project set out to test.** {H('spine_hypothesis_status.original_claim')}\n\n"
        f"**Where it stands.** {H('spine_hypothesis_status.status')}\n\n"
        f"**On the one proxy that was tested first.** {H('spine_hypothesis_status.verdict')}"
    )
    meas = H("spine_hypothesis_status.measurement")
    sp = pd.DataFrame([{
        "Horizon": h,
        "First-order value (Cramer's V)": m["value_V"],
        "First-session depth (Cramer's V)": m["depth_V"],
        "Difference (depth - value)": m["delta_V_depth_minus_value"],
        "95% CI lo": m["delta_V_ci"][0],
        "95% CI hi": m["delta_V_ci"][1],
        "Verdict": "tie" if m["tie"] else "value ahead",
    } for h, m in meas.items()])
    st.dataframe(sp, hide_index=True, width="stretch")
    st.markdown(
        f"**How both results can be true at once.** "
        f"{H('spine_hypothesis_status.reconciliation_with_06.statement')}\n\n"
        f"{H('spine_hypothesis_status.reconciliation_with_06.evidence.reading')}\n\n"
        f"**Binding.** {H('spine_hypothesis_status.reconciliation_with_06.binding')}"
    )
