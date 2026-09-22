"""Eternal Product Analytics -- the dashboard.

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
    page_title="Eternal Product Analytics",
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
    st.markdown("### Eternal Product Analytics")
    st.caption("REES46 cosmetics, Oct 2019 - Feb 2020, plus the Criteo uplift experiment.")

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
        f"{n_pass}/{len(rec)} certified numbers reconcile between the notebooks and the dbt layer."
    )

    with st.expander("Where these numbers come from"):
        st.markdown(
            "This app reads **only** committed extracts and `handoff_params.json`. "
            "The extracts are aggregates built by `dashboard/build_extracts.py` from the "
            "dbt marts in `sql/`; no extract carries a user-level row, and nothing here "
            "recomputes an analytical quantity."
        )
        man = manifest()
        st.dataframe(
            man[["file", "n_rows", "grain", "source"]],
            hide_index=True, width="stretch", height=260,
        )
        st.caption(f"{man.bytes.sum() / 1e6:.2f} MB committed in total.")

    st.divider()
    st.caption(
        f"user_id is **cookie-scoped**, not account-scoped. One person on two devices is two "
        f"rows, so every retention and repeat figure on every page is a **lower bound**. "
        f"({H('data_date_range.span_days')} days of history.)"
    )

nav.run()
