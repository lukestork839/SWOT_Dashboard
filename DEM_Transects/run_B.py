"""
Full rollout of approach B (channel-relative zones) to every transect on both rivers,
producing the figure set for inspection. Reuses the analysis in prototype_B.py.

Outputs (DEM_Transects/outputs/):
  - transect_beta_B.parquet          one row per transect (station_m, are/p2/fpe, har/hm/beta)
  - beta_B_summary_<reach>.png       long profile + H_AR/Hm + beta + example sections
  - beta_B_comparison.png            Kanektok vs Uyak (H_AR, beta)
  - beta_B_map.png                   spatial beta pattern, both rivers
  - beta_B_validation.png            approach B vs recovered ArcGIS original (Kanektok)

Run:  python3 DEM_Transects/run_B.py
"""

from __future__ import annotations

import os

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shapely

import prototype_B as pb
import transects as tr
from prototype_B import analyse_transect

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
POLY = os.path.join(ROOT, "river_poly.zip")
RASTER = os.path.join(ROOT, "batch_outputs", "arcticdem_rivers_2m.tif")
CENTERLINE = os.path.join(HERE, "outputs", "swot_centerlines.gpkg")
OUT = os.path.join(HERE, "outputs")
REACH_NAMES = {"Uyak": "Uyak_Creek", "Kanektok": "Kanektok_River"}
SCALAR_KEYS = ("ch_x", "are", "p2", "fpe", "har", "hm", "beta")


def analyse_reach(samples: pd.DataFrame) -> pd.DataFrame:
    """Run approach B on every transect in a reach's sample points."""
    rows = []
    for tid, g in samples.groupby("transect_id"):
        g = g.sort_values("cross_dist_m")
        r = analyse_transect(g["cross_dist_m"].to_numpy(), g["elevation_m"].to_numpy(),
                             g["in_corridor"].to_numpy())
        rec = {"transect_id": tid, "station_m": float(g["station_m"].iloc[0]),
               "ok": bool(r["ok"]),
               "cx": float(g["cx"].iloc[0]), "cy": float(g["cy"].iloc[0])}
        for k in SCALAR_KEYS:
            rec[k] = float(r[k]) if r["ok"] else np.nan
        rows.append(rec)
    return pd.DataFrame(rows).sort_values("station_m").reset_index(drop=True)


def orient_upstream(b: pd.DataFrame) -> pd.DataFrame:
    """Flip station_m so it increases upstream (with elevation)."""
    bs = b.sort_values("station_m")
    fpe = bs["fpe"].dropna()
    if len(fpe) > 30 and bs["fpe"].head(20).median() > bs["fpe"].tail(20).median():
        b = b.copy()
        b["station_m"] = b["station_m"].max() - b["station_m"]
    return b.sort_values("station_m").reset_index(drop=True)


