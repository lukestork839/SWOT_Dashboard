import ee
import geopandas as gpd
import pandas as pd
import numpy as np
import rasterio
from rasterio.mask import mask as rio_mask
from scipy.interpolate import LinearNDInterpolator
import requests
import os
import glob
import tempfile

# --- CONFIGURATION ---
POLYGON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "river_poly.zip")
OUTPUT_DIR = "batch_outputs"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "dem_river_elevations.parquet")
TIFF_FILE = os.path.join(OUTPUT_DIR, "arcticdem_rivers.tif")

# Export resolution in meters
# 10m gives good detail while keeping file size manageable
EXPORT_RESOLUTION = 10

# Confluence anchor point (same as SWOT_Pull.py)
ANCHOR_LAT = 59.82463509
ANCHOR_LON = -161.33397834

# River name mapping (matches SWOT_Pull.py)
NAME_MAPPING = {
    1: "Uyak_Creek",
    2: "Kanektok_River"
}


def haversine_vectorized(lat1, lon1, lat2, lon2):
    """Distance (km) from each point to the anchor. Matches SWOT_Pull.py."""
    R = 6371.0
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2)**2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2)**2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def export_dem_from_gee(gdf):
    """Export ArcticDEM clipped to river polygon extent as a GeoTIFF via GEE."""
    if os.path.exists(TIFF_FILE):
        print(f"GeoTIFF already exists at {TIFF_FILE}, skipping download")
        return

    print("Initializing Earth Engine...")
    ee.Initialize(project="lukes-swot-project")

    # Build EE geometry from polygon bounds (with small buffer)
    bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
    buffer_deg = 0.005  # ~500m buffer
    region = ee.Geometry.Rectangle([
        bounds[0] - buffer_deg, bounds[1] - buffer_deg,
        bounds[2] + buffer_deg, bounds[3] + buffer_deg
    ])

    dem = ee.Image("UMN/PGC/ArcticDEM/V4/2m_mosaic").select("elevation")
    print("Requesting download URL from Earth Engine...")

    url = dem.getDownloadURL({
        "region": region,
        "scale": EXPORT_RESOLUTION,
        "format": "GEO_TIFF",
        "crs": "EPSG:4326",
    })

    print(f"Downloading ArcticDEM at {EXPORT_RESOLUTION}m resolution...")
    response = requests.get(url, stream=True)
    response.raise_for_status()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Download to temp file first, then move (resumable pattern)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".tif", dir=OUTPUT_DIR) as tmp:
        total = 0
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            tmp.write(chunk)
            total += len(chunk)
            print(f"\r  Downloaded {total / 1024 / 1024:.1f} MB", end="", flush=True)
        tmp_path = tmp.name

    os.rename(tmp_path, TIFF_FILE)
    print(f"\n  Saved to {TIFF_FILE}")


def sample_dem_within_polygons(gdf):
    """Read the GeoTIFF and extract elevation values within each river polygon."""
    print(f"\nSampling DEM within river polygons...")

    with rasterio.open(TIFF_FILE) as src:
        all_rows = []

        for _, row in gdf.iterrows():
            river_id = int(row["id"])
            river_name = NAME_MAPPING.get(river_id)
            if not river_name:
                continue

            # Mask raster to this polygon
            out_image, out_transform = rio_mask(src, [row.geometry], crop=True, nodata=np.nan)
            elev = out_image[0]  # single band

            # Get coordinates for each valid pixel
            rows_idx, cols_idx = np.where(~np.isnan(elev))
            if len(rows_idx) == 0:
                print(f"  {river_name}: no valid pixels")
                continue

            xs, ys = rasterio.transform.xy(out_transform, rows_idx, cols_idx)
            lons = np.array(xs)
            lats = np.array(ys)
            elevations = elev[rows_idx, cols_idx]

            df_river = pd.DataFrame({
                "Reach_Name": river_name,
                "latitude": lats,
                "longitude": lons,
                "wse": elevations,
            })
            all_rows.append(df_river)
            print(f"  {river_name}: {len(df_river)} pixels")

    df = pd.concat(all_rows, ignore_index=True)
    return df


