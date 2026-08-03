"""
Kanektok ADCP depth statistics + the Uyak-vs-Kanektok mouth depth comparison.

We do NOT build a Uyak depth model (the Uyak was surveyed only near its mouth). Instead this script
(1) reports the Kanektok channel-depth statistics from the boat-ADCP survey, and (2) compares the
one reach where BOTH rivers have depth — the mouth (radius ~31-33 km) — to gauge how the two rivers'
depths differ at matched downstream distance.

Sources (raw boat ADCP, ~/Downloads/ADCP Data, May-Jun 2026):
  - Kanektok: all `Kanektok_Day_*/Shapefiles/*_velocity_depth_01_ASC.shp` (thalweg run Day 03 +
    bank-to-bank discharge crossings Days 02/05/06).
  - Uyak:     `Uiyak_Day_04/Shapefiles/*_velocity_depth_01_ASC.shp` (8 crossings near the mouth).

Radius is straight-line distance from the shared anchor (the arc-frame downstream coordinate), so
"same radius" = matched downstream position, consistent with the rest of Approach B.

Outputs: prints a stats table; writes outputs/adcp_depth_comparison.png and a committed
data/uyak_mouth_depth.parquet (so the comparison reproduces without the large raw folder).

Run:  python3 DEM_Transects/adcp_depth_stats.py
"""

from __future__ import annotations

import glob
import os

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "outputs")
DATA = os.path.join(HERE, "data")
ADCP_DIR = "/home/luke/Downloads/ADCP Data"
KAN_THALWEG = os.path.join(DATA, "kanektok_thalweg_depth.parquet")

ANCHOR = (59.82463509, -161.33397834)
R_EARTH = 6371.0088
DEPTH_MAX_M = 10.0   # physical sanity cap — both rivers max ~4 m; drops rare erroneous ADCP pings


def dist_km(lat, lon):
    la1, lo1 = np.radians(ANCHOR[0]), np.radians(ANCHOR[1])
    la2, lo2 = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * R_EARTH * np.arcsin(np.sqrt(a))


def load_depth(pattern):
    """All valid (depth>0) pings under a glob → DataFrame(lat, lon, depth_m, radius_km)."""
    lat, lon, dep = [], [], []
    for f in sorted(glob.glob(pattern)):
        g = gpd.read_file(f)
        lat += list(g["LAT"]); lon += list(g["LON"]); dep += list(g["DEPTH"])
    df = pd.DataFrame({"lat": lat, "lon": lon, "depth_m": dep})
    df = df[np.isfinite(df["depth_m"]) & (df["depth_m"] > 0)
            & (df["depth_m"] < DEPTH_MAX_M)].reset_index(drop=True)
    df["radius_km"] = dist_km(df["lat"], df["lon"])
    return df


def _stats(s):
    return dict(n=len(s), median=s.median(), mean=s.mean(), std=s.std(),
                p10=s.quantile(.10), p90=s.quantile(.90), max=s.max())


def main():
    kan = load_depth(os.path.join(ADCP_DIR, "Kanektok_Day_*", "Shapefiles",
                                  "*_velocity_depth_01_ASC.shp"))
    uy = load_depth(os.path.join(ADCP_DIR, "Uiyak_Day_04", "Shapefiles",
                                 "*_velocity_depth_01_ASC.shp"))
    uy[["lat", "lon", "depth_m", "radius_km"]].to_parquet(
        os.path.join(DATA, "uyak_mouth_depth.parquet"), index=False)

    print(f"Kanektok: {len(kan)} depth pings, radius {kan.radius_km.min():.1f}-{kan.radius_km.max():.1f} km")
    print(f"Uyak (mouth): {len(uy)} depth pings, radius {uy.radius_km.min():.1f}-{uy.radius_km.max():.1f} km")

    # --- Kanektok depth statistics (the deliverable) ---
    print("\n=== Kanektok channel depth (all ADCP pings) ===")
    s = _stats(kan["depth_m"])
    print(f"  n={s['n']}  median {s['median']:.2f}  mean {s['mean']:.2f} ± {s['std']:.2f}  "
          f"p10-p90 {s['p10']:.2f}-{s['p90']:.2f}  max {s['max']:.2f} m")
    print("  by radius band:")
    for lo in range(0, 35, 5):
        sub = kan[(kan.radius_km >= lo) & (kan.radius_km < lo + 5)]
        if len(sub) > 20:
            print(f"    {lo:2d}-{lo+5:2d} km: median {sub.depth_m.median():.2f}  "
                  f"p90 {sub.depth_m.quantile(.9):.2f}  max {sub.depth_m.max():.2f}  (n={len(sub)})")

    # --- mouth comparison: the overlap band where both rivers have depth ---
    band = (uy.radius_km.min(), uy.radius_km.max())
    kb = kan[(kan.radius_km >= band[0]) & (kan.radius_km <= band[1])]
    print(f"\n=== Mouth comparison, radius {band[0]:.1f}-{band[1]:.1f} km (both rivers surveyed) ===")
    for name, s in [("Uyak", _stats(uy["depth_m"])), ("Kanektok", _stats(kb["depth_m"]))]:
        print(f"  {name:9s} n={s['n']:4d}  median {s['median']:.2f}  mean {s['mean']:.2f}  "
              f"p90 {s['p90']:.2f}  max {s['max']:.2f} m")
    ratio = kb["depth_m"].median() / uy["depth_m"].median()
    print(f"  -> Kanektok median depth is {ratio:.2f}x the Uyak's "
          f"(+{kb['depth_m'].median() - uy['depth_m'].median():.2f} m) at matched distance.")

    _fig(kan, uy, band, kb)


def _fig(kan, uy, band, kb):
    fig, ax = plt.subplots(1, 2, figsize=(14, 5))
    # (1) depth vs radius — Kanektok spans the river, Uyak only at the mouth
    ax[0].scatter(kan.radius_km, kan.depth_m, s=3, color="#08519c", alpha=0.25, label="Kanektok")
    ax[0].scatter(uy.radius_km, uy.depth_m, s=6, color="#d94801", alpha=0.5, label="Uyak (mouth)")
    ax[0].axvspan(band[0], band[1], color="0.6", alpha=0.15)
    ax[0].set(xlabel="Distance from anchor (km, ≈ downstream)", ylabel="ADCP river depth (m)",
              title="Channel depth vs downstream distance (grey = overlap band)")
    ax[0].invert_yaxis(); ax[0].legend(fontsize=9, markerscale=2)
    # (2) distributions in the overlap band
    data = [uy["depth_m"].values, kb["depth_m"].values]
    parts = ax[1].violinplot(data, showmedians=True, showextrema=False)
    for pc, c in zip(parts["bodies"], ["#d94801", "#08519c"]):
        pc.set_facecolor(c); pc.set_alpha(0.5)
    ax[1].set_xticks([1, 2], [f"Uyak\n(med {np.median(data[0]):.2f} m)",
                              f"Kanektok\n(med {np.median(data[1]):.2f} m)"])
    ax[1].set(ylabel="ADCP river depth (m)",
              title=f"Depth distribution, radius {band[0]:.0f}-{band[1]:.0f} km "
                    f"(Kanektok {np.median(data[1])/np.median(data[0]):.2f}× deeper)")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "adcp_depth_comparison.png"), dpi=130)
    plt.close(fig)
    print("\nwrote outputs/adcp_depth_comparison.png")
    print("wrote data/uyak_mouth_depth.parquet")


if __name__ == "__main__":
    main()