def summary_fig(reach, b, samples):
    ok = b[b["ok"]]
    x = ok["station_m"] / 1000.0
    fig, ax = plt.subplots(2, 2, figsize=(14, 9))

    ax[0, 0].plot(x, ok["are"], color="#9ecae1", lw=1.3, label="Alluvial Ridge (P98)")
    ax[0, 0].plot(x, ok["fpe"], color="#a1d99b", lw=1.3, label="Floodplain (median)")
    ax[0, 0].plot(x, ok["p2"], color="#08519c", lw=1.3, label="Channel (P2)")
    ax[0, 0].set(xlabel="Distance upstream (km)", ylabel="Elevation (m)",
                 title=f"{reach} — long profile (approach B)")
    ax[0, 0].legend(fontsize=8, loc="upper left")

    ax[0, 1].plot(x, ok["hm"], color="#08519c", lw=1.0, label="Hm = ARE-channel")
    ax[0, 1].plot(x, ok["har"], color="#9ecae1", lw=1.0, label="H_AR = ARE-floodplain")
    ax[0, 1].set(xlabel="Distance upstream (km)", ylabel="Height (m)",
                 title=f"{reach} — H_AR & Hm")
    ax[0, 1].legend(fontsize=8)

    ax[1, 0].plot(x, ok["beta"].clip(-0.2, 2), color="#d94801", lw=1.0)
    ax[1, 0].axhline(1, color="k", ls=":", lw=0.8, label="β=1 (perched)")
    ax[1, 0].axhline(ok["beta"].median(), color="k", ls="--", lw=0.8,
                     label=f"median {ok['beta'].median():.2f}")
    ax[1, 0].set(xlabel="Distance upstream (km)", ylabel="β = H_AR/Hm", ylim=(-0.2, 2),
                 title=f"{reach} — superelevation β")
    ax[1, 0].legend(fontsize=8)

    # example sections: re-run analysis on 3 spread transects to draw the detrended picks.
    tids = ok["transect_id"].to_numpy()
    picks = tids[np.linspace(0, len(tids) - 1, 3).astype(int)]
    for tid in picks:
        g = samples[samples["transect_id"] == tid].sort_values("cross_dist_m")
        r = analyse_transect(g["cross_dist_m"].to_numpy(), g["elevation_m"].to_numpy(),
                             g["in_corridor"].to_numpy())
        if not r["ok"]:
            continue
        st = float(g["station_m"].iloc[0]) / 1000.0
        ax[1, 1].plot(r["rel"], r["z_dt"], lw=0.8, label=f"#{tid} @ {st:.1f} km (β={r['beta']:.2f})")
    ax[1, 1].axvspan(-pb.D_NEAR, pb.D_NEAR, color="#fdd0a2", alpha=0.25)
    ax[1, 1].set(xlabel="distance from channel (m)", ylabel="elevation (m, detrended)",
                 title=f"{reach} — example sections", xlim=(-pb.D_FAR, pb.D_FAR))
    ax[1, 1].legend(fontsize=7)

    fig.tight_layout()
    dst = os.path.join(OUT, f"beta_B_summary_{reach}.png")
    fig.savefig(dst, dpi=130)
    plt.close(fig)
    print(f"  wrote {dst}")


