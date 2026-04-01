import earthaccess
import xarray as xr
import pandas as pd
import geopandas as gpd
import numpy as np
import matplotlib.pyplot as plt
from scipy import stats
from tqdm import tqdm
import os
import shutil
import warnings
import sys
import glob
import math

# --- CONFIGURATION ---
OUTPUT_BASE = "batch_outputs"
TEMP_DIR = "temp_swot_batch"
POLYGON_PATH = "/home/luke/University/SWOT/river_poly.zip"

DEFAULT_CLASSES = [3,4]

# PIXC quality flag filtering (cross-track distance in meters)
CROSS_TRACK_MIN = 10000   # 10 km from nadir (avoid nadir gap)
CROSS_TRACK_MAX = 60000   # 60 km from nadir (avoid far-swath noise)

# Crossover calibration quality filter (bit masks for geolocation_qual)
XOVERCAL_SUSPECT_MASK = 64        # Bit 6: crossover calibration suspect
XOVERCAL_MISSING_MASK = 8388608   # Bit 23: crossover calibration missing entirely

# MAD-based outlier filtering configuration
MAD_THRESHOLD = 3.5  # Conservative threshold (Iglewicz & Hoaglin, 1993)
MIN_POINTS_FOR_MAD = 10  # Minimum sample size for reliable MAD
MIN_POINTS_AFTER_FILTER = 5  # Ensure statistical validity for slope calc

# Optimization settings
KEEP_COLUMNS = [
    'Reach_Name', 'Pass_Date', 'dist_km', 'wse',
    'latitude', 'longitude', 'slope_calc', 'height_uncertainty', 'classification',
    'height_raw', 'geoid', 'solid_tide', 'pole_tide', 'load_tide'
]
ROWS_PER_CHUNK = 100000  # Safe chunk size for dashboard loading

# --- 📍 THE CONFLUENCE ANCHOR ---
# 59.826973° N, 161.372337° W
# All distances will be measured as a straight line from this point.
ANCHOR_LAT = 59.826973
ANCHOR_LON = -161.372337

# --- NAME MAPPING ---
NAME_MAPPING = {
    1: "Uyak_Creek",
    2: "Kanektok_River"
}

# Suppress warnings
warnings.filterwarnings("ignore")

def setup_dirs():
    subdirs = ["graphs", "data", "geopackages"]
    for sd in subdirs:
        os.makedirs(os.path.join(OUTPUT_BASE, sd), exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)

def normalize_longitude(lon_array):
    if np.any(lon_array > 180):
        return ((lon_array + 180) % 360) - 180
    return lon_array

def haversine_vectorized(lat1, lon1, lat2, lon2):
    """
    Calculates true surface distance (km) between data points and the Anchor.
    """
    R = 6371.0  # Earth radius in km

    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)

    a = np.sin(dphi / 2)**2 + \
        np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2)**2

    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))

    return R * c

def calculate_mad_outliers(wse_values, threshold=MAD_THRESHOLD):
    """
    Identify outliers using Modified Z-Score (MAD-based).

    Reference: Iglewicz & Hoaglin (1993) "How to Detect and Handle Outliers"

    Args:
        wse_values: Array of WSE measurements (per-reach)
        threshold: Modified Z-score threshold (default 3.5)

    Returns:
        Boolean mask (True = keep, False = outlier)
    """
    median = np.median(wse_values)
    mad = np.median(np.abs(wse_values - median))

    # Edge case: MAD = 0 (all values identical)
    if mad == 0:
        return np.ones(len(wse_values), dtype=bool)  # Keep all

    # Modified Z-score (0.6745 makes MAD consistent with std dev)
    modified_z_scores = 0.6745 * (wse_values - median) / mad

    # Keep points within threshold
    return np.abs(modified_z_scores) <= threshold

