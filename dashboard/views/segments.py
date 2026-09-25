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
    "Four groups, found by clustering on eight measures of what people did before they bought &mdash; how "
    "much they browsed, how deep they went, at what price. "
    f"{int(H('segmentation.population.clusterable')):,} purchasers had enough history to place in one. "
    "Only group-level figures are on this page; no individual user's row leaves the warehouse.",
    "04_segmentation, via handoff segmentation",
)

kappa = float(H("segmentation.stability.cohens_kappa"))
same = float(H("segmentation.stability.same_cluster_pct"))
chance = float(H("segmentation.stability.chance_pct"))

st.error(
    f"**Use a saved copy of this segment list and you will contact the wrong two users in five.** Only "
    f"**{same}%** of users are still in the same segment two months later, against **{chance}%** you would "
    f"get by assigning them at random &mdash; Cohen's kappa **{kappa}**. The four groups themselves are "
    f"solid: the mix shifts {H('segmentation.stability.proportion_drift_tvd_pp')} pp, and clustering the "
    f"later window from scratch finds the same groups again (ARI "
    f"{H('segmentation.stability.independent_refit_ari')}). It is the people who move between them. So "
    f"segment membership has to be recomputed at the moment it is used, and is never stored as a customer "
    f"attribute. {H('segmentation.stability.binding_rule_for_08_09')}",
    icon=":material/sync_problem:",
)

segs = extract("segments").sort_values("repeat_pct", ascending=False)

# ----------------------------------------------------------------------------------
st.header("The four segments")

cols = st.columns(4)
for col, r in zip(cols, segs.itertuples()):
    col.metric(r.segment, f"{r.repeat_pct:.1f}%",
               delta=f"{int(r.n_users):,} users  ({r.share_pct:.1f}%)", delta_color="off",
               help=f"Share of this group that bought again. Median basket EUR "
                    f"{r.basket_median_eur:.2f}; {r.churn_flag_pct:.1f}% carry the churn flag at the "
                    f"snapshot date.")

fig, ax = frame(figsize=(10, 4.4))
x = np.arange(len(segs))
w = 0.38
ax.bar(x - w / 2, segs.repeat_pct, w, color=BLUE, label="Bought again (held out of the fit)")
ax.bar(x + w / 2, segs.churn_flag_pct, w, color=GREY, label="Carrying the churn flag")
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
    title="Repeat rate runs 4x from one group to the next, on a number the clustering never saw",
    subtitle="All eight clustering features are pre-purchase behaviour. Whether someone bought again, and "
             "whether they carry the churn flag, were held out of the fit -- which is what makes this "
             "spread worth something rather than circular.",
    takeaway=f"{segs.iloc[0].segment} buy again {segs.iloc[0].repeat_pct:.1f}% of the time and "
             f"{segs.iloc[-1].segment} {segs.iloc[-1].repeat_pct:.1f}% &mdash; "
             f"{segs.iloc[0].repeat_pct / segs.iloc[-1].repeat_pct:.1f}x apart on an outcome the "
             f"clustering never saw. So the groups are picking up something real. The next chart is about "
             f"how long any one person stays inside one.",
    source="segments.parquet, from handoff segmentation.clustering.segments",
)

prof = segs[["segment", "n_users", "share_pct", "repeat_pct", "churn_flag_pct",
             "basket_median_eur", "churn_like"]]
prof.columns = ["Segment", "Users", "Share %", "Bought again %", "Churn-flagged %",
                "Median basket (EUR)", "Looks churn-like"]
st.dataframe(prof, hide_index=True, width="stretch",
             column_config={c: st.column_config.NumberColumn(format="%.2f")
                            for c in ["Share %", "Bought again %", "Churn-flagged %",
                                      "Median basket (EUR)"]})

st.caption(
    f"**These groups separate behaviour, not spend.** Across the four of them eta-squared is "
    f"{H('segmentation.clustering.separation.session_depth_eta2_FITTED')} on session depth &mdash; a "
    f"fitted feature &mdash; but only "
    f"{H('segmentation.clustering.separation.basket_value_eta2_EXTERNAL')} on median basket value, which "
    f"was not fitted. {H('segmentation.clustering.separation.verdict')}"
)

# ----------------------------------------------------------------------------------
st.header("The groups hold still. The people move between them.")

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
    ("Do the same groups come back?  (ARI)", ari, GREEN,
     "Clustered from scratch on the later window -- the same four groups come back."),
    ("Does one user stay put?  (Cohen's kappa)", kappa, RED,
     "The same person, two months later."),
    ("Same question, equal-length windows", kappa_ctrl, RED,
     "Nov-Dec against Jan-Feb, so the window length cannot be the explanation."),
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
    title="The groups reproduce. A given user's label does not.",
    subtitle="Clustered on Oct-Dec, then applied to Jan-Feb with the same bounds, scaler and centres; k is "
             "not re-tuned. The bands are the usual reading of an agreement score.",
    takeaway=f"Cluster the later window from scratch and the same four groups come back (ARI {ari:.3f}). "
             f"But one particular person is only in the same group {same}% of the time, against {chance}% "
             f"if you assigned at random -- a kappa of {kappa}. Equal-length windows give the same answer "
             f"({kappa_ctrl}), so this is people changing, not an artefact of measuring one window longer "
             f"than the other. Recompute membership when you target; never store it.",
    source="segment_stability.parquet, from handoff segmentation.stability",
)

