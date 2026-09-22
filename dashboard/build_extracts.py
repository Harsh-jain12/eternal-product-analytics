"""Build the dashboard's committed extracts.

WHY THIS FILE EXISTS. The dashboard is meant to run on Streamlit Community Cloud from a
fresh clone: no DuckDB warehouse, no raw CSVs, no dbt. So the app cannot query the marts
at request time. This script is the bridge -- it runs locally against the built
warehouse, aggregates, and writes small parquet files that are committed to the repo.

THE CONTRACT THIS SCRIPT ENFORCES, and the app relies on:

  1. NO USER-LEVEL ROWS. Every extract is an aggregate. `assert_no_user_level()` fails
     the build if any frame carries a user_id/user_session column or has more rows than
     a stated aggregate grain would allow.

  2. THE APP RECOMPUTES NOTHING ANALYTICAL. Every number the dashboard shows is either a
     column of one of these files or a key of handoff_params.json. Anything that needed
     a GROUP BY, a join or a rate was computed here, in SQL, against the marts.

  3. EVERY EXTRACT DECLARES ITS SOURCE. extract_manifest.parquet carries one row per
     file with its grain and the mart or handoff path it came from. The app's
     provenance captions read that manifest.

  4. RECOMPUTED FIGURES ARE RECONCILED, NOT TRUSTED. Where this script re-aggregates
     something the notebooks already certified -- the pooled retention curve, the Black
     Friday gap -- it asserts equality against handoff_params.json before writing. A
     drift fails the build here rather than appearing on a page.

  5. DETERMINISM. Every extract is written in an explicit, unique sort order, so two
     clean runs produce byte-identical parquet. quantile_cont only (never
     approx_quantile) and DuckDB at threads=1, per CLAUDE.md and src/data.py connect().

Run:  python dashboard/build_extracts.py
"""

from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

import duckdb
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
WAREHOUSE = REPO / "data" / "eternal.duckdb"
HANDOFF = REPO / "outputs" / "handoff_params.json"
OUT = Path(__file__).resolve().parent / "data"

SIZE_BUDGET_MB = 25.0

# Written in the manifest, and rendered by the app as the provenance caption.
MANIFEST: list[dict] = []


# ----------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------
def handoff_get(doc: dict, path: str):
    """Read a dotted json path out of the handoff document. Raises on a missing key --
    a silently absent key would become a silently absent number on a page."""
    node = doc
    for part in path.split("."):
        if isinstance(node, list):
            node = node[int(part)]
        else:
            if part not in node:
                raise KeyError(f"handoff_params.json has no key '{path}' (missing at '{part}')")
            node = node[part]
    return node


def assert_close(label: str, got: float, want: float, tol: float) -> None:
    if abs(float(got) - float(want)) > tol:
        raise AssertionError(f"{label}: extract computed {got!r}, handoff certifies {want!r} (tol {tol})")
    print(f"    reconciled  {label:<52} {got:>12.4f}  ==  {want:<12}")


def assert_no_user_level(name: str, df: pd.DataFrame, max_rows: int) -> None:
    banned = {"user_id", "user_session"}
    hit = banned.intersection({c.lower() for c in df.columns})
    if hit:
        raise AssertionError(f"{name}: extract carries user-level column(s) {sorted(hit)} -- refusing to write")
    if len(df) > max_rows:
        raise AssertionError(f"{name}: {len(df):,} rows exceeds the stated aggregate ceiling of {max_rows:,}")


def write(name: str, df: pd.DataFrame, *, grain: str, source: str, description: str,
          sort: list[str], max_rows: int = 5000) -> None:
    """Sort on a UNIQUE key, check the contract, write, and register in the manifest."""
    df = df.sort_values(sort, kind="mergesort").reset_index(drop=True)
    if df.duplicated(subset=sort).any():
        raise AssertionError(f"{name}: sort key {sort} is not unique -- row order would not be reproducible")
    assert_no_user_level(name, df, max_rows)
    path = OUT / f"{name}.parquet"
    df.to_parquet(path, index=False, compression="zstd")
    MANIFEST.append({
        "file": f"{name}.parquet",
        "n_rows": len(df),
        "n_columns": df.shape[1],
        "bytes": path.stat().st_size,
        "grain": grain,
        "source": source,
        "description": description,
    })
    print(f"  wrote {name + '.parquet':<38} {len(df):>6,} rows  {path.stat().st_size / 1024:>8.1f} KiB")


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson score interval for a single proportion, in percent. Used only where the
    notebooks used one; the point estimate itself always comes from a mart."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (100 * (centre - half), 100 * (centre + half))


