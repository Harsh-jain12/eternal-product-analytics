"""Segments -- four behavioural groups, and the reason not to store the label."""

from __future__ import annotations

import numpy as np
import streamlit as st
from matplotlib.ticker import FuncFormatter

from lib.load import H, extract
from lib.style import (BLUE, FAINT, GREEN, GREY, RED, chart, frame,
                       page_header, thousands)

page_header(
    "Segments",
    "k-means on eight standardised pre-purchase behaviour features, k=4, over the "
    f"{int(H('segmentation.population.clusterable')):,} purchasers with a behavioural profile. "
    "Aggregated profiles only &mdash; no user-level row leaves the warehouse.",
    "04_segmentation, via handoff segmentation",
)

kappa = float(H("segmentation.stability.cohens_kappa"))
same = float(H("segmentation.stability.same_cluster_pct"))
chance = float(H("segmentation.stability.chance_pct"))

st.error(
    f"**A stored segment label is not a durable customer attribute.** Only **{same}%** of users are in the "
    f"same segment two months later, against **{chance}%** expected by chance &mdash; Cohen's kappa "
    f"**{kappa}**. The *structure* reproduces (mix drift "
    f"{H('segmentation.stability.proportion_drift_tvd_pp')} pp, independent-refit ARI "
    f"{H('segmentation.stability.independent_refit_ari')}); the *membership* does not. "
    f"{H('segmentation.stability.binding_rule_for_08_09')}",
    icon=":material/sync_problem:",
)

segs = extract("segments").sort_values("repeat_pct", ascending=False)

# ----------------------------------------------------------------------------------
st.header("The four segments")

cols = st.columns(4)
for col, r in zip(cols, segs.itertuples()):
    col.metric(r.segment, f"{r.repeat_pct:.1f}%",
               delta=f"{int(r.n_users):,} users  ({r.share_pct:.1f}%)", delta_color="off",
               help=f"Repeat rate. Median basket EUR {r.basket_median_eur:.2f}; "
                    f"{r.churn_flag_pct:.1f}% carry the churn flag at the snapshot.")

fig, ax = frame(figsize=(10, 4.4))
x = np.arange(len(segs))
w = 0.38
ax.bar(x - w / 2, segs.repeat_pct, w, color=BLUE, label="Repeat rate (external to the fit)")
ax.bar(x + w / 2, segs.churn_flag_pct, w, color=GREY, label="Churn-flagged at the snapshot")
for i, r in enumerate(segs.itertuples()):
    ax.text(i - w / 2, r.repeat_pct + 1.2, f"{r.repeat_pct:.1f}", ha="center", fontsize=8.5)
    ax.text(i + w / 2, r.churn_flag_pct + 1.2, f"{r.churn_flag_pct:.1f}", ha="center", fontsize=8.5,
            color="#6b7280")
ax.set_xticks(x)
ax.set_xticklabels([s.replace(" ", "\n") for s in segs.segment], fontsize=9)
ax.set_ylabel("% of the segment")
ax.set_ylim(0, 96)
ax.grid(axis="y", lw=0.6)
ax.legend(loc="upper center", ncol=2)
chart(
    fig,
    title="A 4x spread in repeat rate on a variable that was never fitted on",
    subtitle="The eight clustering features are all pre-purchase behaviour. Repeat rate and churn flag are "
             "external to the fit, which is what makes this spread evidence rather than tautology.",
    takeaway=f"{segs.iloc[0].segment} repeat at {segs.iloc[0].repeat_pct:.1f}% and "
             f"{segs.iloc[-1].segment} at {segs.iloc[-1].repeat_pct:.1f}% &mdash; "
             f"{segs.iloc[0].repeat_pct / segs.iloc[-1].repeat_pct:.1f}x apart, on a variable the model "
             f"never saw. The segments describe something real; the next chart is about how long a "
             f"particular user stays inside one.",
    source="segments.parquet, from handoff segmentation.clustering.segments",
)

prof = segs[["segment", "n_users", "share_pct", "repeat_pct", "churn_flag_pct",
             "basket_median_eur", "churn_like"]]
prof.columns = ["Segment", "Users", "Share %", "Repeat %", "Churn-flagged %",
                "Median basket (EUR)", "Churn-like"]
st.dataframe(prof, hide_index=True, width="stretch",
             column_config={c: st.column_config.NumberColumn(format="%.2f")
                            for c in ["Share %", "Repeat %", "Churn-flagged %", "Median basket (EUR)"]})

