"""
Fetch native 2 m ArcticDEM for the river corridor, straight from PGC's public AWS
Open-Data bucket (no Earth Engine, no auth, no resampling).

Why this exists (vs DEM_Pull.py):
  DEM_Pull.py pulls ArcticDEM through Google Earth Engine's getDownloadURL, which caps
  a synchronous request at ~48 MB. That is fine at 10 m (~16 MB) but the corridor at 2 m
  is ~410 MB for the bounding box — ~9x over the cap — so the GEE path cannot deliver 2 m.

  PGC distributes the *native* 2 m mosaic as Cloud-Optimized GeoTIFFs on S3
  (s3://pgc-opendata-dems, also over HTTPS). We read ONLY the corridor window out of the
  covering tiles via GDAL /vsicurl range requests, so we never download the full tiles,
  and we keep the data in its native EPSG:3413 grid — no reprojection/resampling, which
  matters for resolving metre-scale alluvial-ridge crests.

Consumer: the DEM_Transects cross-section / avulsion pipeline. Point it at the output:
    python3 DEM_Transects/build_transects.py \
        --raster batch_outputs/arcticdem_rivers_2m.tif --step 2

The dashboard pipeline (DEM_Pull.py -> dem_river_elevations.parquet) is intentionally
left on 10 m: its longitudinal profile is binned at 0.5 km and would not benefit, and a
2 m parquet (~34 M points) would bloat the GitHub-release / DuckDB-httpfs path.

Run:  python3 DEM_2m_Pull.py
"""

from __future__ import annotations

import os

import geopandas as gpd
import numpy as np
import rasterio
import rasterio.errors
from rasterio.io import MemoryFile
from rasterio.merge import merge as rio_merge
from rasterio.windows import Window, from_bounds

# --- CONFIGURATION ---
HERE = os.path.dirname(os.path.abspath(__file__))
POLYGON_PATH = os.path.join(HERE, "river_poly.zip")
OUTPUT_DIR = os.path.join(HERE, "batch_outputs")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "arcticdem_rivers_2m.tif")

# PGC ArcticDEM v4.1 2 m mosaic, EPSG:3413. COGs are public over HTTPS (us-west-2).
PGC_BASE = ("https://pgc-opendata-dems.s3.us-west-2.amazonaws.com/"
            "arcticdem/mosaics/v4.1/2m")
MOSAIC_CRS = "EPSG:3413"

# Buffer the corridor before windowing so transects (default half-width 1500 m) stay on
# DEM coverage even where they extend beyond the river polygon.
BUFFER_M = 1600.0

# PGC mosaic tile grid (EPSG:3413), derived from the published STAC proj:bbox values.
# A subtile's lower-left corner is at:
#     x_min = X0_TILE + k * TILE_STEP_M ,  k = 2*(col-40) + (subcol-1)
#     y_min = Y0_TILE + m * TILE_STEP_M ,  m = 2*(row-8)  + (subrow-1)
# Each subtile spans TILE_SIZE_M (50 km + 200 m overlap). Inverting gives col/subcol etc.
TILE_STEP_M = 50000.0
TILE_SIZE_M = 50200.0
X0_TILE = -100100.0   # x_min of (col=40, subcol=1)
Y0_TILE = -3300100.0  # y_min of (row=8,  subrow=1)


