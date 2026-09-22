"""Acquisition & cohorts -- the triangle, and the Black Friday contrast."""

from __future__ import annotations

import matplotlib
import numpy as np
import pandas as pd
import streamlit as st

from lib.load import H, extract
from lib.style import BLUE, GREY, ORANGE, RED, chart, frame, page_header

page_header(
    "Acquisition & cohorts",
    "Purchase cohorts by month of first order. The rule that governs this whole page: a cohort appears at "
    "a bucket only if its <em>last</em> joiner has that many trailing days of observation. An ineligible "
    "cell is blank, never zero.",
    "02_cohorts_retention, via marts.mart_cohort_retention",
)

tri = extract("cohort_retention")
pooled = extract("retention_pooled")

metric_choice = st.radio(
    "Retention definition",
    ["Purchase retention (primary)", "Activity retention (superset)"],
    horizontal=True, label_visibility="collapsed",
)
is_purchase = metric_choice.startswith("Purchase")
col = "purchase_retention_pct" if is_purchase else "activity_retention_pct"
ret_col = "purchase_returners" if is_purchase else "activity_returners"
hue = BLUE if is_purchase else ORANGE

# ----------------------------------------------------------------------------------
st.header("The cohort triangle")

wide = tri.pivot(index="cohort_month", columns="bucket_day", values=col)
n_wide = tri.pivot(index="cohort_month", columns="bucket_day", values="eligible_n")
cohort_n = tri.groupby("cohort_month").cohort_n_users.max()
trailing = tri.groupby("cohort_month").min_trailing_days.max()

fig, ax = frame(figsize=(10, 3.9))
data = np.ma.masked_invalid(wide.values)
cmap = matplotlib.colormaps["Blues" if is_purchase else "Oranges"].copy()
cmap.set_bad(GREY)  # ineligible cells are GREY, never the colour of a zero
ax.imshow(data, cmap=cmap, aspect="auto", vmin=0,
               vmax=float(np.nanmax(wide.values)) * 1.15)
for i in range(wide.shape[0]):
    for j in range(wide.shape[1]):
        v = wide.values[i, j]
        if np.isnan(v):
            ax.text(j, i, "not yet\nobservable", ha="center", va="center",
                    fontsize=7.5, color="#4a4a4a", style="italic")
        else:
            dark = v > float(np.nanmax(wide.values)) * 0.62
            ax.text(j, i, f"{v:.1f}%", ha="center", va="center", fontsize=9,
                    color="white" if dark else "#20242b")
ax.set_xticks(range(wide.shape[1]))
ax.set_xticklabels([f"D{int(b)}" for b in wide.columns])
ax.set_yticks(range(wide.shape[0]))
ax.set_yticklabels([f"{m[:7]}  (n={int(cohort_n[m]):,})" for m in wide.index])
ax.set_xlabel("Days since the cohort's first order")
ax.tick_params(length=0)
for s in ax.spines.values():
    s.set_visible(False)
chart(
    fig,
    title=f"{'Purchase' if is_purchase else 'Activity'} retention by acquisition cohort",
    subtitle="Cohort = month of first order. Grey cells are not zero -- the cohort's last joiner has not "
             "been observed that long, so the rate is not yet measurable.",
    takeaway=f"Later cohorts retain worse at every bucket that all of them reach: at D14, "
             f"{wide.iloc[0][14]:.1f}% for the October cohort against {wide.iloc[-1][14]:.1f}% for January. "
             f"The February cohort is absent entirely -- it has no trailing window at all.",
    source="cohort_retention.parquet, from marts.mart_cohort_retention",
)

left, right = st.columns([0.55, 0.45])
with left:
    st.subheader("Why cells go missing")
    st.markdown(
        "The alternative &mdash; filling an unobserved cell with 0, or with a partial denominator "
        "&mdash; would make the most recent cohorts look like the worst ones. This project "
        "excludes them instead, which is why `eligible_n` **falls** as the horizon lengthens:"
    )
    elig = pooled[["bucket_day", "n_cohorts", "eligible_n"]].copy()
    elig.columns = ["Bucket (days)", "Cohorts contributing", "Users in the denominator"]
    st.dataframe(elig, hide_index=True, width="stretch")