def load_polygons():
    print(f"\n📂 Loading polygons from: {POLYGON_PATH}")
    if os.path.exists(POLYGON_PATH):
        try:
            gdf = gpd.read_file(POLYGON_PATH)
            if gdf.crs and gdf.crs.to_string() != "EPSG:4326":
                print("   ⚠️ Re-projecting to EPSG:4326...")
                gdf = gdf.to_crs("EPSG:4326")
            print(f"   ✅ Loaded {len(gdf)} polygons.")
            return gdf
        except Exception as e:
            print(f"❌ Error reading file: {e}")
            sys.exit(1)
    else:
        print(f"❌ File not found at: {POLYGON_PATH}")
        sys.exit(1)

def get_granule_name(granule):
    meta = granule.get("meta", {})
    if "producer-granule-id" in meta: return meta["producer-granule-id"]
    if "native-id" in meta: return meta["native-id"]
    return "Unknown_Granule"

def extract_date_from_granule(granule):
    """Extract formatted date (YYYY-MM-DD) from granule metadata without downloading."""
    granule_name = get_granule_name(granule)
    try:
        parts = granule_name.split("_")
        for part in parts:
            if "T" in part and len(part) == 15 and part[:8].isdigit():
                date_str = part.split("T")[0]
                return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    except:
        pass
    return None

def is_date_already_processed(formatted_date):
    """Check if a daily CSV already exists for this date."""
    csv_path = os.path.join(OUTPUT_BASE, "data", f"{formatted_date}_data.csv")
    return os.path.exists(csv_path)

def resolve_poly_name(row, idx):
    if 'name' in row: raw_id = row['name']
    elif 'id' in row: raw_id = row['id']
    else: raw_id = idx + 1

    if raw_id in NAME_MAPPING: return NAME_MAPPING[raw_id]
    try:
        if int(raw_id) in NAME_MAPPING: return NAME_MAPPING[int(raw_id)]
    except: pass
    return str(raw_id)

