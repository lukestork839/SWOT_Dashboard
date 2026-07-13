"""Shared analysis core for thesis figures.

Data access + the scientific computations, ported VERBATIM from the validated
`dashboard_swot.py` so figures reproduce the dashboard exactly. The only change is
the removal of the `@st.cache_data` decorators and Streamlit dependencies, so this
module can be imported headless (no `st.set_page_config` side effect at import).

If a computation here ever diverges from the dashboard, that is a bug -- keep them
in lockstep. The functions marked "ported from dashboard_swot.py" have matching
implementations there; line references are approximate.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import duckdb
from scipy import stats
from scipy.ndimage import gaussian_filter1d

from . import config

# Open-water months used throughout the analysis (Apr-Nov). Ice season (Dec-Mar)
# inflates WSE by 0.5-2+ m and is excluded by default. Matches SWOT_Pull.py /
# the dashboard's reference-gradient gating.
OPEN_WATER_MONTHS = (4, 5, 6, 7, 8, 9, 10, 11)


# ---------------------------------------------------------------------------
# QC EXCLUSION (single source of truth = config.EXCLUDED_PASSES)
# ---------------------------------------------------------------------------
def _exclusion_condition():
    """Bare SQL condition excluding QC-flagged passes, or None if none."""
    if not config.EXCLUDED_PASSES:
        return None
    dates = ",".join(f"CAST('{d}' AS DATE)" for d in config.EXCLUDED_PASSES)
    return f"CAST(Pass_Date AS DATE) NOT IN ({dates})"


def _drop_excluded(df: pd.DataFrame, date_col: str = "Pass_Date") -> pd.DataFrame:
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

    `river_data` is a view over the parquet so the dashboard's SQL (elevation
    difference, reference-gradient decomposition) runs unchanged.
    """
    path = data_path or config.DATA_PATH
    con = duckdb.connect()
    con.execute(f"CREATE VIEW river_data AS SELECT * FROM '{path}'")
    return con


def load_swot(
    con: duckdb.DuckDBPyConnection,
    reaches=None,
    open_water_only: bool = True,
) -> pd.DataFrame:
    """Return the full SWOT point table (no downsampling), optionally filtered.

    Unlike the dashboard (which systematically samples to MAX_PLOT_POINTS for the
    browser), thesis figures use every qualifying point.
    """
    where = []
    if reaches:
        rlist = "'" + "','".join(reaches) + "'"
        where.append(f"Reach_Name IN ({rlist})")
    if open_water_only:
        months = ",".join(str(m) for m in OPEN_WATER_MONTHS)
        where.append(f"EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) IN ({months})")
    excl = _exclusion_condition()
    if excl:
        where.append(excl)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    return con.execute(
        f"SELECT * FROM river_data {clause} ORDER BY Reach_Name, dist_km"
    ).fetchdf()


def load_temporal_metrics() -> pd.DataFrame:
    """Per-pass temporal metrics (gated, open-water) from temporal_analysis.py.

    Columns: reach, date, year, month, n_nodes, lo_km, span_km, slope_cm_km,
    wse_ref_m (WSE at 15 km = stage proxy), gated, open_water. QC exclusion applied.
    """
    import os
    path = os.path.join(config.TEMPORAL_DIR, "temporal_metrics_per_pass.parquet")
    df = duckdb.connect().execute(f"SELECT * FROM '{path}'").fetchdf()
    df["date"] = pd.to_datetime(df["date"])
    return _drop_excluded(df, "date")


def load_temporal_results() -> dict:
    """The temporal-analysis JSON (method, record, Q1/Q2/Q3 result tables)."""
    import json, os
    with open(os.path.join(config.TEMPORAL_DIR, "temporal_analysis_results.json")) as f:
        return json.load(f)


def load_reference_gradient(path: Optional[str] = None) -> pd.DataFrame:
    """Per-pass reference-gradient artifact (one row per reach x pass).

    Columns: Reach_Name, Pass_Date, month, season, open_water, n_nodes, n_pix,
    lo_km, hi_km, span_km, theilsen_cm_km, ols_cm_km, ols_r2, gated.
    """
    p = path or config.REF_GRADIENT_PATH
    df = duckdb.connect().execute(f"SELECT * FROM '{p}'").fetchdf()
    return _drop_excluded(df, "Pass_Date")


# ---------------------------------------------------------------------------
# COMPUTATIONS (ported from dashboard_swot.py)
# ---------------------------------------------------------------------------
def calculate_detrending(dist_km, wse, method):
    """Baseline + method name for the detrended profile.

    Ported from dashboard_swot.py:calculate_detrending. Returns
    (baseline_pred, coeffs, method_name).
    """
    x_all = np.array(dist_km)
    y_all = np.array(wse)

    if method == "Linear":
        slope, intercept, *_ = stats.linregress(x_all, y_all)
        baseline_pred = slope * x_all + intercept
        coeffs = [slope, intercept]
        method_name = "Linear Fit"
    elif method == "Polynomial (2nd order)":
        poly = np.polynomial.Polynomial.fit(x_all, y_all, 2)
        baseline_pred = poly(x_all)
        coeffs = poly.coef
        method_name = "2nd Order Polynomial"
    elif method == "Polynomial (3rd order)":
        poly = np.polynomial.Polynomial.fit(x_all, y_all, 3)
        baseline_pred = poly(x_all)
        coeffs = poly.coef
        method_name = "3rd Order Polynomial"
    else:  # LOESS (Gaussian-smoothed local regression)
        sorted_idx = np.argsort(x_all)
        y_sorted = y_all[sorted_idx]
        sigma = len(x_all) * 0.15 / 3
        y_smooth = gaussian_filter1d(y_sorted, sigma=sigma, mode="nearest")
        baseline_pred = np.zeros_like(y_all)
        baseline_pred[sorted_idx] = y_smooth
        coeffs = None
        method_name = "LOESS (Local Regression)"

    return baseline_pred, coeffs, method_name


