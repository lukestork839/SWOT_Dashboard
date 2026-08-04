"""Phase-2: channel-specific fine-scale slope from the 2 m ArcticDEM.

Phase 1 showed the corridor-MEDIAN DEM can't tell the two channels apart (they
share a floodplain, so the median is the shared valley surface). Phase 2 fixes
that by sampling each channel's OWN centerline on the native 2 m DEM, giving a
channel-specific longitudinal profile -- and does it in TWO coordinate frames:

  * radial (distance-from-anchor)  -> directly comparable to the SWOT water slope
                                      and the dashboard dist_km axis;
  * along-channel (arc length)     -> the PHYSICALLY CORRECT gradient (drop per
                                      unit flow distance), which accounts for
                                      sinuosity -- a more sinuous channel has a
                                      longer path for the same drop, hence a
                                      gentler true gradient. This is the quantity
                                      that governs the avulsion gradient advantage.

Sampling: at each 20 m station along the SWOT centerline we cut a short swath
perpendicular to the channel and read the 2 m DEM, taking
  * z_min  = swath minimum  -> channel bed / water-surface-at-DEM-epoch proxy
             (ArcticDEM can't see through water, so in-channel this is really the
             water surface at the stereo-imagery date -- noisy, single-epoch, but
             directly comparable to SWOT's water surface);
  * z_p10 / z_med = low-percentile / median of the swath -> near-ground / bank-top
             terrain (a real land surface, but includes canopy per the DSM caveat).

The Uyak is the low part of the shared floodplain, i.e. the escape route a
Kanektok avulsion would take -- so "Kanektok centerline vs Uyak centerline" IS
the current-channel-vs-escape-route comparison, and their slope ratio near the
bifurcation is the gradient-advantage metric.

Reuses the EXACT Fig-9 estimator (thesis_figures.core._fine_slope_theilsen).
DEM-stream exploratory: standalone, untracked, writes to dem_channel_slope_phase2/.
"""

from __future__ import annotations

import os

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from thesis_figures import config, core
from thesis_figures.core import (
    FINE_BASE_BIN_KM, _fine_regular_grid, _fine_slope_theilsen,
)

HERE = os.path.dirname(os.path.abspath(__file__))
RASTER = os.path.join(HERE, "batch_outputs", "arcticdem_rivers_2m.tif")
CENTERLINE = os.path.join(HERE, "DEM_Transects", "outputs", "swot_centerlines.gpkg")
OUT_DIR = os.path.join(HERE, "dem_channel_slope_phase2")
REACHES = ("Kanektok_River", "Uyak_Creek")

ANCHOR = (59.82463509, -161.33397834)     # lat, lon (same anchor as SWOT/DEM dist_km)
R_EARTH = 6371.0088
GEOID = 13.46                             # constant offset; irrelevant to SLOPE (varies <2 cm/km)
STEP_M = 20.0                            # along-channel station spacing
SWATH_HALF_M = 80.0                      # perpendicular half-width for the channel swath
SWATH_STEP_M = 4.0                       # swath sample spacing
RES_KM = 0.5
XMAX = 34.0
BIF = config.BIFURCATION_DIST_KM


