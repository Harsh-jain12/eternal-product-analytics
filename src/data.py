"""Shared DuckDB data-access layer for the Eternal Product Analytics notebooks.

Defined once here (per CLAUDE.md convention) and imported by every notebook after
00_data_quality.ipynb instead of re-deriving connection setup, the cleaning rules
certified in outputs/tables/data_quality_audit.csv, or the certified order-
reconstruction rule.
"""

import os

import duckdb
import numpy as np
import pandas as pd


def round_sig(df, cols, sig=6):
    """Round float columns to `sig` significant figures, in place, and return df.

    THE GUARD FOR NON-DETERMINISTIC FLOAT AGGREGATES, promised in connect()'s note 3 and
    first actually needed in 04. Parallel `avg`/`sum` in DuckDB reduce in physical scan
    order, so the last few ULPs of any float aggregate move between evaluations of the
    same query. Measured in 04 over the 109,732-row feature table, two runs of one query
    inside a single session (the exact counts, and which rows differ, move between
    executions -- that is the phenomenon, not noise in measuring it):

        mean_price_pct_viewed   ~30,000 rows differ, max |diff| 6.7e-16
        category_entropy        ~27,000 rows differ, max |diff| 8.9e-15
        brand_entropy           ~24,000 rows differ, max |diff| 4.4e-15
        mean_intersession_gap_d     ~30 rows differ, max |diff| 1.8e-15

    That is cosmetic for a reported mean and NOT cosmetic for anything iterative: fed to
    k-means it moved ~0.1% of users across cluster boundaries and changed every segment
    size between runs at a fixed seed. Rounding to 6 significant figures drops all three
    to zero differing rows while preserving far more precision than any figure this
    project reports.

    Use significant figures, not decimals: these features span 1e-3 to 1e3, so a fixed
    decimal count would over-round the small ones and under-round the large ones.

    THIS GUARD ALONE IS NOT SUFFICIENT. There is a second, independent source of
    non-determinism in the same pipeline: `fetchdf()` returns rows in parallel-scan
    order, which is not stable across evaluations, and k-means++ picks its initial
    centres by sampling row INDICES. Rounding the values and leaving the order alone
    still produced different segment sizes on every run. Always pair this with a
    canonical sort:

        df = round_sig(con.execute(SQL).fetchdf(), FLOAT_COLS).sort_values("user_id")

    Row order is irrelevant to every order-invariant statistic, which is exactly why it
    is easy to miss.
    """
    for c in cols:
        v = df[c].to_numpy(dtype="float64", copy=True)
        ok = np.isfinite(v) & (v != 0)
        if ok.any():
            mag = np.floor(np.log10(np.abs(v[ok])))
            factor = np.power(10.0, (sig - 1) - mag)
            v[ok] = np.round(v[ok] * factor) / factor
        df[c] = v
    return df


def key_round(x, dp=6):
    """Round a float BEFORE it is used as an ORDERING or BUCKETING key. The RC-1 guard.

    THE FOURTH FAILURE MODE, and the only one that AMPLIFIES. connect()'s notes 1-3 cover
    values that wobble in their last bits; that is cosmetic for a reported mean. It is not
    cosmetic when the wobbling float is a SORT KEY, a rank key, or a quantile-cut key,
    because then a difference of 1e-13 decides an ORDERING and comes back out as a whole
    rank step -- a difference of order 1e-2 in a percentile, or a row moving to the other
    side of a bucket boundary. A sub-reported-precision wobble is amplified into a
    difference that is visible at reported precision. Measured in 05's prod_ref:

        percent_rank() OVER (PARTITION BY d ORDER BY psp/pn, product_id)
            two processes, same data -> 597,236 of 3,113,627 ranks differ, max |diff| 0.0423
        percent_rank() OVER (PARTITION BY d ORDER BY round(psp/pn, 6), product_id)
            two processes, same data -> 0 differ

    The tie-break column (product_id) does not save you: two products at the same price are
    not equal once their accumulated sums differ by one bit, so the tie-break never fires.
    Rounding restores the tie, and only then does the declared tie-break decide it.

    6 decimal places is the project default: coarser than any observed wobble (~1e-13) by
    seven orders of magnitude, and finer than any quantity this project reports. Use
    sig_round() instead for a key that spans many orders of magnitude, such as a predicted
    probability, where a fixed decimal count would erase the small end.
    """
    if isinstance(x, pd.Series):
        return x.round(dp)
    return np.round(np.asarray(x, dtype="float64"), dp)


