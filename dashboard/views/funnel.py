"""Funnel health -- the same funnel at two scopes, side by side."""

from __future__ import annotations

import numpy as np
import streamlit as st
from matplotlib.ticker import FuncFormatter

from lib.load import extract, scope_value
from lib.style import BLUE, GREEN, ORANGE, PURPLE, chart, frame, page_header, thousands

page_header(
    "Funnel health",
    "The same four stages counted three ways. They disagree by up to 1.8x at the purchase step, and which "
    "one is on the slide changes what the number means &mdash; so both scopes are shown together rather "
    "than one being picked.",
    "01_funnel, via marts.fct_sessions",
)

funnel = extract("funnel_scopes").copy()
NICE = {"view": "Viewed", "cart": "Added to cart", "remove_from_cart": "Removed from cart",
        "purchase": "Purchased"}
funnel["nice"] = funnel.stage.map(NICE)
purchase = funnel.loc[funnel.stage == "purchase"].iloc[0]

st.warning(
    "**Every user-scoped figure on this page is a lower bound.** `user_id` is cookie-scoped, not "
    "account-scoped: one person on two devices is two users. That inflates the denominator of any "
    "per-user rate and can only push it down. The session scope is unaffected by this, and is not "
    "therefore the safer number &mdash; it answers a different question.",
    icon=":material/warning:",
)

# ----------------------------------------------------------------------------------
st.header("Session scope and user scope, side by side")

c1, c2, c3 = st.columns(3)
c1.metric("Purchase rate, RAW EVENT scope", f"{purchase.raw_events_pct_of_view:.2f}%",
          help="Purchase event rows as a share of view event rows. Inflated by repeated actions and by "
               "multi-line orders -- shown here because it is what a naive event-count funnel produces.")
c2.metric("Purchase rate, SESSION scope", f"{purchase.sessions_reaching_pct_of_view:.2f}%",
          help="Sessions containing a purchase / sessions containing a view.")
c3.metric("Purchase rate, USER scope", f"{purchase.users_reaching_pct_of_view:.2f}%",
          help="Users who ever purchased / users who ever viewed. A LOWER BOUND.")

ratio = purchase.users_reaching_pct_of_view / purchase.sessions_reaching_pct_of_view

fig, ax = frame(figsize=(10, 4.6))
stages = funnel.sort_values("stage_order")
x = np.arange(len(stages))
w = 0.38
ax.bar(x - w / 2, stages.sessions_reaching_pct_of_view, w, color=BLUE, label="Session scope")
ax.bar(x + w / 2, stages.users_reaching_pct_of_view, w, color=ORANGE, label="User scope")
for i, r in enumerate(stages.itertuples()):
    ax.text(i - w / 2, r.sessions_reaching_pct_of_view + 1.4, f"{r.sessions_reaching_pct_of_view:.1f}",
            ha="center", fontsize=8.5, color=BLUE)
    ax.text(i + w / 2, r.users_reaching_pct_of_view + 1.4, f"{r.users_reaching_pct_of_view:.1f}",
            ha="center", fontsize=8.5, color=ORANGE)
ax.set_xticks(x)
ax.set_xticklabels(stages.nice)
ax.set_ylabel("% of the stage-1 denominator")
ax.set_ylim(0, 112)
ax.grid(axis="y", lw=0.6)
ax.legend(loc="upper right")
chart(
    fig,
    title="The same funnel, two denominators, two different stories",
    subtitle="Both indexed to 100 at 'Viewed'. Session scope asks what a visit does; user scope asks what "
             "a person eventually does.",
    takeaway=f"At the purchase step the user scope reads {purchase.users_reaching_pct_of_view:.2f}% against "
             f"{purchase.sessions_reaching_pct_of_view:.2f}% at session scope &mdash; {ratio:.1f}x apart, "
             f"because a person who browses across five visits and buys in one is 20% at session scope and "
             f"100% at user scope. Neither is wrong; quoting one as the other is.",
    source="funnel_scopes.parquet, from marts.fct_sessions (rolled up to user grain for the user scope)",
)

tab = funnel.sort_values("stage_order")[[
    "nice", "raw_events", "sessions_reaching", "users_reaching",
    "raw_events_pct_of_view", "sessions_reaching_pct_of_view", "users_reaching_pct_of_view"]]
tab.columns = ["Stage", "Raw event rows", "Sessions reaching", "Users reaching",
               "Raw %", "Session %", "User %"]
st.dataframe(
    tab, hide_index=True, width="stretch",
    column_config={c: st.column_config.NumberColumn(format="%.2f")
                   for c in ["Raw %", "Session %", "User %"]},
)
st.caption(
    "Raw event rows are **not** deduplicated. 00's audit found the 10.4% exact-duplicate rows are real "
    "repeated actions logged at 1-second resolution, and the 0.07% repeated purchase lines are quantity. "
    "Deduplication in this project is a grain &mdash; the two right-hand scopes &mdash; not a cleaning step."
)