def newcombe_diff(k1: int, n1: int, k0: int, n0: int) -> tuple[float, float]:
    """Newcombe's method for a difference of two proportions, in percentage points.
    Built from the two Wilson intervals, so it inherits their small-sample behaviour."""
    l1, u1 = wilson(k1, n1)
    l0, u0 = wilson(k0, n0)
    d = 100 * (k1 / n1 - k0 / n0)
    lo = d - math.sqrt((100 * k1 / n1 - l1) ** 2 + (u0 - 100 * k0 / n0) ** 2)
    hi = d + math.sqrt((u1 - 100 * k1 / n1) ** 2 + (100 * k0 / n0 - l0) ** 2)
    return lo, hi


# ----------------------------------------------------------------------------------
def main() -> int:
    if not WAREHOUSE.exists():
        print(f"ERROR: no warehouse at {WAREHOUSE}. Run `cd sql && DBT_PROFILES_DIR=. dbt build` first.")
        return 1
    if not HANDOFF.exists():
        print(f"ERROR: no handoff document at {HANDOFF}.")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*.parquet"):
        stale.unlink()

    doc = json.loads(HANDOFF.read_text())
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    # connect() note 3: a parallel float reduction is not reproducible. Every aggregate
    # below is one, so the fetch runs single-threaded exactly as src/data.py does it.
    con.execute("SET threads TO 1")
    q = lambda sql: con.execute(sql).fetchdf()  # noqa: E731

    print("\n1. scope ------------------------------------------------------------------")
    build_scope(q, doc)

    print("\n2. funnel -----------------------------------------------------------------")
    build_funnel(q)

    print("\n3. retention and cohorts --------------------------------------------------")
    build_retention(q, doc)

    print("\n4. churn ------------------------------------------------------------------")
    build_churn(doc)

    print("\n5. segments ---------------------------------------------------------------")
    build_segments(doc)

    print("\n6. monitoring -------------------------------------------------------------")
    build_monitoring(q)

    print("\n7. model and impact -------------------------------------------------------")
    build_model_and_impact(doc)

    print("\n8. reconciliation ---------------------------------------------------------")
    build_reconciliation(q)

    print("\n9. handoff copy and manifest ----------------------------------------------")
    shutil.copyfile(HANDOFF, OUT / "handoff_params.json")
    hsize = (OUT / "handoff_params.json").stat().st_size
    MANIFEST.append({
        "file": "handoff_params.json",
        "n_rows": 0,
        "n_columns": 0,
        "bytes": hsize,
        "grain": "one document",
        "source": "outputs/handoff_params.json (verbatim copy)",
        "description": "Every constant notebooks 00-09 certified. Carries no user-level data. "
                       "The app reads scalars from it by json path and shows the path as the source.",
    })
    print(f"  copied handoff_params.json             {hsize / 1024:>8.1f} KiB")

    man = pd.DataFrame(MANIFEST)
    man = man.sort_values("file", kind="mergesort").reset_index(drop=True)
    man.to_parquet(OUT / "extract_manifest.parquet", index=False, compression="zstd")

    total_mb = sum(p.stat().st_size for p in OUT.iterdir() if p.is_file()) / 1e6
    print(f"\n  TOTAL {total_mb:.2f} MB across {len(list(OUT.iterdir()))} files "
          f"(budget {SIZE_BUDGET_MB:.0f} MB)")
    if total_mb > SIZE_BUDGET_MB:
        print("  ERROR: over the committed-extract budget.")
        return 1
    print("  OK\n")
    return 0