def haversine_km(lat, lon):
    la1, lo1 = np.radians(ANCHOR[0]), np.radians(ANCHOR[1])
    la2, lo2 = np.radians(np.asarray(lat)), np.radians(np.asarray(lon))
    a = (np.sin((la2 - la1) / 2) ** 2
         + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R_EARTH * np.arcsin(np.sqrt(a))


def longest_line(geom):
    if geom.geom_type == "MultiLineString":
        return max(geom.geoms, key=lambda s: s.length)
    return geom


def sample_centerline(reach, src, cl_crs):
    """Return a per-station DataFrame for one reach centerline.

    Columns: s_km (along-channel), dist_km (radial from anchor), z_min, z_p10,
    z_med (m, orthometric), n_valid (swath pixels).
    """
    cl = gpd.read_file(CENTERLINE)
    line = longest_line(cl[cl["Reach_Name"] == reach].geometry.iloc[0])

    # UTM -> raster CRS (3413) and UTM -> lat/lon (4326) transformers
    to_ras = Transformer.from_crs(cl_crs, src.crs, always_xy=True)
    to_ll = Transformer.from_crs(cl_crs, 4326, always_xy=True)

    s_vals = np.arange(0.0, line.length, STEP_M)
    offs = np.arange(-SWATH_HALF_M, SWATH_HALF_M + 1e-6, SWATH_STEP_M)

    # Build all swath sample points (UTM), remembering which station each belongs to.
    cx = np.array([line.interpolate(s).x for s in s_vals])
    cy = np.array([line.interpolate(s).y for s in s_vals])
    # unit normal from local tangent (central difference on the densified centre points)
    tx = np.gradient(cx)
    ty = np.gradient(cy)
    tn = np.hypot(tx, ty)
    tn[tn == 0] = 1.0
    nx, ny = -ty / tn, tx / tn                       # perpendicular unit vector

    # swath grid: (n_station, n_off)
    sx = cx[:, None] + nx[:, None] * offs[None, :]
    sy = cy[:, None] + ny[:, None] * offs[None, :]
    rx, ry = to_ras.transform(sx.ravel(), sy.ravel())
    z = np.array([v[0] for v in src.sample(np.column_stack([rx, ry]))], float)
    z[(z == src.nodata) | (z == 0)] = np.nan
    z = (z - GEOID).reshape(sx.shape)                # (n_station, n_off)

    with np.errstate(all="ignore"):
        z_min = np.nanmin(z, axis=1)
        z_p10 = np.nanpercentile(z, 10, axis=1)
        z_med = np.nanmedian(z, axis=1)
        n_valid = np.sum(np.isfinite(z), axis=1)

    lon, lat = to_ll.transform(cx, cy)
    dist_km = haversine_km(lat, lon)

    df = pd.DataFrame(dict(s_km=s_vals / 1000.0, dist_km=dist_km,
                           z_min=z_min, z_p10=z_p10, z_med=z_med,
                           n_valid=n_valid))
    return df[df["n_valid"] >= 5].reset_index(drop=True)


def binned_slope(df, xcol, zcol, res_km=RES_KM, xmax=XMAX):
    """Bin z to 0.1 km in the `xcol` frame (median), then fine-scale Theil-Sen.
    Returns (grid_km, elev_m, slope_abs_cm_km)."""
    d = df[df[xcol] <= xmax].copy()
    d["bin"] = (d[xcol] / FINE_BASE_BIN_KM).round() * FINE_BASE_BIN_KM
    g = d.groupby("bin")[zcol].median().reset_index()
    g["ibin"] = (g["bin"] / FINE_BASE_BIN_KM).round().astype(int)
    g = g.rename(columns={zcol: "wse"})
    if len(g) < 5:
        return np.array([]), np.array([]), np.array([])
    ix, y = _fine_regular_grid(g)
    grid = ix * FINE_BASE_BIN_KM
    slope = np.abs(_fine_slope_theilsen(grid, y, res_km))
    return grid, y, slope


def nb_mean(grid, slope, lo=1.0, hi=5.0):
    m = (grid >= lo) & (grid <= hi) & np.isfinite(slope)
    return float(np.nanmean(slope[m])) if m.any() else np.nan


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    cl_crs = gpd.read_file(CENTERLINE).crs

    data = {}
    with rasterio.open(RASTER) as src:
        for r in REACHES:
            df = sample_centerline(r, src, cl_crs)
            df.to_parquet(os.path.join(OUT_DIR, f"centerline_{r}.parquet"),
                          index=False)
            sinuosity = df["s_km"].max() / df["dist_km"].max()
            print(f"{r:16s} {len(df):4d} stations | along-channel {df['s_km'].max():.1f} km "
                  f"| radial {df['dist_km'].max():.1f} km | sinuosity {sinuosity:.3f}")
            data[r] = df

    # SWOT water slope (radial frame), exact Fig-9 computation
    con = core.connect()
    swot = core.finescale_slope_profile(con, reaches=REACHES, res_km=RES_KM, xmax=XMAX)

    # slopes in both frames on z_min (bed/water proxy)
    slopes = {}
    for r in REACHES:
        slopes[(r, "radial")] = binned_slope(data[r], "dist_km", "z_min")
        slopes[(r, "along")] = binned_slope(data[r], "s_km", "z_min")

    # ---- numeric summary ----
    print("\n=== Near-bifurcation (1-5 km) mean |slope|, cm/km ===")
    print(f"{'reach':16s} {'DEMradial':>10s} {'DEMalong':>10s} {'SWOTwater':>10s}")
    summ = []
    for r in REACHES:
        gr, _, sr = slopes[(r, "radial")]
        ga, _, sa = slopes[(r, "along")]
        s = swot.get(r, {})
        dr = nb_mean(gr, sr)
        da = nb_mean(ga, sa)
        sw = nb_mean(s.get("grid", np.array([])), s.get("med", np.array([]))) if s else np.nan
        print(f"{r:16s} {dr:10.1f} {da:10.1f} {sw:10.1f}")
        summ.append(dict(reach=r, dem_radial=dr, dem_along=da, swot_water=sw))
    pd.DataFrame(summ).to_csv(os.path.join(OUT_DIR, "nb_summary.csv"), index=False)

    # gradient advantage near bifurcation (along-channel, the physical frame)
    ka = nb_mean(*[slopes[("Kanektok_River", "along")][i] for i in (0, 2)])
    ua = nb_mean(*[slopes[("Uyak_Creek", "along")][i] for i in (0, 2)])
    print(f"\nAlong-channel bed gradient @1-5 km:  Kanektok {ka:.0f}  Uyak {ua:.0f} cm/km  "
          f"-> ratio K/U = {ka/ua:.2f}" if np.isfinite(ka) and np.isfinite(ua) and ua else "")

    _plot(data, slopes, swot)


def _style_x(ax, xmax):
    ax.set_xlim(xmax, 0)
    ax.axvline(BIF, color="#888888", ls=":", lw=1.0)
    ax.grid(True, ls="--", lw=0.5, color="#E0E0E0")


def _plot(data, slopes, swot):
    config.apply_style()

    # Figure 1: channel bed long profiles (radial frame) + Uyak-minus-Kanektok
    fig, ax = plt.subplots(2, 1, figsize=(config.FIG_WIDTH_FULL, 5.4), sharex=True)
    for r in REACHES:
        g, z, _ = slopes[(r, "radial")]
        ax[0].plot(g, z, color=config.river_color(r), lw=1.4,
                   label=config.river_label(r))
    ax[0].set_ylabel("Channel min elev.\n(m, water/bed proxy)")
    ax[0].legend(fontsize=9)
    _style_x(ax[0], XMAX)
    # difference on a shared 0.1 km grid
    gk, zk, _ = slopes[("Kanektok_River", "radial")]
    gu, zu, _ = slopes[("Uyak_Creek", "radial")]
    common = np.intersect1d(np.round(gk, 2), np.round(gu, 2))
    zki = np.interp(common, gk, zk)
    zui = np.interp(common, gu, zu)
    ax[1].axhline(0, color="k", lw=0.7)
    ax[1].plot(common, zui - zki, color="#6a51a3", lw=1.3)
    ax[1].set_ylabel("Uyak - Kanektok (m)\n(Uyak higher if +)")
    ax[1].set_xlabel("Distance from anchor (km)")
    _style_x(ax[1], XMAX)
    fig.suptitle("Phase 2 - channel-specific long profiles (2 m DEM centerline)",
                 fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    fig.savefig(os.path.join(OUT_DIR, "channel_profiles.png"), dpi=150)

    # Figure 2: fine-scale slope, DEM channel vs SWOT water (radial) + along-channel
    fig2, axes = plt.subplots(2, 2, figsize=(config.FIG_WIDTH_FULL, 6.2),
                              sharex="col")
    for i, r in enumerate(REACHES):
        col = config.river_color(r)
        s = swot.get(r, {})
        # left col: radial frame (DEM vs SWOT)
        axL = axes[i, 0]
        if s:
            axL.fill_between(s["grid"], s["lo"], s["hi"], color=col, alpha=0.18, lw=0)
            axL.plot(s["grid"], s["med"], color=col, lw=1.6,
                     label="SWOT water")
        gr, _, sr = slopes[(r, "radial")]
        axL.plot(gr, sr, color="#222222", lw=1.3, label="DEM channel (radial)")
        _style_x(axL, XMAX)
        axL.set_ylim(0, 500)
        axL.set_ylabel(f"{config.river_label(r)}\n|slope| (cm/km)")
        if i == 0:
            axL.set_title("Radial frame: DEM channel vs SWOT water", fontsize=9)
            axL.legend(fontsize=8, loc="upper left")
        if i == 1:
            axL.set_xlabel("Distance from anchor (km)")
        # right col: along-channel frame (the physical gradient), zoom to bifurcation
        axR = axes[i, 1]
        ga, _, sa = slopes[(r, "along")]
        axR.plot(ga, sa, color=col, lw=1.5, label="DEM channel (along-channel)")
        axR.set_xlim(8, 0)
        axR.axvline(BIF, color="#888888", ls=":", lw=1.0)
        axR.grid(True, ls="--", lw=0.5, color="#E0E0E0")
        axR.set_ylim(0, 500)
        if i == 0:
            axR.set_title("Along-channel frame (0-8 km)", fontsize=9)
        if i == 1:
            axR.set_xlabel("Along-channel distance (km)")
    fig2.suptitle("Phase 2 - channel bed fine-scale slope (Theil-Sen, 0.5 km)",
                  fontsize=11)
    fig2.tight_layout(rect=(0, 0, 1, 0.98))
    fig2.savefig(os.path.join(OUT_DIR, "channel_slope.png"), dpi=150)

    # Figure 3: sinuosity (along-channel vs radial distance)
    fig3, ax3 = plt.subplots(figsize=(config.FIG_WIDTH_FULL, 3.4))
    for r in REACHES:
        d = data[r]
        ax3.plot(d["dist_km"], d["s_km"], color=config.river_color(r), lw=1.5,
                 label=config.river_label(r))
    ax3.plot([0, 35], [0, 35], color="k", ls="--", lw=0.8, label="1:1 (straight)")
    ax3.set_xlabel("Radial distance from anchor (km)")
    ax3.set_ylabel("Along-channel distance (km)")
    ax3.set_title("Sinuosity: along-channel vs radial distance", fontsize=10)
    ax3.legend(fontsize=9)
    ax3.grid(True, ls="--", lw=0.5, color="#E0E0E0")
    fig3.tight_layout()
    fig3.savefig(os.path.join(OUT_DIR, "sinuosity.png"), dpi=150)
    print(f"\nWrote figures to {OUT_DIR}/")


if __name__ == "__main__":
    main()
