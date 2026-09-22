"""Data access for the dashboard.

THE ONLY TWO SOURCES. `extract(name)` reads a committed parquet built by
build_extracts.py from the dbt marts; `H(path)` reads a scalar out of the committed copy
of handoff_params.json by json path. There is no third source and no database
connection -- the app is meant to run on Streamlit Community Cloud from a fresh clone,
with no DuckDB warehouse and no raw CSVs anywhere near it.

Nothing here computes an analytical quantity. Rates, gaps, cohort cells and anomaly flags
were all computed upstream, in SQL, against the marts. What the app does is arithmetic on
the break-even page -- a formula whose every input is a labelled ledger row -- and
formatting.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd
import streamlit as st

DATA = Path(__file__).resolve().parents[1] / "data"


class MissingSource(KeyError):
    """A number was asked for that no extract or handoff key provides."""


@st.cache_data(show_spinner=False)
def extract(name: str) -> pd.DataFrame:
    """Read one committed extract. Fails loudly: a missing file means a page would
    otherwise render a blank where a number belongs."""
    path = DATA / f"{name}.parquet"
    if not path.exists():
        raise MissingSource(
            f"dashboard/data/{name}.parquet is missing. Run `python dashboard/build_extracts.py` "
            f"against a built warehouse."
        )
    return pd.read_parquet(path)


@st.cache_data(show_spinner=False)
def handoff() -> dict:
    path = DATA / "handoff_params.json"
    if not path.exists():
        raise MissingSource("dashboard/data/handoff_params.json is missing. Run build_extracts.py.")
    return json.loads(path.read_text())


@lru_cache(maxsize=512)
def _split(path: str) -> tuple[str, ...]:
    return tuple(path.split("."))


def H(path: str, default=MissingSource):
    """Read a dotted json path out of handoff_params.json.

    Keys that themselves contain a dot (`nb03_status.p75_42.2`) are matched greedily
    against the remaining path, so the caller writes the path as it appears in the file.
    """
    node = handoff()
    parts = list(_split(path))
    while parts:
        if isinstance(node, list):
            node = node[int(parts.pop(0))]
            continue
        if not isinstance(node, dict):
            break
        # longest key first, so 'p75_42.2' wins over a spurious 'p75_42'
        for take in range(len(parts), 0, -1):
            key = ".".join(parts[:take])
            if key in node:
                node = node[key]
                parts = parts[take:]
                break
        else:
            if default is MissingSource:
                raise MissingSource(f"handoff_params.json has no key '{path}'")
            return default
    return node


def manifest() -> pd.DataFrame:
    path = DATA / "extract_manifest.parquet"
    if not path.exists():
        raise MissingSource("dashboard/data/extract_manifest.parquet is missing. Run build_extracts.py.")
    return pd.read_parquet(path)


def scope_value(metric_id: str) -> float:
    s = extract("scope")
    row = s.loc[s.id == metric_id]
    if row.empty:
        raise MissingSource(f"scope.parquet has no metric '{metric_id}'")
    return float(row.value.iloc[0])