def main():
    polys = gpd.read_file(POLY)
    polys_m = polys.to_crs(32604)
    polys_3413 = polys.to_crs(3413)
    guides = gpd.read_file(CENTERLINE).to_crs(32604)
    poly3413 = {REACH_NAMES[r.Name]: r.geometry for r in polys_3413.itertuples()}

    all_beta = []
    for reach in ["Kanektok_River", "Uyak_Creek"]:
        print(f"=== {reach} ===")
        guide = guides[guides["Reach_Name"] == reach].geometry.iloc[0]
        tx = tr.generate_transects(guide, 32604, spacing=100.0, half_width=pb.HALF_WIDTH)
        samples, _ = tr.sample_dem_along_transects(tx, RASTER, step=pb.STEP)
        # vectorized in-corridor test (lon/lat cols are raster-CRS 3413 x/y).
        samples["in_corridor"] = shapely.contains_xy(
            poly3413[reach], samples["lon"].to_numpy(), samples["lat"].to_numpy())
        # attach channel-crossing coords for the map
        cxy = tx.set_index("transect_id")[["cx", "cy"]]
        samples = samples.merge(cxy, on="transect_id", how="left")
        print(f"  {len(tx)} transects, {len(samples)} sample points")

        b = orient_upstream(analyse_reach(samples))
        b.insert(0, "Reach_Name", reach)
        n_ok = int(b["ok"].sum())
        print(f"  {n_ok}/{len(b)} transects passed QC | "
              f"β median {b.loc[b.ok, 'beta'].median():.2f}, "
              f"H_AR median {b.loc[b.ok, 'har'].median():.2f} m, "
              f"perched (β>1) {(b.loc[b.ok, 'beta'] > 1).mean()*100:.0f}%")
        summary_fig(reach, b, samples)
        all_beta.append(b)

    beta = pd.concat(all_beta, ignore_index=True)
    beta.to_parquet(os.path.join(OUT, "transect_beta_B.parquet"), index=False)

    # comparison
    fig, ax = plt.subplots(1, 2, figsize=(13, 5))
    for reach, b in beta.groupby("Reach_Name"):
        o = b[b["ok"]].sort_values("station_m")
        ax[0].plot(o["station_m"] / 1000, o["har"], lw=1.0, label=reach)
        ax[1].plot(o["station_m"] / 1000,
                   o["beta"].rolling(11, center=True, min_periods=1).median(), lw=1.2, label=reach)
    ax[0].set(xlabel="Distance upstream (km)", ylabel="H_AR (m)",
              title="Ridge height H_AR — Kanektok vs Uyak")
    ax[1].axhline(1, color="k", ls=":", lw=0.8)
    ax[1].set(xlabel="Distance upstream (km)", ylabel="β (11-transect median)",
              title="Superelevation β — Kanektok vs Uyak", ylim=(0, 1.4))
    for a in ax:
        a.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "beta_B_comparison.png"), dpi=130)
    plt.close(fig)
    print("wrote beta_B_comparison.png")

    # spatial beta map (rough, no basemap) in UTM metres, equal aspect
    fig, ax = plt.subplots(figsize=(11, 7))
    o = beta[beta["ok"]]
    sc = ax.scatter(o["cx"], o["cy"], c=o["beta"].clip(0, 1.4), cmap="YlOrRd",
                    s=14, vmin=0, vmax=1.4)
    for reach, g in polys_m.set_index("Name").iterrows():
        xs, ys = g.geometry.exterior.xy if g.geometry.geom_type == "Polygon" else (None, None)
        if xs is not None:
            ax.plot(xs, ys, color="0.6", lw=0.6)
    ax.set_aspect("equal")
    ax.set(title="Superelevation β per transect (both rivers)",
           xlabel="Easting (m, UTM 4N)", ylabel="Northing (m)")
    fig.colorbar(sc, label="β")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "beta_B_map.png"), dpi=130)
    plt.close(fig)
    print("wrote beta_B_map.png")

    # validation: approach B vs recovered ArcGIS original (Kanektok)
    orig_path = "/tmp/original_beta.parquet"
    if os.path.exists(orig_path):
        orig = pd.read_parquet(orig_path).reset_index().sort_values("ORIG_SEQ_1")
        if orig["median"].head(15).median() > orig["median"].tail(15).median():
            orig = orig.iloc[::-1].reset_index(drop=True)
        orig_x = np.arange(len(orig)) * (26.68 / len(orig))
        kb = beta[(beta.Reach_Name == "Kanektok_River") & beta.ok].sort_values("station_m")
        fig, ax = plt.subplots(1, 2, figsize=(13, 5))
        ax[0].plot(orig_x, orig["har"], color="#c0392b", lw=1.0, label="original (ArcGIS, 2-zone)")
        ax[0].plot(kb["station_m"] / 1000, kb["har"], color="#2c7fb8", lw=1.0, label="approach B (2m)")
        ax[0].set(xlabel="Distance upstream (km)", ylabel="H_AR (m)", title="Kanektok H_AR — B vs original")
        ax[0].legend(fontsize=8)
        ax[1].plot(orig_x, orig["beta"].clip(0, 2), color="#c0392b", lw=1.0, label="original")
        ax[1].plot(kb["station_m"] / 1000, kb["beta"].clip(0, 2), color="#2c7fb8", lw=1.0, label="approach B")
        ax[1].axhline(1, color="k", ls=":", lw=0.8)
        ax[1].set(xlabel="Distance upstream (km)", ylabel="β", title="Kanektok β — B vs original", ylim=(0, 2))
        ax[1].legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(OUT, "beta_B_validation.png"), dpi=130)
        plt.close(fig)
        print("wrote beta_B_validation.png")


if __name__ == "__main__":
    main()