# ----------------------------------------------------------------------------------
def build_scope(q, doc) -> None:
    """The project's shape, as a long register. Two columns of provenance per row so the
    app never has to guess where a number came from."""
    ev = q("select count(*) n, min(event_time) lo, max(event_time) hi, "
           "count(distinct user_id) u, count(distinct user_session) s from staging.stg_events").iloc[0]
    users = q("select count(*) n, count(*) filter (where is_purchaser) p, "
              "count(*) filter (where is_black_friday_cohort) bf, "
              "count(*) filter (where is_bulk_buyer) bulk from marts.dim_users").iloc[0]
    orders = q("select count(*) n, sum(n_items) items from marts.fct_orders").iloc[0]
    bots = q("select count(*) n from staging.stg_bot_users").iloc[0]

    rows = [
        ("raw_event_rows", "Raw event rows, all five monthly files",
         float(handoff_get(doc, "row_counts.total_events")), "count",
         "handoff", "row_counts.total_events",
         "Before bot exclusion. The five REES46 cosmetics CSVs, 2019-10-01 to 2020-02-29."),
        ("analysis_event_rows", "Event rows in the analysis base",
         float(ev.n), "count", "mart", "staging.stg_events",
         "After dropping null-session rows and the bot users. Duplicate rows are KEPT -- 00's audit "
         "found the 10.4% exact duplicates are real repeated actions at 1-second resolution."),
        ("bot_users_excluded", "Bot-like users excluded",
         float(bots.n), "count", "mart", "staging.stg_bot_users",
         "More than 29.0 sessions per active day, the exact 99.9th percentile of the real distribution."),
        ("users_any_event", "Users with at least one event",
         float(users.n), "count", "mart", "marts.dim_users",
         "Cookie-scoped. One person on two devices is two rows."),
        ("purchasers", "Users who placed at least one order",
         float(users.p), "count", "mart", "marts.dim_users",
         "The population every retention and repeat figure in this project is measured on."),
        ("orders", "Reconstructed orders",
         float(orders.n), "count", "mart", "marts.fct_orders",
         "There is no order_id in this data. Orders are GROUP BY (user_id, user_session, event_time) "
         "on purchase rows -- 00's certified rule."),
        ("order_lines", "Purchase lines across those orders",
         float(orders["items"]), "count", "mart", "marts.fct_orders",
         "Repeated purchase lines are quantity, not duplication."),
        ("sessions", "Sessions",
         float(ev.s), "count", "mart", "staging.stg_events",
         "user_session is not unique on its own -- session IDs are reused. Every session join in this "
         "project keys on (user_id, user_session)."),
        ("black_friday_cohort_users", "Purchasers acquired in the Black Friday week",
         float(users.bf), "count", "mart", "marts.dim_users",
         "First order on a day the 02 discount detector flagged. All seven flagged days fall inside one "
         "trading week, which is why the flag is named for that week and not for discounting in general."),
        ("bulk_buyers", "Bulk / reseller-signature buyers, kept and flagged",
         float(users.bulk), "count", "mart", "marts.dim_users",
         "At or above the certified P99.9 order size. 0.19% of orders, 1.4% of revenue -- kept, flagged, "
         "and kept out of every mean-based monetary metric."),
        ("span_days", "Days of history",
         float(handoff_get(doc, "data_date_range.span_days")), "count", "handoff", "data_date_range.span_days",
         "Five months. Short enough that the churn threshold is not identified by this data -- see Retention & churn."),
    ]
    df = pd.DataFrame(rows, columns=["id", "label", "value", "unit", "source_kind", "source_ref", "note"])
    df["date_min"] = str(ev.lo)
    df["date_max"] = str(ev.hi)

    assert_close("stg_events users == dim_users rows", users.n, ev.u, 0)
    write("scope", df, grain="one row per scope metric",
          source="marts.dim_users, marts.fct_orders, staging.stg_events, staging.stg_bot_users, handoff",
          description="Dataset scope, as a long register with a source per row.",
          sort=["id"])