def sig_round(x, sig=12):
    """key_round() for a key spanning many orders of magnitude (e.g. a probability).

    Keeps `sig` significant figures rather than `dp` decimals. 12 is the default: far finer
    than anything reported (deciles are quoted to 3-4 s.f.), far coarser than the wobble.
    """
    v = np.asarray(x, dtype="float64").copy()
    ok = np.isfinite(v) & (v != 0)
    if ok.any():
        mag = np.floor(np.log10(np.abs(v[ok])))
        factor = np.power(10.0, (sig - 1) - mag)
        v[ok] = np.round(v[ok] * factor) / factor
    return pd.Series(v, index=x.index, name=x.name) if isinstance(x, pd.Series) else v


RAW_GLOB = os.path.join("data", "raw", "*.csv")


def connect(memory_limit="5GB", threads=6):
    """Open a DuckDB connection tuned for out-of-core CSV scans on an 8GB machine.

    DETERMINISM UNDER MULTI-THREADING (isolated empirically in 02; supersedes the
    blanket threads=1 that 01 was run under). Multi-threaded execution is safe and
    is the default again, PROVIDED three guardrails hold. What was actually
    non-deterministic, and what was not:

      NOT deterministic
      1. `row_number() OVER ()` inside a LAZY VIEW. A view is re-evaluated on every
         reference, and with no ORDER BY the id is assigned in physical scan order,
         which differs per evaluation once the scan is parallelised. Measured: 99.97%
         of ids pointed at a DIFFERENT row across two evaluations of the same view.
         This is a CORRECTNESS bug (joins land on the wrong rows), not a cosmetic
         one, and it is plan-dependent -- it does NOT reproduce on small inputs, so
         "it looked fine" is not evidence of safety.
         GUARD: materialise anything carrying a synthetic row id -- see materialize().
      2. `approx_quantile` (sketch-based). Measured 4.0754 vs 4.0705 for the same
         median across two runs -- materially different, not a rounding artefact.
         GUARD: use `quantile_cont` (exact) for every reported percentile.
      3. Raw float `sum`/`avg`: parallel summation order changes the last ~7
         significant figures. Cosmetic only *as a value*, but see 4.
         GUARD: round to reporting precision (2dp money, 6dp rates) -- round_sig().
      4. ANY OF THE ABOVE USED AS AN ORDERING OR BUCKETING KEY. This is the one that
         amplifies, and it is why 3 is not merely cosmetic. A wobble of 1e-13 in a
         value is invisible; the same wobble in a `percent_rank` ORDER BY, a
         `pd.qcut` key or a `np.digitize` key decides an ORDERING and re-emerges as a
         whole rank step -- measured at max |diff| 0.0423 on a percentile in 05's
         prod_ref, 597,236 of 3,113,627 ranks moving between two processes. A
         tie-break column does not save you: the values are no longer tied.
         GUARD: key_round() / sig_round() -- round the key BEFORE it is used as one.

      Deterministic (verified): count(*), count(DISTINCT), min/max, quantile_cont,
      and window functions over an already-materialised table.
    """
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET threads={threads}")
    con.execute("SET enable_progress_bar=false")
    return con


def materialize(con, name, select_sql):
    """Create `name` as a real TABLE (not a view) from select_sql.

    Use for (a) anything carrying a synthetic row id -- mandatory for correctness,
    see connect() -- and (b) any relation referenced more than a couple of times,
    since a view over the raw CSVs re-scans ~2.4GB on every single reference.
    """
    con.execute(f"CREATE OR REPLACE TABLE {name} AS {select_sql}")
    return con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]


def materialize_view(con, view_name):
    """Replace an existing lazy view with an identically-named materialised table."""
    tmp = f"{view_name}__mat"
    con.execute(f"CREATE OR REPLACE TABLE {tmp} AS SELECT * FROM {view_name}")
    con.execute(f"DROP VIEW IF EXISTS {view_name}")
    con.execute(f"ALTER TABLE {tmp} RENAME TO {view_name}")
    return con.execute(f"SELECT count(*) FROM {view_name}").fetchone()[0]


