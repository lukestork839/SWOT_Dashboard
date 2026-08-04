"""Phase-1 feasibility spike: fine-scale TERRAIN slope from ArcticDEM, overlaid on
the SWOT fine-scale WATER-SURFACE slope.

Question this answers: does the land-surface (terrain) gradient agree with the
water-surface (hydraulic) gradient near the bifurcation, and is the backwater-scale
(~0.5 km) structure even legible through the DEM's canopy/single-epoch noise?

It deliberately reuses the *exact* fine-scale estimator that produced thesis Fig 9
(`thesis_figures.core._fine_slope_theilsen` / `_fine_regular_grid`) so the two
sides are methodologically identical -- the ONLY differences are:
  * data source: dem_river_elevations.parquet (terrain) vs master_all_data (water),
  * aggregation: the DEM is a single static epoch, so there is NO per-pass median /
    across-pass IQR band -- one terrain profile, one Theil-Sen sweep.

This is DEM-stream exploratory work: standalone, untracked, writes PNGs to
dem_finescale_slope_spike/. Not wired into the dashboard or thesis_figures.
"""

from __future__ import annotations

import os

import duckdb
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from thesis_figures import config, core
from thesis_figures.core import (
    FINE_BASE_BIN_KM, FINE_MIN_PIX_BIN, _fine_regular_grid, _fine_slope_theilsen,
)

OUT_DIR = os.path.join(config.REPO_ROOT, "dem_finescale_slope_spike")
REACHES = ("Kanektok_River", "Uyak_Creek")
RES_KM = 0.5          # backwater scale (matches Fig 9); 1.0 shown as a robustness check
XMAX = 34.0
ZOOM_KM = 8.0
BIF = config.BIFURCATION_DIST_KM


# ---------------------------------------------------------------------------
# DEM fine-scale terrain slope (single epoch -> no per-pass aggregation)
# ---------------------------------------------------------------------------
def dem_finescale_slope(dem_con, reach, res_km=RES_KM, xmax=XMAX):
    """Terrain-slope profile for one reach: 0.1 km binned-median DEM elevation,
    then the same sliding Theil-Sen used for the SWOT water slope.

    Returns (grid_km, elev_m, slope_abs_cm_km). Slope is |cm/km| (steepness) to
    match the SWOT convention; NaN where the 0.1 km bin is too sparse.
    """
    df = dem_con.execute(f"""
        SELECT ROUND(dist_km / {FINE_BASE_BIN_KM}) * {FINE_BASE_BIN_KM} AS bin,
               MEDIAN(wse) AS wse,
               COUNT(*)    AS npix
        FROM dem
        WHERE Reach_Name = '{reach}'
        GROUP BY bin
    """).fetchdf()
    df = df[(df["npix"] >= FINE_MIN_PIX_BIN) & (df["bin"] <= xmax)].copy()
    df["ibin"] = (df["bin"] / FINE_BASE_BIN_KM).round().astype(int)
    if len(df) < 5:
        return np.array([]), np.array([]), np.array([])

    # Regular 0.1 km grid with short internal gaps filled (identical helper to Fig 9).
    ix, y = _fine_regular_grid(df)
    grid = ix * FINE_BASE_BIN_KM
    slope = np.abs(_fine_slope_theilsen(grid, y, res_km))
    return grid, y, slope


# ---------------------------------------------------------------------------
def reference_gradients():
    """Per-reach reference gradient (median per-pass Theil-Sen), for dashed overlay.
    Falls back to the canonical numbers if the artifact is unavailable."""
    try:
        ref = core.load_reference_gradient()
        ref = ref[ref["gated"]] if "gated" in ref.columns else ref
        g = ref.groupby("Reach_Name")["theilsen_cm_km"].median().abs()
        return {r: float(g.get(r, np.nan)) for r in REACHES}
    except Exception:
        return {"Kanektok_River": 195.4, "Uyak_Creek": 191.7}


def near_bif_summary(grid, slope, lo=1.0, hi=5.0):
    """Mean |slope| in the [lo, hi] km near-bifurcation window."""
    m = (grid >= lo) & (grid <= hi) & np.isfinite(slope)
    return float(np.mean(slope[m])) if m.any() else np.nan


