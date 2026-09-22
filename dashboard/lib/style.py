"""Chart and page styling.

THE FIGURE CONVENTION IS THE NOTEBOOKS'. CLAUDE.md: every figure carries a title via
fig.text, a one-line subtitle stating scope and caveats, and a bottom-anchored TAKEAWAY
box stating the point in one sentence. No figure without a takeaway. `frame`,
`add_title`, `add_takeaway` and `thousands` are the same helpers as src/plotting.py,
re-stated here rather than imported because the deployed app is a fresh clone of
dashboard/ alone and must not reach back into the repo's analysis package.

THE PALETTE IS ALSO THE NOTEBOOKS'. Five hues, used for the same meanings everywhere in
this dashboard: PURCHASE is the primary metric and is always blue; ACTIVITY is the
superset and is always orange; a flagged or negative result is always red.
"""

from __future__ import annotations

import html

import matplotlib
import matplotlib.pyplot as plt
import streamlit as st

matplotlib.use("Agg")

# The seaborn-deep hues the notebooks draw in.
BLUE = "#4C72B0"    # purchase retention, the primary metric, DATA
ORANGE = "#DD8452"  # activity retention, the superset
GREEN = "#55A868"   # a positive / healthy reading
RED = "#C44E52"     # a flag, a negative result, an ASSUMPTION
PURPLE = "#8172B2"  # a third series
GREY = "#B0B0B0"    # ineligible, censored, not evaluable
INK = "#333333"
FAINT = "#E8E8E8"

SEQUENCE = [BLUE, ORANGE, GREEN, RED, PURPLE]

TAKEAWAY_FACE = "#FFF3CD"
TAKEAWAY_EDGE = "#8a6d3b"

BASE_RC = {
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.edgecolor": "#CCCCCC",
    "axes.labelcolor": INK,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.color": INK,
    "ytick.color": INK,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "text.color": INK,
    "legend.frameon": False,
    "legend.fontsize": 9,
    "grid.color": FAINT,
    "font.size": 10,
}
plt.rcParams.update(BASE_RC)


# Space reserved OUTSIDE the axes, in INCHES rather than as a fraction of the figure.
# src/plotting.py reserves a fraction, which is right when every figure is 6 inches tall;
# this dashboard draws figures from 3.2 to 5.2 inches, and a fraction that leaves room on
# the tall ones puts the x-axis label underneath the takeaway box on the short ones.
TITLE_BAND_IN = 0.90   # title + subtitle above the axes
TAKEAWAY_BAND_IN = 1.20  # x label, tick labels and the takeaway box below them


def frame(figsize=(10, 5.2)):
    """fig/ax with room reserved at the top for the title and at the bottom for the
    takeaway box -- src/plotting.py frame(), with the reserve measured in inches."""
    fig, ax = plt.subplots(figsize=figsize)
    h = float(figsize[1])
    fig.subplots_adjust(top=1 - TITLE_BAND_IN / h, bottom=TAKEAWAY_BAND_IN / h,
                        left=0.09, right=0.97)
    return fig, ax


def _plain(text) -> str:
    """Matplotlib draws text, not HTML. Titles and takeaways are written for both this
    and st.markdown, and several are interpolated from handoff strings, so entities are
    resolved here rather than being banned by convention and then slipping through."""
    return html.unescape(str(text))


def add_title(fig, title, subtitle=None):
    h = fig.get_size_inches()[1]
    fig.text(0.02, 1 - 0.14 / h, _plain(title), fontsize=13, fontweight="bold",
             ha="left", va="top")
    if subtitle:
        fig.text(0.02, 1 - 0.46 / h, _plain(subtitle), fontsize=9, color="dimgray",
                 ha="left", va="top")


def add_takeaway(fig, text):
    fig.text(
        0.02, 0.10 / fig.get_size_inches()[1], f"TAKEAWAY: {_plain(text)}",
        fontsize=9, ha="left", va="bottom", wrap=True,
        bbox=dict(boxstyle="round,pad=0.5", facecolor=TAKEAWAY_FACE,
                  edgecolor=TAKEAWAY_EDGE, linewidth=0.8),
    )


def thousands(x, _pos=None):
    try:
        return f"{x:,.0f}"
    except (TypeError, ValueError):
        return str(x)


def chart(fig, *, title, subtitle, takeaway, source):
    """Render one figure with its title, subtitle, takeaway and provenance line.

    `source` is not decoration -- it is the design rule for this dashboard: every number
    on screen names the mart or handoff key it came from.
    """
    add_title(fig, title, subtitle)
    add_takeaway(fig, takeaway)
    st.pyplot(fig, width="stretch")
    st.caption(f"Source: {source}")
    plt.close(fig)


# ----------------------------------------------------------------------------------
# page furniture
# ----------------------------------------------------------------------------------
CSS = """
<style>
  .block-container {padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1200px;}
  h1, h2, h3 {letter-spacing: -0.01em;}
  h1 {font-size: 1.85rem !important; margin-bottom: 0.1rem;}
  h2 {font-size: 1.22rem !important; margin-top: 1.9rem; padding-top: 0.6rem;
      border-top: 1px solid #E8E8E8;}
  h3 {font-size: 1.02rem !important; margin-top: 1.1rem;}
  .stCaption, [data-testid="stCaptionContainer"] {color: #6b7280;}
  div[data-testid="stMetricValue"] {font-size: 1.55rem;}
  div[data-testid="stMetricLabel"] {font-size: 0.8rem; color: #4b5563;}
  .tag {display:inline-block; padding:1px 7px; border-radius:3px; font-size:0.70rem;
        font-weight:700; letter-spacing:0.04em; margin-right:6px; vertical-align:middle;}
  .tag-data {background:#E4F0E7; color:#2F6B45; border:1px solid #9CC7AA;}
  .tag-assumption {background:#FBE6E6; color:#8E3035; border:1px solid #DFA3A6;}
  .tag-design {background:#E7ECF6; color:#2F4A7D; border:1px solid #A5B6D6;}
  .tag-scenario {background:#F1EAF7; color:#5B4A8A; border:1px solid #C0B0D8;}
  .lead {font-size:1.02rem; line-height:1.55; color:#374151;}
  .srcline {font-size:0.78rem; color:#6b7280; margin-top:-0.4rem;}
</style>
"""

_TAG_CLASS = {
    "DATA": "tag-data",
    "ASSUMPTION": "tag-assumption",
    "DESIGN": "tag-design",
    "SCENARIO": "tag-scenario",
}


def tag(kind: str) -> str:
    """The DATA / ASSUMPTION / DESIGN / SCENARIO chip, coloured exactly as 09 separates
    them. Returns HTML for inline use."""
    cls = _TAG_CLASS.get(kind.upper(), "tag-design")
    return f'<span class="tag {cls}">{kind.upper()}</span>'


def page_header(title: str, standfirst: str, notebooks: str):
    st.markdown(CSS, unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<p class="lead">{standfirst}</p>', unsafe_allow_html=True)
    st.caption(f"Built from: {notebooks}")


def source_line(text: str):
    st.markdown(f'<p class="srcline">Source: {text}</p>', unsafe_allow_html=True)
