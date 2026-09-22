"""Monitoring -- daily KPIs against a trailing robust baseline."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import streamlit as st
from matplotlib.ticker import FuncFormatter

from lib.load import H, extract
from lib.style import (BLUE, GREEN, GREY, ORANGE, RED, chart, frame,
                       page_header, thousands)

page_header(
    "Monitoring",
    "Daily KPIs with a rolling robust baseline. The rule is the same family as the discount detector in "
    "02 &mdash; median plus or minus 3 &times; 1.4826 &times; MAD &mdash; but made causal: the window is "
    "trailing and excludes the day it is scoring, so the flag is something that could actually run "
    "the morning after.",
    "mart_kpi_anomalies, built on mart_daily_kpis",
)

an = extract("kpi_anomalies")
kpi_daily = extract("daily_kpis")

win = int(an.baseline_window_days.iloc[0])
minb = int(an.min_baseline_days.iloc[0])
mult = float(an.mad_multiplier.iloc[0])

flagged_days = an[an.is_anomaly == True].activity_date.nunique()  # noqa: E712
bf_days = an[(an.is_anomaly == True)  # noqa: E712
             & (an.activity_date >= "2019-11-21") & (an.activity_date <= "2019-11-30")]

k1, k2, k3, k4 = st.columns(4)
k1.metric("KPIs monitored", f"{an.kpi.nunique()}")
k2.metric("Days with at least one flag", f"{flagged_days}",
          delta=f"of {an.activity_date.nunique()} days", delta_color="off")
k3.metric("Flags in Black Friday week", f"{bf_days.activity_date.nunique()} days",
          help="2019-11-21 to 2019-11-30. This span is the dbt layer's independent validation of the rule: "
               "handoff's discount detector found it from PRICE dispersion with no calendar input; this "
               "one finds it from volume and value series and knows nothing about price.")
k4.metric("Rule", f"median +/- {mult:.0f} x 1.4826 x MAD",
          help=f"Trailing {win}-day window, exclusive of the day itself, requiring at least {minb} "
               f"prior days.")

st.success(
    f"**Independent validation.** `mart_kpi_anomalies` flags "
    f"**{bf_days.activity_date.nunique()} of the 10 days** in the "
    f"{H('black_friday_cohort.spike_day_span.0')} to {H('black_friday_cohort.spike_day_span.1')} span that "
    f"02's price-dispersion detector independently identified as the discount week &mdash; using different "
    f"inputs, a different statistic and no calendar. A dbt test asserts this and fails the build if the "
    f"monitor stops seeing the largest trading event in the window.",
    icon=":material/verified:",
)

# ----------------------------------------------------------------------------------
st.header("One series at a time")

labels = (an[["kpi", "kpi_label"]].drop_duplicates().sort_values("kpi_label"))
choice = st.selectbox("KPI", labels.kpi_label.tolist(),
                      index=labels.kpi_label.tolist().index("Orders"))
s = an[an.kpi_label == choice].sort_values("activity_date").reset_index(drop=True)
unit = s.kpi_unit.iloc[0]
src = s.kpi_source_model.iloc[0]

scored = s[s.not_evaluable_reason.isna()]
unscored = s[s.not_evaluable_reason.notna()]
hits = scored[scored.is_anomaly == True]  # noqa: E712

fig, ax = frame(figsize=(11, 4.6))
ax.fill_between(scored.activity_date, scored.baseline_lower, scored.baseline_upper,
                color=BLUE, alpha=0.10, label=f"Baseline +/- {mult:.0f} scaled MAD")
ax.plot(scored.activity_date, scored.baseline_median, color=BLUE, lw=1.2, ls="--",
        label=f"Trailing {win}-day median")
ax.plot(s.activity_date, s.kpi_value, color="#444444", lw=1.3, label=choice)
if len(unscored):
    ax.axvspan(unscored.activity_date.min(), unscored.activity_date.max(),
               color=GREY, alpha=0.16, zorder=0)
    ax.text(unscored.activity_date.min(), ax.get_ylim()[1] * 0.97, " not evaluable",
            fontsize=8, color="#5a5a5a", va="top")
hi = hits[hits.anomaly_direction == "high"]
lo = hits[hits.anomaly_direction == "low"]
ax.scatter(hi.activity_date, hi.kpi_value, s=48, color=RED, zorder=6, label="Flagged high")
ax.scatter(lo.activity_date, lo.kpi_value, s=48, color=ORANGE, zorder=6, label="Flagged low")
ax.axvspan(pd.Timestamp("2019-11-21"), pd.Timestamp("2019-11-30"), color=GREEN, alpha=0.07, zorder=0)
ax.text(pd.Timestamp("2019-11-21"), ax.get_ylim()[0], " Black Friday week", fontsize=8,
        color="#2F6B45", va="bottom")
if unit == "count":
    ax.yaxis.set_major_formatter(FuncFormatter(thousands))
ax.set_ylabel({"count": "Count", "percent": "%", "eur": "EUR"}[unit])
ax.grid(axis="y", lw=0.6)
ax.legend(loc="upper right", ncol=2, fontsize=8)
fig.autofmt_xdate(rotation=0, ha="center")

n_hits = len(hits)
first_gap = "" if len(unscored) == 0 else (
    f" The first {len(unscored)} day(s) are grey because the rule has no baseline to test them against "
    f"-- an unmonitored day is not a clean one, so it carries no flag rather than a passing one.")
chart(
    fig,
    title=f"{choice}: {n_hits} flagged day{'s' if n_hits != 1 else ''} in "
          f"{s.activity_date.nunique()} days",
    subtitle=f"Trailing {win}-day window ending the day BEFORE each point, so no day contributes to its "
             f"own baseline. Requires at least {minb} prior days.",
    takeaway=(f"{choice} is flagged on {n_hits} day(s), "
              f"{len(hits[(hits.activity_date >= '2019-11-21') & (hits.activity_date <= '2019-11-30')])} "
              f"of them inside Black Friday week." + first_gap)
    if n_hits else
    f"{choice} never leaves the band. A KPI with no flags is a result, not an empty chart.{first_gap}",
    source=f"kpi_anomalies.parquet, from marts.mart_kpi_anomalies (series originates in marts.{src})",
)

# ----------------------------------------------------------------------------------
st.header("Every KPI at once")

grid = an[an.not_evaluable_reason.isna()].pivot_table(
    index="kpi_label", columns="activity_date", values="robust_z", aggfunc="first")
order = (an[an.is_anomaly == True].groupby("kpi_label").size()  # noqa: E712
         .reindex(grid.index).fillna(0).sort_values(ascending=False).index)
grid = grid.loc[order]

# The takeaway is computed rather than written, so it cannot drift from the data: it
# names the days on which the most series flagged together, whatever those turn out to be.
_by_day = (an[an.is_anomaly == True]  # noqa: E712
           .groupby("activity_date").size().sort_values(ascending=False))
_n_kpi = an.kpi.nunique()
_WIDE = math.ceil(_n_kpi / 2)          # "half the monitored series or more"
_wide_days = _by_day[_by_day >= _WIDE]
_wide_in_bf = int(((_wide_days.index >= pd.Timestamp("2019-11-21"))
                   & (_wide_days.index <= pd.Timestamp("2019-11-30"))).sum())
_top_line = (
    f"{len(_wide_days)} days move {_WIDE} or more of the {_n_kpi} series at once and "
    f"{_wide_in_bf} of them fall inside Black Friday week. The widest are "
    + ", ".join(f"{d.date()} ({n} of {_n_kpi})" for d, n in _by_day.head(4).items())
    + ". The isolated single-series runs in December, January and February are the day-14 trigger pool "
      "echoing an acquisition spike fourteen days later, which is the pool doing what its definition says."
)

fig, ax = frame(figsize=(11, 4.2))
import matplotlib  # noqa: E402  (local: only this chart needs the colormap object)
cmap = matplotlib.colormaps["RdBu_r"].copy()
cmap.set_bad("white")
m = ax.imshow(np.ma.masked_invalid(grid.values), aspect="auto", cmap=cmap, vmin=-6, vmax=6)
ax.set_yticks(range(len(grid.index)))
ax.set_yticklabels(grid.index, fontsize=8.5)
dates = pd.to_datetime(grid.columns)
month_start = [i for i, d in enumerate(dates) if d.day == 1]
ax.set_xticks(month_start)
ax.set_xticklabels([dates[i].strftime("%b %Y") for i in month_start], fontsize=8.5)
ax.tick_params(length=0)
for sp in ax.spines.values():
    sp.set_visible(False)
cb = fig.colorbar(m, ax=ax, pad=0.012, fraction=0.022)
cb.set_label("robust z (deviation / scaled MAD)", fontsize=8)
cb.ax.tick_params(labelsize=7.5)
for i in range(len(grid.index)):
    for j, d in enumerate(dates):
        v = grid.values[i, j]
        if not np.isnan(v) and abs(v) > mult:
            ax.scatter(j, i, s=5, color="black", zorder=4)
chart(
    fig,
    title="Where the whole business moved at once",
    subtitle="Robust z for every monitored series. Black dots are flags. White columns are days with no "
             "baseline yet, or a zero-MAD window -- not days that passed.",
    takeaway=f"{_top_line}",
    source="kpi_anomalies.parquet, from marts.mart_kpi_anomalies",
)

# ----------------------------------------------------------------------------------
st.header("The flagged days")

tbl = (an[an.is_anomaly == True]  # noqa: E712
       .groupby("activity_date")
       .agg(kpis_flagged=("kpi_label", "count"),
            which=("kpi_label", lambda x: ", ".join(sorted(x))),
            max_abs_z=("robust_z", lambda x: max(abs(x))))
       .reset_index().sort_values("activity_date"))
tbl["in_black_friday_span"] = ((tbl.activity_date >= "2019-11-21") & (tbl.activity_date <= "2019-11-30"))
tbl.columns = ["Date", "KPIs flagged", "Which", "Largest |z|", "In the Black Friday span"]
st.dataframe(tbl, hide_index=True, width="stretch", height=330,
             column_config={"Largest |z|": st.column_config.NumberColumn(format="%.1f")})

with st.expander("Days the rule declines to score, and why"):
    ne = (an[an.not_evaluable_reason.notna()]
          .groupby(["kpi_label", "not_evaluable_reason"])
          .agg(days=("activity_date", "count"), first=("activity_date", "min"),
               last=("activity_date", "max")).reset_index())
    ne.columns = ["KPI", "Reason", "Days", "From", "To"]
    st.dataframe(ne, hide_index=True, width="stretch")
    st.markdown(
        f"These carry `is_anomaly = NULL`, never `false`. The first {minb} days of the series have no "
        f"baseline; the day-14 trigger pool additionally has a stretch where the trailing window is "
        f"constant at zero, so there is no scale to test a deviation against. Reporting either as "
        f"\"no anomaly\" would be reporting an absence of measurement as a clean reading."
    )

# ----------------------------------------------------------------------------------
st.header("The underlying daily table")

opts = {
    "Sessions and orders": ["n_sessions", "n_orders"],
    "Conversion, both scopes": ["conversion_rate_session_scope_pct", "conversion_rate_user_scope_pct"],
    "AOV: median and winsorised mean": ["aov_median_eur", "aov_mean_winsorised_eur"],
    "New first-time buyers": ["n_new_first_time_buyers"],
    "Day-14 trigger pool": ["day14_trigger_pool_n", "day14_trigger_pool_observable_n"],
}
pick = st.radio("Series", list(opts), horizontal=True, label_visibility="collapsed")
cols = opts[pick]

fig, ax = frame(figsize=(11, 3.8))
# Two series on one axis only when they are on the same order of magnitude. Sessions run
# at ~30,000/day and orders at ~1,000; drawn together on one scale the orders line is a
# flat smear against the bottom and the chart cannot show what its takeaway claims.
maxima = [float(kpi_daily[c].max()) for c in cols]
twin = len(cols) == 2 and max(maxima) > 5 * min(maxima)
axes = [ax, ax.twinx()] if twin else [ax] * len(cols)
handles = []
for c, colour, a in zip(cols, [BLUE, ORANGE], axes):
    (ln,) = a.plot(kpi_daily.activity_date, kpi_daily[c], lw=1.4, color=colour,
                   label=c + (" (right axis)" if twin and a is not ax else ""))
    handles.append(ln)
    if kpi_daily[c].max() > 1000:
        a.yaxis.set_major_formatter(FuncFormatter(thousands))
if twin:
    axes[1].spines["right"].set_visible(True)
    axes[1].spines["right"].set_color(ORANGE)
    axes[1].tick_params(labelsize=8, colors=ORANGE)
    ax.tick_params(axis="y", colors=BLUE)
ax.grid(axis="y", lw=0.6)
ax.legend(handles, [h.get_label() for h in handles], loc="upper left", fontsize=8.5)
fig.autofmt_xdate(rotation=0, ha="center")

TAKE = {
    "Sessions and orders": "On their own scales (orders on the right axis, ~30x smaller) the two series "
                           "track each other: the same Black Friday peak, the same New Year trough. "
                           "Traffic and demand are not decoupling anywhere in this window.",
    "Conversion, both scopes": "The two scopes track each other in shape and sit about 1.8x apart in "
                               "level, every day. That constant offset is the reason both are stored "
                               "and labelled rather than one being published as 'conversion'.",
    "AOV: median and winsorised mean": "The median and the P99-winsorised mean stay close, which is the "
                                       "point of reporting both: a raw mean would be moved by 143 bulk "
                                       "buyers taking 1.4% of revenue on 0.19% of orders.",
    "New first-time buyers": "First-time buyer inflow is what 08's trigger is sized on, and Black Friday "
                             "is a visible bulge in it -- which is why 09 uses a four-month average "
                             "rather than a peak-week rate.",
    "Day-14 trigger pool": "The observable series ENDS before the operational one does. Once the 30-day "
                           "outcome window runs past the end of the data the column is NULL, not zero -- "
                           "an unobserved window is not an empty one.",
}
chart(
    fig,
    title=pick,
    subtitle="Straight from marts.mart_daily_kpis. Nothing on this chart is recomputed by the app.",
    takeaway=TAKE[pick],
    source="daily_kpis.parquet, from marts.mart_daily_kpis",
)

st.caption(
    "Conversion appears at two labelled scopes throughout because they are different quantities with "
    "different denominators; AOV is a median and a winsorised mean, never a raw mean. Both conventions "
    "are enforced in the mart, not in this page."
)