# ----------------------------------------------------------------------------------
def build_funnel(q) -> None:
    """01's funnel at three scopes. The scopes are the finding: they are 1.8x apart and
    naming the wrong one is how a funnel chart lies."""
    sql = """
    with per_user as (
        select user_id,
               bool_or(has_view)    as u_view,
               bool_or(has_cart)    as u_cart,
               bool_or(has_removal) as u_removal,
               bool_or(converted)   as u_purchase
        from marts.fct_sessions group by 1
    ),
    raw as (
        select sum(n_view_events) v, sum(n_cart_events) c,
               sum(n_removal_events) r, sum(n_purchase_events) p
        from marts.fct_sessions
    ),
    sess as (
        select count(*) filter (where has_view) v, count(*) filter (where has_cart) c,
               count(*) filter (where has_removal) r, count(*) filter (where converted) p
        from marts.fct_sessions
    ),
    usr as (
        select count(*) filter (where u_view) v, count(*) filter (where u_cart) c,
               count(*) filter (where u_removal) r, count(*) filter (where u_purchase) p
        from per_user
    )
    select 'view' stage, 0 stage_order, raw.v raw_events, sess.v sessions_reaching, usr.v users_reaching from raw, sess, usr
    union all select 'cart', 1, raw.c, sess.c, usr.c from raw, sess, usr
    union all select 'remove_from_cart', 2, raw.r, sess.r, usr.r from raw, sess, usr
    union all select 'purchase', 3, raw.p, sess.p, usr.p from raw, sess, usr
    """
    df = q(sql)
    for col in ["raw_events", "sessions_reaching", "users_reaching"]:
        top = df.loc[df.stage == "view", col].iloc[0]
        df[f"{col}_pct_of_view"] = 100.0 * df[col] / top

    # 01's published figures, as a guard on the scope definitions.
    assert_close("funnel raw view events", df.loc[df.stage == "view", "raw_events"].iloc[0], 9401634, 0)
    assert_close("funnel sessions reaching purchase", df.loc[df.stage == "purchase", "sessions_reaching"].iloc[0], 154641, 0)
    assert_close("funnel users reaching purchase", df.loc[df.stage == "purchase", "users_reaching"].iloc[0], 109732, 0)

    write("funnel_scopes", df, grain="one row per funnel stage",
          source="marts.fct_sessions (rolled up to user grain for the user scope)",
          description="The funnel at three scopes: raw event rows, sessions reaching the stage, users "
                      "reaching the stage. Every user-scoped figure is a LOWER BOUND -- user_id is "
                      "cookie-scoped.",
          sort=["stage_order"])

    ft = q("""
        select user_type, count(*) n_sessions, count(*) filter (where converted) n_converted
        from marts.fct_sessions group by 1
    """)
    ft["conv_rate_pct"] = 100.0 * ft.n_converted / ft.n_sessions
    ci = [wilson(int(r.n_converted), int(r.n_sessions)) for r in ft.itertuples()]
    ft["ci_low_pct"] = [c[0] for c in ci]
    ft["ci_high_pct"] = [c[1] for c in ci]
    assert_close("first-time session conversion %",
                 ft.loc[ft.user_type == "first_time", "conv_rate_pct"].iloc[0], 2.3773, 0.001)
    assert_close("returning session conversion %",
                 ft.loc[ft.user_type == "returning", "conv_rate_pct"].iloc[0], 4.3260, 0.001)
    write("funnel_first_time_vs_returning", ft, grain="one row per user_type",
          source="marts.fct_sessions (is_first_time_session)",
          description="Session-scope conversion split by whether the session was the user's first. "
                      "Wilson 95% intervals computed in this extract; the counts come from the mart.",
          sort=["user_type"])

    depth = q("""
        select session_depth_bucket,
               case session_depth_bucket when '1' then 0 when '2-3' then 1 when '4-6' then 2
                    when '7-10' then 3 else 4 end as bucket_order,
               count(*) n_sessions, count(*) filter (where converted) n_converted,
               count(*) filter (where has_cart) n_with_cart
        from marts.fct_sessions group by 1, 2
    """)
    depth["conv_rate_pct"] = 100.0 * depth.n_converted / depth.n_sessions
    depth["cart_rate_pct"] = 100.0 * depth.n_with_cart / depth.n_sessions
    write("funnel_by_session_depth", depth, grain="one row per session-depth bucket",
          source="marts.fct_sessions",
          description="Session-scope conversion by how many events the session contained.",
          sort=["bucket_order"])


