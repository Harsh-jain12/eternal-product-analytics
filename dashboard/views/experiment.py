"""Experiment & impact -- the design, the Criteo evidence behind it, and the break-even."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import streamlit as st
from matplotlib.ticker import FuncFormatter

from lib.load import H, extract
from lib.style import (BLUE, GREEN, GREY, ORANGE, PURPLE, RED, TAKEAWAY_FACE,
                       chart, frame, page_header, tag)

page_header(
    "Experiment & impact",
    "Nobody ran an experiment on this shop, so <strong>no number on this page is a measured effect and "
    "none of it is a forecast</strong>. What is here: a test worth running, the real randomised experiment "
    "from Criteo that settles who it should target, and a calculator showing what the test would have to "
    "achieve to pay for itself. The inputs you can move are the ones the business decides, not the ones "
    "this data measured.",
    "07_criteo_experiment, 08_experiment_design and 09_impact, via handoff",
)

st.warning(
    f"**{H('experiment_design.status')}** {H('impact.status')}",
    icon=":material/science:",
)

# ==================================================================================
st.header("The test, on one screen")

st.markdown(
    "**Two versions of the same test appear on this page.** Design B is the one recommended: big enough to "
    "tell a lift that pays from one that does not. Design A is the cheaper version, kept here to show what "
    "buying fewer users costs you in certainty. Everything below is design B unless it says otherwise."
)

d1, d2, d3, d4 = st.columns(4)
d1.metric("Contact them on", f"day {H('experiment_design.trigger.days_since_first_order'):.0f}",
          help=H("experiment_design.trigger.why_day_14"))
d2.metric("Users per arm", f"{int(H('experiment_design.economics.n_per_arm')):,}",
          help=H("experiment_design.economics.power_basis.shipped"))
d3.metric("Time to fill it", f"{H('experiment_design.economics.enrolment_weeks')} weeks",
          delta=f"{H('experiment_design.economics.weeks_to_primary_readout')} weeks until you can read it",
          delta_color="off")
d4.metric("Cost of the messages", f"EUR {H('experiment_design.economics.contact_spend_eur'):,.0f}",
          help="At the assumed cost per contact. It is the cheapest part of this; the expensive input is "
               "the time it takes to run.")

a, b = st.columns(2)
with a:
    st.markdown(
        f"**Who is in it.** {H('experiment_design.population.rule')} &mdash; "
        f"{int(H('experiment_design.population.n_historical_analogue')):,} users in the historical "
        f"analogue, repeating at {H('experiment_design.population.base_rate_pct'):.2f}%.\n\n"
        f"**How to describe it.** {H('experiment_design.population.framing')}\n\n"
        f"**How users are split.** {H('experiment_design.assignment.allocation')} at the "
        f"{H('experiment_design.assignment.unit')} level, "
        f"`{H('experiment_design.assignment.mechanism')}`, blocked on "
        f"{H('experiment_design.assignment.blocks')}.\n\n"
        f"**Why not just split on the user id.** "
        f"{H('experiment_design.assignment.id_range_split_is_unsafe')}"
    )
with b:
    st.markdown(
        f"**What it measures.** {H('experiment_design.estimand.primary')}. "
        f"What it must not be read as: {H('experiment_design.estimand.forbidden')}.\n\n"
        f"**The metric.** `{H('experiment_design.metrics.primary')}`, measured over "
        f"{H('experiment_design.metrics.naming_rule.experiment_window')}, with the clock starting at "
        f"{H('experiment_design.metrics.clock_starts_at')}.\n\n"
        f"**Why day 14 and not the churn flag.** "
        f"{H('experiment_design.trigger.why_time_not_churn_flag')}"
    )

st.error(
    f"**Two base rates that get mixed up, and must not be.** The experiment's population buys again at "
    f"**{H('experiment_design.metrics.naming_rule.experiment_base_rate_pct')}%** over "
    f"{H('experiment_design.metrics.naming_rule.experiment_window')}; the model's population buys again at "
    f"**{H('experiment_design.metrics.naming_rule.nb06_base_rate_pct')}%** over "
    f"{H('experiment_design.metrics.naming_rule.nb06_window')}. "
    f"{H('experiment_design.metrics.naming_rule.rule')}",
    icon=":material/swap_horiz:",
)

# ==================================================================================
st.header("Why the target is not the people most likely to leave")

st.markdown(
    "Knowing who is about to leave is not the same as knowing who would come back if you contacted them. "
    "Telling those apart takes an experiment, and this project has none of its own &mdash; so it borrows "
    "one. Criteo withheld ads from a random group and showed them to everyone else, across "
    f"{H('criteo_experiment.data.rows'):,} users. Six ways of choosing whom to target were then scored on "
    "a held-out half that no model was fitted on:"
)

pol = pd.DataFrame(H("criteo_experiment.policy_comparison.policies"))
pol["ci_lo"] = pol.ci.apply(lambda c: c[0])
pol["ci_hi"] = pol.ci.apply(lambda c: c[1])
pol = pol.sort_values("pct_of_total_effect")

COL = []
for p in pol.policy:
    if "RISK" in p:
        COL.append(RED)
    elif "random" in p:
        COL.append(GREY)
    elif "UPLIFT" in p:
        COL.append(GREEN)
    elif "propensity" in p:
        COL.append(BLUE)
    else:
        COL.append(PURPLE)

fig, ax = frame(figsize=(10, 4.8))
y = np.arange(len(pol))
ax.barh(y, pol.pct_of_total_effect, color=COL, height=0.55)
# 95% intervals, rescaled onto the same "% of total effect" axis as the bars.
scale = 100.0 / pol.incremental.max()
ax.errorbar(pol.pct_of_total_effect, y,
            xerr=[(pol.incremental - pol.ci_lo) * scale, (pol.ci_hi - pol.incremental) * scale],
            fmt="none", ecolor="#3a3a3a", capsize=3, lw=1.1)
ax.axvline(50, color=GREY, ls="--", lw=1.2)
ax.text(50.8, len(pol) - 0.45, "a random half", fontsize=8.5, color="#6b7280")
for i, r in enumerate(pol.itertuples()):
    # clear of the whisker, not of the bar
    ax.text(r.ci_hi * scale + 2.0, i, f"{r.pct_of_total_effect:.1f}%  "
                                      f"({r.inc_per_1000_targeted:.2f} per 1k targeted)",
            va="center", fontsize=9)
ax.set_yticks(y)
ax.set_yticklabels(pol.policy, fontsize=9)
ax.set_xlim(0, 152)
ax.set_xlabel("% of the available extra conversions captured")
ax.grid(axis="x", lw=0.6)
chart(
    fig,
    title="Targeting the most at-risk half captured 1% of the effect",
    subtitle="Criteo's experiment, held-out half. Every rule except 'treat everyone' spends the same half "
             "of the budget, so they compare directly.",
    takeaway=f"{H('criteo_experiment.policy_comparison.headline')} Targeting the most at-risk users is not "
             f"merely no better than picking at random here. It is much worse, and the interval on that "
             f"difference does not include zero.",
    source="handoff criteo_experiment.policy_comparison.policies",
)

c1, c2 = st.columns([0.55, 0.45])
with c1:
    st.markdown(
        f"**The result nobody was expecting.** "
        f"{H('criteo_experiment.policy_comparison.the_expected_result_that_did_not_hold')}"
    )
    st.markdown(
        f"Uplift losing to propensity on conversion is "
        f"{H('criteo_experiment.uplift.why_uplift_lost_on_conversion.verdict')}"
    )
with c2:
    qini = H("criteo_experiment.uplift.qini")
    rows = [{"Ranking": k.split(" | ", 1)[1], "Qini ratio": v["qini_ratio"],
             "CI lo": v["ci"][0], "CI hi": v["ci"][1]}
            for k, v in qini.items() if k.startswith("conversion |")]
    st.dataframe(pd.DataFrame(rows).sort_values("Qini ratio", ascending=False),
                 hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%.3f")
                                for c in ["Qini ratio", "CI lo", "CI hi"]})
    st.caption("Qini ratio on conversions, held-out half. It scores how fast a ranking picks up the "
               "available effect: 1.0 is as fast as a perfect ranking, 0 is no better than random. The "
               "\"most at risk first\" row is the one that matters here.")

st.info(
    "**What carries over to this shop, and what does not.** "
    + " ".join(H("criteo_experiment.carry_back_to_rees46.what_transfers"))
    + " &nbsp;**Does not transfer:** "
    + " ".join(H("criteo_experiment.carry_back_to_rees46.what_does_not_transfer")),
    icon=":material/compare_arrows:",
)

# ==================================================================================
st.header("What the test would have to achieve")

ledger = extract("impact_ledger")


def L(name: str) -> float:
    row = ledger.loc[ledger.input == name]
    if row.empty:
        raise KeyError(f"impact_ledger.parquet has no input '{name}'")
    return float(row.value.iloc[0])


BASE_RATE = L("base_rate")
AOV = L("aov_second_order")
DOWNSTREAM = L("downstream_uplift")
INFLOW = L("first_buyer_inflow_per_day")
SURVIVAL = L("trigger_survival_share")
COST_DEFAULT = L("contact_cost")
MARGIN_DEFAULT = L("contribution_margin")

HOLDBACK = float(H("impact.reach.holdback_share"))
N_PER_ARM_B = float(H("experiment_design.economics.n_per_arm"))
N_PER_ARM_A = float(H("experiment_design.economics.alternative_design.n_per_arm"))
DAYS_PER_YEAR = float(H("impact.reach.enrolments_per_year")) / float(H("impact.reach.enrolments_per_day"))
Z975 = 1.959963984540054

st.markdown(
    "**Break-even lift is the smallest increase in the repeat rate that pays for the messages.** Below it "
    "the campaign costs more than it brings in; above it, it makes money. Everything below is arithmetic "
    "over labelled inputs. It is not a forecast and it does not predict what the campaign would do."
)
st.markdown(
    f"{tag('DATA')} measured in this dataset. &nbsp; {tag('ASSUMPTION')} a number the business sets, which "
    f"nothing here measures. &nbsp; {tag('SCENARIO')} a lift no experiment has run to measure. "
    f"&nbsp; {tag('DESIGN')} a choice made when the test was designed. &nbsp;**Only the ASSUMPTION and "
    f"SCENARIO inputs move.** The DATA inputs are fixed and shown with the file they came from.",
    unsafe_allow_html=True,
)

inputs, outputs = st.columns([0.40, 0.60])

with inputs:
    st.subheader("Inputs the business sets")
    st.markdown(f"{tag('ASSUMPTION')} **Cost per contact** &mdash; you set this", unsafe_allow_html=True)
    contact_cost = st.slider("Cost per contact (EUR)", 0.01, 0.30, float(COST_DEFAULT), 0.005,
                             format="EUR %.3f", label_visibility="collapsed")
    st.caption(f"Nothing in this data observes it. The design assumes EUR {COST_DEFAULT:.2f}. "
               f"{ledger.loc[ledger.input == 'contact_cost', 'source'].iloc[0]}")

    st.markdown(f"{tag('ASSUMPTION')} **Contribution margin** &mdash; you set this",
                unsafe_allow_html=True)
    margin = st.slider("Contribution margin", 0.10, 0.50, float(MARGIN_DEFAULT), 0.01,
                       format="%.2f", label_visibility="collapsed")
    st.caption(f"What the business keeps on a sale after the cost of the goods. The design assumes "
               f"{MARGIN_DEFAULT:.0%}. "
               f"{ledger.loc[ledger.input == 'contribution_margin', 'source'].iloc[0]}")

    st.markdown(f"{tag('SCENARIO')} **The lift the campaign actually produces** &mdash; nobody knows this",
                unsafe_allow_html=True)
    lift_pp = st.slider("True lift (pp)", 0.0, 3.0, float(H("experiment_design.economics.mde_pp")), 0.05,
                        format="%.2f pp", label_visibility="collapsed")
    st.caption("No experiment has run. Move this to ask \"what if the lift were X\" -- it is not an "
               f"estimate of anything. The design is sized for "
               f"{H('experiment_design.economics.mde_pp'):.2f} pp.")

    st.divider()
    st.subheader("Inputs that are measured, and fixed")
    fixed = ledger[ledger.tag == "DATA"][["label", "value", "source"]].copy()
    fixed.columns = ["Input", "Value", "Where it came from"]
    st.dataframe(fixed, hide_index=True, width="stretch",
                 column_config={"Value": st.column_config.NumberColumn(format="%.4f")})
    st.caption(
        f"Plus two choices made when the test was designed: {HOLDBACK:.0%} of users are held back and "
        f"never contacted, and each arm gets {int(N_PER_ARM_B):,} users."
    )

# --- the arithmetic. Every term above is a labelled ledger row. ---
value_margin = AOV * margin
value_downstream = value_margin * DOWNSTREAM
value_per_order = value_margin + value_downstream
break_even_pp = 100.0 * contact_cost / value_per_order
break_even_rel = 100.0 * break_even_pp / (100.0 * BASE_RATE)

enrol_per_day = INFLOW * SURVIVAL
enrol_per_year = enrol_per_day * DAYS_PER_YEAR
contacted_per_year = enrol_per_year * (1 - HOLDBACK)

inc_orders = contacted_per_year * lift_pp / 100.0
gross = inc_orders * value_per_order
spend = contacted_per_year * contact_cost
net = gross - spend


def phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def se_pp(delta_pp: float, n_per_arm: float) -> float:
    """Standard error of the arm difference, in percentage points. Unpooled, with the
    treatment rate taken at base + delta -- the form 08 solved its sample size from."""
    p0 = BASE_RATE
    p1 = min(max(p0 + delta_pp / 100.0, 1e-9), 1 - 1e-9)
    return 100.0 * math.sqrt((p0 * (1 - p0) + p1 * (1 - p1)) / n_per_arm)


def p_ship(delta_pp: float, n_per_arm: float) -> float:
    """P(the 95% CI lower bound clears break-even) when the true effect is delta."""
    return phi((delta_pp - break_even_pp) / se_pp(delta_pp, n_per_arm) - Z975)


def p_kill(delta_pp: float, n_per_arm: float) -> float:
    """P(the 95% CI upper bound falls below break-even) when the true effect is delta."""
    return phi((break_even_pp - delta_pp) / se_pp(delta_pp, n_per_arm) - Z975)


ship_B = p_ship(lift_pp, N_PER_ARM_B)
kill_B0 = p_kill(0.0, N_PER_ARM_B)

# The smallest true lift design B can clear break-even on 80% of the time. SE itself
# depends on the lift (through the treatment-arm rate), so this is a fixed point rather
# than a formula; it converges in two passes because that dependence is very weak.
Z80 = 0.8416212335729143
mde_B = break_even_pp + (Z975 + Z80) * se_pp(break_even_pp, N_PER_ARM_B)
for _ in range(3):
    mde_B = break_even_pp + (Z975 + Z80) * se_pp(mde_B, N_PER_ARM_B)

with outputs:
    st.subheader("What that adds up to")
    o1, o2, o3 = st.columns(3)
    o1.metric("What one extra 2nd order is worth", f"EUR {value_per_order:.2f}",
              help=f"An average second order of {AOV:.2f} x {margin:.0%} margin = EUR {value_margin:.2f}, "
                   f"plus EUR {value_downstream:.2f} for the orders that tend to follow a second one "
                   f"({1 + DOWNSTREAM:.2f}x).")
    o2.metric("Lift needed to break even", f"{break_even_pp:.3f} pp",
              delta=f"{break_even_rel:.2f}% relative", delta_color="off")
    o3.metric(f"Net per year IF the lift is {lift_pp:.2f} pp",
              f"EUR {net:,.0f}",
              delta="pays for itself" if net > 0 else "loses money",
              delta_color="normal" if net > 0 else "inverse")

    p1, p2, p3 = st.columns(3)
    p1.metric("Could the test settle it?",
              "yes" if ship_B >= 0.80 else ("marginal" if ship_B >= 0.5 else "no"),
              help="Yes means: if the lift really were this big, design B would have at least an 80% "
                   "chance of coming back with a 95% interval sitting entirely above break-even.")
    p2.metric("Chance of a clear ship", f"{100 * ship_B:.0f}%",
              help="How often the whole 95% confidence interval lands above break-even at this lift.")
    p3.metric("Chance of a clear kill if it does nothing", f"{100 * kill_B0:.0f}%",
              help="How often the whole 95% confidence interval lands below break-even when the campaign "
                   "truly has no effect.")

    fig, ax = frame(figsize=(7.6, 3.9))
    grid = np.linspace(0, 3.0, 241)
    nets = contacted_per_year * (grid / 100.0 * value_per_order - contact_cost)
    ax.plot(grid, nets, color=BLUE, lw=2)
    ax.axhline(0, color="#555555", lw=1)
    ax.axvline(break_even_pp, color=GREEN, ls="--", lw=1.4)
    ax.axvline(lift_pp, color=ORANGE, ls="-", lw=1.6)
    ax.axvspan(0, break_even_pp, color=RED, alpha=0.07)
    # The band this design cannot act on: profitable, but below what it can detect.
    if mde_B > break_even_pp:
        ax.axvspan(break_even_pp, min(mde_B, 3.0), color=TAKEAWAY_FACE, alpha=0.85, zorder=0)
        ax.text((break_even_pp + min(mde_B, 3.0)) / 2, nets.max() * 0.06,
                "makes money,\ncannot be proven", ha="center", fontsize=8, color="#8a6d3b")
    ax.scatter([lift_pp], [net], s=60, color=ORANGE, zorder=6)
    ax.annotate(f"scenario {lift_pp:.2f} pp\nEUR {net:,.0f}", xy=(lift_pp, net),
                xytext=(12, -28), textcoords="offset points",
                fontsize=8.5, color="#a35a2a", va="top",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#e0c3ad", lw=0.8))
    ax.annotate(f"break-even\n{break_even_pp:.3f} pp", xy=(break_even_pp, 0),
                xytext=(break_even_pp + 0.08, nets.max() * 0.45), fontsize=8.5, color="#2F6B45")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v/1000:,.0f}k"))
    ax.set_xlabel("Lift in the 30-day repeat rate, if the campaign produced it (pp)")
    ax.set_ylabel("Net EUR per year")
    ax.grid(axis="y", lw=0.6)
    chart(
        fig,
        title="What the campaign would be worth at any lift",
        subtitle=f"At EUR {contact_cost:.3f} per contact, {margin:.0%} margin and "
                 f"{contacted_per_year:,.0f} contacts a year after holding {HOLDBACK:.0%} back. The x axis "
                 f"is a question, not a prediction -- no lift here has been measured.",
        takeaway=(
            f"The campaign starts paying above {break_even_pp:.3f} pp ({break_even_rel:.2f}% relative), and "
            f"design B can only reliably see {mde_B:.2f} pp -- {mde_B / break_even_pp:.1f}x that. So every "
            f"lift in the amber band would make money and still come back unproven. That is why the "
            f"read-out is a three-way call against break-even instead of a significance test against zero."
        ),
        source="impact_ledger.parquet (marts + handoff experiment_design.economics.ledger); the arithmetic "
               "is this page's, the inputs are not",
    )

st.markdown("##### The same thing, line by line")
chain = pd.DataFrame([
    {"Step": "Average value of a second order", "Tag": "DATA", "Value": f"EUR {AOV:.2f}",
     "Source": ledger.loc[ledger.input == "aov_second_order", "source"].iloc[0]},
    {"Step": "x contribution margin", "Tag": "ASSUMPTION", "Value": f"{margin:.0%}",
     "Source": "slider -- the design's default is 30%"},
    {"Step": "= what the shop keeps on it", "Tag": "DATA x ASSUMPTION",
     "Value": f"EUR {value_margin:.4f}", "Source": "computed"},
    {"Step": f"+ credit for the orders that follow it ({1 + DOWNSTREAM:.2f}x)", "Tag": "DATA",
     "Value": f"EUR {value_downstream:.4f}",
     "Source": ledger.loc[ledger.input == "downstream_uplift", "source"].iloc[0]},
    {"Step": "= value of one extra second order", "Tag": "DATA x ASSUMPTION",
     "Value": f"EUR {value_per_order:.4f}", "Source": "computed"},
    {"Step": "Cost per contact", "Tag": "ASSUMPTION", "Value": f"EUR {contact_cost:.4f}",
     "Source": "slider -- the design's default is EUR 0.05"},
    {"Step": "= LIFT NEEDED TO BREAK EVEN", "Tag": "DATA x ASSUMPTION", "Value": f"{break_even_pp:.4f} pp",
     "Source": "cost / value"},
    {"Step": "New first-time buyers per day", "Tag": "DATA", "Value": f"{INFLOW:,.1f}",
     "Source": ledger.loc[ledger.input == "first_buyer_inflow_per_day", "source"].iloc[0]},
    {"Step": "x share still eligible on day 14", "Tag": "DATA", "Value": f"{SURVIVAL:.4f}",
     "Source": ledger.loc[ledger.input == "trigger_survival_share", "source"].iloc[0]},
    {"Step": "= people entering per year", "Tag": "DATA", "Value": f"{enrol_per_year:,.0f}",
     "Source": "computed"},
    {"Step": f"x (1 - {HOLDBACK:.0%} held back)", "Tag": "DESIGN", "Value": f"{contacted_per_year:,.0f}",
     "Source": "09 holdback_share"},
    {"Step": "x the lift, if it happens", "Tag": "SCENARIO", "Value": f"{lift_pp:.2f} pp",
     "Source": "slider"},
    {"Step": "= extra second orders per year", "Tag": "DATA x SCENARIO x DESIGN",
     "Value": f"{inc_orders:,.0f}", "Source": "computed"},
    {"Step": "= NET PER YEAR", "Tag": "DATA x ASSUMPTION x SCENARIO x DESIGN",
     "Value": f"EUR {net:,.0f}", "Source": "money in - money out"},
])
st.dataframe(chain, hide_index=True, width="stretch")

if abs(contact_cost - COST_DEFAULT) < 1e-9 and abs(margin - MARGIN_DEFAULT) < 1e-9 \
        and abs(lift_pp - float(H("experiment_design.economics.mde_pp"))) < 1e-9:
    st.success(
        f"At the default settings this reproduces notebook 09 exactly: break-even "
        f"{H('experiment_design.economics.break_even_lift_pp'):.4f} pp, EUR "
        f"{H('impact.value_per_incremental_second_order_eur'):.3f} per extra second order, and EUR "
        f"{H('impact.sensitivity.base_net_eur'):,.0f} net a year at the 1.00 pp scenario.",
        icon=":material/check_circle:",
    )

# ----------------------------------------------------------------------------------
st.subheader("Could the test actually tell you which side of break-even you are on?")

ad1, ad2 = st.columns([0.55, 0.45])
with ad1:
    grid = np.linspace(0.01, 2.5, 200)
    fig, ax = frame(figsize=(7.4, 3.6))
    ax.plot(grid, [100 * p_ship(g, N_PER_ARM_B) for g in grid], color=BLUE, lw=2,
            label=f"Design B, n={int(N_PER_ARM_B):,}/arm")
    ax.plot(grid, [100 * p_ship(g, N_PER_ARM_A) for g in grid], color=GREY, lw=1.6, ls="--",
            label=f"Design A, n={int(N_PER_ARM_A):,}/arm")
    ax.axhline(80, color=GREEN, ls=":", lw=1.2)
    ax.axvline(break_even_pp, color=GREEN, ls="--", lw=1.2)
    ax.axvline(lift_pp, color=ORANGE, lw=1.6)
    ax.set_xlabel("Lift, if the campaign produced it (pp)")
    ax.set_ylabel("Chance of a clear ship, %")
    ax.set_ylim(0, 100)
    ax.grid(axis="y", lw=0.6)
    ax.legend(loc="lower right", fontsize=8.5)
    chart(
        fig,
        title="Sized against break-even, not against zero",
        subtitle="A clear ship means the whole 95% interval lands above break-even. Design B is sized so "
                 "that happens 80% of the time at a 1.00 pp lift; design A is the cheaper alternative.",
        takeaway=f"If the lift were {lift_pp:.2f} pp, design B would come back with a clear answer "
                 f"{100 * ship_B:.0f}% of the time and design A "
                 f"{100 * p_ship(max(lift_pp, 0.01), N_PER_ARM_A):.0f}%. Both collapse near break-even, "
                 f"because the users you need scale with the distance from break-even rather than from "
                 f"zero -- aim at a target sitting on the line and no sample size is enough.",
        source="handoff experiment_design.economics (n per arm, base rate); the power curve is computed "
               "here from those inputs",
    )
with ad2:
    st.markdown(
        f"**How the result gets read.** {H('experiment_design.decision_rule.shape')}\n\n"
        f"- **Ship** if {H('experiment_design.decision_rule.ship')}\n"
        f"- **Kill** if {H('experiment_design.decision_rule.kill')}\n"
        f"- **Inconclusive** if {H('experiment_design.decision_rule.inconclusive')}\n\n"
        f"{H('experiment_design.decision_rule.why')}"
    )
    st.markdown(
        f"**If it comes back inconclusive.** It probably will &mdash; "
        f"{H('impact.value_of_the_experiment.inconclusive.probability_at_zero_pct')}% of the time if the "
        f"true effect is zero, {H('impact.value_of_the_experiment.inconclusive.probability_at_target_pct')}% "
        f"at the target. {H('impact.value_of_the_experiment.inconclusive.recommended_branch')}"
    )
    st.caption(f"Written down before launch, not after the result: "
               f"{H('impact.value_of_the_experiment.inconclusive.must_be_pre_registered_before_launch')}")

# ----------------------------------------------------------------------------------
st.subheader("What would change the answer")

sens = extract("impact_sensitivity").sort_values("swing_eur", ascending=True)
_lo = min(sens.net_at_low_eur.min(), sens.net_at_high_eur.min())
_hi = max(sens.net_at_low_eur.max(), sens.net_at_high_eur.max())

fig, ax = frame(figsize=(10, 4.0))
y = np.arange(len(sens))
for i, r in enumerate(sens.itertuples()):
    colour = RED if r.flips_the_decision else GREY
    ax.plot([r.net_at_low_eur, r.net_at_high_eur], [i, i], color=colour, lw=6, solid_capstyle="round")
    ax.text(_hi + 2500, i,
            f"{r.low} -> {r.high}", va="center", fontsize=8.5, color="#4b5563")
ax.axvline(0, color="#555555", lw=1.2)
ax.set_yticks(y)
ax.set_yticklabels([f"{r.input}  [{r.tag}]" for r in sens.itertuples()], fontsize=8.5)
ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v/1000:,.0f}k"))
ax.set_xlim(_lo - 3000, _hi + (_hi - _lo) * 0.95)
ax.set_xlabel("Net EUR per year, if the lift were 1.00 pp")
ax.grid(axis="x", lw=0.6)
chart(
    fig,
    title="Only one input can turn a profit into a loss",
    subtitle="Each input moved on its own across its plausible range, holding the lift at 1.00 pp. Red = "
             "the range crosses zero, so the answer changes somewhere inside it.",
    takeaway=f"{H('impact.sensitivity.verdict')}",
    source="impact_sensitivity.parquet, from handoff impact.sensitivity.rows",
)

st.markdown(
    f"**The risk this test cannot rule out on its own: people buying sooner, not buying more.** "
    f"{H('impact.pull_forward.rule')} At the lift on the slider, "
    f"**{100 * break_even_pp / lift_pp if lift_pp > 0 else float('nan'):.1f}%** of it has to be genuinely "
    f"new demand rather than an order that was coming anyway, or the campaign does not pay. If every extra "
    f"order is just an earlier one, it loses "
    f"EUR {abs(H('impact.pull_forward.net_if_wholly_rescheduled_eur')):,.0f} a year. That is what the "
    f"second read-out at {H('experiment_design.economics.weeks_to_g2_readout')} weeks "
    f"({H('impact.pull_forward.decided_by')}) is there to decide."
)

# ==================================================================================
st.header("What to actually do")

recs = pd.DataFrame(H("impact.recommendations"))
TIER_ICON = {"DO NOW": ":material/bolt:", "TEST NEXT": ":material/science:",
             "STOP / DON'T START": ":material/block:"}
for tier in ["DO NOW", "TEST NEXT", "STOP / DON'T START"]:
    block = recs[recs.tier == tier]
    st.subheader(f"{tier}  ({len(block)})")
    for r in block.itertuples():
        with st.expander(f"**{r.id}** — {r.what}"):
            st.markdown(
                f"**Why.** {r.why}\n\n"
                f"**What it should be worth.** {r.expected_impact}\n\n"
                f"**What it costs.** {r.cost}\n\n"
                f"**What could go wrong.** {r.risk}\n\n"
                f"**How you would know it worked.** {r.how_it_is_tested}"
            )
            st.caption(f"Evidence: {r.evidence}")

# ==================================================================================
st.header("Questions this data cannot answer")

limits = pd.DataFrame(H("impact.cannot_answer"))
limits.columns = ["Limit", "What it stops you doing", "Where it was established",
                  "What would settle it"]
st.dataframe(limits, hide_index=True, width="stretch", height=330)
st.caption(
    "This is a list rather than a footnote because the honest answer to several reasonable questions about "
    "this business is that five months of cookie-scoped clickstream cannot produce one."
)
