"""
Stage 3 (experimental): auto-pick channel, alluvial-ridge crest, and floodplain from each
DEM cross-section, then derive ridge height (H_AR) and orthogonal ridge slope (S_AR).

Gearon et al. picked these features by hand. This is a first-pass automation of their
definitions (Gearon 2024 Methods, "Calculating beta"):

  channel : lowest point near cross_dist=0 (the centerline rides the channel).
  ARE     : alluvial ridge crest elevation = the LOWER of the two levee-peak elevations
            on either side of the channel ("lowest of the two high points").
  FPE     : floodplain elevation where the ridge flank asymptotes to the surrounding
            floodplain, on the same side as the controlling (lower) crest.
  H_AR    = ARE - FPE                       (ridge height)
  S_AR    = H_AR / (crest -> floodplain horizontal distance)   (orthogonal ridge slope)

Combined with the down-channel slope S_M (from the centerline long profile), this yields a
DEM-only estimate of gamma = S_AR / S_M. beta needs channel depth (SWOT WSE or BASED) and
is deferred to Stage 4.

NOTE: ArcticDEM is a hydroflattened DSM with sub-metre floodplain relief near its noise
floor, so individual picks are rough — these heuristics are a scaffold to iterate on, not
a finished estimator. Tunables are exposed so we can refine against the real centerline.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter1d


def _smooth(z: np.ndarray, step: float, smooth_m: float) -> np.ndarray:
    """Gaussian-smooth a profile that may contain NaN (interpolate gaps first)."""
    z = np.asarray(z, dtype="float64")
    if np.isnan(z).any():
        idx = np.arange(len(z))
        good = ~np.isnan(z)
        if good.sum() < 2:
            return z
        z = np.interp(idx, idx[good], z[good])
    sigma = max(smooth_m / step, 0.5)
    return gaussian_filter1d(z, sigma=sigma)


def pick_transect(cross_dist, elev, step: float = 10.0, smooth_m: float = 15.0,
                  channel_halfwidth_m: float = 120.0, ridge_search_m: float = 600.0,
                  fp_inner_m: float = 50.0, fp_outer_m: float = 400.0) -> dict:
    """Pick channel / ridge crest / floodplain on one cross-section.

    Args:
        cross_dist: signed distance from channel centre (m), ascending.
        elev: elevation (m) at each cross_dist.
        step: sample spacing (m) along the transect.
        smooth_m: Gaussian smoothing scale (m) applied before picking.
        channel_halfwidth_m: search window for the channel low point around cross_dist=0.
        ridge_search_m: how far out from the channel to look for each levee crest.
        fp_inner_m, fp_outer_m: window (from the crest, outward) used to estimate the
            floodplain elevation as a robust median.

    Returns:
        dict of picks and derived metrics (NaN where a pick fails).
    """
    cd = np.asarray(cross_dist, dtype="float64")
    z = _smooth(elev, step, smooth_m)
    out = {k: np.nan for k in (
        "channel_x", "channel_z", "left_crest_x", "left_crest_z",
        "right_crest_x", "right_crest_z", "are", "fpe", "har", "sar", "fp_side")}
    if len(cd) < 5 or np.all(np.isnan(z)):
        return out

    # 1. Channel: lowest point within the central window.
    ch = np.abs(cd) <= channel_halfwidth_m
    if not ch.any():
        return out
    ci = np.where(ch)[0][np.argmin(z[ch])]
    cx = cd[ci]
    out["channel_x"], out["channel_z"] = cx, z[ci]

    # 2. Levee crest on each side: highest point between the channel and ridge_search_m out.
    def crest(side_mask):
        if not side_mask.any():
            return np.nan, np.nan
        i = np.where(side_mask)[0][np.argmax(z[side_mask])]
        return cd[i], z[i]

    left_mask = (cd < cx) & (cd >= cx - ridge_search_m)
    right_mask = (cd > cx) & (cd <= cx + ridge_search_m)
    lx, lz = crest(left_mask)
    rx, rz = crest(right_mask)
    out["left_crest_x"], out["left_crest_z"] = lx, lz
    out["right_crest_x"], out["right_crest_z"] = rx, rz

    # 3. ARE = lower of the two crests; floodplain estimated on that crest's side.
    crests = [(lz, lx, -1), (rz, rx, +1)]
    crests = [c for c in crests if np.isfinite(c[0])]
    if not crests:
        return out
    are_z, crest_x, side = min(crests, key=lambda c: c[0])
    out["are"] = are_z
    out["fp_side"] = "left" if side < 0 else "right"

    # 4. FPE: robust median in a window beyond the crest, moving away from the channel.
    lo, hi = crest_x + side * fp_inner_m, crest_x + side * fp_outer_m
    fp_mask = (cd >= min(lo, hi)) & (cd <= max(lo, hi))
    if fp_mask.sum() >= 2:
        fp_z = float(np.nanmedian(z[fp_mask]))
        fp_x = float(np.nanmedian(cd[fp_mask]))
        out["fpe"] = fp_z
        out["har"] = are_z - fp_z
        dx = abs(crest_x - fp_x)
        out["sar"] = (are_z - fp_z) / dx if dx > 0 else np.nan
    return out


def pick_all(samples, **kwargs):
    """Run pick_transect over every transect in a tidy samples DataFrame.

    Args:
        samples: DataFrame with columns Reach_Name, transect_id, station_m,
            cross_dist_m, elevation_m (output of build_transects.py).
        **kwargs: forwarded to pick_transect.

    Returns:
        DataFrame with one row per transect: the picks plus Reach_Name/station_m.
    """
    import pandas as pd

    rows = []
    for (reach, tid), g in samples.groupby(["Reach_Name", "transect_id"]):
        g = g.sort_values("cross_dist_m")
        rec = pick_transect(g["cross_dist_m"].to_numpy(), g["elevation_m"].to_numpy(),
                            **kwargs)
        rec["Reach_Name"] = reach
        rec["transect_id"] = tid
        rec["station_m"] = float(g["station_m"].iloc[0])
        rows.append(rec)
    return pd.DataFrame(rows).sort_values(["Reach_Name", "station_m"]).reset_index(drop=True)


def downchannel_slope(picks, smooth_km: float = 1.0):
    """Add S_M: down-channel slope from the channel long profile, per reach.

    S_M is |d(channel_z)/d(station)|, computed on a Gaussian-smoothed long profile so it
    reflects the reach-scale gradient rather than per-transect noise. Adds 'sm' and
    'gamma' (= S_AR / S_M) columns in place and returns the DataFrame.
    """
    import pandas as pd  # noqa: F401

    picks = picks.copy()
    picks["sm"] = np.nan
    for reach, g in picks.groupby("Reach_Name"):
        g = g.sort_values("station_m")
        st = g["station_m"].to_numpy()
        cz = _smooth(g["channel_z"].to_numpy(), step=np.median(np.diff(st)) or 1.0,
                     smooth_m=smooth_km * 1000.0)
        sm = np.abs(np.gradient(cz, st))
        picks.loc[g.index, "sm"] = sm
    picks["gamma"] = picks["sar"] / picks["sm"]
    return picks


def main():
    """Run the picker over outputs/transect_elevations.parquet → transect_picks.parquet."""
    import os

    import pandas as pd

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    samples = pd.read_parquet(os.path.join(out, "transect_elevations.parquet"))
    picks = downchannel_slope(pick_all(samples))
    dst = os.path.join(out, "transect_picks.parquet")
    picks.to_parquet(dst, index=False)
    for reach, g in picks.groupby("Reach_Name"):
        clean = ((g.har > 0.1) & (g.gamma.between(0, 20))).sum()
        print(f"{reach}: {len(g)} transects, {clean} clean picks, "
              f"H_AR median {g[g.har > 0.1].har.median():.2f} m, "
              f"γ median {g[g.gamma > 0].gamma.median():.2f}")
    print(f"wrote {dst}")


if __name__ == "__main__":
    main()