# ----------------------------------------------------------------------------------
def build_retention(q, doc) -> None:
    """The cohort triangle, the pooled curve, and the Black Friday contrast -- all three
    reconciled against what 02 certified before anything is written."""
    tri = q("""
        select cohort_month, bucket_day, cohort_n_users, min_trailing_days, eligible_n,
               purchase_returners, activity_returners,
               purchase_retention_pct, activity_retention_pct
        from marts.mart_cohort_retention
    """)
    tri["cohort_month"] = tri.cohort_month.astype(str)
    write("cohort_retention", tri, grain="one row per (cohort_month, bucket_day)",
          source="marts.mart_cohort_retention",
          description="The cohort triangle. An INELIGIBLE CELL HAS NO ROW -- a cohort contributes to "
                      "bucket x only if its last joiner has x trailing days. Never zero-filled.",
          sort=["cohort_month", "bucket_day"])

    pooled = q("""
        select bucket_day,
               count(*)                    as n_cohorts,
               sum(eligible_n)             as eligible_n,
               sum(purchase_returners)     as purchase_returners,
               sum(activity_returners)     as activity_returners,
               100.0 * sum(purchase_returners) / sum(eligible_n) as purchase_retention_pct,
               100.0 * sum(activity_returners) / sum(eligible_n) as activity_retention_pct
        from marts.mart_cohort_retention group by 1
    """)
    pooled["gap_pp"] = pooled.activity_retention_pct - pooled.purchase_retention_pct
    for r in pooled.itertuples():
        d = f"d{int(r.bucket_day)}"
        assert_close(f"pooled purchase retention {d}", r.purchase_retention_pct,
                     handoff_get(doc, f"retention_measured.purchase_retention_pct.{d}"), 0.005)
        assert_close(f"pooled activity retention {d}", r.activity_retention_pct,
                     handoff_get(doc, f"retention_measured.activity_retention_pct.{d}"), 0.005)
        assert_close(f"pooled eligible_n {d}", r.eligible_n,
                     handoff_get(doc, f"retention_measured.eligible_n.{d}"), 0)
    write("retention_pooled", pooled, grain="one row per bucket_day",
          source="marts.mart_cohort_retention, pooled as sum(returners)/sum(eligible_n)",
          description="The headline curves. Pooled additively over the cohorts present at each bucket, "
                      "never as an average of cohort rates. Reconciled cell by cell against "
                      "handoff retention_measured before writing.",
          sort=["bucket_day"])

    # Black Friday vs the rest, on the population held FIXED at the D90-eligible cohorts,
    # exactly as 02's primary comparison does it. The eligible cohort set is read off the
    # mart rather than hardcoded.
    bf = q("""
        with d90_cohorts as (
            select distinct cohort_month from marts.mart_cohort_retention where bucket_day = 90
        ),
        buckets as (select distinct bucket_day from marts.mart_cohort_retention),
        base as (
            select u.user_id, u.first_order_ts, u.first_order_session, u.is_black_friday_cohort
            from marts.dim_users u
            join d90_cohorts c on c.cohort_month = u.first_order_cohort_month
            where u.is_purchaser
        ),
        nxt as (
            select b.user_id,
                   min(date_diff('second', b.first_order_ts, o.order_ts) / 86400.0) as days_to_next_order
            from base b
            join marts.fct_orders o on o.user_id = b.user_id
            where o.order_ts > b.first_order_ts and o.user_session <> b.first_order_session
            group by 1
        )
        select k.bucket_day,
               case when b.is_black_friday_cohort then 'Black Friday week' else 'Rest of the window' end as cohort_group,
               count(*) as n_users,
               count(*) filter (where n.days_to_next_order <= k.bucket_day) as returners
        from base b
        cross join buckets k
        left join nxt n on n.user_id = b.user_id
        group by 1, 2
    """)
    bf["purchase_retention_pct"] = 100.0 * bf.returners / bf.n_users
    wide = bf.pivot(index="bucket_day", columns="cohort_group",
                    values=["n_users", "returners", "purchase_retention_pct"])
    gaps = []
    for bd in sorted(bf.bucket_day.unique()):
        k1 = int(wide.loc[bd, ("returners", "Black Friday week")])
        n1 = int(wide.loc[bd, ("n_users", "Black Friday week")])
        k0 = int(wide.loc[bd, ("returners", "Rest of the window")])
        n0 = int(wide.loc[bd, ("n_users", "Rest of the window")])
        lo, hi = newcombe_diff(k1, n1, k0, n0)
        gaps.append({
            "bucket_day": int(bd),
            "bf_n": n1, "bf_returners": k1, "bf_pct": 100.0 * k1 / n1,
            "rest_n": n0, "rest_returners": k0, "rest_pct": 100.0 * k0 / n0,
            "gap_pp": 100.0 * (k1 / n1 - k0 / n0), "gap_lo_pp": lo, "gap_hi_pp": hi,
        })
    gdf = pd.DataFrame(gaps)
    for r in gdf.itertuples():
        key = f"black_friday_cohort.gap_pp.d{r.bucket_day}"
        try:
            want = handoff_get(doc, key)
        except KeyError:
            continue  # 02 publishes the gap from D7 onward only
        assert_close(f"black friday gap d{r.bucket_day}", r.gap_pp, want, 0.006)
    write("black_friday_retention", gdf, grain="one row per bucket_day",
          source="marts.dim_users x marts.fct_orders, cohorts held fixed at the D90-eligible set "
                 "read from marts.mart_cohort_retention",
          description="Black Friday week acquisitions against everyone else, on ONE fixed population so "
                    "the trajectory is not composition. Gap reconciled against handoff "
                    "black_friday_cohort.gap_pp; the interval is Newcombe, computed here.",
          sort=["bucket_day"])

    lifecycle = q("""
        select order_seq, count(*) n_users
        from (select user_id, max(order_seq) order_seq from marts.fct_orders group by 1)
        where order_seq <= 5 group by 1
        union all
        select 6, count(*) from (select user_id, max(order_seq) s from marts.fct_orders group by 1) where s > 5
    """)
    lifecycle["label"] = lifecycle.order_seq.map(
        {1: "1 order", 2: "2 orders", 3: "3 orders", 4: "4 orders", 5: "5 orders", 6: "6+ orders"})
    write("orders_per_user", lifecycle, grain="one row per lifetime-order-count bucket",
          source="marts.fct_orders",
          description="How far purchasers get. Right-censored by construction -- a five-month window "
                      "cannot see an order placed in month six.",
          sort=["order_seq"])