st.dataframe(
    stab[["test", "value", "unit", "verdict", "note"]].rename(
        columns={"test": "Test", "value": "Value", "unit": "Unit", "verdict": "Reads as", "note": "Note"}),
    hide_index=True, width="stretch",
)

st.caption(
    f"**One known confound, stated rather than buried.** {H('segmentation.stability.known_confound')}"
)

# ----------------------------------------------------------------------------------
st.header("Whether there are four groups at all")

ks = extract("segment_k_selection")
fig, ax = frame(figsize=(10, 3.4))
ax.plot(ks.k, ks.silhouette, marker="o", color=BLUE, lw=2)
ax.axhline(0.25, color=RED, ls="--", lw=1.2)
ax.text(ks.k.max() - 0.4, 0.253, "0.25 -- below this, the groups are not cleanly separated",
        fontsize=8.5, color=RED, ha="right")
chosen = ks.loc[ks.k == 4].iloc[0]
ax.scatter([4], [chosen.silhouette], s=110, facecolor="none", edgecolor=GREEN, lw=2, zorder=5)
ax.annotate("k=4, picked on the elbow\nBEFORE the stability test was run",
            xy=(4, chosen.silhouette), xytext=(4.6, 0.225), fontsize=8.5, color="#2F6B45",
            arrowprops=dict(arrowstyle="->", color=GREEN, lw=1))
ax.set_xlabel("k")
ax.set_ylabel("Mean silhouette")
ax.set_ylim(0.15, 0.28)
ax.grid(axis="y", lw=0.6)
chart(
    fig,
    title="No number of groups separates these users cleanly",
    subtitle="k was picked on the elbow, and picked before the stability test was run rather than after "
             "seeing how it came out.",
    takeaway=f"Every silhouette in the sweep is below 0.25, which means there are no natural, "
             f"well-separated groups here to find. {H('segmentation.clustering.k_selection.caveat')} "
             f"These four are a useful way to cut a continuum, and nothing downstream treats them as real "
             f"customer types.",
    source="segment_k_selection.parquet, from handoff segmentation.clustering.k_selection",
)

# ----------------------------------------------------------------------------------
st.header("Where RFM and behaviour disagree")

st.markdown(
    f"RFM scores a customer on three things: how recently they bought, how often, and how much. It is the "
    f"standard retail lens and it says almost nothing about the behavioural one &mdash; Cramer's V between "
    f"the two is **{H('segmentation.cross_tab.cramers_v_rfm_x_cluster')}** "
    f"(**{H('segmentation.cross_tab.cramers_v_value_x_cluster')}** against the value score alone). "
    f"{H('segmentation.cross_tab.interpretation')} Below are the cells where the two point in opposite "
    f"directions, which is the whole reason to run both."
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
    title="Six cells where the two lenses disagree",
    subtitle="Red = RFM looks healthier than the behaviour does. Blue = RFM writes a user off and the "
             "behaviour does not.",
    takeaway=f"The two biggest cells, B2 and B3, are not really disagreement -- those users look low-value "
             f"because they only just arrived and the window ends before they could prove otherwise. Among "
             f"the rest, {H('segmentation.cross_tab.headline')}",
    source="segment_disagreement.parquet, from handoff segmentation.cross_tab.disagreement_cells",
)

dshow = dis[["cell", "label", "n_users", "pct_of_purchasers", "recency_median_d",
             "monetary_median_eur", "one_order_pct", "churn_flagged", "note"]]
dshow.columns = ["Cell", "What it is", "Users", "% of purchasers", "Days since last order (median)",
                 "Median spend (EUR)", "Bought once only %", "Churn-flagged", "How to read it"]
st.dataframe(dshow, hide_index=True, width="stretch",
             column_config={c: st.column_config.NumberColumn(format="%.2f")
                            for c in ["% of purchasers", "Days since last order (median)",
                                      "Median spend (EUR)", "Bought once only %"]})

c1, c2 = st.columns(2)
with c1:
    st.info(
        f"**B1 looked like the obvious group to target. It was not.** "
        f"{H('segmentation.cross_tab.b1_tenure_test.verdict')} "
        f"{H('segmentation.cross_tab.b1_tenure_test.implication_for_08')}",
        icon=":material/change_history:",
    )
with c2:
    st.info(
        f"**The group the experiment is designed around is B3.** "
        f"{H('segmentation.cross_tab.disagreement_cells.B3.note')} "
        f"{H('experiment_design.population.reconciles_with_04')}",
        icon=":material/target:",
    )

st.caption(
    f"**A calculation that was wrong, left on the page rather than deleted.** "
    f"{H('segmentation.cross_tab.disagreement_cells_recall_correction.what_was_wrong')} "
    f"{H('segmentation.cross_tab.disagreement_cells_recall_correction.correct_base_arithmetic')}"
)

st.caption(
    f"**The F in RFM does not work on this data.** {H('segmentation.rfm.one_order_share_pct')}% of "
    f"purchasers bought exactly once, so both frequency cut-points land on the same value and the score "
    f"has to be built on natural breaks instead. "
    f"{H('segmentation.rfm.recency_tercile_is_the_churn_flag')}"
)
