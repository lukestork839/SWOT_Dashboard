"""
Stage 1 orchestrator: river polygons + ArcticDEM raster -> per-transect cross-section
elevation profiles, written to parquet for the dashboard (offline-precompute pattern,
mirroring DEM_Pull.py).

For each river corridor polygon:
  1. reproject to a metric CRS (auto-picked UTM, override with --epsg),
  2. derive a temporary centerline by skeletonization (or load one with --centerline),
  3. generate perpendicular transects at fixed spacing,
  4. sample the DEM along each transect.

Outputs (under DEM_Transects/outputs/):
  - transect_elevations.parquet : tidy sample points (one row per point along a transect)
  - transects.gpkg              : transect + centerline geometries for QC / map overlay

Run:  python3 DEM_Transects/build_transects.py
      python3 DEM_Transects/build_transects.py --spacing 200 --half-width 1500 --step 10
      python3 DEM_Transects/build_transects.py --centerline path/to/coworker_centerline.gpkg
"""

from __future__ import annotations

import argparse
import os

import geopandas as gpd
import pandas as pd

import centerline as cl
import transects as tr

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_POLY = os.path.join(ROOT, "river_poly.zip")
DEFAULT_RASTER = os.path.join(ROOT, "batch_outputs", "arcticdem_rivers.tif")
OUT_DIR = os.path.join(HERE, "outputs")

# Polygon Name -> dashboard Reach_Name (match the SWOT/DEM parquet convention).
REACH_NAMES = {"Uyak": "Uyak_Creek", "Kanektok": "Kanektok_River"}


def pick_utm_epsg(gdf: gpd.GeoDataFrame) -> int:
    """Auto-pick the WGS84/UTM zone EPSG for the data's centroid longitude."""
    c = gdf.to_crs(4326).union_all().centroid
    zone = int((c.x + 180) // 6) + 1
    return 32600 + zone  # northern hemisphere


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--polygons", default=DEFAULT_POLY)
    ap.add_argument("--raster", default=DEFAULT_RASTER)
    ap.add_argument("--centerline", default=None,
                    help="Optional centerline file; if omitted, derive temporary one per polygon.")
    ap.add_argument("--epsg", type=int, default=None, help="Override projected CRS EPSG.")
    ap.add_argument("--spacing", type=float, default=200.0, help="Transect spacing (m).")
    ap.add_argument("--half-width", type=float, default=1500.0, help="Transect half-length (m).")
    ap.add_argument("--step", type=float, default=10.0, help="DEM sample step along transect (m).")
    ap.add_argument("--geoid-offset", type=float, default=13.46,
                    help="Ellipsoidal->orthometric offset (m).")
    args = ap.parse_args()

    polys = gpd.read_file(args.polygons)
    epsg = args.epsg or pick_utm_epsg(polys)
    polys_m = polys.to_crs(epsg)
    print(f"Loaded {len(polys)} polygons; projecting to EPSG:{epsg}")

    supplied_cl = cl.load_centerline(args.centerline, epsg) if args.centerline else None

    all_samples, all_transects, all_centerlines = [], [], []
    for poly_row in polys_m.itertuples():
        name = getattr(poly_row, "Name", None) or f"poly_{poly_row.Index}"
        reach = REACH_NAMES.get(name, name)
        print(f"\n=== {reach} ===")

        if supplied_cl is not None:
            # Prefer the centerline tagged for this reach; otherwise fall back to clipping
            # everything to the polygon. Selecting by reach avoids mixing in the other
            # river where they share a confluence.
            if "Reach_Name" in supplied_cl.columns and (supplied_cl["Reach_Name"] == reach).any():
                # Already reach-specific and channel-following — use it whole. Clipping a
                # sinuous line to the corridor only fragments it.
                line = supplied_cl[supplied_cl["Reach_Name"] == reach].union_all()
            else:
                line = supplied_cl.clip(poly_row.geometry).union_all()
            if line.geom_type == "MultiLineString":
                line = max(line.geoms, key=lambda g: g.length)  # keep the main stem
        else:
            line = cl.polygon_to_centerline(poly_row.geometry)
        print(f"  centerline length: {line.length/1000:.1f} km")

        tx = tr.generate_transects(line, epsg, spacing=args.spacing,
                                   half_width=args.half_width)
        print(f"  {len(tx)} transects @ {args.spacing:.0f} m spacing")

        samples, n_nodata = tr.sample_dem_along_transects(
            tx, args.raster, step=args.step, geoid_offset=args.geoid_offset)
        samples.insert(0, "Reach_Name", reach)
        print(f"  {len(samples)} sample points ({n_nodata} nodata)")

        tx = tx.assign(Reach_Name=reach)
        all_samples.append(samples)
        all_transects.append(tx)
        all_centerlines.append(gpd.GeoDataFrame(
            {"Reach_Name": [reach]}, geometry=[line], crs=epsg))

    os.makedirs(OUT_DIR, exist_ok=True)
    samples_df = pd.concat(all_samples, ignore_index=True)
    parquet_path = os.path.join(OUT_DIR, "transect_elevations.parquet")
    samples_df.to_parquet(parquet_path, index=False)
    print(f"\nWrote {len(samples_df)} rows -> {parquet_path}")

    # QC geometries (one file, layered) so we can eyeball transect placement on a map.
    gpkg = os.path.join(OUT_DIR, "transects.gpkg")
    pd.concat(all_transects, ignore_index=True).to_file(gpkg, layer="transects", driver="GPKG")
    pd.concat(all_centerlines, ignore_index=True).to_file(gpkg, layer="centerlines", driver="GPKG")
    print(f"Wrote QC geometries -> {gpkg} (layers: transects, centerlines)")


if __name__ == "__main__":
    main()