# ----------------------------------------------------------------------------------
def build_churn(doc) -> None:
    v = handoff_get(doc, "churn_definition.validation")
    # nb03_status keys embed the threshold value ("p75_42.2"), so they are read off the
    # dict rather than through the dotted-path reader -- the key itself contains a dot.
    status = handoff_get(doc, "churn_threshold_candidates_days.nb03_status")
    rows = []
    for days_key in ["median", "p75", "p85", "p95"]:
        days = float(handoff_get(doc, f"churn_threshold_candidates_days.{days_key}"))
        matches = [k for k in status if k.startswith(f"{days_key}_")]
        if len(matches) != 1:
            raise KeyError(f"handoff churn_threshold_candidates_days.nb03_status: expected exactly one "
                           f"'{days_key}_*' key, found {matches}")
        rows.append({"candidate": days_key, "threshold_days": days, "status": status[matches[0]]})
    cand = pd.DataFrame(rows)
    write("churn_candidates", cand, grain="one row per threshold candidate",
          source="handoff churn_threshold_candidates_days",
          description="The four percentile candidates and what 03 did with each. Only P75 was certified; "
                      "P95 was never scorable at all in a 152-day window.",
          sort=["threshold_days"])

    spec = pd.DataFrame([
        {"spec": "Spec A -- matched window", "forward_window_days": v["forward_window_days_specA_matched"],
         "fp_rate_pct": v["specA"]["fp_rate_pct"], "fp_ci_lo": v["specA"]["fp_ci"][0],
         "fp_ci_hi": v["specA"]["fp_ci"][1], "recall_pct": v["specA"]["recall_pct"],
         "recall_ci_lo": v["specA"]["recall_ci"][0], "recall_ci_hi": v["specA"]["recall_ci"][1],
         "precision_pct": v["specA"]["precision_pct"], "n_flagged": v["specA"]["n_flagged"],
         "youden_j": float("nan")},
        {"spec": "Spec B -- fixed 56.9d window", "forward_window_days": v["forward_window_days_specB_fixed"],
         "fp_rate_pct": v["specB"]["fp_rate_pct"], "fp_ci_lo": v["specB"]["fp_ci"][0],
         "fp_ci_hi": v["specB"]["fp_ci"][1], "recall_pct": v["specB"]["recall_pct"],
         "recall_ci_lo": v["specB"]["recall_ci"][0], "recall_ci_hi": v["specB"]["recall_ci"][1],
         "precision_pct": v["specB"]["precision_pct"], "n_flagged": v["specB"]["n_flagged"],
         "youden_j": v["specB"]["youden_J"]},
    ])
    write("churn_validation", spec, grain="one row per validation spec",
          source="handoff churn_definition.validation",
          description="Forward validation of the certified 42.2-day rule at flag date 2020-01-04.",
          sort=["spec"])

    ap = handoff_get(doc, "churn_definition.addressable_population")
    pop = pd.DataFrame([
        {"quantity": "Evaluable base", "n": ap["n_evaluable_base"], "order": 0,
         "note": "Users scorable at the flag date."},
        {"quantity": "Truly at risk", "n": ap["n_true_at_risk"], "order": 1,
         "note": "correctly_flagged / recall. This, not the flagged count, is the population an "
                 "intervention has to be sized against."},
        {"quantity": "Flagged by the rule", "n": ap["n_flagged"], "order": 2,
         "note": "What the 42.2-day rule actually returns."},
        {"quantity": "Correctly flagged", "n": ap["n_correctly_flagged"], "order": 3,
         "note": "Flagged AND truly at risk. Precision 91.4%."},
        {"quantity": "At risk and missed", "n": ap["n_missed"], "order": 4,
         "note": "All of them sit BELOW 42.2 days of recency at the flag date -- median 23.7d. "
                 "The rule is still waiting on them."},
    ])
    write("churn_population", pop, grain="one row per population quantity",
          source="handoff churn_definition.addressable_population",
          description="Flagged is not at-risk. Recall is 53.09%, so the flagged count understates the "
                      "at-risk base by 40% -- 08 and 09 size on the flow, not on this stock.",
          sort=["order"])