def process_granule(granule_result, gdf_polygons):
    granule_name = get_granule_name(granule_result)
    
    try:
        parts = granule_name.split("_")
        raw_timestamp = "UnknownDate"
        for part in parts:
            if "T" in part and len(part) == 15 and part[:8].isdigit():
                raw_timestamp = part
                break
        
        if raw_timestamp != "UnknownDate":
            date_str = raw_timestamp.split("T")[0]
            formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        else:
            formatted_date = "Unknown_Date"
    except:
        formatted_date = "Unknown_Date"
    
    try:
        files = earthaccess.download(granule_result, TEMP_DIR)
        if not files: return None
        local_path = files[0]
        
        all_data = [] 
        
        with xr.open_dataset(local_path, group='pixel_cloud', engine='netcdf4') as ds:
            lat = ds['latitude'].values
            lon = normalize_longitude(ds['longitude'].values)
            
            for idx, row in gdf_polygons.iterrows():
                poly_name = resolve_poly_name(row, idx)
                bounds = row.geometry.bounds
                
                mask_rough = (
                    (lon >= bounds[0]-0.02) & (lon <= bounds[2]+0.02) &
                    (lat >= bounds[1]-0.02) & (lat <= bounds[3]+0.02)
                )
                if np.sum(mask_rough) == 0: continue 

                df = pd.DataFrame({
                    'latitude': lat[mask_rough], 'longitude': lon[mask_rough],
                    'height_raw': ds['height'].values[mask_rough],
                    'classification': ds['classification'].values[mask_rough],
                    'geoid': ds['geoid'].values[mask_rough],
                    'solid_tide': ds['solid_earth_tide'].values[mask_rough],
                    'pole_tide': ds['pole_tide'].values[mask_rough],
                    'load_tide': ds['load_tide_fes'].values[mask_rough] if 'load_tide_fes' in ds else
                                 (ds['load_tide_height'].values[mask_rough] if 'load_tide_height' in ds else 0),
                    'height_uncertainty': ds['height_uncert'].values[mask_rough] if 'height_uncert' in ds else np.nan,
                    # PIXC quality flags (for filtering, not exported)
                    'geolocation_qual': ds['geolocation_qual'].values[mask_rough] if 'geolocation_qual' in ds else np.nan,
                    'classification_qual': ds['classification_qual'].values[mask_rough] if 'classification_qual' in ds else np.nan,
                    'cross_track': ds['cross_track'].values[mask_rough] if 'cross_track' in ds else np.nan,
                    'height_cor_xover_qual': ds['height_cor_xover_qual'].values[mask_rough] if 'height_cor_xover_qual' in ds else np.nan,
                })

                gdf_temp = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.longitude, df.latitude), crs="EPSG:4326")
                df_exact = gdf_temp[gdf_temp.geometry.within(row.geometry)].copy()
                
                if len(df_exact) == 0: continue

                # Calculate WSE
                df_exact['wse'] = df_exact['height_raw'] - df_exact['geoid'] - df_exact['solid_tide'] - df_exact['pole_tide'] - df_exact['load_tide']
                df_exact['Reach_Name'] = poly_name
                df_exact['Pass_Date'] = formatted_date 
                
                # --- 📏 UNIFIED DISTANCE CALCULATION ---
                # Calculate straight-line distance from the Professor's Anchor Point
                df_exact['dist_km'] = haversine_vectorized(
                    df_exact['latitude'].values, 
                    df_exact['longitude'].values, 
                    ANCHOR_LAT, 
                    ANCHOR_LON
                )

                # --- PIXC Quality Flag Filtering ---
                # Filter order: cross-track → crossover_cal → classification → MAD
                # Rationale: Remove pixels with poor geometry/calibration before science filters
                n_before = len(df_exact)

                # Cross-track distance filter (avoid nadir gap and far-swath noise)
                if 'cross_track' in df_exact.columns and df_exact['cross_track'].notna().any():
                    ct_mask = (np.abs(df_exact['cross_track']) >= CROSS_TRACK_MIN) & (np.abs(df_exact['cross_track']) <= CROSS_TRACK_MAX)
                    n_pass = ct_mask.sum()
                    tqdm.write(f"   Quality Filter: {n_pass:,}/{len(df_exact):,} points passed cross_track ({CROSS_TRACK_MIN/1000:.0f}-{CROSS_TRACK_MAX/1000:.0f}km)")
                    df_exact = df_exact[ct_mask]

                # Crossover calibration quality filter
                # Exclude pixels where crossover calibration is MISSING (bit 23 of geolocation_qual)
                # This correction removes meter-scale roll/phase errors — without it, WSE is unreliable
                # Width-independent: affects both rivers equally, should not reduce data significantly
                # Reference: SWOT Handbook Section 9.4.2
                if 'geolocation_qual' in df_exact.columns and df_exact['geolocation_qual'].notna().any():
                    xover_mask = (df_exact['geolocation_qual'].astype(int) & XOVERCAL_MISSING_MASK) == 0
                    n_pass = xover_mask.sum()
                    tqdm.write(f"   Quality Filter: {n_pass:,}/{len(df_exact):,} points passed xovercal (crossover cal not missing)")
                    df_exact = df_exact[xover_mask]

                # NOTE: geolocation_qual and classification_qual filters DISABLED
                # These bit-flag filters are too aggressive for narrow rivers like Uyak Creek,
                # removing nearly all pixels in the middle section (5-25km).
                # Awaiting SWOT expert guidance on which specific bits to exclude.
                # The cross-track, classification, and MAD filters provide sufficient quality control.
                # TODO: Re-enable with targeted bit-mask filtering after expert consultation

                if len(df_exact) == 0: continue

                # Classification filtering (SWOT quality classes)
                df_final = df_exact[df_exact['classification'].isin(DEFAULT_CLASSES)]

                # MAD-based outlier filtering (per-reach)
                # Purpose: Remove anomalous WSE values (plateau artifacts, bad measurements)
                # Applied per-reach to account for different elevation ranges
                if len(df_final) >= MIN_POINTS_FOR_MAD:
                    for reach_name in df_final['Reach_Name'].unique():
                        reach_mask = df_final['Reach_Name'] == reach_name
                        reach_wse = df_final.loc[reach_mask, 'wse'].values

                        if len(reach_wse) >= MIN_POINTS_FOR_MAD:
                            # Calculate outlier mask
                            keep_mask = calculate_mad_outliers(reach_wse, threshold=MAD_THRESHOLD)
                            outliers_removed = (~keep_mask).sum()

                            # Safety check: preserve minimum points
                            if keep_mask.sum() >= MIN_POINTS_AFTER_FILTER:
                                # Apply filter
                                reach_indices = df_final[reach_mask].index
                                indices_to_remove = reach_indices[~keep_mask]
                                df_final = df_final.drop(indices_to_remove)

                                # Log statistics
                                pct_removed = (outliers_removed / len(reach_wse)) * 100
                                tqdm.write(f"   MAD Filter ({reach_name}): {outliers_removed}/{len(reach_wse)} outliers removed ({pct_removed:.1f}%)")
                            else:
                                tqdm.write(f"   MAD Filter ({reach_name}): Skipped (would remove too many points)")

                if len(df_final) > 5:
                    all_data.append(df_final)

        if all_data:
            full_df = pd.concat(all_data, ignore_index=True)
            
            # Recalculate Slope for Export
            for reach_name in full_df['Reach_Name'].unique():
                subset = full_df[full_df['Reach_Name'] == reach_name]
                if len(subset) > 5:
                    slope, _, _, _, _ = stats.linregress(subset['dist_km'], subset['wse'])
                    full_df.loc[subset.index, 'slope_calc'] = slope * 100
            
            # Save CSV
            cols_export = ['Reach_Name', 'Pass_Date', 'latitude', 'longitude', 'wse', 'dist_km', 'slope_calc', 'height_uncertainty', 'classification', 'height_raw', 'geoid', 'solid_tide', 'pole_tide', 'load_tide']
            final_cols = [c for c in cols_export if c in full_df.columns]
            full_df[final_cols].to_csv(os.path.join(OUTPUT_BASE, "data", f"{formatted_date}_data.csv"), index=False)

            tqdm.write(f"   ✅ {formatted_date}: Saved {len(full_df):,} points")
            return full_df
        else:
            return None

    except Exception as e:
        tqdm.write(f"   ❌ {formatted_date}: Failed - {e}")
        return None
    finally:
        if 'local_path' in locals() and os.path.exists(local_path):
            os.remove(local_path)

