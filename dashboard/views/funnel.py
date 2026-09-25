"""Funnel health -- the same funnel at two scopes, side by side."""

from __future__ import annotations

import numpy as np
import streamlit as st
from matplotlib.ticker import FuncFormatter

from lib.load import extract, scope_value
from lib.style import BLUE, GREEN, ORANGE, PURPLE, chart, frame, page_header, thousands

page_header(
    "Funnel health",
    "The same four steps &mdash; viewed, added to cart, removed, bought &mdash; counted three ways: per "
    "event, per visit and per person. They disagree by up to 1.8x at the purchase step, and which one ends "
    "up on a slide changes what the number means. So they are shown together rather than one being picked.",
    "01_funnel, via marts.fct_sessions",
)

funnel = extract("funnel_scopes").copy()
NICE = {"view": "Viewed", "cart": "Added to cart", "remove_from_cart": "Removed from cart",
        "purchase": "Purchased"}
funnel["nice"] = funnel.stage.map(NICE)
purchase = funnel.loc[funnel.stage == "purchase"].iloc[0]

st.warning(
    "**Every per-person figure on this page is a floor.** These are cookie IDs, not accounts: one person on "
    "a phone and a laptop counts as two people. That adds people who never bought to the bottom of every "
    "per-person rate, which can only push the rate down. Counting per visit avoids this, but it is not "
    "therefore the safer number &mdash; it answers a different question.",
    icon=":material/warning:",
)

# ----------------------------------------------------------------------------------
st.header("Per visit and per person, side by side")

c1, c2, c3 = st.columns(3)
c1.metric("Counted per event", f"{purchase.raw_events_pct_of_view:.2f}%",
          help="Purchase rows as a share of view rows. Repeated clicks and multi-item orders both inflate "
               "it. It is here because this is what you get if you just count events.")
c2.metric("Counted per visit", f"{purchase.sessions_reaching_pct_of_view:.2f}%",
          help="Visits that contained a purchase, out of visits that contained a view.")
c3.metric("Counted per person", f"{purchase.users_reaching_pct_of_view:.2f}%",
          help="People who ever bought, out of people who ever looked. A floor, because of the cookie ID "
               "problem above.")

ratio = purchase.users_reaching_pct_of_view / purchase.sessions_reaching_pct_of_view

fig, ax = frame(figsize=(10, 4.6))
stages = funnel.sort_values("stage_order")
x = np.arange(len(stages))
w = 0.38
ax.bar(x - w / 2, stages.sessions_reaching_pct_of_view, w, color=BLUE, label="Per visit")
ax.bar(x + w / 2, stages.users_reaching_pct_of_view, w, color=ORANGE, label="Per person")
for i, r in enumerate(stages.itertuples()):
    ax.text(i - w / 2, r.sessions_reaching_pct_of_view + 1.4, f"{r.sessions_reaching_pct_of_view:.1f}",
            ha="center", fontsize=8.5, color=BLUE)
    ax.text(i + w / 2, r.users_reaching_pct_of_view + 1.4, f"{r.users_reaching_pct_of_view:.1f}",
            ha="center", fontsize=8.5, color=ORANGE)
ax.set_xticks(x)
ax.set_xticklabels(stages.nice)
ax.set_ylabel("% of those who viewed")
ax.set_ylim(0, 112)
ax.grid(axis="y", lw=0.6)
ax.legend(loc="upper right")
chart(
    fig,
    title="The same funnel, two denominators, two different stories",
    subtitle="Both start at 100 at 'Viewed'. Per visit asks what one trip to the site does; per person asks "
             "what someone does in the end.",
    takeaway=f"At the purchase step, counting per person reads "
             f"{purchase.users_reaching_pct_of_view:.2f}% and counting per visit reads "
             f"{purchase.sessions_reaching_pct_of_view:.2f}% &mdash; {ratio:.1f}x apart. Someone who "
             f"browses across five visits and buys on one is 20% one way and 100% the other. Neither is "
             f"wrong. Quoting one as the other is.",
    source="funnel_scopes.parquet, from marts.fct_sessions (rolled up to user grain for the user scope)",
)

tab = funnel.sort_values("stage_order")[[
    "nice", "raw_events", "sessions_reaching", "users_reaching",
    "raw_events_pct_of_view", "sessions_reaching_pct_of_view", "users_reaching_pct_of_view"]]
tab.columns = ["Step", "Event rows", "Visits reaching", "People reaching",
               "Per event %", "Per visit %", "Per person %"]
st.dataframe(
    tab, hide_index=True, width="stretch",
    column_config={c: st.column_config.NumberColumn(format="%.2f")
                   for c in ["Per event %", "Per visit %", "Per person %"]},
)
st.caption(
    "Event rows are **not** deduplicated, on purpose. The data-quality audit found the 10.4% of rows that "
    "look like exact duplicates are real repeated clicks logged to the nearest second, and the 0.07% "
    "repeated purchase lines are quantity. So duplicates get handled by choosing what to count -- the two "
    "right-hand columns -- rather than by deleting rows."
)

# ----------------------------------------------------------------------------------
st.header("A first visit against a repeat visit")

