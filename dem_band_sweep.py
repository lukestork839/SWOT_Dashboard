"""Band-limited along-channel DEM gradient sweep on the field centerlines.

Re-derivation (2026-08-31) of the P6 channel-slope sweep on the CURRENT
(trimmed 2026-08-21) field centerlines, for the DEM-vs-SWOT gradient-ratio
cross-check in the thesis Results. The P6 original (2026-08-10, see
docs/DEM_WRITEUP_PLAN.md section 1.5) ran on the pre-trim lines, whose Uyak
Kanektok-entry tail inflated the near-bifurcation path length; this script
reproduces that table exactly when pointed at the pre-trim lines
(git show HEAD:DEM_Transects/data/..._centerline_official.gpkg) and reports
what survives on the trimmed ones.

Method, per window W in {0, 50, 100, 200, 400} m:
  1. resample the field centerline (reprojected to UTM 32604) at 10 m
     stations and boxcar-smooth the coordinates at W;
  2. re-parameterise arc length s along the smoothed path;
  3. sample the 2 m ArcticDEM in a +/-80 m perpendicular swath at each
     station and take z_p05 as the channel bed / water-at-DEM-epoch proxy;
  4. slope = fine-scale sliding Theil-Sen (the thesis Fig 7 estimator) on
     0.1 km bins, summarised over the near-bifurcation window two ways:
       * P6 convention  -- window 1-5 km in the frame's own coordinate
         (along-channel s is line-start-relative: NOT stable when a line's
         start moves, which is exactly what the 2026-08-21 trim did);
       * frame-matched  -- stations selected by RADIAL distance 1-5 km (the
         SWOT window), single Theil-Sen of z_p05 vs s over those stations.

Findings on the trimmed lines (recorded in thesis_canonical_values.md
section 1.9): the Kanektok is the steeper channel in every frame, window
convention, and smoothing tested, but the K/U magnitude is not stable
against centerline preparation (1.04-1.43 across defensible
configurations), so the quantitative advantage is quoted from the
centerline-free SWOT pass-paired measurement instead.

Run:  python3 dem_band_sweep.py            (current lines)
      python3 dem_band_sweep.py KAN.gpkg UYAK.gpkg   (alternate lines)
"""

from __future__ import annotations

import os
import sys

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from scipy import stats as sps

from thesis_figures.core import (
    FINE_BASE_BIN_KM, _fine_regular_grid, _fine_slope_theilsen,
)

HERE = os.path.dirname(os.path.abspath(__file__))
RASTER = os.path.join(HERE, "batch_outputs", "arcticdem_rivers_2m.tif")
KAN_CL = os.path.join(HERE, "DEM_Transects", "data",
                      "kanektok_centerline_official.gpkg")
UYAK_CL = os.path.join(HERE, "DEM_Transects", "data",
                       "uyak_centerline_official.gpkg")

ANCHOR = (59.82463509, -161.33397834)     # same anchor as every other analysis
R_EARTH = 6371.0088
GEOID = 13.46                             # constant: irrelevant to slope
UTM = 32604                               # field lines are EPSG:4326 -- reproject first
STATION_M = 10.0
SWATH_HALF_M = 80.0
SWATH_STEP_M = 4.0
RES_KM = 0.5
XMAX = 34.0
WINDOWS = (0, 50, 100, 200, 400)
NB_LO, NB_HI = 1.0, 5.0


