"""
Corrected single-analysis superelevation (beta) for the Kanektok avulsion study.

ONE set of long parallel transects across the floodplain. Each runs
    Kanektok (perched main channel) -> floodplain -> Uyak (low avulsion target).
The Uyak is part of the floodplain, not a separate channel. Per transect:

    P98    = alluvial-ridge crest, from the near-Kanektok band
    P2     = channel bed,          from the near-Kanektok band
    median = floodplain elevation, from the broad floodplain out toward the Uyak
    H_AR = P98 - median,  Hm = P98 - P2,  beta = H_AR / Hm

Faithful to the prior ArcGIS notebook. NO cross-valley detrend: the floodplain's downhill
slope from the perched Kanektok toward the low Uyak IS the avulsion signal.

Transect source: the real `Avulsion_Lines_2` + `Guide_Lines_2`, committed as
reference/avulsion_transects.gpkg (exported from the recovered ArcGIS gdb — see
recover_original_beta.py for the gdb archive location; set AVULSION_TRANSECTS to
read another copy). The validation overlay reads reference/original_beta.parquet,
the recovered ArcGIS result (also rebuilt by recover_original_beta.py).

Run:  python3 DEM_Transects/beta_floodplain.py
"""

from __future__ import annotations

import os

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import Point

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.environ.get("AVULSION_TRANSECTS",
                     os.path.join(HERE, "reference", "avulsion_transects.gpkg"))
RASTER = os.path.join(ROOT, "batch_outputs", "arcticdem_rivers_2m.tif")
OUT = os.path.join(HERE, "outputs")

GEOID = 13.46           # ellipsoidal->orthometric (beta is datum-invariant; for readable elev)
STEP = 2.0              # DEM sample step (m)
D_NEAR = 700.0          # near-Kanektok band: [0, D_NEAR] from the Kanektok end -> P98/P2
FP_INNER = 700.0        # floodplain band inner edge (m from Kanektok)
MIN_PTS = 20


def sample_line(src, geom, step):
    """Sample raster values + along-distance for one (Multi)LineString in the raster CRS."""
    g = geom.geoms[0] if geom.geom_type == "MultiLineString" else geom
    n = max(2, int(g.length / step) + 1)
    d = np.linspace(0.0, g.length, n)
    pts = [g.interpolate(x) for x in d]
    z = np.array([v[0] for v in src.sample([(p.x, p.y) for p in pts])], float)
    nod = src.nodata
    z[(z == nod) | (z == 0)] = np.nan   # 0 = GEE fill; real heights >> 0
    return d, z - GEOID, g


def analyse(d, z):
    """Two-zone picks along one transect, x=0 at the Kanektok end."""
    good = np.isfinite(z)
    near = good & (d <= D_NEAR)
    flood = good & (d > FP_INNER)
    if near.sum() < MIN_PTS or flood.sum() < MIN_PTS:
        return None
    p98 = float(np.percentile(z[near], 98))
    p2 = float(np.percentile(z[near], 2))
    med = float(np.median(z[flood]))
    har, hm = p98 - med, p98 - p2
    return {"are_p98": p98, "channel_p2": p2, "floodplain_median": med,
            "har": har, "hm": hm, "beta": har / hm if hm > 0 else np.nan}