def _tile_name(k: int, m: int) -> str:
    """Map grid indices (k in x, m in y) to a PGC subtile id 'RR_CC_subrow_subcol'."""
    col = 40 + (k // 2)
    subcol = (k % 2) + 1
    row = 8 + (m // 2)
    subrow = (m % 2) + 1
    return f"{row:02d}_{col:02d}_{subrow}_{subcol}"


def covering_subtiles(bounds_3413):
    """Yield (id, dem_url) for every 2 m subtile intersecting the buffered AOI bbox."""
    x0, y0, x1, y1 = bounds_3413
    k_lo = int(np.floor((x0 - X0_TILE - TILE_SIZE_M) / TILE_STEP_M)) + 1
    k_hi = int(np.floor((x1 - X0_TILE) / TILE_STEP_M))
    m_lo = int(np.floor((y0 - Y0_TILE - TILE_SIZE_M) / TILE_STEP_M)) + 1
    m_hi = int(np.floor((y1 - Y0_TILE) / TILE_STEP_M))
    for k in range(k_lo, k_hi + 1):
        for m in range(m_lo, m_hi + 1):
            name = _tile_name(k, m)
            supertile = "_".join(name.split("_")[:2])
            url = f"{PGC_BASE}/{supertile}/{name}_2m_v4.1_dem.tif"
            yield name, url


def fetch_2m_corridor():
    if os.path.exists(OUTPUT_FILE):
        print(f"2 m raster already exists at {OUTPUT_FILE}, skipping")
        return

    gdf = gpd.read_file(POLYGON_PATH)
    g3413 = gdf.to_crs(MOSAIC_CRS)
    x0, y0, x1, y1 = g3413.total_bounds
    aoi = (x0 - BUFFER_M, y0 - BUFFER_M, x1 + BUFFER_M, y1 + BUFFER_M)
    print(f"Corridor bbox (EPSG:3413, +{BUFFER_M:.0f} m buffer): "
          f"[{aoi[0]:.0f}, {aoi[1]:.0f}, {aoi[2]:.0f}, {aoi[3]:.0f}]")

    # GDAL env for anonymous, efficient COG range reads.
    env = rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                       CPL_VSIL_CURL_USE_HEAD="NO",
                       GDAL_HTTP_MAX_RETRY="3", GDAL_HTTP_RETRY_DELAY="2")

    datasets, profile, nodata = [], None, None
    with env:
        for name, url in covering_subtiles(aoi):
            vurl = f"/vsicurl/{url}"
            try:
                src = rasterio.open(vurl)
            except rasterio.errors.RasterioIOError:
                print(f"  {name}: not present in mosaic, skipping")
                continue
            # Window-read only the AOI intersection with this tile.
            wx0, wy0 = max(aoi[0], src.bounds.left), max(aoi[1], src.bounds.bottom)
            wx1, wy1 = min(aoi[2], src.bounds.right), min(aoi[3], src.bounds.top)
            if wx0 >= wx1 or wy0 >= wy1:
                src.close()
                continue
            # Snap the window to whole source pixels so the output grid stays exactly
            # phase-aligned with the native ArcticDEM grid (no sub-pixel shift, which
            # would bias ridge-crest positions). float bounds -> integer pixel window.
            win = from_bounds(wx0, wy0, wx1, wy1, src.transform)
            win = win.round_offsets(op="floor").round_lengths(op="ceil")
            win = win.intersection(Window(0, 0, src.width, src.height))
            arr = src.read(1, window=win)
            win_transform = src.window_transform(win)
            nodata = src.nodata if src.nodata is not None else -9999.0
            profile = src.profile
            print(f"  {name}: read window {arr.shape} from native 2 m COG")

            # Stage as an in-memory dataset so rasterio.merge can mosaic the windows.
            memfile = MemoryFile()
            mem = memfile.open(driver="GTiff", height=arr.shape[0], width=arr.shape[1],
                               count=1, dtype=arr.dtype, crs=src.crs,
                               transform=win_transform, nodata=nodata)
            mem.write(arr, 1)
            datasets.append((memfile, mem))
            src.close()

    if not datasets or profile is None:
        raise RuntimeError("No ArcticDEM 2 m tiles intersect the corridor.")

    mosaic, out_transform = rio_merge([m for _, m in datasets], nodata=nodata)
    for memfile, mem in datasets:
        mem.close()
        memfile.close()

    out_profile = profile.copy()
    out_profile.update(height=mosaic.shape[1], width=mosaic.shape[2],
                       transform=out_transform, count=1, nodata=nodata,
                       compress="deflate", predictor=3, tiled=True,
                       blockxsize=256, blockysize=256)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with rasterio.open(OUTPUT_FILE, "w", **out_profile) as dst:
        dst.write(mosaic[0], 1)

    valid = mosaic[0][mosaic[0] != nodata]
    print(f"\nSaved {OUTPUT_FILE}")
    print(f"  grid: {mosaic.shape[2]} x {mosaic.shape[1]} px @ 2 m, EPSG:3413")
    print(f"  valid pixels: {valid.size:,}  "
          f"elev (ellipsoidal) min/median/max: "
          f"{valid.min():.1f} / {np.median(valid):.1f} / {valid.max():.1f} m")


if __name__ == "__main__":
    fetch_2m_corridor()
