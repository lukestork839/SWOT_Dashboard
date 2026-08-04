"""
Vegetation-inflation filter experiment: can a moving-window percentile/median filter
recover bare-earth from raw ArcticDEM V4 (a photogrammetric DSM) over the Kanektok
floodplain, validated against NOAA QL1 LiDAR bare-earth ground truth?

Motivation: aggregate ArcticDEM-vs-LiDAR bias is ~0, but a manager flagged a sinuous
"snaky high" of apparent vegetation inflation in the hillshade. Aggregate stats hide
spatially-structured canopy bias on narrow riparian features (the exact geometry that
matters for alluvial-ridge / avulsion work). A MERIT-calibrated correction was already
shown to DEGRADE accuracy vs LiDAR (RMSE 0.55 -> 0.65). Here we test a self-contained,
DEM-only alternative: morphological / low-percentile ground filters.

Method:
  1. Load raw ArcticDEM (10m, WGS84 ellipsoidal) over the LiDAR footprint; resample LiDAR
     (1m, NAVD88) onto the ArcticDEM grid (average).
  2. Vertically align ArcticDEM to LiDAR with a single bare-ground datum offset, estimated
     robustly as a LOW percentile of (arctic - lidar) -- bare/short-veg pixels are the
     small-difference tail, so this avoids letting canopy inflate the datum. Cross-check
     vs the GEE NLCD-bare-ground offset (12.765 m).
  3. Difference map (arctic_aligned - lidar) = the vegetation-inflation map (diagnostic).
  4. Sweep filters (median + percentile{10..40}) x windows{100,200,300 m}.
  5. Score each vs LiDAR, STRATIFIED into bare pixels (|raw resid|<=0.3 m) and vegetated
     pixels (raw resid > 0.5 m). A good filter cuts veg RMSE/bias toward 0 WITHOUT harming
     bare ground (no new negative bias). That is precisely the median-vs-low-pct tradeoff.

Outputs (dem_veg_filter/outputs/): results table (csv + md), inflation map + best-filter
before/after maps (png).
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import Resampling, reproject
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "outputs")
ARCTIC = os.path.join(ROOT, "batch_outputs", "arcticdem_rivers.tif")
LIDAR = "/home/luke/University/ArcticDEM/lidar_dem_wgs84.tif"

GEE_BARE_OFFSET = 12.764754844924473  # ArcticDEM-LiDAR bare-ground offset from GEE script
FILL_BELOW = 5.0          # raw ellipsoidal heights here are >12 m; <5 m is GEE 0-fill
DATUM_PCTL = 15.0         # low percentile of (arctic-lidar) used as bare-ground datum
BARE_TOL = 0.30           # |residual| <= this  -> "bare/matched" pixel
VEG_THRESH = 0.50         # residual >  this    -> "vegetated/inflated" pixel
PIX_M = 9.983             # ArcticDEM pixel size in metres (8.983e-5 deg * 111139 m/deg)


def load_aligned():
    """Return (arctic_raw, lidar, valid_mask, transform) on the ArcticDEM grid over the
    LiDAR footprint. arctic_raw is RAW ellipsoidal (not yet datum-shifted)."""
    with rasterio.open(LIDAR) as lid:
        lb = lid.bounds
    with rasterio.open(ARCTIC) as src:
        # Window the ArcticDEM to the LiDAR bounds (+ a margin so filter windows have data).
        margin = 0.004  # ~440 m
        win = src.window(lb.left - margin, lb.bottom - margin,
                         lb.right + margin, lb.top + margin)
        win = win.round_offsets().round_lengths()
        arctic = src.read(1, window=win).astype("float64")
        transform = src.window_transform(win)
        h, w = arctic.shape
        dst_crs = src.crs

    arctic[arctic < FILL_BELOW] = np.nan

    # Resample LiDAR (1 m) onto this exact ArcticDEM grid by averaging.
    lidar = np.full((h, w), np.nan, dtype="float64")
    with rasterio.open(LIDAR) as lid:
        reproject(
            source=rasterio.band(lid, 1),
            destination=lidar,
            src_transform=lid.transform, src_crs=lid.crs,
            dst_transform=transform, dst_crs=dst_crs,
            resampling=Resampling.average,
            src_nodata=lid.nodata, dst_nodata=np.nan,
        )
    lidar[lidar < FILL_BELOW] = np.nan
    valid = np.isfinite(arctic) & np.isfinite(lidar)
    return arctic, lidar, valid


def fill_nan_nearest(a):
    """Fill NaN holes with nearest valid value so fast C filters don't propagate NaN.
    (Holes here are water/edges, mostly outside the compared valid mask.)"""
    nan = np.isnan(a)
    if not nan.any():
        return a
    _, idx = ndimage.distance_transform_edt(nan, return_distances=True, return_indices=True)
    return a[tuple(idx)]


def apply_filter(arctic_aligned, kind, param, win_m):
    """kind: 'median' or 'pctl'. param: percentile (ignored for median). win_m: window (m)."""
    size = max(3, int(round(win_m / PIX_M)))
    if size % 2 == 0:
        size += 1
    filled = fill_nan_nearest(arctic_aligned)
    if kind == "median":
        out = ndimage.median_filter(filled, size=size, mode="nearest")
    else:
        out = ndimage.percentile_filter(filled, percentile=param, size=size, mode="nearest")
    out[np.isnan(arctic_aligned)] = np.nan
    return out


def stats(resid, mask):
    r = resid[mask]
    r = r[np.isfinite(r)]
    if r.size == 0:
        return dict(n=0, mean=np.nan, std=np.nan, rmse=np.nan)
    return dict(n=int(r.size), mean=float(r.mean()), std=float(r.std()),
                rmse=float(np.sqrt((r ** 2).mean())))


def main():
    os.makedirs(OUT, exist_ok=True)
    arctic_raw, lidar, valid = load_aligned()
    print(f"grid {arctic_raw.shape}, {valid.sum():,} valid (arctic & lidar) pixels")

    # --- datum alignment ---
    # Use the GEE NLCD-bare-ground offset (validated against NLCD bare classes at 2 m).
    # A low percentile of (arctic-lidar) is shown here for cross-reference only -- it is
    # biased low by negative photogrammetric noise (cutbanks, water edges, 10 m averaging),
    # so it is NOT used as the datum.
    raw_diff = arctic_raw - lidar
    p_lo = float(np.nanpercentile(raw_diff[valid], DATUM_PCTL))
    offset = GEE_BARE_OFFSET
    print(f"datum offset (GEE NLCD-bare-ground): {offset:.3f} m "
          f"[cross-ref p{DATUM_PCTL:.0f} of arctic-lidar: {p_lo:.3f} m]")
    arctic = arctic_raw - offset
    resid0 = arctic - lidar  # inflation map (aligned)

    bare = valid & (np.abs(resid0) <= BARE_TOL)
    veg = valid & (resid0 > VEG_THRESH)
    print(f"  bare/matched pixels: {bare.sum():,}  ({100*bare.sum()/valid.sum():.0f}%)")
    print(f"  vegetated/inflated:  {veg.sum():,}  ({100*veg.sum()/valid.sum():.0f}%)")

    rows = []
    def record(label, resid):
        a, b, v = stats(resid, valid), stats(resid, bare), stats(resid, veg)
        rows.append(dict(filter=label,
                         all_rmse=a["rmse"], all_mean=a["mean"],
                         bare_rmse=b["rmse"], bare_mean=b["mean"],
                         veg_rmse=v["rmse"], veg_mean=v["mean"]))

    record("raw ArcticDEM (aligned)", resid0)

    best = None
    for win_m in (50, 100, 150, 200, 300):
        med = apply_filter(arctic, "median", None, win_m)
        record(f"median {win_m}m", med - lidar)
        for pct in (10, 20, 30, 40):
            filt = apply_filter(arctic, "pctl", pct, win_m)
            resid = filt - lidar
            record(f"p{pct} {win_m}m", resid)
            sv = stats(resid, veg)["rmse"]; sb = stats(resid, bare)["rmse"]
            # score: minimise veg RMSE while keeping bare RMSE near baseline.
            score = sv + max(0.0, sb - stats(resid0, bare)["rmse"]) * 2.0
            if best is None or score < best[0]:
                best = (score, f"p{pct} {win_m}m", filt)

    # --- GATED filters: correct ONLY vegetated pixels, keep raw bare ground. ---
    # The gate here is the LiDAR-defined veg mask, i.e. an ORACLE / upper bound on what a
    # perfect vegetation gate achieves. A deployable gate must come from an INDEPENDENT
    # layer (Sentinel-2 NDVI/EVI), since LiDAR does not cover most of the corridor.
    for pct, win_m in ((20, 50), (30, 50), (20, 100)):
        filt = apply_filter(arctic, "pctl", pct, win_m)
        gated = np.where(veg, filt, arctic)
        record(f"GATED p{pct} {win_m}m (oracle)", gated - lidar)

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT, "filter_results.csv"), index=False)
    cols = list(df.columns)
    md = ["# Filter sweep vs LiDAR ground truth\n",
          f"Datum offset {offset:.3f} m (GEE NLCD bare ground); "
          f"bare {bare.sum():,} px, veg {veg.sum():,} px, valid {valid.sum():,} px.\n",
          "| " + " | ".join(cols) + " |",
          "| " + " | ".join("---" for _ in cols) + " |"]
    for _, r in df.round(3).iterrows():
        md.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    with open(os.path.join(OUT, "filter_results.md"), "w") as f:
        f.write("\n".join(md) + "\n")
    print("\n" + df.round(3).to_string(index=False))
    print(f"\nbest veg-removing filter (guarded): {best[1]}")

    # --- maps: inflation + best-filter before/after ---
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        bf = best[2] - lidar
        fig, ax = plt.subplots(1, 3, figsize=(18, 5))
        for a, img, ttl in [
            (ax[0], np.where(valid, resid0, np.nan), "Raw ArcticDEM - LiDAR (inflation map)"),
            (ax[1], np.where(valid, bf, np.nan), f"{best[1]} - LiDAR (after)"),
            (ax[2], np.where(valid, resid0 - bf, np.nan), "removed by filter (raw - filtered)")]:
            im = a.imshow(img, cmap="RdBu_r", vmin=-2, vmax=2)
            a.set_title(ttl); a.axis("off"); fig.colorbar(im, ax=a, shrink=0.7, label="m")
        fig.tight_layout(); fig.savefig(os.path.join(OUT, "inflation_maps.png"), dpi=120)
        print("wrote inflation_maps.png")
    except Exception as e:  # noqa: BLE001
        print(f"(map skipped: {e})")


if __name__ == "__main__":
    main()
