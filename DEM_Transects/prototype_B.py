"""
Prototype of approach B (channel-relative zones) on a handful of transects, for visual
approval before rolling out to all transects.

Per transect:
  1. sample the 2 m DEM along a transect perpendicular to the (sinuous) SWOT centerline,
  2. detect the true channel = lowest point within a central window; re-centre cross-dist
     on it,
  3. near-channel band = |dist from channel| <= D_near  -> P98 (ridge ARE), P2 (channel),
  4. floodplain band  = |dist from channel| >  D_near AND inside the corridor polygon
     -> median (FPE),
  5. H_AR = ARE - FPE, Hm = ARE - channel, beta = H_AR / Hm.

Each transect is plotted annotated so the zone placement and picks can be eyeballed.

Run:  python3 DEM_Transects/prototype_B.py
"""

from __future__ import annotations

import os

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import transects as tr

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
POLY = os.path.join(ROOT, "river_poly.zip")
RASTER = os.path.join(ROOT, "batch_outputs", "arcticdem_rivers_2m.tif")
CENTERLINE = os.path.join(HERE, "outputs", "swot_centerlines.gpkg")
OUT_DIR = os.path.join(HERE, "outputs")

REACH_NAMES = {"Uyak": "Uyak_Creek", "Kanektok": "Kanektok_River"}

# Approach-B parameters (the knobs we would tune).
D_NEAR = 600.0          # near-channel band half-width (m) — the levee/meander belt
D_FAR = 1800.0          # floodplain annulus outer edge (m): band = D_NEAR < |dist| < D_FAR
CH_SEARCH = 300.0       # channel search half-window around the transect centre (m)
HALF_WIDTH = 3000.0     # transect half-length (m)
STEP = 2.0              # DEM sample step (m)
MIN_PTS = 20            # min valid pixels required in a band
DETREND = True          # remove the linear cross-valley tilt before picking


def analyse_transect(cross, elev, in_corridor):
    """Approach-B picks for one transect. cross/elev/in_corridor are 1-D arrays,
    cross ascending, cross=0 at the centerline crossing."""
    z = np.asarray(elev, float)
    cd = np.asarray(cross, float)
    good = np.isfinite(z)
    out = {"ok": False}
    if good.sum() < MIN_PTS:
        return out

    # 1. channel = lowest point within the central search window.
    central = good & (np.abs(cd) <= CH_SEARCH)
    if central.sum() < 3:
        central = good
    ci = np.where(central)[0][np.argmin(z[central])]
    ch_x, ch_z = cd[ci], z[ci]
    rel = cd - ch_x  # re-centre on the channel

    # 2. bands: near-channel levee belt, and a symmetric floodplain annulus (bounded so it
    #    can't run out onto distant high ground even where the corridor clip is one-sided).
    near = good & (np.abs(rel) <= D_NEAR)
    flood = good & (np.abs(rel) > D_NEAR) & (np.abs(rel) <= D_FAR) \
        & np.asarray(in_corridor, bool)
    if near.sum() < MIN_PTS or flood.sum() < MIN_PTS:
        return out

    # 3. detrend the cross-valley tilt so FPE no longer depends on which side is sampled.
    #    Estimate the tilt from the floodplain MEDIAN on each side (two robust points), not
    #    from all annulus points — this keeps levee/valley-wall highs from tilting the fit
    #    (which over-corrected before). Needs floodplain on both sides; else no detrend.
    z_dt = z.copy()
    slope = 0.0
    if DETREND:
        left = flood & (rel < 0)
        right = flood & (rel > 0)
        if left.sum() >= MIN_PTS and right.sum() >= MIN_PTS:
            xl, xr = np.median(rel[left]), np.median(rel[right])
            zl, zr = np.median(z[left]), np.median(z[right])
            if xr > xl:
                slope = float((zr - zl) / (xr - xl))
                z_dt = z - slope * rel

    are = float(np.percentile(z_dt[near], 98))   # ridge crest
    p2 = float(np.percentile(z_dt[near], 2))      # channel bed (robust min)
    fpe = float(np.median(z_dt[flood]))           # floodplain
    har, hm = are - fpe, are - p2
    out.update(ok=True, ch_x=ch_x, ch_z=z_dt[ci], rel=rel, near=near, flood=flood,
               z_dt=z_dt, slope=slope, are=are, p2=p2, fpe=fpe, har=har, hm=hm,
               beta=(har / hm if hm > 0 else np.nan))
    return out