st.caption(
    f"**Behaviour is not a proxy for value.** Across these four segments eta-squared is "
    f"{H('segmentation.clustering.separation.session_depth_eta2_FITTED')} on session depth &mdash; a "
    f"fitted feature &mdash; but only "
    f"{H('segmentation.clustering.separation.basket_value_eta2_EXTERNAL')} on median basket value, which "
    f"was not fitted. {H('segmentation.clustering.separation.verdict')}"
)

# ----------------------------------------------------------------------------------
st.header("Stability: the structure holds, the membership does not")

stab = extract("segment_stability").sort_values("order")

# Mix drift is in percentage points and the other three are agreement coefficients on
# [0, 1], so they do not belong on one axis -- an earlier version of this chart put a
# 1.54 pp drift alongside a kappa of 0.309 and made the drift look enormous. The chart
# now shows only the agreement coefficients, against the Landis-Koch bands that are how
# a kappa is read; mix drift stays in the table below, where its unit is stated.
ari = float(H("segmentation.stability.independent_refit_ari"))
kappa_ctrl = float(H("segmentation.stability.equal_window_control.cohens_kappa"))

BANDS = [(0.00, 0.20, "slight"), (0.20, 0.40, "fair"), (0.40, 0.60, "moderate"),
         (0.60, 0.80, "substantial"), (0.80, 1.00, "almost perfect")]
POINTS = [
    ("Structure: independent-refit ARI", ari, GREEN,
     "Refit from scratch on the later window -- the same four groups come back."),
    ("Membership: Cohen's kappa", kappa, RED,
     "The same USER, two months later."),
    ("Membership: equal-window control", kappa_ctrl, RED,
     "Nov-Dec vs Jan-Feb, so window length is ruled out."),
]

fig, ax = frame(figsize=(10, 3.6))
for lo, hi, name in BANDS:
    ax.axvspan(lo, hi, color=FAINT, alpha=0.55 if name in ("fair", "substantial") else 0.25, zorder=0)
    ax.text((lo + hi) / 2, 2.62, name, ha="center", fontsize=8, color="#6b7280")
for i, (label, val, colour, _note) in enumerate(POINTS):
    yy = len(POINTS) - 1 - i
    ax.plot([0, val], [yy, yy], color=colour, lw=3, solid_capstyle="round", alpha=0.35)
    ax.scatter([val], [yy], s=130, color=colour, zorder=5)
    ax.text(val + 0.022, yy, f"{val:.3f}", va="center", fontsize=10, fontweight="bold", color=colour)
ax.set_yticks(range(len(POINTS)))
ax.set_yticklabels([p[0] for p in reversed(POINTS)], fontsize=9)
ax.set_ylim(-0.6, 2.9)
ax.set_xlim(0, 1.0)
ax.set_xlabel("Agreement coefficient (0 = chance, 1 = perfect)")
ax.grid(axis="x", lw=0.6)
chart(
    fig,
    title="Almost-perfect structure, fair membership",
    subtitle="Fit on Oct-Dec, score Jan-Feb with the same clip bounds, scaler and centroids; k is not "
             "re-tuned. Bands are the conventional Landis-Koch reading of an agreement coefficient.",
    takeaway=f"Refitting the clustering from scratch on the later window recovers the same four groups "
             f"(ARI {ari:.3f}) -- but the same individual user only stays in the same segment "
             f"{same}% of the time against {chance}% by chance, a kappa of {kappa}. An equal-length "
             f"window control reproduces that ({kappa_ctrl}), so it is behaviour, not an artefact of the "
             f"window. Re-score at targeting time; do not store the label.",
    source="segment_stability.parquet, from handoff segmentation.stability",
)

st.dataframe(
    stab[["test", "value", "unit", "verdict", "note"]].rename(
        columns={"test": "Test", "value": "Value", "unit": "Unit", "verdict": "Reads as", "note": "Note"}),
    hide_index=True, width="stretch",
)

st.caption(
    f"**Known confound.** {H('segmentation.stability.known_confound')}"
)

# ----------------------------------------------------------------------------------
st.header("How many groups there really are")

ks = extract("segment_k_selection")
fig, ax = frame(figsize=(10, 3.4))
ax.plot(ks.k, ks.silhouette, marker="o", color=BLUE, lw=2)
ax.axhline(0.25, color=RED, ls="--", lw=1.2)
ax.text(ks.k.max() - 0.4, 0.253, "0.25 -- below this, no well-separated structure",
        fontsize=8.5, color=RED, ha="right")
chosen = ks.loc[ks.k == 4].iloc[0]
ax.scatter([4], [chosen.silhouette], s=110, facecolor="none", edgecolor=GREEN, lw=2, zorder=5)
ax.annotate("k=4, chosen on the elbow\nBEFORE the stability test",
            xy=(4, chosen.silhouette), xytext=(4.6, 0.225), fontsize=8.5, color="#2F6B45",
            arrowprops=dict(arrowstyle="->", color=GREEN, lw=1))