def _style_x(ax, xmax):
    ax.set_xlim(xmax, 0)   # reversed: mouth left, anchor (0 km) right (thesis convention)
    ax.axvline(BIF, color="#888888", ls=":", lw=1.0, zorder=1)
    ax.grid(True, ls="--", lw=0.5, color="#E0E0E0")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # --- DEM (terrain) -----------------------------------------------------
    dem_con = duckdb.connect()
    dem_con.execute(f"CREATE VIEW dem AS SELECT * FROM '{config.DEM_PATH}'")
    dem = {}
    for r in REACHES:
        for res in (RES_KM, 1.0):
            grid, elev, slope = dem_finescale_slope(dem_con, r, res_km=res)
            dem[(r, res)] = dict(grid=grid, elev=elev, slope=slope)

    # --- SWOT (water) fine slope, exact Fig-9 computation ------------------
    con = core.connect()
    swot = {}
    for res in (RES_KM, 1.0):
        swot[res] = core.finescale_slope_profile(con, reaches=REACHES,
                                                  res_km=res, xmax=XMAX)

    refg = reference_gradients()

    # --- numeric agreement summary ----------------------------------------
    print("\n=== Near-bifurcation (1-5 km) mean |slope|, cm/km ===")
    print(f"{'reach':16s} {'res':>5s} {'DEM terrain':>12s} {'SWOT water':>11s} "
          f"{'ref grad':>9s}")
    rows = []
    for r in REACHES:
        for res in (RES_KM, 1.0):
            d = dem[(r, res)]
            s = swot[res].get(r, {})
            dem_nb = near_bif_summary(d["grid"], d["slope"])
            swot_nb = (near_bif_summary(s["grid"], s["med"])
                       if s else np.nan)
            print(f"{r:16s} {res:5.1f} {dem_nb:12.1f} {swot_nb:11.1f} "
                  f"{refg.get(r, np.nan):9.1f}")
            rows.append(dict(reach=r, res_km=res, dem_terrain_cmkm=dem_nb,
                             swot_water_cmkm=swot_nb, ref_grad_cmkm=refg.get(r)))
    pd.DataFrame(rows).to_csv(os.path.join(OUT_DIR, "near_bif_summary.csv"),
                              index=False)

    # Correlation of the two slope profiles over the common grid (0.5 km, 1-30 km)
    print("\n=== Profile-shape agreement (0.5 km, 1-30 km) ===")
    for r in REACHES:
        d = dem[(r, RES_KM)]
        s = swot[RES_KM].get(r, {})
        if not s:
            continue
        # interpolate DEM slope onto the SWOT grid
        gs, ms = s["grid"], s["med"]
        di = np.interp(gs, d["grid"], d["slope"], left=np.nan, right=np.nan)
        m = np.isfinite(di) & np.isfinite(ms) & (gs >= 1) & (gs <= 30)
        if m.sum() > 5:
            rho = np.corrcoef(di[m], ms[m])[0, 1]
            bias = np.mean(di[m] - ms[m])
            print(f"{r:16s} Pearson r={rho:+.2f}  mean(DEM-SWOT)={bias:+6.1f} cm/km"
                  f"  (n={m.sum()} bins)")

    config.apply_style()

    # --- figure: rows = rivers, cols = full reach / bifurcation zoom -------
    fig, axes = plt.subplots(2, 2, figsize=(config.FIG_WIDTH_FULL, 6.2),
                             sharex="col")
    for i, r in enumerate(REACHES):
        col = config.river_color(r)
        d = dem[(r, RES_KM)]
        s = swot[RES_KM].get(r, {})
        for j, (xmax, zoom) in enumerate([(XMAX, False), (ZOOM_KM, True)]):
            ax = axes[i, j]
            # SWOT water slope: median line + IQR band
            if s:
                ax.fill_between(s["grid"], s["lo"], s["hi"], color=col,
                                alpha=0.18, lw=0, zorder=2)
                ax.plot(s["grid"], s["med"], color=col, lw=1.7, zorder=4,
                        label="SWOT water-surface slope")
            # DEM terrain slope: single black line (no band -- single epoch)
            ax.plot(d["grid"], d["slope"], color="#222222", lw=1.4, ls="-",
                    zorder=5, label="DEM terrain slope")
            # reference (reach-average) gradient
            ax.axhline(refg.get(r, np.nan), color=col, ls="--", lw=1.0,
                       alpha=0.7, zorder=3)
            _style_x(ax, xmax)
            if zoom:
                ax.set_ylim(0, 500)
            else:
                ax.set_ylim(0, 500)
            if i == 1:
                ax.set_xlabel("Distance from anchor (km)")
            if j == 0:
                ax.set_ylabel(f"{config.river_label(r)}\n|slope| (cm/km)")
            if i == 0:
                ax.set_title("Full reach" if not zoom
                             else f"Bifurcation zoom (0-{ZOOM_KM:.0f} km)",
                             fontsize=10)
    axes[0, 0].legend(loc="upper left", fontsize=8)
    fig.suptitle("Fine-scale terrain (DEM) vs water-surface (SWOT) slope  "
                 f"-- sliding Theil-Sen, {RES_KM:.1f} km window",
                 fontsize=11, y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    out = os.path.join(OUT_DIR, "dem_vs_swot_finescale_slope.png")
    fig.savefig(out, dpi=150)
    print(f"\nWrote {out}")

    # --- companion: DEM terrain ELEVATION profile (sanity check) -----------
    fig2, ax2 = plt.subplots(figsize=(config.FIG_WIDTH_FULL, 3.4))
    for r in REACHES:
        d = dem[(r, RES_KM)]
        ax2.plot(d["grid"], d["elev"], color=config.river_color(r), lw=1.5,
                 label=config.river_label(r))
    _style_x(ax2, XMAX)
    ax2.set_xlabel("Distance from anchor (km)")
    ax2.set_ylabel("Terrain elevation (m, EGM2008)")
    ax2.set_title("DEM binned-median terrain profile (0.1 km)", fontsize=10)
    ax2.legend(fontsize=9)
    fig2.tight_layout()
    out2 = os.path.join(OUT_DIR, "dem_terrain_profile.png")
    fig2.savefig(out2, dpi=150)
    print(f"Wrote {out2}")


if __name__ == "__main__":
    main()