# ----------------------------------------------------------------------------------
def build_segments(doc) -> None:
    segs = handoff_get(doc, "segmentation.clustering.segments")
    df = pd.DataFrame([{
        "segment": name,
        "n_users": s["n"],
        "share_pct": s["pct"],
        "repeat_pct": s["repeat_pct"],
        "churn_flag_pct": s["churn_flag_pct"],
        "basket_median_eur": s["basket_median_eur"],
        "churn_like": s["churn_like"],
    } for name, s in segs.items()])
    write("segments", df, grain="one row per behavioural segment",
          source="handoff segmentation.clustering.segments",
          description="k-means, k=4, on 8 standardised pre-purchase behaviour features. Repeat rate is "
                      "EXTERNAL -- never fitted on -- which is what makes the 4x spread across segments "
                      "evidence rather than tautology.",
          sort=["segment"])

    cells = handoff_get(doc, "segmentation.cross_tab.disagreement_cells")
    cdf = pd.DataFrame([{
        "cell": k,
        "label": c["label"],
        "n_users": c["n"],
        "pct_of_purchasers": c["pct_of_purchasers"],
        "recency_median_d": c["R_median_d"],
        "monetary_median_eur": c["M_median_eur"],
        "one_order_pct": c["one_order_pct"],
        "churn_flagged": c["churn_flagged"],
        "note": c["note"],
    } for k, c in cells.items()])
    write("segment_disagreement", cdf, grain="one row per RFM x cluster disagreement cell",
          source="handoff segmentation.cross_tab.disagreement_cells",
          description="Where the two lenses disagree. Cramer's V between them is 0.19, so they are "
                      "largely independent axes -- which is what makes these cells informative.",
          sort=["cell"])

    sil = handoff_get(doc, "segmentation.clustering.k_selection.silhouette_by_k")
    sdf = pd.DataFrame([{"k": int(k), "silhouette": v} for k, v in sil.items()])
    sdf["inertia_drop_pct"] = [handoff_get(doc, "segmentation.clustering.k_selection.inertia_drop_pct_by_k").get(str(k))
                               for k in sdf.k]
    write("segment_k_selection", sdf, grain="one row per k in the sweep",
          source="handoff segmentation.clustering.k_selection",
          description="Every silhouette in the sweep is below 0.25. These are a partition of a continuum, "
                      "not discrete customer types, and nothing downstream treats them as latent classes.",
          sort=["k"])

    st = handoff_get(doc, "segmentation.stability")
    stab = pd.DataFrame([
        {"test": "Mix drift (total variation)", "value": st["proportion_drift_tvd_pp"], "unit": "pp",
         "verdict": "structure holds", "order": 0,
         "note": "Segment proportions barely move between the fit window and the score window."},
        {"test": "Independent refit agreement (ARI)", "value": st["independent_refit_ari"], "unit": "ratio",
         "verdict": "structure holds", "order": 1,
         "note": "Refitting from scratch on the later window recovers the same four groups."},
        {"test": "Same segment two months later", "value": st["same_cluster_pct"], "unit": "pct",
         "verdict": "MEMBERSHIP DOES NOT HOLD", "order": 2,
         "note": f"Against {st['chance_pct']}% expected by chance."},
        {"test": "Cohen's kappa on membership", "value": st["cohens_kappa"], "unit": "ratio",
         "verdict": "MEMBERSHIP DOES NOT HOLD", "order": 3,
         "note": "Fair agreement at best. A stored segment label misdirects roughly two users in five."},
        {"test": "Equal-window control kappa", "value": st["equal_window_control"]["cohens_kappa"],
         "unit": "ratio", "verdict": "not an artefact", "order": 4,
         "note": "Nov-Dec vs Jan-Feb reproduces it, so the instability is behaviour, not window length."},
    ])
    write("segment_stability", stab, grain="one row per stability test",
          source="handoff segmentation.stability",
          description="The structure reproduces; the membership does not. Both halves are reported.",
          sort=["order"])


# ----------------------------------------------------------------------------------
def build_monitoring(q) -> None:
    kpi = q("""
        select activity_date, n_sessions, n_active_users, n_events, n_orders, n_items,
               n_sessions_converted, n_purchasing_users,
               conversion_rate_session_scope_pct, conversion_rate_user_scope_pct,
               gross_revenue_eur, aov_median_eur, aov_mean_winsorised_eur,
               n_orders_from_bulk_buyers, n_new_first_time_buyers, n_first_time_sessions,
               day14_trigger_pool_n, day14_trigger_pool_observable_n,
               day14_trigger_pool_repeaters_n, trigger_outcome_window_closed
        from marts.mart_daily_kpis
    """)
    kpi["activity_date"] = pd.to_datetime(kpi.activity_date)
    write("daily_kpis", kpi, grain="one row per calendar day", source="marts.mart_daily_kpis",
          description="The daily monitoring surface. Conversion appears at two LABELLED scopes because "
                      "they are different quantities; AOV is a median and a winsorised mean, never a raw "
                      "mean.",
          sort=["activity_date"])

    an = q("""
        select kpi, kpi_label, kpi_unit, kpi_source_model, activity_date, kpi_value,
               baseline_n_days, baseline_median, baseline_mad, baseline_scaled_mad,
               baseline_lower, baseline_upper, robust_z, mad_multiplier,
               baseline_window_days, min_baseline_days, not_evaluable_reason,
               is_anomaly, anomaly_direction
        from marts.mart_kpi_anomalies
    """)
    an["activity_date"] = pd.to_datetime(an.activity_date)
    n_bf = an[(an.is_anomaly == True) & (an.activity_date >= "2019-11-21")  # noqa: E712
              & (an.activity_date <= "2019-11-30")].activity_date.nunique()
    if n_bf < 1:
        raise AssertionError("monitoring rule flags no day in the Black Friday span -- extract refuses to write")
    print(f"    validated   monitoring flags {n_bf} day(s) in 2019-11-21..2019-11-30 (Black Friday)")
    write("kpi_anomalies", an, grain="one row per (kpi, activity_date)", source="marts.mart_kpi_anomalies",
          description="Trailing 28-day rolling median +/- 3 * 1.4826 * MAD, exclusive of the day itself. "
                      "A day that cannot be scored carries is_anomaly = NULL and a reason, never false.",
          sort=["kpi", "activity_date"], max_rows=5000)


