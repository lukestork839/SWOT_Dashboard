"""The project's scientific computations, shared by every consumer.

History: these functions previously existed twice — in `dashboard_swot.py`
(with `st.cache_data`) and hand-copied into `thesis_figures/core.py` — and the
copies drifted (the 2026-08 gap-honest slope rewrite and the polynomial
coefficient-domain fix reached only the dashboard). This module is the single
surviving implementation, taken from the validated dashboard versions;
`tools/regression_gate.py` proved output-identity at extraction time.

No streamlit here: apps add `st.cache_data` wrappers at their own layer.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from scipy.ndimage import gaussian_filter1d

from . import config
from .data import exclusion_condition


# ---------------------------------------------------------------------------
# BINNING
# ---------------------------------------------------------------------------
def round_half_away(x):
    """Round to the nearest integer with ties going AWAY from zero.

    Distance binning happens in two domains — DuckDB SQL (``ROUND(dist_km/w)*w``,
    which rounds ties away from zero) and numpy (``np.round``, which rounds ties
    to the nearest EVEN integer, "banker's rounding"). dist_km is float32, so
    values like 9.25 or 24.75 sit EXACTLY on a bin boundary and the two
    conventions put them in different bins (in the archive: 76 exact ties at
    the 0.1 km width, 14 at 0.5 km, 10 at 1.0 km). Every numpy binning site
    rounds through this helper so both domains agree; the project standardizes
    on half-away-from-zero because the heavy binning lives in SQL.

    PRECISION INVARIANT: the tie convention is only half of the agreement —
    the quotient ``dist_km / w`` must also be formed in float32, because that
    is what DuckDB does (REAL / DECIMAL evaluates in FLOAT). 17 archive points
    at the 0.1 km width are exact ties in float32 but not in float64 (e.g.
    35.049999f/0.1 == 350.5 in float32, 350.4999… in float64), so a caller
    that divides in float64 lands them in a different bin than SQL no matter
    how the tie is broken. Callers holding float64 values (e.g. from
    ``.tolist()``) must cast to float32 before dividing; ``.to_numpy()`` on
    the stored float32 column divided by a Python-float width already stays
    float32.

    Only exact .5 ties are overridden — everything else is np.round — so this
    has none of the float-drift of the naive ``floor(x + 0.5)``.
    """
    x = np.asarray(x, dtype=float)
    a = np.abs(x)
    fl = np.floor(a)
    nearest = np.where(a - fl == 0.5, fl + 1.0, np.round(a))
    return np.copysign(nearest, x)


# ---------------------------------------------------------------------------
# DETRENDING + RESIDUAL FLAGGING
# ---------------------------------------------------------------------------
def calculate_detrending(dist_km, wse, method):
    """Baseline for the detrended profile.

    Returns (baseline_pred, coeffs, method_name). `coeffs` are in the REAL
    dist_km domain (`poly.convert().coef` — numpy's `poly.coef` alone is in an
    internal scaled domain, a reporting trap) and in ASCENDING power order for
    every method (c0 + c1*x + …), so any method's baseline can be re-evaluated
    at new points with `np.polynomial.polynomial.polyval(x, coeffs)`.

    Note: the retired LOESS baseline was removed with the dashboard's method
    selector (only the 2nd-order polynomial is exposed in the UI; Linear/3rd
    remain for analysis use). An unknown method now raises instead of silently
    falling through to LOESS.
    """
    x_all = np.array(dist_km)
    y_all = np.array(wse)

    if method == "Linear":
        slope, intercept, *_ = stats.linregress(x_all, y_all)
        baseline_pred = slope * x_all + intercept
        coeffs = [intercept, slope]  # ascending, like the polynomial branches
        method_name = "Linear Fit"
    elif method == "Polynomial (2nd order)":
        poly = np.polynomial.Polynomial.fit(x_all, y_all, 2)
        baseline_pred = poly(x_all)
        coeffs = poly.convert().coef
        method_name = "2nd Order Polynomial"
    elif method == "Polynomial (3rd order)":
        poly = np.polynomial.Polynomial.fit(x_all, y_all, 3)
        baseline_pred = poly(x_all)
        coeffs = poly.convert().coef
        method_name = "3rd Order Polynomial"
    else:
        raise ValueError(f"unsupported detrend method {method!r} (LOESS was retired)")

    return baseline_pred, coeffs, method_name


def flag_residual_outliers(residuals, threshold=config.RESIDUAL_MAD_THRESHOLD):
    """Flag detrended residuals as outliers via the Modified Z-Score (MAD-based).

    Same estimator as the ingestion filter (calculate_mad_outliers in SWOT_Pull.py):
    Modified Z = 0.6745 * (x - median) / MAD, flagged when |Z| > threshold. The
    difference is the DOMAIN: applied here to residuals (data minus baseline), not
    raw WSE, so the trend no longer inflates the spread and the flag isolates the
    genuinely anomalous points instead of being masked by the downstream gradient.

    Returns a boolean array (True = outlier) aligned to `residuals`. Nothing is
    deleted -- callers decide how to present flagged points.
    """
    r = np.asarray(residuals, dtype=float)
    if len(r) == 0:
        return np.zeros(0, dtype=bool)
    median = np.median(r)
    mad = np.median(np.abs(r - median))
    if mad == 0:  # degenerate spread -> flag nothing
        return np.zeros(len(r), dtype=bool)
    modified_z = 0.6745 * (r - median) / mad
    return np.abs(modified_z) > threshold


# ---------------------------------------------------------------------------
# POOLED SLOPE PROFILE (Slope Profile tab / thesis Fig 8)
# ---------------------------------------------------------------------------
def calculate_slope_profile(dist_km, wse, smooth_km=2.0, n_eval=200):
    """Smoothed interval-slope profile for one river (pooled across passes).

    1. Bin raw data into regular 100 m intervals (median WSE per bin)
    2. NaN-aware Gaussian smoothing of the binned WSE (window ~ smooth_km)
    3. Numerical derivative of the smoothed curve

    Returns (x_eval, slope_cm_km, y_fitted). Coverage holes stay NaN — gaps are
    honest, never interpolated across (the pre-2026-08 version smoothed across
    holes and could invent up to ~280 cm/km of spurious slope).
    """
    x = np.array(dist_km)
    y = np.array(wse)

    # Bin into 100m intervals and take median (robust to outliers).
    # round_half_away keeps exact-boundary points in the same bin as the SQL
    # ROUND-based paths (np.round would send ties to the even bin instead).
    # The division must happen in float32 like DuckDB's REAL/DECIMAL: callers
    # pass .tolist() (float64), where 17 archive points lose their exact-tie
    # status and would bin differently (see the round_half_away docstring).
    bin_size = 0.1  # km
    bins = round_half_away(x.astype(np.float32) / np.float32(bin_size)) * bin_size
    df = pd.DataFrame({'bin': bins, 'wse': y})
    bin_medians = df.groupby('bin')['wse'].median().sort_index()

    # Place the bins on an EXPLICIT regular grid with NaN holes. The raw bin
    # list skips empty bins, and both the Gaussian filter (which smooths over
    # array positions, not distance) and np.interp would otherwise treat bins
    # on opposite sides of a coverage hole as adjacent — measured up to
    # ~280 cm/km of spurious slope on sparse selections.
    ibin = np.round(bin_medians.index.values / bin_size).astype(int)
    grid_i = np.arange(ibin.min(), ibin.max() + 1)
    x_grid = grid_i * bin_size
    y_grid = np.full(grid_i.shape, np.nan)
    y_grid[ibin - ibin[0]] = bin_medians.values

    # NaN-aware Gaussian smoothing (normalized convolution): smooth the data
    # with missing bins as zero, smooth the coverage mask the same way, and
    # divide — each output is a weighted mean of the data the kernel actually
    # saw. Where real data carries <25% of the kernel weight (deep inside a
    # hole or far past the data ends) the estimate is untrustworthy: leave NaN
    # so the profile shows a gap instead of an invented curve.
    sigma_bins = smooth_km / bin_size
    have = ~np.isnan(y_grid)
    num = gaussian_filter1d(np.where(have, y_grid, 0.0), sigma=sigma_bins, mode='constant')
    den = gaussian_filter1d(have.astype(float), sigma=sigma_bins, mode='constant')
    with np.errstate(invalid='ignore', divide='ignore'):
        y_smooth = num / den
    y_smooth[den < 0.25] = np.nan

    # Interpolate onto regular eval grid, keeping gaps as gaps
    x_eval = np.linspace(x_grid.min(), x_grid.max(), n_eval)
    valid = ~np.isnan(y_smooth)
    y_fitted = np.interp(x_eval, x_grid[valid], y_smooth[valid])
    coverage = np.interp(x_eval, x_grid, valid.astype(float))
    y_fitted[coverage < 0.5] = np.nan

    # Numerical derivative: slope in m/km -> * 100 for cm/km
    # (NaN gaps propagate to the slope at and beside gap bins — honest gaps.)
    slope_cm_km = np.gradient(y_fitted, x_eval) * 100

    return x_eval, slope_cm_km, y_fitted


# ---------------------------------------------------------------------------
# FINE-SCALE SLOPE (per-pass then aggregate)
# ---------------------------------------------------------------------------
# Unlike calculate_slope_profile (which POOLS all passes then Gaussian-smooths at
# ~2 km, mixing stage into the slope), this computes the slope WITHIN each pass
# (stage constant), then aggregates the median across passes -- resolving the
# backwater-scale (~0.5 km) structure near the bifurcation. Requires the FULL
# multi-pass record; a handful of passes starves the min-pass gate.
FINE_BASE_BIN_KM = 0.1          # base grid for per-pass profiles
FINE_MIN_PIX_BIN = 30           # trust a bin's median only with >= this many pixels
FINE_FILL_GAP_KM = 0.3          # per pass, interpolate internal gaps up to this wide


def fine_slope_theilsen(x, y, res_km):
    """Robust sliding Theil-Sen slope (cm/km); window width = res_km.

    At each grid point xc, take every pair of binned elevations within +/- res_km/2
    of xc, compute each pair's slope, and use the MEDIAN of those pairwise slopes
    (Theil-Sen). Median-of-pairs is robust: a contaminated bin only taints the pairs
    that include it, so it is outvoted. This is the same estimator as the reference
    gradient, applied at fine resolution. It is the sole fine-scale estimator (the
    Gaussian/Sav-Gol alternatives were dropped -- they agree at 0.5 km and Theil-Sen
    is the defensible choice).
    """
    half = res_km / 2.0
    out = np.full_like(y, np.nan)
    for i, xc in enumerate(x):
        m = np.abs(x - xc) <= half
        if m.sum() >= 3:
            xs, ys = x[m], y[m]
            good = np.isfinite(ys)
            if good.sum() >= 3:
                out[i] = stats.theilslopes(ys[good], xs[good])[0] * 100.0
    return out


def fine_regular_grid(sub):
    """One pass -> (integer 0.1 km index, wse) on a regular grid, short gaps filled.

    Gaps STRICTLY WIDER than FINE_FILL_GAP_KM are left as NaN. (pandas
    `interpolate(limit=N)` alone would fabricate WSE in the first N cells of
    EVERY gap, however wide — so long gaps are re-masked after interpolating.)
    """
    sub = sub.sort_values("ibin")
    i0, i1 = int(sub["ibin"].min()), int(sub["ibin"].max())
    idx = np.arange(i0, i1 + 1)
    s = pd.Series(np.nan, index=idx, dtype=float)
    s.loc[sub["ibin"].values] = sub["wse"].values
    max_gap = int(round(FINE_FILL_GAP_KM / FINE_BASE_BIN_KM))
    filled = s.interpolate(limit_area="inside")
    isna = s.isna()
    run_len = isna.groupby((~isna).cumsum()).transform("sum")
    filled[isna & (run_len > max_gap)] = np.nan
    return idx.astype(int), filled.to_numpy(dtype=float)


def fine_pass_matrix(con, where_clause, res_km, xmax):
    """Per-pass fine-scale slope MATRIX for each river (robust sliding Theil-Sen).

    This is the expensive step: one Theil-Sen sweep per pass. It deliberately stops
    BEFORE aggregating, returning the full (grid x pass) matrix plus the pass dates,
    so every temporal regrouping and coverage gate is a free numpy operation on the
    matrix rather than a re-query + re-fit. Aggregate with `fine_aggregate`.

    Returns {reach: dict(grid, mat, passes, n_passes)} where `mat` holds SIGNED
    slopes (cm/km, negative = downhill) on a 0.1 km grid, NaN where a pass did not
    image that bin. `where_clause` is the caller's full SQL WHERE string (the
    dashboards pass their selection; `finescale_slope_profile` builds the standard
    open-water + QC clause).
    """
    df = con.execute(f"""
        SELECT CAST(Pass_Date AS DATE) AS pass,
               Reach_Name AS reach,
               ROUND(dist_km / {FINE_BASE_BIN_KM}) * {FINE_BASE_BIN_KM} AS bin,
               MEDIAN(wse) AS wse,
               COUNT(*) AS npix
        FROM river_data
        {where_clause}
        GROUP BY pass, reach, bin
    """).fetchdf()
    if len(df) == 0:
        return {}
    df = df[df["npix"] >= FINE_MIN_PIX_BIN].copy()
    df["ibin"] = (df["bin"] / FINE_BASE_BIN_KM).round().astype(int)
    fn = fine_slope_theilsen

    out = {}
    for reach, d in df.groupby("reach"):
        d = d[d["bin"] <= xmax]
        if len(d) == 0:
            continue
        imax = int(d["ibin"].max())
        grid = np.arange(1, imax + 1) * FINE_BASE_BIN_KM
        passes = d["pass"].unique()
        mat = np.full((len(grid), len(passes)), np.nan)
        for j, p in enumerate(passes):
            ix, y = fine_regular_grid(d[d["pass"] == p])
            if len(ix) < 5:
                continue
            sl = fn(ix * FINE_BASE_BIN_KM, y, res_km)
            pos = ix - 1
            ok = (pos >= 0) & (pos < len(grid))
            mat[pos[ok], j] = sl[ok]
        # n_passes = passes that actually landed data on the grid; passes whose
        # profile was too sparse to fit (< 5 bins, skipped above) don't count
        # toward the reliability gate or the legend.
        out[str(reach)] = dict(grid=grid, mat=mat,
                               passes=pd.to_datetime(pd.Series(list(passes))).to_numpy(),
                               n_passes=int(np.isfinite(mat).any(axis=0).sum()))
    return out


def fine_aggregate(mat, cols=None, min_passes=0):
    """Aggregate a per-pass slope matrix across a subset of passes (columns).

    Pure numpy on the matrix -- no re-query, no re-fit -- so regrouping by
    period is instant. Returns (med, lo, hi, n) as ABSOLUTE slope (steepness,
    cm/km); bins imaged by fewer than `min_passes` passes are set to NaN.
    """
    sub = mat if cols is None else mat[:, cols]
    med = np.full(mat.shape[0], np.nan)
    q25, q75 = med.copy(), med.copy()
    n = np.sum(np.isfinite(sub), axis=1) if sub.shape[1] else np.zeros(mat.shape[0], dtype=int)
    if sub.shape[1] == 0:
        return med, q25, q75, n
    # Reduce only over bins that some pass actually imaged: an all-NaN bin is normal
    # here (coverage gaps), and feeding one to nanmedian just raises a noisy warning.
    # Steepness = |slope| PER ELEMENT first, THEN quantiles: quantiles of the
    # signed slopes folded with abs() afterwards mis-order the band wherever a
    # bin's slopes straddle zero (the median could plot outside its own band).
    # For same-sign bins the two constructions are identical.
    seen = n > 0
    if seen.any():
        a = np.abs(sub[seen])
        med[seen] = np.nanmedian(a, axis=1)
        q25[seen] = np.nanquantile(a, 0.25, axis=1)
        q75[seen] = np.nanquantile(a, 0.75, axis=1)
    lo, hi = q25, q75
    if min_passes > 0:
        gap = n < min_passes
        med[gap] = lo[gap] = hi[gap] = np.nan
    return med, lo, hi, n


def fine_window_mask(grid, window):
    """Boolean mask for the analysis window (lo, hi) on the 0.1 km grid."""
    lo, hi = window
    return (grid >= lo) & (grid <= hi)


def fine_window_coverage(mat, grid, window):
    """Per-pass fraction of the analysis window that yielded a valid slope.

    This is the pass-quality gate: the fine-scale slope of a pass is only
    meaningful where that pass actually imaged the river, so a pass that caught
    only a sliver of the window should not contribute a 'window slope'.
    """
    m = fine_window_mask(grid, window)
    if not m.any():
        return np.zeros(mat.shape[1])
    return np.isfinite(mat[m, :]).mean(axis=0)


def fine_window_slope(mat, grid, window):
    """Per-pass steepness (|cm/km|) summarised over the analysis window.

    Median of that pass's local sliding-Theil-Sen slopes inside the window -- i.e.
    exactly the quantity the profile plot draws, condensed to one number per pass,
    so the time series and the profile can never disagree.
    """
    out = np.full(mat.shape[1], np.nan)
    m = fine_window_mask(grid, window)
    if not m.any():
        return out
    sub = mat[m, :]
    valid = np.isfinite(sub).any(axis=0)     # passes that imaged part of the window
    if valid.any():
        out[valid] = np.abs(np.nanmedian(sub[:, valid], axis=0))
    return out


def _standard_where_clause(reaches, open_water_only):
    """The standard analysis WHERE clause: reaches + open-water + QC exclusion."""
    where = []
    rlist = "'" + "','".join(reaches) + "'"
    where.append(f"Reach_Name IN ({rlist})")
    if open_water_only:
        months = ",".join(str(m) for m in config.OPEN_WATER_MONTHS)
        where.append(f"EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) IN ({months})")
    excl = exclusion_condition()
    if excl:
        where.append(excl)
    return "WHERE " + " AND ".join(where)


def finescale_slope_profile(con, reaches=("Kanektok_River", "Uyak_Creek"),
                            res_km: float = 0.5, method: str = "theilsen",
                            xmax: float = 34.0, open_water_only: bool = True,
                            min_passes: int = 3):
    """Per-pass-then-aggregate fine-scale slope for each river (headless entry).

    Convenience composition of `fine_pass_matrix` + `fine_aggregate` over the
    standard open-water + QC clause — the thesis Fig 9 pipeline. Returns
    {reach: dict(grid, med, lo, hi, n, n_passes)} where med/lo/hi are the
    across-pass median and 25/75-percentile ABSOLUTE slope (cm/km, steepness) and
    `n` is the per-bin pass count. Bins with n < `min_passes` are set to NaN so a
    caller can plot them as gaps rather than interpolate across them.
    """
    if method != "theilsen":
        raise ValueError(f"unsupported fine-slope method {method!r}; only 'theilsen' "
                         "remains (savgol/gaussian variants were retired)")
    clause = _standard_where_clause(reaches, open_water_only)
    data = fine_pass_matrix(con, clause, res_km, xmax)
    out = {}
    for reach, d in data.items():
        med, lo, hi, n = fine_aggregate(d["mat"], min_passes=min_passes)
        out[reach] = dict(grid=d["grid"], med=med, lo=lo, hi=hi,
                          n=n, n_passes=d["n_passes"])
    return out


# ---------------------------------------------------------------------------
# ELEVATION DIFFERENCE (per-pass paired Kanektok - Uyak)
# ---------------------------------------------------------------------------
def elevation_difference(con, reaches=("Kanektok_River", "Uyak_Creek"),
                         open_water_only: bool = True, bin_km: float = 0.1,
                         band=(25, 75)):
    """Per-pass Kanektok-minus-Uyak WSE difference, aggregated across passes.

    Method (the same per-pass paired approach on every surface; it replaced the
    old pooled-AVG difference, which was artifact-sensitive): each SWOT pass
    images both adjacent channels near-simultaneously, so we difference WITHIN
    each pass -- removing stage/temporal variability -- then aggregate.
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
        months = ",".join(str(m) for m in config.OPEN_WATER_MONTHS)
        where.append(f"EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) IN ({months})")
    excl = exclusion_condition()
    if excl:
        where.append(excl)
    clause = "WHERE " + " AND ".join(where)
    pts = con.execute(
        f"SELECT CAST(Pass_Date AS DATE) AS pass, Reach_Name, dist_km, wse "
        f"FROM river_data {clause}"
    ).fetchdf()

    # round_half_away: match the dashboard tab's SQL ROUND binning of the same
    # data (pandas .round is banker's and disagreed on exact-boundary points).
    pts["dist_bin"] = round_half_away(pts["dist_km"].to_numpy() / bin_km) * bin_km
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