def rebuild_master_from_daily_csvs():
    """Rebuild master CSV/Parquet from all daily CSV files in batch_outputs/data/
    Includes automatic optimization: column pruning, dtype optimization, compression, and partitioning.
    """
    data_dir = os.path.join(OUTPUT_BASE, "data")
    csv_files = sorted([f for f in os.listdir(data_dir) if f.endswith("_data.csv")])

    if not csv_files:
        print("   ⚠️ No daily CSV files found to aggregate.")
        return

    print(f"\n📦 Rebuilding and optimizing master files from {len(csv_files)} daily CSVs...")
    all_dataframes = []

    for csv_file in tqdm(csv_files, desc="Aggregating CSVs", unit="file"):
        csv_path = os.path.join(data_dir, csv_file)
        try:
            df = pd.read_csv(csv_path)
            all_dataframes.append(df)
        except Exception as e:
            tqdm.write(f"   ⚠️ Warning: Could not read {csv_file}: {e}")

    if not all_dataframes:
        print("   ⚠️ No data to aggregate.")
        return

    final_df = pd.concat(all_dataframes, ignore_index=True)
    original_rows = len(final_df)

    # --- OPTIMIZATION STEP 1: Keep only necessary columns ---
    existing_cols = [c for c in KEEP_COLUMNS if c in final_df.columns]
    final_df = final_df[existing_cols]
    print(f"   📉 Pruned to essential columns: {existing_cols}")

    # --- OPTIMIZATION STEP 2: Optimize data types ---
    # Convert float64 to float32 (50% size reduction, ~1cm precision is plenty)
    float_cols = final_df.select_dtypes(include=['float64']).columns
    for col in float_cols:
        final_df[col] = final_df[col].astype('float32')

    # Convert Reach_Name to category (stores string once instead of N times)
    if 'Reach_Name' in final_df.columns:
        final_df['Reach_Name'] = final_df['Reach_Name'].astype('category')

    print(f"   🔧 Optimized data types (float64→float32, categorical)")

    # --- SAVE MASTER CSV (unoptimized for compatibility) ---
    csv_path = os.path.join(OUTPUT_BASE, "master_all_data.csv")
    final_df.to_csv(csv_path, index=False)
    print(f"   ✅ Master CSV saved: {csv_path} ({original_rows:,} points)")

    # --- SAVE MASTER PARQUET (single file, optimized) ---
    parquet_path = os.path.join(OUTPUT_BASE, "master_all_data.parquet")
    final_df.to_parquet(parquet_path, index=False, compression='zstd')
    print(f"   ✅ Master Parquet saved: {parquet_path}")

    # --- OPTIMIZATION STEP 3: Create partitioned Parquet files for dashboard ---
    # Split into chunks for better dashboard performance and GitHub size limits
    num_chunks = math.ceil(original_rows / ROWS_PER_CHUNK)

    if num_chunks > 1:
        print(f"   ✂️  Creating {num_chunks} optimized partitions for dashboard...")

        # Clean old partitioned files
        for old_file in glob.glob(os.path.join(OUTPUT_BASE, "master_all_data_part_*.parquet")):
            os.remove(old_file)

        for i in tqdm(range(num_chunks), desc="Creating partitions", unit="partition"):
            start = i * ROWS_PER_CHUNK
            end = start + ROWS_PER_CHUNK
            chunk = final_df.iloc[start:end]

            out_name = os.path.join(OUTPUT_BASE, f"master_all_data_part_{i}.parquet")
            chunk.to_parquet(out_name, index=False, compression='zstd')

        print(f"   ✅ Created {num_chunks} optimized partition(s)")
    else:
        # Single partition for small datasets
        print(f"   📦 Dataset small enough for single partition")
        part_path = os.path.join(OUTPUT_BASE, "master_all_data_part_0.parquet")
        final_df.to_parquet(part_path, index=False, compression='zstd')
        print(f"   ✅ Created optimized partition: {part_path}")

    print(f"   🎉 Optimization complete! Dashboard-ready files created.")