# ----------------------------------------------------------------------------------
def build_model_and_impact(doc) -> None:
    base = handoff_get(doc, "modelling.baselines")
    bdf = pd.DataFrame([{
        "model": name, "ap": v["AP"], "roc": v["ROC"],
        "pct_of_shipped_excess_ap": v["pct_of_shipped_excess_AP"],
    } for name, v in base.items()])
    bdf["is_shipped"] = bdf.model.str.contains("SHIPPED")
    write("model_baselines", bdf, grain="one row per model or baseline",
          source="handoff modelling.baselines",
          description="The ladder from prevalence to LightGBM on repeat_purchase_30d. AP is the primary "
                      "metric; ROC is secondary. One raw feature recovers 74% of the shipped model's "
                      "excess AP over prevalence.",
          sort=["ap"])

    dec = handoff_get(doc, "modelling.shipped_model")
    dm = pd.DataFrame([
        {"metric": "Test AP (primary)", "value": dec["test_AP"], "order": 0,
         "note": f"Against a prevalence baseline of {base['BASE  prevalence only']['AP']:.4f} -- a lift of "
                 f"{dec['test_AP_lift_vs_base']:.2f}x."},
        {"metric": "Test ROC-AUC (secondary)", "value": dec["test_ROC_AUC"], "order": 1,
         "note": "Against the 0.6097 single-feature ceiling 05 measured across all 81 features."},
        {"metric": "Brier score", "value": dec["test_Brier_shipped"], "order": 2, "note": "Calibration."},
        {"metric": "Decile-1 lift", "value": dec["decile1_lift"], "order": 3,
         "note": "The top decile repeats 1.88x the base rate."},
        {"metric": "Top-3 decile capture %", "value": dec["top3_decile_capture_pct"], "order": 4,
         "note": "30% of users carry 45% of the repeat purchases."},
    ])
    write("model_headline", dm, grain="one row per shipped-model metric",
          source="handoff modelling.shipped_model",
          description="What the shipped logistic model actually achieves. Weak, and reported as weak.",
          sort=["order"])

    ledger = handoff_get(doc, "experiment_design.economics.ledger")
    ldf = pd.DataFrame([{
        "input": k, "value": v["value"], "tag": v["tag"], "source": v["source"],
    } for k, v in ledger.items()])
    label = {
        "base_rate": "Base rate of the day-14 trigger pool",
        "aov_second_order": "AOV of a second order (EUR)",
        "downstream_uplift": "Downstream value multiplier - 1",
        "first_buyer_inflow_per_day": "First-time buyers per day",
        "trigger_survival_share": "Share still enrollable at day 14",
        "contact_cost": "Cost per contact (EUR)",
        "contribution_margin": "Contribution margin",
        "discount_rate": "Discount offered in the treatment arm",
    }
    ldf["label"] = ldf.input.map(label).fillna(ldf.input)
    write("impact_ledger", ldf, grain="one row per economic input",
          source="handoff experiment_design.economics.ledger",
          description="The break-even inputs, each tagged DATA or ASSUMPTION at source. The dashboard's "
                      "calculator gives a slider ONLY to the ASSUMPTION rows and to the scenario lift; "
                      "the DATA rows are fixed and shown with their provenance.",
          sort=["input"])

    sens = handoff_get(doc, "impact.sensitivity.rows")
    if isinstance(sens, list) and sens and isinstance(sens[0], dict):
        write("impact_sensitivity", pd.DataFrame(sens).assign(_o=range(len(sens))),
              grain="one row per sensitivity input", source="handoff impact.sensitivity.rows",
              description="One-at-a-time sensitivity around the 1.00 pp scenario.",
              sort=["_o"])


# ----------------------------------------------------------------------------------
def build_reconciliation(q) -> None:
    rec = q("""
        select check_name, handoff_json_path, model_value, handoff_value, tolerance, passed
        from marts.mart_reconciliation
    """)
    n_fail = int((~rec.passed.astype(bool)).sum())
    if n_fail:
        raise AssertionError(f"{n_fail} reconciliation check(s) failing in the warehouse -- refusing to "
                             f"publish extracts built on it")
    print(f"    validated   all {len(rec)} reconciliation checks pass in the warehouse")
    write("reconciliation", rec, grain="one row per certified number",
          source="marts.mart_reconciliation",
          description="Every certified figure, recomputed from the raw CSVs by the dbt layer and compared "
                      "back to what the notebooks published. All must pass or this extract is not written.",
          sort=["check_name"])


if __name__ == "__main__":
    sys.exit(main())