ax.set_xlabel("k")
ax.set_ylabel("Mean silhouette")
ax.set_ylim(0.15, 0.28)
ax.grid(axis="y", lw=0.6)
chart(
    fig,
    title="Every silhouette in the sweep is below 0.25",
    subtitle="k chosen on the elbow in inertia, and chosen before the stability test was run rather than "
             "after seeing it.",
    takeaway=f"There are no well-separated natural groups in this feature space. "
             f"{H('segmentation.clustering.k_selection.caveat')} These are a useful partition of a "
             f"continuum, and nothing downstream treats them as latent classes.",
    source="segment_k_selection.parquet, from handoff segmentation.clustering.k_selection",
)

# ----------------------------------------------------------------------------------
st.header("Where RFM and behaviour disagree")

st.markdown(
    f"Cramer's V between the RFM lens and the behavioural lens is "
    f"**{H('segmentation.cross_tab.cramers_v_rfm_x_cluster')}** "
    f"(**{H('segmentation.cross_tab.cramers_v_value_x_cluster')}** against the value score). "
    f"{H('segmentation.cross_tab.interpretation')} These are the cells where the two lenses point in "
    f"opposite directions &mdash; the reason to run both."
)

dis = extract("segment_disagreement").sort_values("n_users", ascending=False)

fig, ax = frame(figsize=(10, 4.2))
y = np.arange(len(dis))
ax.barh(y, dis.n_users, color=[RED if c.startswith("A") else BLUE for c in dis.cell], height=0.55)
for i, r in enumerate(dis.itertuples()):
    ax.text(r.n_users * 1.02, i, f"  {int(r.n_users):,}  ({r.pct_of_purchasers:.1f}% of purchasers)",
            va="center", fontsize=9)
ax.set_yticks(y)
ax.set_yticklabels(dis.label, fontsize=8.5)
ax.invert_yaxis()
ax.set_xlim(0, dis.n_users.max() * 1.5)
ax.xaxis.set_major_formatter(FuncFormatter(thousands))
ax.set_xlabel("Users in the cell")
ax.grid(axis="x", lw=0.6)
chart(
    fig,
    title="Six cells where RFM and behaviour disagree",
    subtitle="Red = RFM looks healthier than the behaviour does. Blue = RFM writes off users the behaviour "
             "does not.",
    takeaway=f"The two largest cells, B2 and B3, are censoring rather than disagreement -- those users "
             f"look low-value only because they are new. Among the rest, "
             f"{H('segmentation.cross_tab.headline')}",
    source="segment_disagreement.parquet, from handoff segmentation.cross_tab.disagreement_cells",
)

dshow = dis[["cell", "label", "n_users", "pct_of_purchasers", "recency_median_d",
             "monetary_median_eur", "one_order_pct", "churn_flagged", "note"]]
dshow.columns = ["Cell", "What it is", "Users", "% of purchasers", "Median recency (d)",
                 "Median spend (EUR)", "One-order %", "Churn-flagged", "Read"]
st.dataframe(dshow, hide_index=True, width="stretch",
             column_config={c: st.column_config.NumberColumn(format="%.2f")
                            for c in ["% of purchasers", "Median recency (d)", "Median spend (EUR)",
                                      "One-order %"]})

c1, c2 = st.columns(2)
with c1:
    st.info(
        f"**B1 was the obvious target, and it was the wrong one.** "
        f"{H('segmentation.cross_tab.b1_tenure_test.verdict')} "
        f"{H('segmentation.cross_tab.b1_tenure_test.implication_for_08')}",
        icon=":material/change_history:",
    )
with c2:
    st.info(
        f"**The cell 08 designs on is B3.** {H('segmentation.cross_tab.disagreement_cells.B3.note')} "
        f"{H('experiment_design.population.reconciles_with_04')}",
        icon=":material/target:",
    )

st.caption(
    f"**A withdrawn calculation, kept visible.** "
    f"{H('segmentation.cross_tab.disagreement_cells_recall_correction.what_was_wrong')} "
    f"{H('segmentation.cross_tab.disagreement_cells_recall_correction.correct_base_arithmetic')}"
)

st.caption(
    f"**RFM frequency is degenerate here.** {H('segmentation.rfm.one_order_share_pct')}% of purchasers "
    f"have exactly one order, so both F tercile boundaries land on F=1 and F is scored on natural breaks "
    f"instead. {H('segmentation.rfm.recency_tercile_is_the_churn_flag')}"
)
