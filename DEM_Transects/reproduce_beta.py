"""
Simple per-transect superelevation (beta) reproduction — the Python equivalent of the
prior ArcGIS/arcpy workflow (guide line -> perpendicular transects -> sample ArcticDEM Z ->
percentile stats per line), extended to BOTH rivers (Kanektok + Uyak).

Prior method (from `V6. adding beta calculation values for each line.ipynb`), per transect:

    ridge crest (ARE) = P98 of elevation along the transect      ("Alluvial Ridge")
    channel bottom    = P2  of elevation along the transect      ("River Depth")
    floodplain (FPE)  = median elevation along the transect      ("Floodplain")
    H_AR = P98 - median        (ridge height above floodplain)
    Hm   = P98 - P2            (total relief, crest above channel bottom)
    beta = H_AR / Hm           (superelevation ratio, in [0, 1])

No channel/ridge/floodplain point-picking — just percentiles over each transect's DEM
profile, which is robust to the sub-metre floodplain noise in ArcticDEM. Transects are
clipped to the river-corridor polygon (the old `Avulsion_Polygon` step) so valley walls
don't leak into P98.

Pipeline (offline precompute, mirrors DEM_Pull.py):
  1. load corridor polygons, project to a metric CRS (auto UTM),
  2. per reach, get a channel guide line (SWOT-water centerline by default, or --centerline),
  3. build perpendicular transects at fixed spacing,
  4. clip each transect to its reach polygon,
  5. sample the 2 m ArcticDEM along each transect,
  6. reduce each transect to P98/P2/median -> H_AR/Hm/beta.

Outputs (DEM_Transects/outputs/):
  - transect_beta.parquet      : one row per transect (station_m, p98, p2, median, har, hm, beta)
  - transect_profiles.parquet  : one row per sample point (for side-profile figures)
  - transect_beta.gpkg         : transect + guide-line geometries for QC / mapping

Run:
  python3 DEM_Transects/reproduce_beta.py
  python3 DEM_Transects/reproduce_beta.py --spacing 100 --step 2
  python3 DEM_Transects/reproduce_beta.py --centerline path/to/hand_drawn_guidelines.gpkg
"""

from __future__ import annotations

import argparse
import os

import geopandas as gpd
import numpy as np
import pandas as pd

import centerline as cl
import transects as tr

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_POLY = os.path.join(ROOT, "river_poly.zip")
DEFAULT_RASTER = os.path.join(ROOT, "batch_outputs", "arcticdem_rivers_2m.tif")
DEFAULT_CENTERLINE = os.path.join(HERE, "outputs", "swot_centerlines.gpkg")
OUT_DIR = os.path.join(HERE, "outputs")

# Polygon Name -> dashboard Reach_Name (match the SWOT/DEM parquet convention).
REACH_NAMES = {"Uyak": "Uyak_Creek", "Kanektok": "Kanektok_River"}


