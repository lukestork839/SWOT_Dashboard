"""
Derive temporary channel centerlines from SWOT water-pixel points and write them to a
GeoPackage that build_transects.py can consume via --centerline.

SWOT pixels are classified water, so they sit on the actual channel — their per-distance
median trace follows the real river far better than the corridor-polygon medial axis. This
is a stopgap until a surveyed/coworker centerline arrives; the output format is identical,
so swapping sources is a one-line change.

Run:  python3 DEM_Transects/make_swot_centerline.py
      python3 DEM_Transects/make_swot_centerline.py --bin-km 0.2 --reach Kanektok_River
"""

from __future__ import annotations

import argparse
import os

import duckdb
import geopandas as gpd

import centerline as cl

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_SWOT = os.path.join(ROOT, "dashboard_data.parquet")
OUT = os.path.join(HERE, "outputs", "swot_centerlines.gpkg")
DEFAULT_EPSG = 32604  # WGS84 / UTM 4N (study area)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--swot", default=DEFAULT_SWOT, help="SWOT water-point parquet.")
    ap.add_argument("--epsg", type=int, default=DEFAULT_EPSG)
    ap.add_argument("--bin-km", type=float, default=0.2)
    ap.add_argument("--min-pts", type=int, default=20)
    ap.add_argument("--smooth-window", type=int, default=5)
    ap.add_argument("--reach", default=None, help="Limit to one Reach_Name (default: all).")
    args = ap.parse_args()

    con = duckdb.connect()
    reaches = con.execute(
        f"SELECT DISTINCT Reach_Name FROM read_parquet('{args.swot}') ORDER BY 1"
    ).fetchdf()["Reach_Name"].tolist()
    if args.reach:
        reaches = [r for r in reaches if r == args.reach]

    rows = []
    for reach in reaches:
        df = con.execute(f"""
            SELECT longitude, latitude, dist_km
            FROM read_parquet('{args.swot}')
            WHERE Reach_Name = ? AND classification IN (3, 4)
        """, [reach]).fetchdf()
        line = cl.points_to_centerline(
            df["longitude"], df["latitude"], df["dist_km"], args.epsg,
            bin_km=args.bin_km, min_pts=args.min_pts, smooth_window=args.smooth_window)
        rows.append({"Reach_Name": reach, "geometry": line})
        print(f"{reach}: {len(df):,} water pts -> centerline {line.length/1000:.1f} km")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    gpd.GeoDataFrame(rows, crs=args.epsg).to_file(OUT, driver="GPKG")
    print(f"\nWrote {OUT}")
    print(f"Next: python3 DEM_Transects/build_transects.py --centerline {OUT}")


if __name__ == "__main__":
    main()
