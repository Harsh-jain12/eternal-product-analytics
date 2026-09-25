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
    "Everyone who bought for the first time, grouped by the month they did it. One rule governs the whole "
    "page: a month only shows a number at day 30, 60 or 90 if its <em>last</em> joiner has been watched "
    "that long. Where nobody has been, the cell stays blank &mdash; never a zero.",
    "02_cohorts_retention, via marts.mart_cohort_retention",
)

tri = extract("cohort_retention")
pooled = extract("retention_pooled")

metric_choice = st.radio(
    "What counts as coming back",
    ["Bought again (the primary metric)", "Came back at all"],
    horizontal=True, label_visibility="collapsed",
)
is_purchase = metric_choice.startswith("Bought")
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
ax.set_xlabel("Days since the first order")
ax.tick_params(length=0)
for s in ax.spines.values():
    s.set_visible(False)
chart(
    fig,
    title=f"{'Bought again' if is_purchase else 'Came back at all'}, by the month people first bought",
    subtitle="One row per month of first order. Grey cells are not zeroes -- that month's last joiner has "
             "not been watched long enough yet, so there is nothing to measure.",
    takeaway=f"Each month's intake does worse than the one before it, at every point all of them reach. At "
             f"day 14 the October cohort is at {wide.iloc[0][14]:.1f}% and January at "
             f"{wide.iloc[-1][14]:.1f}%. February is missing entirely -- the data ends before anyone in it "
             f"has had 14 days.",
    source="cohort_retention.parquet, from marts.mart_cohort_retention",
)

left, right = st.columns([0.55, 0.45])
with left:
    st.subheader("Why cells go missing")
    st.markdown(
        "Filling an unwatched cell with a zero, or with a partial count, would make the newest cohorts "
        "look like the worst ones when all that is wrong with them is that they only just arrived. They "
        "are left out instead, which is why the number of people measured **falls** as the horizon gets "
        "longer:"
    )
    elig = pooled[["bucket_day", "n_cohorts", "eligible_n"]].copy()
    elig.columns = ["Days since first order", "Months contributing", "People measured"]
    st.dataframe(elig, hide_index=True, width="stretch")
with right:
    st.subheader("How long each month has been watched")
    cw = pd.DataFrame({
        "Month": [m[:7] for m in cohort_n.index],
        "First-time buyers": cohort_n.values,
        "Days watched, for the last person to join": trailing.values,
    })
    st.dataframe(cw, hide_index=True, width="stretch")
    st.caption(
        "The clock is set by the LAST person to join the month, not the average one. That is what decides "
        "whether a month gets a number at day 30, 60 or 90."
    )

# ----------------------------------------------------------------------------------
st.header("Black Friday buyers against everyone else")

bf = extract("black_friday_retention")
d60 = bf.loc[bf.bucket_day == 60].iloc[0]
d7 = bf.loc[bf.bucket_day == 7].iloc[0]

m1, m2, m3, m4 = st.columns(4)
m1.metric("First bought in the discount week", f"{int(d60.bf_n):,}",
          help="Their first order fell on one of the 7 days the price detector flagged.")
m2.metric("First bought any other week", f"{int(d60.rest_n):,}")
m3.metric("Gap at day 60", f"{d60.gap_pp:+.2f} pp",
          delta=f"{d60.bf_pct:.1f}% vs {d60.rest_pct:.1f}%", delta_color="off")
m4.metric("Found without a calendar", f"{int(H('black_friday_cohort.n_spike_days'))} days",
          help="The detector compares what each item sold for against that item's own usual price. It was "
               "never told the date and found the week from prices alone.")

fig, ax = frame(figsize=(10, 4.4))
ax.plot(bf.bucket_day, bf.rest_pct, marker="o", color=BLUE, lw=2, label="Every other week")
ax.plot(bf.bucket_day, bf.bf_pct, marker="o", color=RED, lw=2, label="Black Friday week")
ax.fill_between(bf.bucket_day, bf.bf_pct, bf.rest_pct, color=RED, alpha=0.09)
ax.set_xticks(list(bf.bucket_day))
ax.set_xlabel("Days since first order")
ax.set_ylabel("% who bought again")
ax.grid(axis="y", lw=0.6)
ax.legend(loc="upper left")
chart(
    fig,
    title="The discount week bought worse customers, and the gap got wider",
    subtitle="The same group of people at every point -- the cohorts measurable at day 90 -- so the shape "
             "is these customers behaving, not the measured population changing underneath.",
    takeaway=f"Black Friday buyers start {abs(d7.gap_pp):.1f} pp behind at day 7 and are "
             f"{abs(d60.gap_pp):.1f} pp behind by day 60. The gap widens, which is the opposite of what "
             f"\"they just need more time\" would predict. One trading week, and a correlation.",
    source="black_friday_retention.parquet, from marts.dim_users x marts.fct_orders; "
           "gap reconciled against handoff black_friday_cohort.gap_pp",
)

show = bf.copy()
show.columns = ["Days since first order", "BF buyers", "BF bought again", "BF %", "Other buyers",
                "Other bought again", "Other %", "Gap (pp)", "Gap 95% lo", "Gap 95% hi"]
st.dataframe(
    show, hide_index=True, width="stretch",
    column_config={c: st.column_config.NumberColumn(format="%.2f")
                   for c in ["BF %", "Other %", "Gap (pp)", "Gap 95% lo", "Gap 95% hi"]},
)
st.caption(
    "The gap matches the certified `black_friday_cohort.gap_pp` at every point notebook 02 published. The "
    "confidence interval is the one number here the notebooks did not publish themselves -- it is computed "
    "in the extract, by Newcombe's method."
)

st.info(
    f"**What this does not show.** {H('black_friday_cohort.interpretation_limit')}",
    icon=":material/info:",
)
