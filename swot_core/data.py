"""Headless data access: DuckDB connection + loaders with QC exclusion applied.

These are the streamlit-free loaders (previously `thesis_figures/core.py`). The
dashboards keep their own connection layer (`get_database_connection`) because it
adds Streamlit-specific concerns — resource caching, httpfs fallback messaging,
extra views — but the SQL contract is shared: every consumer binds the SWOT point
table to a `river_data` view so the computations in `swot_core.stats` run
unchanged against any source.
"""

from __future__ import annotations

import json
import os
from typing import Optional

import duckdb
import pandas as pd

from . import config


# ---------------------------------------------------------------------------
# QC EXCLUSION (single source of truth = config.EXCLUDED_PASSES -> qc_registry)
# ---------------------------------------------------------------------------
def exclusion_condition():
    """Bare SQL condition excluding QC-flagged passes, or None if none."""
    if not config.EXCLUDED_PASSES:
        return None
    dates = ",".join(f"CAST('{d}' AS DATE)" for d in sorted(config.EXCLUDED_PASSES))
    return f"CAST(Pass_Date AS DATE) NOT IN ({dates})"


def drop_excluded(df: pd.DataFrame, date_col: str = "Pass_Date") -> pd.DataFrame:
    """Filter QC-flagged passes out of a DataFrame (dates compared as strings)."""
    if not config.EXCLUDED_PASSES or date_col not in df.columns:
        return df
    d = pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d")
    return df.loc[~d.isin(config.EXCLUDED_PASSES)]


# ---------------------------------------------------------------------------
# DATA ACCESS
# ---------------------------------------------------------------------------
def connect(data_path: Optional[str] = None) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection with `river_data` bound to the SWOT parquet.

    Defaults to the FULL local archive (thesis convention); pass
    `config.DEPLOY_DATA_PATH` or a URL for the deployment subset. `river_data`
    is a view over the parquet so the shared SQL runs unchanged.
    """
    path = data_path or config.FULL_DATA_PATH
    con = duckdb.connect()
    con.execute(f"CREATE VIEW river_data AS SELECT * FROM '{path}'")
    return con


def load_swot(
    con: duckdb.DuckDBPyConnection,
    reaches=None,
    open_water_only: bool = True,
) -> pd.DataFrame:
    """Return the full SWOT point table (no downsampling), optionally filtered.

    Unlike the dashboards (which systematically sample to a plot-point cap for
    the browser), this returns every qualifying point.
    """
    where = []
    if reaches:
        rlist = "'" + "','".join(reaches) + "'"
        where.append(f"Reach_Name IN ({rlist})")
    if open_water_only:
        months = ",".join(str(m) for m in config.OPEN_WATER_MONTHS)
        where.append(f"EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) IN ({months})")
    excl = exclusion_condition()
    if excl:
        where.append(excl)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    return con.execute(
        f"SELECT * FROM river_data {clause} ORDER BY Reach_Name, dist_km"
    ).fetchdf()


def load_reference_gradient(path: Optional[str] = None) -> pd.DataFrame:
    """Per-pass reference-gradient artifact (one row per reach x pass).

    Columns: Reach_Name, Pass_Date, month, season, open_water, n_nodes, n_pix,
    lo_km, hi_km, span_km, theilsen_cm_km, ols_cm_km, ols_r2, gated.
    """
    p = path or config.REF_GRADIENT_PATH
    df = duckdb.connect().execute(f"SELECT * FROM '{p}'").fetchdf()
    return drop_excluded(df, "Pass_Date")


def load_temporal_metrics() -> pd.DataFrame:
    """Per-pass temporal metrics (gated, open-water) from temporal_analysis.py.

    Columns: reach, date, year, month, n_nodes, lo_km, span_km, slope_cm_km,
    wse_ref_m (WSE at 15 km = stage proxy), gated, open_water. QC exclusion applied.
    """
    path = os.path.join(config.TEMPORAL_DIR, "temporal_metrics_per_pass.parquet")
    df = duckdb.connect().execute(f"SELECT * FROM '{path}'").fetchdf()
    df["date"] = pd.to_datetime(df["date"])
    return drop_excluded(df, "date")


def load_temporal_results() -> dict:
    """The temporal-analysis JSON (method, record, Q1/Q2/Q3 result tables)."""
    with open(os.path.join(config.TEMPORAL_DIR, "temporal_analysis_results.json")) as f:
        return json.load(f)