with right:
    st.subheader("Cohort windows")
    cw = pd.DataFrame({
        "Cohort": [m[:7] for m in cohort_n.index],
        "First-time buyers": cohort_n.values,
        "Trailing days for the last joiner": trailing.values,
    })
    st.dataframe(cw, hide_index=True, width="stretch")
    st.caption(
        "The trailing window is measured on the LAST joiner, not on the average user. That is what "
        "makes a cohort's rate at a bucket measurable or not."
    )

# ----------------------------------------------------------------------------------
st.header("Black Friday week against everyone else")

bf = extract("black_friday_retention")
d60 = bf.loc[bf.bucket_day == 60].iloc[0]
d7 = bf.loc[bf.bucket_day == 7].iloc[0]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Acquired in the spike week", f"{int(d60.bf_n):,}",
          help="First order on one of the 7 days the discount detector flagged.")
m2.metric("Everyone else, same cohorts", f"{int(d60.rest_n):,}")
m3.metric("D60 gap", f"{d60.gap_pp:+.2f} pp",
          delta=f"{d60.bf_pct:.1f}% vs {d60.rest_pct:.1f}%", delta_color="off")
m4.metric("Detected without a calendar", f"{int(H('black_friday_cohort.n_spike_days'))} days",
          help="The detector compares each purchased line's price to that product's own median. "
               "It was given no calendar input and isolated the week on price dispersion alone.")

fig, ax = frame(figsize=(10, 4.4))
ax.plot(bf.bucket_day, bf.rest_pct, marker="o", color=BLUE, lw=2, label="Rest of the window")
ax.plot(bf.bucket_day, bf.bf_pct, marker="o", color=RED, lw=2, label="Black Friday week")
ax.fill_between(bf.bucket_day, bf.bf_pct, bf.rest_pct, color=RED, alpha=0.09)
ax.set_xticks(list(bf.bucket_day))
ax.set_xlabel("Days since first order")
ax.set_ylabel("% placing a further order")
ax.grid(axis="y", lw=0.6)
ax.legend(loc="upper left")
chart(
    fig,
    title="The discount week bought worse customers, and the gap widened",
    subtitle="One fixed population -- the cohorts eligible at D90 -- held constant across every bucket, so "
             "the trajectory is behaviour rather than a change in who is being measured.",
    takeaway=f"The Black Friday cohort starts {abs(d7.gap_pp):.1f} pp behind at D7 and is "
             f"{abs(d60.gap_pp):.1f} pp behind by D60. The gap widens rather than closing, which is the "
             f"opposite of what a \"they just need time\" reading would predict. Associational, and about "
             f"one trading week.",
    source="black_friday_retention.parquet, from marts.dim_users x marts.fct_orders; "
           "gap reconciled against handoff black_friday_cohort.gap_pp",
)

show = bf.copy()
show.columns = ["Bucket (days)", "BF n", "BF returners", "BF %", "Rest n", "Rest returners",
                "Rest %", "Gap (pp)", "Gap 95% lo", "Gap 95% hi"]
st.dataframe(
    show, hide_index=True, width="stretch",
    column_config={c: st.column_config.NumberColumn(format="%.2f")
                   for c in ["BF %", "Rest %", "Gap (pp)", "Gap 95% lo", "Gap 95% hi"]},
)
st.caption(
    "The gap reconciles to the certified `black_friday_cohort.gap_pp` at every bucket 02 published. "
    "The interval is Newcombe's, computed in the extract; it is the one number on this page the "
    "notebooks did not themselves publish."
)

st.info(
    f"**What this is not.** {H('black_friday_cohort.interpretation_limit')}",
    icon=":material/info:",
)