# ----------------------------------------------------------------------------------
st.header("First-time visits against returning visits")

ft = extract("funnel_first_time_vs_returning").copy()
ft["label"] = ft.user_type.map({"first_time": "First-time session", "returning": "Returning session"})
first = ft.loc[ft.user_type == "first_time"].iloc[0]
ret = ft.loc[ft.user_type == "returning"].iloc[0]

a, b, c = st.columns(3)
a.metric("First-time session conversion", f"{first.conv_rate_pct:.2f}%",
         help=f"95% Wilson interval [{first.ci_low_pct:.2f}%, {first.ci_high_pct:.2f}%] "
              f"over {int(first.n_sessions):,} sessions.")
b.metric("Returning session conversion", f"{ret.conv_rate_pct:.2f}%",
         help=f"95% Wilson interval [{ret.ci_low_pct:.2f}%, {ret.ci_high_pct:.2f}%] "
              f"over {int(ret.n_sessions):,} sessions.")
c.metric("Ratio", f"{ret.conv_rate_pct / first.conv_rate_pct:.2f}x",
         help="Returning sessions convert at nearly twice the rate. This is selection as much as "
              "behaviour -- a user only has returning sessions if they came back.")

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
ax.set_xlabel("Sessions containing a purchase (%)  -- SESSION SCOPE")
ax.grid(axis="x", lw=0.6)
chart(
    fig,
    title="A returning visit converts at about twice a first visit",
    subtitle="Session scope. Bars carry 95% Wilson intervals; at these sample sizes the intervals are "
             "narrower than the marker, which is why the effect size is the number to read, not the p-value.",
    takeaway=f"Returning sessions convert at {ret.conv_rate_pct:.2f}% against {first.conv_rate_pct:.2f}% for "
             f"first-time sessions &mdash; {ret.conv_rate_pct / first.conv_rate_pct:.2f}x. Most of that is "
             f"selection: a user only has returning sessions because they chose to come back. It is not a "
             f"measurement of what a second visit causes.",
    source="funnel_first_time_vs_returning.parquet, from marts.fct_sessions (is_first_time_session)",
)

# ----------------------------------------------------------------------------------
st.header("Conversion by how much the session contains")

depth = extract("funnel_by_session_depth")
fig, ax = frame(figsize=(10, 4.0))
x = np.arange(len(depth))
ax.bar(x, depth.conv_rate_pct, color=BLUE, width=0.55, label="Contained a purchase")
ax.plot(x, depth.cart_rate_pct, marker="o", color=PURPLE, lw=1.8, label="Contained a cart add")
for i, r in enumerate(depth.itertuples()):
    ax.text(i, r.conv_rate_pct + 1.2, f"{r.conv_rate_pct:.1f}%", ha="center", fontsize=8.5)
ax2 = ax.twinx()
ax2.plot(x, depth.n_sessions, color="#9aa3ad", ls="--", lw=1.2, label="Sessions (right axis)")
ax2.yaxis.set_major_formatter(FuncFormatter(thousands))
ax2.set_ylabel("Sessions", color="#6b7280", fontsize=9)
ax2.tick_params(labelsize=8, colors="#6b7280")
ax2.spines["right"].set_visible(True)
ax2.spines["right"].set_color("#DDDDDD")
ax.set_xticks(x)
ax.set_xticklabels(depth.session_depth_bucket)
ax.set_xlabel("Events in the session")
ax.set_ylabel("% of sessions")
ax.grid(axis="y", lw=0.6)
h1, l1 = ax.get_legend_handles_labels()
h2, l2 = ax2.get_legend_handles_labels()
ax.legend(h1 + h2, l1 + l2, loc="upper left")
chart(
    fig,
    title="Deeper sessions convert, and most sessions are not deep",
    subtitle="Session scope. The dashed line is the session count on the right axis -- the highest-"
             "converting bucket is also among the smallest.",
    takeaway=f"Sessions with 11+ events convert at {depth.iloc[-1].conv_rate_pct:.1f}% against "
             f"{depth.iloc[0].conv_rate_pct:.1f}% for single-event sessions, but only "
             f"{100 * depth.iloc[-1].n_sessions / depth.n_sessions.sum():.0f}% of sessions are that deep. "
             f"Depth predicts conversion within a visit; 02 tested whether it also predicts the SECOND "
             f"purchase and found it does not &mdash; see Retention & churn.",
    source="funnel_by_session_depth.parquet, from marts.fct_sessions",
)

st.caption(
    f"Denominators on this page: {int(scope_value('sessions')):,} sessions and "
    f"{int(scope_value('users_any_event')):,} users, both after bot exclusion "
    f"({int(scope_value('bot_users_excluded')):,} users removed at more than 29.0 sessions per active day)."
)