def pick_utm_epsg(gdf: gpd.GeoDataFrame) -> int:
    """Auto-pick the WGS84/UTM zone EPSG for the data's centroid longitude."""
    c = gdf.to_crs(4326).union_all().centroid
    zone = int((c.x + 180) // 6) + 1
    return 32600 + zone  # northern hemisphere


def guide_line_for_reach(supplied, reach, poly_geom):
    """Return a single channel guide LineString for one reach.

    Prefer a supplied line tagged for this reach; else clip the supplied lines to the
    polygon; else fall back to the corridor-polygon skeleton. Orientation is handled
    downstream (station_m is flipped to increase upstream, by elevation).
    """
    if supplied is not None:
        if "Reach_Name" in supplied.columns and (supplied["Reach_Name"] == reach).any():
            line = supplied[supplied["Reach_Name"] == reach].union_all()
        else:
            line = supplied.clip(poly_geom).union_all()
        if line.geom_type == "MultiLineString":
            line = max(line.geoms, key=lambda g: g.length)  # keep the main stem
        return line
    return cl.polygon_to_centerline(poly_geom)


def clip_to_polygon(transects: gpd.GeoDataFrame, poly_geom) -> gpd.GeoDataFrame:
    """Clip each transect to the corridor polygon, keeping the segment that crosses the
    channel (the one nearest the centre point). Drops transects that miss the polygon."""
    kept = []
    for row in transects.itertuples():
        center = row.geometry.interpolate(row.geometry.length / 2.0)  # geometric midpoint
        center_pt = gpd.points_from_xy([row.cx], [row.cy])[0]
        inter = row.geometry.intersection(poly_geom)
        if inter.is_empty:
            continue
        if inter.geom_type == "LineString":
            seg = inter
        else:  # MultiLineString / GeometryCollection -> nearest segment to channel crossing
            segs = [g for g in getattr(inter, "geoms", [inter])
                    if g.geom_type == "LineString"]
            if not segs:
                continue
            seg = min(segs, key=lambda g: g.distance(center_pt))
        if seg.length < 1.0:
            continue
        kept.append({"transect_id": row.transect_id, "station_m": row.station_m,
                     "cx": row.cx, "cy": row.cy, "geometry": seg})
    return gpd.GeoDataFrame(kept, crs=transects.crs)


def beta_per_transect(samples: pd.DataFrame) -> pd.DataFrame:
    """Reduce sampled points to one row per transect: P98/P2/median -> H_AR/Hm/beta."""
    rows = []
    for tid, g in samples.groupby("transect_id"):
        z = g["elevation_m"].to_numpy()
        z = z[np.isfinite(z)]
        if z.size < 10:  # too few valid pixels to trust the percentiles
            continue
        p98 = float(np.percentile(z, 98))
        p2 = float(np.percentile(z, 2))
        med = float(np.median(z))
        har = p98 - med
        hm = p98 - p2
        rows.append({
            "transect_id": tid,
            "station_m": float(g["station_m"].iloc[0]),
            "n_pts": int(z.size),
            "are_p98": p98, "channel_p2": p2, "floodplain_median": med,
            "har": har, "hm": hm,
            "beta": har / hm if hm > 0 else np.nan,
        })
    return pd.DataFrame(rows).sort_values("station_m").reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--polygons", default=DEFAULT_POLY)
    ap.add_argument("--raster", default=DEFAULT_RASTER)
    ap.add_argument("--centerline", default=DEFAULT_CENTERLINE,
                    help="Channel guide line(s). Default: SWOT-water centerlines. "
                         "Pass a hand-drawn file to reproduce the original guide lines.")
    ap.add_argument("--epsg", type=int, default=None, help="Override projected CRS EPSG.")
    ap.add_argument("--spacing", type=float, default=100.0, help="Transect spacing (m).")
    ap.add_argument("--half-width", type=float, default=2500.0,
                    help="Transect half-length (m) before corridor clip.")
    ap.add_argument("--step", type=float, default=2.0, help="DEM sample step along transect (m).")
    args = ap.parse_args()

    polys = gpd.read_file(args.polygons)
    epsg = args.epsg or pick_utm_epsg(polys)
    polys_m = polys.to_crs(epsg)
    print(f"Loaded {len(polys)} polygons; projecting to EPSG:{epsg}")

    supplied = (cl.load_centerline(args.centerline, epsg)
                if args.centerline and os.path.exists(args.centerline) else None)
    print(f"Guide line source: {args.centerline if supplied is not None else 'polygon skeleton'}")

    all_beta, all_profiles, all_tx, all_guides = [], [], [], []
    for poly_row in polys_m.itertuples():
        name = getattr(poly_row, "Name", None) or f"poly_{poly_row.Index}"
        reach = REACH_NAMES.get(name, name)
        print(f"\n=== {reach} ===")

        guide = guide_line_for_reach(supplied, reach, poly_row.geometry)
        print(f"  guide line: {guide.length/1000:.1f} km")

        tx = tr.generate_transects(guide, epsg, spacing=args.spacing,
                                   half_width=args.half_width)
        tx = clip_to_polygon(tx, poly_row.geometry)
        print(f"  {len(tx)} transects @ {args.spacing:.0f} m spacing (clipped to corridor)")

        samples, n_nodata = tr.sample_dem_along_transects(tx, args.raster, step=args.step)
        samples.insert(0, "Reach_Name", reach)
        print(f"  {len(samples)} sample points ({n_nodata} nodata)")

        beta = beta_per_transect(samples)
        # Orient station_m as distance UPSTREAM: it should increase with elevation. The
        # guide line may run either way; flip if the low-station end is the high ground.
        bs = beta.sort_values("station_m")
        if (bs["floodplain_median"].head(20).median()
                > bs["floodplain_median"].tail(20).median()):
            beta["station_m"] = beta["station_m"].max() - beta["station_m"]
            beta = beta.sort_values("station_m").reset_index(drop=True)
        beta.insert(0, "Reach_Name", reach)
        print(f"  {len(beta)} transects with valid beta | "
              f"beta median {beta['beta'].median():.2f}, "
              f"H_AR median {beta['har'].median():.2f} m")

        all_beta.append(beta)
        all_profiles.append(samples)
        all_tx.append(tx.assign(Reach_Name=reach))
        all_guides.append(gpd.GeoDataFrame({"Reach_Name": [reach]},
                                           geometry=[guide], crs=epsg))

    os.makedirs(OUT_DIR, exist_ok=True)
    beta_df = pd.concat(all_beta, ignore_index=True)
    prof_df = pd.concat(all_profiles, ignore_index=True)
    beta_df.to_parquet(os.path.join(OUT_DIR, "transect_beta.parquet"), index=False)
    prof_df.to_parquet(os.path.join(OUT_DIR, "transect_profiles.parquet"), index=False)
    print(f"\nWrote {len(beta_df)} transects -> outputs/transect_beta.parquet")
    print(f"Wrote {len(prof_df)} points   -> outputs/transect_profiles.parquet")

    gpkg = os.path.join(OUT_DIR, "transect_beta.gpkg")
    pd.concat(all_tx, ignore_index=True).to_file(gpkg, layer="transects", driver="GPKG")
    pd.concat(all_guides, ignore_index=True).to_file(gpkg, layer="guides", driver="GPKG")
    print(f"Wrote QC geometries -> {gpkg} (layers: transects, guides)")


if __name__ == "__main__":
    main()