def main():
    al = gpd.read_file(SRC, layer="Avulsion_Lines_2").to_crs(3413)
    al = al.sort_values("ORIG_SEQ").reset_index(drop=True)
    kan = gpd.read_file(SRC, layer="Guide_Lines_2").to_crs(3413).geometry.iloc[1]

    rows = []
    with rasterio.open(RASTER) as src:
        for t in al.itertuples():
            d, z, g = sample_line(src, t.geometry, STEP)
            # orient so x=0 is the Kanektok end (endpoint nearest the Kanektok guide line)
            p0, p1 = Point(g.coords[0]), Point(g.coords[-1])
            if p0.distance(kan) > p1.distance(kan):
                z = z[::-1]
            r = analyse(d, z)
            if r is None:
                continue
            # station = distance of the Kanektok end along the Kanektok guide line
            kan_end = p0 if p0.distance(kan) <= p1.distance(kan) else p1
            r["station_m"] = float(kan.project(kan_end))
            r["ORIG_SEQ"] = int(t.ORIG_SEQ)
            r["geometry"] = t.geometry
            rows.append(r)

    b = gpd.GeoDataFrame(rows, crs=3413)
    # orient station as distance upstream (elevation increases upstream)
    bs = b.sort_values("station_m")
    if bs["floodplain_median"].head(20).median() > bs["floodplain_median"].tail(20).median():
        b["station_m"] = b["station_m"].max() - b["station_m"]
    b = b.sort_values("station_m").reset_index(drop=True)

    b.drop(columns="geometry").to_parquet(os.path.join(OUT, "beta_floodplain.parquet"),
                                          index=False)
    print(f"{len(b)} transects | beta median {b['beta'].median():.2f}, "
          f"H_AR median {b['har'].median():.2f} m, "
          f"perched (beta>1) {(b['beta'] > 1).mean()*100:.0f}%")

    x = b["station_m"] / 1000.0
    fig, ax = plt.subplots(2, 2, figsize=(14, 9))
    ax[0, 0].plot(x, b["are_p98"], color="#9ecae1", lw=1.3, label="Alluvial Ridge (P98)")
    ax[0, 0].plot(x, b["floodplain_median"], color="#a1d99b", lw=1.3, label="Floodplain (median)")
    ax[0, 0].plot(x, b["channel_p2"], color="#08519c", lw=1.3, label="Channel (P2)")
    ax[0, 0].set(xlabel="Distance upstream (km)", ylabel="Elevation (m)",
                 title="Kanektok long profile (2m DEM, two-zone)")
    ax[0, 0].legend(fontsize=8, loc="upper left")

    ax[0, 1].plot(x, b["hm"], color="#08519c", lw=1.0, label="Hm = P98-P2")
    ax[0, 1].plot(x, b["har"], color="#9ecae1", lw=1.0, label="H_AR = P98-median")
    ax[0, 1].set(xlabel="Distance upstream (km)", ylabel="Height (m)", title="H_AR & Hm")
    ax[0, 1].legend(fontsize=8)

    ax[1, 0].plot(x, b["beta"].clip(0, 2), color="#d94801", lw=1.0)
    ax[1, 0].axhline(1, color="k", ls=":", lw=0.8, label="β=1 (perched)")
    ax[1, 0].axhline(b["beta"].median(), color="k", ls="--", lw=0.8,
                     label=f"median {b['beta'].median():.2f}")
    ax[1, 0].set(xlabel="Distance upstream (km)", ylabel="β", ylim=(0, 2), title="Superelevation β")
    ax[1, 0].legend(fontsize=8)

    # spatial beta map: transects colored by beta
    bb = b.copy()
    bb["betac"] = bb["beta"].clip(0, 1.5)
    bb.plot(ax=ax[1, 1], column="betac", cmap="YlOrRd", linewidth=2, legend=True,
            legend_kwds={"label": "β", "shrink": 0.7}, vmin=0, vmax=1.5)
    kanline = gpd.GeoSeries([kan], crs=3413)
    kanline.plot(ax=ax[1, 1], color="#08519c", lw=1.0)
    ax[1, 1].set_title("β per transect (Kanektok blue)")
    ax[1, 1].set_aspect("equal")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "beta_floodplain_summary.png"), dpi=130)
    plt.close(fig)
    print("wrote beta_floodplain_summary.png")

    # overlay vs recovered ArcGIS original (committed; rebuild with recover_original_beta.py)
    op = os.path.join(HERE, "reference", "original_beta.parquet")
    if os.path.exists(op):
        o = pd.read_parquet(op).reset_index().sort_values("ORIG_SEQ_1")
        if o["median"].head(15).median() > o["median"].tail(15).median():
            o = o.iloc[::-1].reset_index(drop=True)
        ox = np.arange(len(o)) * (26.68 / len(o))
        fig, ax = plt.subplots(1, 2, figsize=(13, 5))
        ax[0].plot(ox, o["har"], color="#c0392b", lw=1.0, label="original (ArcGIS Z)")
        ax[0].plot(x, b["har"], color="#2c7fb8", lw=1.0, label="rebuild (2m DEM)")
        ax[0].set(xlabel="Distance upstream (km)", ylabel="H_AR (m)", title="H_AR — rebuild vs original")
        ax[0].legend(fontsize=8)
        ax[1].plot(ox, o["beta"].clip(0, 2), color="#c0392b", lw=1.0, label="original")
        ax[1].plot(x, b["beta"].clip(0, 2), color="#2c7fb8", lw=1.0, label="rebuild")
        ax[1].axhline(1, color="k", ls=":", lw=0.8)
        ax[1].set(xlabel="Distance upstream (km)", ylabel="β", ylim=(0, 2), title="β — rebuild vs original")
        ax[1].legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(OUT, "beta_floodplain_validation.png"), dpi=130)
        plt.close(fig)
        print("wrote beta_floodplain_validation.png")


if __name__ == "__main__":
    main()