def main():
    print("\n🌊 --- SWOT BATCH: CONFLUENCE ANCHOR (RESUMABLE) --- 🌊")
    setup_dirs()
    gdf_poly = load_polygons()

    print("\n📅 Date Selection")
    start_date = input("   Start Date (YYYY-MM-DD): ").strip()
    end_date = input("   End Date   (YYYY-MM-DD): ").strip()

    print("\n🔍 Searching NASA Earthdata...")
    auth = earthaccess.login()

    all_results = earthaccess.search_data(short_name="SWOT_L2_HR_PIXC_D", bounding_box=tuple(gdf_poly.total_bounds), temporal=(start_date, end_date))
    print(f"   Found {len(all_results)} potential passes (Version D).")

    if not all_results: return

    # Check for already-processed dates
    print("\n🔍 Checking for existing processed data...")
    skipped_count = 0
    processed_count = 0

    # Use tqdm progress bar for granule processing
    for granule in tqdm(all_results, desc="Processing granules", unit="granule"):
        # Extract date from granule metadata (without downloading)
        formatted_date = extract_date_from_granule(granule)

        if formatted_date and is_date_already_processed(formatted_date):
            tqdm.write(f"   ⏭️  Skipping {formatted_date} (already processed)")
            skipped_count += 1
            continue

        # Process granule (download + process)
        df_result = process_granule(granule, gdf_poly)
        if df_result is not None:
            processed_count += 1

    # Always rebuild master file from ALL daily CSVs (both old and new)
    print(f"\n📊 Summary: {processed_count} new, {skipped_count} skipped")
    rebuild_master_from_daily_csvs()

    print(f"\n✨ Batch Complete!")

if __name__ == "__main__":
    main()