def load_raw_events(con, glob_path=RAW_GLOB, view_name="ev_raw"):
    """Create a typed view directly over the raw CSVs. Returns the row count."""
    con.execute(f"CREATE OR REPLACE VIEW {view_name} AS SELECT * FROM read_csv_auto('{glob_path}', filename=true)")
    return con.execute(f"SELECT count(*) FROM {view_name}").fetchone()[0]


def drop_null_sessions(con, raw_view="ev_raw", out_view="ev_valid_session"):
    """Structural cleaning rule from 00 (null_user_session, 0.02% of rows): every
    session-scoped join in this project uses (user_id, user_session) as its key, so
    rows without a session cannot participate and are excluded here, once."""
    before = con.execute(f"SELECT count(*) FROM {raw_view}").fetchone()[0]
    con.execute(f"CREATE OR REPLACE VIEW {out_view} AS SELECT * FROM {raw_view} WHERE user_session IS NOT NULL")
    after = con.execute(f"SELECT count(*) FROM {out_view}").fetchone()[0]
    return before, after


def compute_user_activity_stats(con, events_view="ev_valid_session", view_name="user_activity_stats"):
    """Per-user event/session/active-day counts -- the basis for the bot-exclusion
    threshold (a rate: sessions per active day), not a hardcoded rule."""
    con.execute(f"""
        CREATE OR REPLACE VIEW {view_name} AS
        SELECT user_id,
               count(*) AS n_events,
               count(DISTINCT user_session) AS n_sessions,
               count(DISTINCT date_trunc('day', event_time)) AS n_active_days,
               count(DISTINCT user_session) * 1.0 / count(DISTINCT date_trunc('day', event_time)) AS sess_per_active_day
        FROM {events_view}
        GROUP BY user_id
    """)
    return view_name


def exclude_users(con, events_view, excluded_ids_view, out_view="ev"):
    """Project-wide bot exclusion: drop every event belonging to a flagged user_id.
    excluded_ids_view must expose a single `user_id` column."""
    before = con.execute(f"SELECT count(*) FROM {events_view}").fetchone()[0]
    con.execute(f"""
        CREATE OR REPLACE VIEW {out_view} AS
        SELECT * FROM {events_view}
        WHERE user_id NOT IN (SELECT user_id FROM {excluded_ids_view})
    """)
    after = con.execute(f"SELECT count(*) FROM {out_view}").fetchone()[0]
    return before, after


CERTIFIED_ORDER_RULE_SQL = """
    -- round(sum(price), 6): sum() is a parallel float reduction, so order_value differed
    -- in its last bit on 10 of 158,399 orders between two clean runs. Cosmetic as a value
    -- (6 dp on a euro sum is four orders of magnitude finer than anything reported) and
    -- NOT cosmetic the moment anything sorts or buckets on it -- see connect() note 4.
    -- Rounded here, once, so the view and data/processed/orders.parquet cannot disagree.
    SELECT user_id, user_session, event_time AS order_ts,
           count(*) AS n_items, round(sum(price), 6) AS order_value
    FROM {events_view}
    WHERE event_type = 'purchase'
    GROUP BY user_id, user_session, event_time
"""


def create_orders_view(con, events_view="ev", view_name="orders"):
    """Certified order-reconstruction rule from 00_data_quality.ipynb:
    GROUP BY (user_id, user_session, event_time) on purchase events -- validated at
    98.1% same-timestamp agreement across multi-purchase-row sessions. Do not
    substitute a gap-based or session-only rule; always call this function."""
    con.execute(f"CREATE OR REPLACE VIEW {view_name} AS {CERTIFIED_ORDER_RULE_SQL.format(events_view=events_view)}")
    return view_name


REJECTED_SESSION_ONLY_ORDER_SQL = """
    SELECT user_id, user_session, min(event_time) AS order_ts,
           count(*) AS n_items, round(sum(price), 6) AS order_value
    FROM {events_view}
    WHERE event_type = 'purchase'
    GROUP BY user_id, user_session
"""


def create_rejected_session_only_orders_view(con, events_view="ev", view_name="orders_session_only_rejected"):
    """The rule 00 rejected (one order per session, ignoring within-session timestamp
    splits). Kept available only for the one-line robustness comparison nb01 reports
    -- never used as the basis for any rate."""
    con.execute(f"CREATE OR REPLACE VIEW {view_name} AS {REJECTED_SESSION_ONLY_ORDER_SQL.format(events_view=events_view)}")
    return view_name