def main():
    polys = gpd.read_file(POLY).to_crs(32604)
    guides = gpd.read_file(CENTERLINE).to_crs(32604)
    reach_poly = {REACH_NAMES[r.Name]: r.geometry for r in polys.itertuples()}
    # corridor polygons in the raster CRS (3413) for the in-corridor test on sample points.
    reach_poly_3413 = {REACH_NAMES[r.Name]: r.geometry
                       for r in polys.to_crs(3413).itertuples()}

    picks_by_reach = {}
    fig, axes = plt.subplots(2, 3, figsize=(19, 10))
    for row, reach in enumerate(["Kanektok_River", "Uyak_Creek"]):
        guide = guides[guides["Reach_Name"] == reach].geometry.iloc[0]
        tx = tr.generate_transects(guide, 32604, spacing=100.0, half_width=HALF_WIDTH)
        # choose 3 transects spread along the reach
        ids = tx["transect_id"].to_numpy()
        chosen = ids[np.linspace(0, len(ids) - 1, 5).astype(int)[1:4]]  # 25/50/75%
        sub = tx[tx["transect_id"].isin(chosen)].copy()
        samples, _ = tr.sample_dem_along_transects(sub, RASTER, step=STEP)

        # in-corridor flag per sample point (lon/lat cols are 3413 x/y here).
        pts = gpd.GeoSeries(gpd.points_from_xy(samples["lon"], samples["lat"]), crs=3413)
        samples["in_corridor"] = pts.within(reach_poly_3413[reach]).to_numpy()

        for col, tid in enumerate(chosen):
            g = samples[samples["transect_id"] == tid].sort_values("cross_dist_m")
            r = analyse_transect(g["cross_dist_m"], g["elevation_m"], g["in_corridor"])
            ax = axes[row, col]
            cx = g["cross_dist_m"].to_numpy()
            if not r["ok"]:
                ax.plot(cx, g["elevation_m"], color="0.5", lw=0.8)
                ax.set_title(f"{reach} #{tid} — insufficient data")
                continue
            zdt = r["z_dt"]
            lo, hi = np.nanmin(zdt), np.nanmax(zdt)
            # faint original profile for reference; solid = detrended (what picks use).
            ax.plot(cx, g["elevation_m"], color="0.75", lw=0.6, ls=":", zorder=1,
                    label="raw profile")
            ax.plot(cx, zdt, color="0.35", lw=0.9, zorder=2, label="detrended")
            ax.fill_between(cx, lo, hi, where=r["near"], color="#fdd0a2", alpha=0.4,
                            label="near-channel band")
            ax.fill_between(cx, lo, hi, where=r["flood"], color="#c7e9c0", alpha=0.4,
                            label="floodplain annulus")
            ax.axhline(r["are"], color="#e6550d", lw=1.0, label=f"ARE P98={r['are']:.1f}")
            ax.axhline(r["fpe"], color="#31a354", lw=1.0, label=f"FPE med={r['fpe']:.1f}")
            ax.axhline(r["p2"], color="#3182bd", lw=1.0, label=f"chan P2={r['p2']:.1f}")
            ax.plot(r["ch_x"], r["ch_z"], "kv", ms=7, label="channel")
            ax.set_title(f"{reach} #{tid} — H_AR={r['har']:.2f} Hm={r['hm']:.2f} "
                         f"β={r['beta']:.2f} (tilt {r['slope']*1000:.1f} m/km)")
            ax.set_xlabel("cross-distance (m, 0=centerline)")
            ax.set_ylabel("elevation (m, detrended)")
            ax.legend(fontsize=6, loc="upper right")
            picks_by_reach.setdefault(reach, []).append((tid, r["har"], r["hm"], r["beta"]))

    fig.suptitle(f"Approach B prototype — D_near={D_NEAR:.0f} m, D_far={D_FAR:.0f} m, "
                 f"channel search ±{CH_SEARCH:.0f} m, detrend={DETREND}", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    dst = os.path.join(OUT_DIR, "prototypeB_transects.png")
    fig.savefig(dst, dpi=130)
    plt.close(fig)
    print(f"wrote {dst}")
    for reach, rows in picks_by_reach.items():
        for tid, har, hm, beta in rows:
            print(f"  {reach} #{tid}: H_AR={har:.2f} m, Hm={hm:.2f} m, beta={beta:.2f}")


if __name__ == "__main__":
    main()