def flag_residual_outliers(residuals, threshold=config.RESIDUAL_MAD_THRESHOLD):
    """Modified Z-Score (MAD-based) outlier flag on detrended residuals.

    Ported from dashboard_swot.py:flag_residual_outliers. Returns a boolean array
    (True = outlier). Nothing is deleted; callers decide how to present flags.
    """
    r = np.asarray(residuals, dtype=float)
    if len(r) == 0:
        return np.zeros(0, dtype=bool)
    median = np.median(r)
    mad = np.median(np.abs(r - median))
    if mad == 0:
        return np.zeros(len(r), dtype=bool)
    modified_z = 0.6745 * (r - median) / mad
    return np.abs(modified_z) > threshold


def calculate_slope_profile(dist_km, wse, smooth_km=2.0, n_eval=200):
    """Smoothed interval-slope profile for one river.

    Ported from dashboard_swot.py:calculate_slope_profile.
    Bins to 100 m medians, Gaussian-smooths (window ~smooth_km), then takes the
    numerical derivative. Returns (x_eval, slope_cm_km, y_fitted).
    """
    x = np.array(dist_km)
    y = np.array(wse)

    bin_size = 0.1  # km
    bins = np.round(x / bin_size) * bin_size
    df = pd.DataFrame({"bin": bins, "wse": y})
    bin_medians = df.groupby("bin")["wse"].median().sort_index()

    x_binned = np.asarray(bin_medians.index.values, dtype=float)
    y_binned = np.asarray(bin_medians.values, dtype=float)

    sigma_bins = smooth_km / bin_size
    y_smooth = gaussian_filter1d(y_binned, sigma=sigma_bins, mode="nearest")

    x_eval = np.linspace(x_binned.min(), x_binned.max(), n_eval)
    y_fitted = np.interp(x_eval, x_binned, y_smooth)
    slope_cm_km = np.gradient(y_fitted, x_eval) * 100

    return x_eval, slope_cm_km, y_fitted


def elevation_difference(con, reaches=("Kanektok_River", "Uyak_Creek"),
                         open_water_only: bool = True, bin_km: float = 0.1,
                         band=(25, 75)):
    """Per-pass Kanektok-minus-Uyak WSE difference, aggregated across passes.

    Method (improves on the dashboard's pooled AVG, which is artifact-sensitive):
    each SWOT pass images both adjacent channels near-simultaneously, so we
    difference WITHIN each pass -- removing stage/temporal variability -- then
    aggregate across passes.
      1. bin distance to `bin_km`; take the MEDIAN WSE per (pass, bin, river)
         (median = robust to localised contamination like elevated-lake pixels),
      2. within each (pass, bin) keep only bins where BOTH rivers were imaged,
         and difference Kanektok - Uyak,
      3. per bin, report the median difference across passes plus a `band`
         (percentile) spread and the contributing pass count.

    Returns a DataFrame: dist_bin, diff (median across passes), lo, hi (band
    percentiles), n_passes. `band=None` omits lo/hi.
    """
    k, u = reaches
    where = [f"Reach_Name IN ('{k}','{u}')"]
    if open_water_only:
        months = ",".join(str(m) for m in OPEN_WATER_MONTHS)
        where.append(f"EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) IN ({months})")
    excl = _exclusion_condition()
    if excl:
        where.append(excl)
    clause = "WHERE " + " AND ".join(where)
    pts = con.execute(
        f"SELECT CAST(Pass_Date AS DATE) AS pass, Reach_Name, dist_km, wse "
        f"FROM river_data {clause}"
    ).fetchdf()

    pts["dist_bin"] = (pts["dist_km"] / bin_km).round() * bin_km
    # per (pass, bin, river) median WSE
    per = (pts.groupby(["pass", "dist_bin", "Reach_Name"])["wse"].median()
              .unstack("Reach_Name"))
    per = per.dropna(subset=[k, u])          # both rivers imaged in that pass+bin
    per["diff"] = per[k] - per[u]

    grp = per.groupby("dist_bin")["diff"]
    out = grp.median().rename("diff").to_frame()
    out["n_passes"] = grp.size()
    if band is not None:
        out["lo"] = grp.quantile(band[0] / 100.0)
        out["hi"] = grp.quantile(band[1] / 100.0)
    return out.reset_index().sort_values("dist_bin").reset_index(drop=True)