def build_geoid_interpolator():
    """Build a geoid undulation interpolator from SWOT CSV data.

    SWOT data contains per-pixel EGM2008 geoid values. We use these to
    create a spatial interpolator so we can convert ArcticDEM ellipsoidal
    heights to orthometric heights matching SWOT's vertical datum.
    """
    csv_pattern = os.path.join(OUTPUT_DIR, "data", "*.csv")
    csv_files = sorted(glob.glob(csv_pattern))
    if not csv_files:
        print("  WARNING: No SWOT CSVs found — using constant geoid offset (13.46 m)")
        return None

    # Sample a subset of CSVs for efficiency
    sample_files = csv_files[::max(1, len(csv_files) // 10)]
    chunks = []
    for f in sample_files:
        df = pd.read_csv(f, usecols=["latitude", "longitude", "geoid"])
        chunks.append(df)
    geoid_df = pd.concat(chunks, ignore_index=True).dropna()

    # Bin to ~0.005 degree grid to reduce points for interpolation
    geoid_df["lat_bin"] = (geoid_df["latitude"] / 0.005).round() * 0.005
    geoid_df["lon_bin"] = (geoid_df["longitude"] / 0.005).round() * 0.005
    geoid_grid = geoid_df.groupby(["lat_bin", "lon_bin"])["geoid"].mean().reset_index()

    interp = LinearNDInterpolator(
        list(zip(geoid_grid["lat_bin"], geoid_grid["lon_bin"])),
        geoid_grid["geoid"].values
    )
    print(f"  Built geoid interpolator from {len(geoid_grid)} grid points "
          f"(geoid range: {geoid_grid['geoid'].min():.2f}–{geoid_grid['geoid'].max():.2f} m)")
    return interp


FALLBACK_GEOID = 13.46  # Mean geoid undulation for study area (m)


def process_dataframe(df):
    """Add distance from anchor, apply geoid correction, and sort."""
    df["dist_km"] = haversine_vectorized(
        df["latitude"].values, df["longitude"].values,
        ANCHOR_LAT, ANCHOR_LON
    )

    # Convert ellipsoidal heights to orthometric (matching SWOT datum)
    print("\nApplying geoid correction (WGS84 ellipsoidal → EGM2008 orthometric)...")
    geoid_interp = build_geoid_interpolator()
    if geoid_interp is not None:
        geoid_values = geoid_interp(df["latitude"].values, df["longitude"].values)
        # Fall back to constant for points outside interpolation hull
        nan_mask = np.isnan(geoid_values)
        if nan_mask.any():
            geoid_values[nan_mask] = FALLBACK_GEOID
            print(f"  {nan_mask.sum()} points outside SWOT coverage, used fallback ({FALLBACK_GEOID} m)")
        df["wse"] = df["wse"] - geoid_values
        print(f"  Subtracted geoid (mean: {np.nanmean(geoid_values):.2f} m)")
    else:
        df["wse"] = df["wse"] - FALLBACK_GEOID
        print(f"  Subtracted constant geoid offset: {FALLBACK_GEOID} m")

    df = df[["Reach_Name", "dist_km", "wse", "latitude", "longitude"]].copy()
    df = df.sort_values(["Reach_Name", "dist_km"]).reset_index(drop=True)
    return df


def main():
    print("=== ArcticDEM River Elevation Extraction ===\n")

    # Load river polygons
    gdf = gpd.read_file(POLYGON_PATH)
    print(f"Loaded {len(gdf)} river polygons from {POLYGON_PATH}")

    # Step 1: Export DEM from GEE (skips if already downloaded)
    export_dem_from_gee(gdf)

    # Step 2: Sample elevations within river polygons locally
    df = sample_dem_within_polygons(gdf)
    df = process_dataframe(df)

    print(f"\nResults: {len(df)} points")
    for name, group in df.groupby("Reach_Name"):
        print(f"  {name}: {len(group)} points, "
              f"dist {group['dist_km'].min():.1f}-{group['dist_km'].max():.1f} km, "
              f"elev {group['wse'].min():.1f}-{group['wse'].max():.1f} m")

    # Save
    df.to_parquet(OUTPUT_FILE, index=False)
    print(f"\nSaved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