ft = extract("funnel_first_time_vs_returning").copy()
ft["label"] = ft.user_type.map({"first_time": "First visit", "returning": "Repeat visit"})
first = ft.loc[ft.user_type == "first_time"].iloc[0]
ret = ft.loc[ft.user_type == "returning"].iloc[0]

a, b, c = st.columns(3)
a.metric("A first visit buys", f"{first.conv_rate_pct:.2f}%",
         help=f"95% confidence interval [{first.ci_low_pct:.2f}%, {first.ci_high_pct:.2f}%] "
              f"over {int(first.n_sessions):,} visits.")
b.metric("A repeat visit buys", f"{ret.conv_rate_pct:.2f}%",
         help=f"95% confidence interval [{ret.ci_low_pct:.2f}%, {ret.ci_high_pct:.2f}%] "
              f"over {int(ret.n_sessions):,} visits.")
c.metric("Difference", f"{ret.conv_rate_pct / first.conv_rate_pct:.2f}x",
         help="Repeat visits buy at nearly twice the rate, but that is mostly who they are, not what a "
              "second visit does -- you only have repeat visits if you chose to come back.")

fig, ax = frame(figsize=(10, 3.4))
y = np.arange(len(ft))
ax.barh(y, ft.conv_rate_pct, color=[ORANGE, GREEN], height=0.5)
ax.errorbar(ft.conv_rate_pct, y,
            xerr=[ft.conv_rate_pct - ft.ci_low_pct, ft.ci_high_pct - ft.conv_rate_pct],
            fmt="none", ecolor="#444444", capsize=4, lw=1.2)
for i, r in enumerate(ft.itertuples()):
    ax.text(r.conv_rate_pct + 0.22, i, f"{r.conv_rate_pct:.2f}%  (n={int(r.n_sessions):,})",
            va="center", fontsize=9)
ax.set_yticks(y)
ax.set_yticklabels(ft.label)
ax.set_xlim(0, 6.2)
ax.set_xlabel("Visits that contained a purchase (%)")
ax.grid(axis="x", lw=0.6)
chart(
    fig,
    title="A repeat visit buys about twice as often as a first visit",
    subtitle="Counted per visit. The bars carry 95% confidence intervals, which at this many visits are "
             "narrower than the dot -- so read the size of the gap, not the p-value.",
    takeaway=f"Repeat visits buy {ret.conv_rate_pct:.2f}% of the time against "
             f"{first.conv_rate_pct:.2f}% for first visits &mdash; "
             f"{ret.conv_rate_pct / first.conv_rate_pct:.2f}x. Most of that is who those visits belong to: "
             f"you only have repeat visits because you chose to come back. It does not measure what a "
             f"second visit causes.",
    source="funnel_first_time_vs_returning.parquet, from marts.fct_sessions (is_first_time_session)",
)

# ----------------------------------------------------------------------------------
st.header("How much people do in a visit, against whether they buy")

depth = extract("funnel_by_session_depth")
fig, ax = frame(figsize=(10, 4.0))
x = np.arange(len(depth))
ax.bar(x, depth.conv_rate_pct, color=BLUE, width=0.55, label="Bought something")
ax.plot(x, depth.cart_rate_pct, marker="o", color=PURPLE, lw=1.8, label="Added to cart")
for i, r in enumerate(depth.itertuples()):
    ax.text(i, r.conv_rate_pct + 1.2, f"{r.conv_rate_pct:.1f}%", ha="center", fontsize=8.5)
ax2 = ax.twinx()
ax2.plot(x, depth.n_sessions, color="#9aa3ad", ls="--", lw=1.2, label="Visits (right axis)")
ax2.yaxis.set_major_formatter(FuncFormatter(thousands))
ax2.set_ylabel("Visits", color="#6b7280", fontsize=9)
ax2.tick_params(labelsize=8, colors="#6b7280")
ax2.spines["right"].set_visible(True)
ax2.spines["right"].set_color("#DDDDDD")
ax.set_xticks(x)
ax.set_xticklabels(depth.session_depth_bucket)
ax.set_xlabel("Things done in the visit")
ax.set_ylabel("% of visits")
ax.grid(axis="y", lw=0.6)
h1, l1 = ax.get_legend_handles_labels()
h2, l2 = ax2.get_legend_handles_labels()
ax.legend(h1 + h2, l1 + l2, loc="upper left")
chart(
    fig,
    title="Busy visits buy, and most visits are not busy",
    subtitle="Counted per visit. The dashed line is how many visits are in each bucket -- the "
             "best-converting one is also among the smallest.",
    takeaway=f"Visits with 11 or more actions buy {depth.iloc[-1].conv_rate_pct:.1f}% of the time against "
             f"{depth.iloc[0].conv_rate_pct:.1f}% for a single-action visit, but only "
             f"{100 * depth.iloc[-1].n_sessions / depth.n_sessions.sum():.0f}% of visits are that busy. "
             f"How much someone does in a visit tells you whether they will buy in it. It does not tell "
             f"you whether they will come back and buy again -- see Retention & churn.",
    source="funnel_by_session_depth.parquet, from marts.fct_sessions",
)

st.caption(
    f"What is being counted on this page: {int(scope_value('sessions')):,} visits and "
    f"{int(scope_value('users_any_event')):,} people, both after bots were dropped "
    f"({int(scope_value('bot_users_excluded')):,} users, at more than 29.0 visits per active day)."
)
