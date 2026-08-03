"""
Avulsion topographic metrics — superelevation (beta), gradient advantage (gamma),
and the avulsion threshold (Lambda), following Gearon et al. (2024, Nature 634, 91-95)
and the follow-up Gearon et al. (2025, GRL).

This is the production core of the DEM_Transects analysis. The formulas are ported
verbatim from the authors' released code (github.com/jameshgrn/rulesofriveravulsion,
Zenodo 10.5281/zenodo.13693548, MIT) so our pipeline produces numbers directly
comparable to the published dataset. The validation harness in
validation/validate_against_gearon.py checks this module against their published
fig2_data.csv before we apply it to our own Kanektok/Uyak cross-sections.

Definitions (per transect / cross-section):
    H_AR  alluvial ridge height = ridge crest elevation (ARE) - floodplain elevation (FPE)
    H_M   channel (bankfull) depth — three conventions, selected per site by method_used
    S_AR  alluvial-ridge slope, measured ORTHOGONAL to flow (ridge crest -> floodplain)
    S_M   down-channel (main-stem) slope

    beta  (superelevation)      = H_AR / H_M
    gamma (gradient advantage)  = S_AR / S_M
    Lambda (avulsion threshold) = beta * gamma     (avulsion favored when >= ~2.1)

Reference: Gearon Figure2.py:60-70 (beta), reproduce_figs.py:59-61 (gamma),
Figure3.py (Lambda = beta*gamma).
"""

from __future__ import annotations

import numpy as np

# Avulsion threshold central tendency reported by Gearon et al. (2024): median Lambda ~ 2.1.
LAMBDA_MEDIAN = 2.1

# Depth-convention codes (Gearon's `method_used`).
METHOD_BASED = 1      # H_M = model-predicted bankfull depth (BASED / xgb_depth)
METHOD_WSE = 2        # H_M = ARE - WSE              (ridge crest above water surface)
METHOD_WSE_BASED = 3  # H_M = ARE - (WSE - depth)    (ridge crest above channel bed)


def ridge_height(are_m: float, fpe_m: float) -> float:
    """H_AR: alluvial ridge height = ridge crest elevation - floodplain elevation."""
    return are_m - fpe_m


def channel_depth(method: int, are_m: float = np.nan, wse_m: float = np.nan,
                  xgb_depth: float = np.nan) -> float:
    """H_M: channel depth under the selected convention (Gearon Figure2.py:65-70).

    method 1 (BASED):     H_M = xgb_depth
    method 2 (WSE):       H_M = ARE - WSE
    method 3 (WSE+BASED): H_M = ARE - (WSE - xgb_depth)
    """
    if method == METHOD_BASED:
        return xgb_depth
    if method == METHOD_WSE:
        return are_m - wse_m
    if method == METHOD_WSE_BASED:
        return are_m - (wse_m - xgb_depth)
    raise ValueError(f"Unknown depth method {method!r}; expected 1, 2, or 3.")


def superelevation(are_m: float, fpe_m: float, method: int,
                   wse_m: float = np.nan, xgb_depth: float = np.nan) -> float:
    """beta for a single transect = H_AR / H_M (Gearon Figure2.py:60-70)."""
    return ridge_height(are_m, fpe_m) / channel_depth(method, are_m, wse_m, xgb_depth)


def gradient_advantage(sar_mean: float, sm_mean: float) -> float:
    """gamma = S_AR / S_M (Gearon reproduce_figs.py:61)."""
    return sar_mean / sm_mean


def avulsion_lambda(beta: float, gamma: float) -> float:
    """Lambda = beta * gamma (Gearon Figure3.py). Avulsion favored when >= ~2.1."""
    return beta * gamma


def mean_slope(slopes) -> float:
    """Mean of the per-transect slope measurements, ignoring NaN.

    NOTE: Gearon's reproduce_figs.py:59 computes sar_mean as mean(sar1, sar1, sar3)
    — sar1 is duplicated and sar2 is dropped, which looks like a typo. We use the
    intended mean(sar1, sar2, sar3). The validation harness flags any site where
    this changes the published gamma so the discrepancy is explicit, not silent.
    """
    arr = np.asarray(slopes, dtype=float)
    return float(np.nanmean(arr))


def site_superelevation(are, fpe, method: int, wse=None, xgb_depth: float = np.nan,
                        transects=(1, 2, 3)) -> float:
    """Mean beta over a site's available transects (deterministic; no error sampling).

    `are`, `fpe`, `wse` are dict-likes keyed by transect number (1, 2, 3). This is the
    expected value of Gearon's Monte-Carlo beta (their triangular error terms are
    zero-mean), and is what the offline pipeline writes to parquet.
    """
    vals = []
    for i in transects:
        a = are.get(i, np.nan)
        if not np.isfinite(a):
            continue
        f = fpe.get(i, np.nan)
        w = wse.get(i, np.nan) if wse is not None else np.nan
        vals.append(superelevation(a, f, method, w, xgb_depth))
    return float(np.nanmean(vals)) if vals else np.nan


def site_superelevation_mc(are, fpe, method: int, wse=None, xgb_depth: float = np.nan,
                           transects=(1, 2, 3), n_simulations: int = 1000,
                           ridge_elev_error: float = 0.25,
                           water_surface_elev_error: float = 0.25,
                           xgb_depth_error: float = 1.0, rng=None):
    """Monte-Carlo beta mirroring Gearon Figure2.py:54-75 exactly (mean, std).

    Each iteration picks one transect at random and perturbs ridge height, WSE, and
    depth by zero-mean triangular noise. Returns (mean_beta, std_beta). Used only to
    reproduce their published uncertainty; the deterministic version above is the
    production estimator. Pass a seeded numpy Generator for reproducibility.
    """
    rng = np.random.default_rng() if rng is None else rng
    avail = [i for i in transects if np.isfinite(are.get(i, np.nan))]
    if not avail:
        return np.nan, np.nan
    out = []
    for _ in range(n_simulations):
        i = rng.choice(avail)
        a, f = are[i], fpe.get(i, np.nan)
        w = wse.get(i, np.nan) if wse is not None else np.nan
        har = (a - f) + rng.triangular(-ridge_elev_error, 0, ridge_elev_error)
        w_s = w + rng.triangular(-water_surface_elev_error, 0, water_surface_elev_error)
        d_s = xgb_depth + rng.triangular(-xgb_depth_error, 0, xgb_depth_error)
        if method == METHOD_BASED:
            out.append(har / d_s)
        elif method == METHOD_WSE:
            out.append(har / (a - w_s))
        elif method == METHOD_WSE_BASED:
            out.append(har / (a - (w_s - d_s)))
    return float(np.mean(out)), float(np.std(out))
