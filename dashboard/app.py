"""Cosmetics Retention & Growth Analytics -- the dashboard.

Entry point. Streamlit Community Cloud is pointed at this file; everything it needs is
in dashboard/ and nothing outside it is imported or read.

WHAT THIS APP IS. A reading surface over a finished analysis. It reads committed parquet
extracts built by build_extracts.py from the dbt marts, plus the copy of
handoff_params.json that carries every constant notebooks 00-09 certified. It recomputes
no analytical quantity. The single exception is the break-even calculator on the last
page, which is arithmetic over a labelled ledger and says so on screen.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.load import H, extract, manifest  # noqa: E402
from lib.style import CSS  # noqa: E402

st.set_page_config(
    page_title="Cosmetics Retention & Growth Analytics",
    page_icon="chart_with_upwards_trend",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(CSS, unsafe_allow_html=True)

PAGES = [
    ("views/overview.py", "Overview", ":material/home:"),
    ("views/acquisition.py", "Acquisition & cohorts", ":material/group_add:"),
    ("views/funnel.py", "Funnel health", ":material/filter_alt:"),
    ("views/retention.py", "Retention & churn", ":material/trending_down:"),
    ("views/segments.py", "Segments", ":material/scatter_plot:"),
    ("views/monitoring.py", "Monitoring", ":material/monitor_heart:"),
    ("views/experiment.py", "Experiment & impact", ":material/science:"),
]

with st.sidebar:
    st.markdown("### Cosmetics Retention & Growth Analytics")
    st.caption("Cosmetics shop clickstream, Oct 2019 to Feb 2020, plus Criteo's randomised ad test.")

nav = st.navigation([st.Page(p, title=t, icon=i, default=(i2 == 0))
                     for i2, (p, t, i) in enumerate(PAGES)])

with st.sidebar:
    st.divider()
    st.caption(
        f"**{int(extract('scope').loc[extract('scope').id == 'analysis_event_rows', 'value'].iloc[0]):,}** "
        f"events &nbsp;·&nbsp; "
        f"**{int(extract('scope').loc[extract('scope').id == 'purchasers', 'value'].iloc[0]):,}** purchasers"
    )
    rec = extract("reconciliation")
    n_pass = int(rec.passed.astype(bool).sum())
    st.caption(
        f"{n_pass} of {len(rec)} published numbers match between the notebooks and the SQL layer."
    )

    with st.expander("Where these numbers come from"):
        st.markdown(
            "Every number on every page was computed upstream in SQL and is read here from a "
            "checked-in file. Nothing in this app recalculates an analytical result, and no file "
            "it reads contains an individual user's row."
        )
        man = manifest()
        st.dataframe(
            man[["file", "n_rows", "grain", "source"]],
            hide_index=True, width="stretch", height=260,
        )
        st.caption(f"{man.bytes.sum() / 1e6:.2f} MB of data in total.")

    st.divider()
    st.caption(
        f"These are **cookie IDs, not accounts**. One person on a phone and a laptop counts twice, so "
        f"every retention and repeat figure on every page is a **floor, not an estimate**. "
        f"({H('data_date_range.span_days')} days of history.)"
    )

nav.run()