def haversine_km(lat, lon):
    la1, lo1 = np.radians(ANCHOR[0]), np.radians(ANCHOR[1])
    la2, lo2 = np.radians(np.asarray(lat)), np.radians(np.asarray(lon))
    a = (np.sin((la2 - la1) / 2) ** 2
         + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R_EARTH * np.arcsin(np.sqrt(a))


def boxcar(a, win_pts):
    if win_pts <= 1:
        return np.asarray(a, float).copy()
    k = np.ones(win_pts) / win_pts
    pad = win_pts // 2
    ap = np.pad(np.asarray(a, float), pad, mode="edge")
    return np.convolve(ap, k, mode="same")[pad:pad + len(a)]


def longest_line(geom):
    if geom.geom_type == "MultiLineString":
        return max(geom.geoms, key=lambda s: s.length)
    return geom


def stations(path, W, src):
    """Per-station s (km along smoothed path), radial dist (km), z_p05 (m)."""
    g = gpd.read_file(path).to_crs(UTM)
    line = longest_line(g.geometry.iloc[0])
    s_vals = np.arange(0.0, line.length, STATION_M)
    x = np.array([line.interpolate(v).x for v in s_vals])
    y = np.array([line.interpolate(v).y for v in s_vals])
    wp = max(1, int(round(W / STATION_M)))
    xs, ys = boxcar(x, wp), boxcar(y, wp)
    s_km = np.concatenate(
        [[0.0], np.cumsum(np.hypot(np.diff(xs), np.diff(ys)))]) / 1000.0
    tx, ty = np.gradient(xs), np.gradient(ys)
    tn = np.hypot(tx, ty)
    tn[tn == 0] = 1.0
    nx, ny = -ty / tn, tx / tn
    offs = np.arange(-SWATH_HALF_M, SWATH_HALF_M + 1e-6, SWATH_STEP_M)
    px = xs[:, None] + nx[:, None] * offs[None, :]
    py = ys[:, None] + ny[:, None] * offs[None, :]
    to_ras = Transformer.from_crs(UTM, src.crs, always_xy=True)
    to_ll = Transformer.from_crs(UTM, 4326, always_xy=True)
    rx, ry = to_ras.transform(px.ravel(), py.ravel())
    z = np.array([v[0] for v in src.sample(np.column_stack([rx, ry]))], float)
    z[(z == src.nodata) | (z == 0)] = np.nan
    z = (z - GEOID).reshape(px.shape)
    with np.errstate(all="ignore"):
        z_p05 = np.nanpercentile(z, 5, axis=1)
        n_valid = np.isfinite(z).sum(axis=1)
    lon, lat = to_ll.transform(xs, ys)
    R = haversine_km(lat, lon)
    ok = (n_valid >= 5) & np.isfinite(z_p05)
    return s_km[ok], R[ok], z_p05[ok]


def binned_slope(xvals, zvals):
    """0.1 km binned medians -> fine-scale sliding Theil-Sen (Fig 7 estimator)."""
    d = pd.DataFrame({"x": xvals, "z": zvals})
    d = d[d["x"] <= XMAX]
    d["bin"] = (d["x"] / FINE_BASE_BIN_KM).round() * FINE_BASE_BIN_KM
    g = d.groupby("bin")["z"].median().reset_index()
    g["ibin"] = (g["bin"] / FINE_BASE_BIN_KM).round().astype(int)
    g = g.rename(columns={"z": "wse"})
    if len(g) < 5:
        return np.array([]), np.array([])
    ix, y = _fine_regular_grid(g)
    grid = ix * FINE_BASE_BIN_KM
    return grid, np.abs(_fine_slope_theilsen(grid, y, RES_KM))


def nb_mean(grid, slope):
    m = (grid >= NB_LO) & (grid <= NB_HI) & np.isfinite(slope)
    return float(np.nanmean(slope[m])) if m.any() else np.nan


def main(kan_path=KAN_CL, uyak_path=UYAK_CL):
    rows = []
    with rasterio.open(RASTER) as src:
        for reach, path in (("Kanektok", kan_path), ("Uyak", uyak_path)):
            print(f"{reach}: {os.path.relpath(path, HERE)}")
            for W in WINDOWS:
                s, R, z = stations(path, W, src)
                # P6 convention: 1-5 km in each frame's own coordinate
                ga, sa = binned_slope(s, z)
                gr, sr = binned_slope(R, z)
                # frame-matched: radial 1-5 km window, gradient along the path
                m = (R >= NB_LO) & (R <= NB_HI)
                ts = sps.theilslopes(z[m], s[m])
                sin15 = ((s[m].max() - s[m].min()) / (R[m].max() - R[m].min())
                         if m.sum() > 2 else np.nan)
                rows.append(dict(reach=reach, W=W, sin_1_5=sin15,
                                 along_p6=nb_mean(ga, sa),
                                 radial=nb_mean(gr, sr),
                                 along_matched=abs(ts[0]) * 100))
                r = rows[-1]
                print(f"  W={W:3d}  sin(1-5km)={sin15:5.3f}  "
                      f"along(P6)={r['along_p6']:6.1f}  "
                      f"along(matched)={r['along_matched']:6.1f}  "
                      f"radial={r['radial']:6.1f}", flush=True)

    out = pd.DataFrame(rows)
    piv = out.pivot(index="W", columns="reach",
                    values=["along_p6", "along_matched", "radial", "sin_1_5"])
    for col in ("along_p6", "along_matched", "radial"):
        piv[(f"K/U {col}", "")] = piv[(col, "Kanektok")] / piv[(col, "Uyak")]
    pd.set_option("display.width", 220)
    print("\n" + piv.round(3).to_string())
    print("\nSWOT pass-paired reference (frozen archive, radial 1-5 km, "
          ">=80% coverage): paired medians 254.4 / 229.2 cm/km, advantage "
          "+24.6 cm/km on 44 of 45 paired passes, ratio 1.110.")
    return out


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        main(sys.argv[1], sys.argv[2])
    else:
        main()
