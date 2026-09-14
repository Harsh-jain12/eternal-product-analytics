"""Shared DuckDB data-access layer for the Eternal Product Analytics notebooks.

Defined once here (per CLAUDE.md convention) and imported by every notebook after
00_data_quality.ipynb instead of re-deriving connection setup, the cleaning rules
certified in outputs/tables/data_quality_audit.csv, or the certified order-
reconstruction rule.
"""

import os

import duckdb

RAW_GLOB = os.path.join("data", "raw", "*.csv")


def connect(memory_limit="5GB", threads=6):
    """Open a DuckDB connection tuned for out-of-core CSV scans on an 8GB machine."""
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET threads={threads}")
    con.execute("SET enable_progress_bar=false")
    return con


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
    SELECT user_id, user_session, event_time AS order_ts,
           count(*) AS n_items, sum(price) AS order_value
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
           count(*) AS n_items, sum(price) AS order_value
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
