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
POLYGON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "river_poly.zip")

DEFAULT_CLASSES = [3,4]

# PIXC quality flag filtering (cross-track distance in meters)
CROSS_TRACK_MIN = 10000   # 10 km from nadir (avoid nadir gap)
CROSS_TRACK_MAX = 60000   # 60 km from nadir (avoid far-swath noise)

# Crossover calibration quality filter (bit masks for geolocation_qual)
XOVERCAL_SUSPECT_MASK = 64        # Bit 6: crossover calibration suspect
XOVERCAL_MISSING_MASK = 8388608   # Bit 23: crossover calibration missing entirely

# MAD-based outlier filtering configuration
# The filter runs on NODE-MEDIAN RESIDUALS, not raw WSE: the rivers carry
# ~66 m of real along-stream relief, so raw-domain MAD reads the profile
# itself as spread and amputates whole upstream reaches on dates where pixel
# density is downstream-weighted (code review 2026-08, critical finding).
# Subtracting each pixel's node-median WSE first removes all along-stream
# structure (linear or concave), leaving only within-node scatter to police.
MAD_THRESHOLD = 3.5  # Conservative threshold (Iglewicz & Hoaglin, 1993)
MIN_POINTS_FOR_MAD = 10  # Minimum sample size for reliable MAD
MIN_POINTS_AFTER_FILTER = 5  # Ensure statistical validity for slope calc
MAD_NODE_KM = 1.0  # residual reference profile node size (matches REFGRAD_NODE_KM)
MAD_MIN_NODE_PIXELS = 3  # sparse nodes borrow the nearest well-populated node's median

# Optimization settings
KEEP_COLUMNS = [
    'Reach_Name', 'Pass_Date', 'dist_km', 'wse',
    'latitude', 'longitude', 'height_uncertainty', 'classification',
    'height_raw', 'geoid', 'solid_tide', 'pole_tide', 'load_tide'
]
ROWS_PER_CHUNK = 100000  # Safe chunk size for dashboard loading

# --- QC EXCLUSIONS (single source of truth: qc_registry.py) ---
# ICE_SAFE_MONTHS: May-Oct ice-season hard line, applied at master rebuild.
# KNOWN_BAD_PASSES: documented per-date exclusion registry, same filter point.
# Both live in qc_registry.py so ingestion and thesis figures can never drift;
# see that module for the empirical calibration evidence.
from qc_registry import ICE_SAFE_MONTHS, KNOWN_BAD_PASSES

# --- REFERENCE GRADIENT (per-pass robust slope) ---
# Authoritative reach gradient. See SCIENTIFIC_METHODOLOGY.md ->
# "Reference Gradient (Per-Pass Robust Regression)". Computed at the end of every
# pull into reference_gradient_per_pass.parquet; the dashboard's Hydraulic Gradient
# tab reads it. Headline value = MEDIAN of per-pass Theil-Sen slopes over gated
# open-water passes, per river.
REFGRAD_NODE_KM = 1.0        # node bin size (pixels -> nodes), removes density bias
REFGRAD_MIN_NODES = 8        # need >= this many nodes to fit a per-pass slope
# Full-coverage gate: the rivers are concave (steep near the confluence, gentle toward
# the mouth), so a pass's slope depends on WHICH reach it images. To compare rivers
# fairly we keep only passes that image the full river: a long span AND a downstream
# start (so the steep near-confluence reach is always included). A pass that clips the
# steep end reports an artificially gentle slope. See SCIENTIFIC_METHODOLOGY.md.
REFGRAD_MIN_SPAN_KM = 30.0   # coverage gate: pass must span >= this (near the full ~35-36 km)
REFGRAD_MAX_START_KM = 3.0   # coverage gate: pass must start <= this (includes steep downstream reach)
REFGRAD_OPEN_WATER_MONTHS = ICE_SAFE_MONTHS  # May-Oct (ice-season hard line, see above)
REFGRAD_HIGH_FLOW_MONTHS = {5}     # May freshet
REFGRAD_LOW_FLOW_MONTHS = {7, 8}   # Jul-Aug baseflow
REFGRAD_OUTPUT = os.path.join(OUTPUT_BASE, "reference_gradient_per_pass.parquet")

# --- 📍 THE CONFLUENCE ANCHOR ---
# 59.82463509° N, 161.33397834° W
# All distances will be measured as a straight line from this point.
ANCHOR_LAT = 59.82463509
ANCHOR_LON = -161.33397834

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

def calculate_mad_outliers(values, threshold=MAD_THRESHOLD):
    """
    Identify outliers using Modified Z-Score (MAD-based).

    Reference: Iglewicz & Hoaglin (1993) "How to Detect and Handle Outliers"

    Args:
        values: Array to screen — per-reach node-median WSE residuals
                (see node_median_residuals), NOT raw WSE
        threshold: Modified Z-score threshold (default 3.5)

    Returns:
        Boolean mask (True = keep, False = outlier)
    """
    median = np.median(values)
    mad = np.median(np.abs(values - median))

    # Edge case: MAD = 0 (all values identical)
    if mad == 0:
        return np.ones(len(values), dtype=bool)  # Keep all

    # Modified Z-score (0.6745 makes MAD consistent with std dev)
    modified_z_scores = 0.6745 * (values - median) / mad

    # Keep points within threshold
    return np.abs(modified_z_scores) <= threshold

def node_median_residuals(dist_km, wse, node_km=MAD_NODE_KM, min_node_pixels=MAD_MIN_NODE_PIXELS):
    """Residual WSE after subtracting the per-node median profile.

    Bins pixels into node_km distance nodes (same node structure as the
    reference gradient) and subtracts each pixel's node-median WSE, so the
    outlier filter never sees the river's real along-stream relief — only
    within-node scatter.

    Pixels in sparse nodes (< min_node_pixels) would self-define their own
    median (residual ~0, shielding isolated artifacts), so they are
    referenced to the nearest well-populated node's median instead.

    Returns an array of residuals, or None if no node is well populated
    (caller should skip filtering and keep all points).
    """
    node = np.round(np.asarray(dist_km, dtype=float) / node_km) * node_km
    wse = np.asarray(wse, dtype=float)
    grp = pd.Series(wse).groupby(node)

    node_counts = grp.size()
    good = node_counts[node_counts >= min_node_pixels]
    if good.empty:
        return None

    reference = grp.transform("median").to_numpy()
    sparse = grp.transform("size").to_numpy() < min_node_pixels
    if sparse.any():
        good_pos = good.index.to_numpy(dtype=float)
        good_med = grp.median()[good.index].to_numpy(dtype=float)
        nearest = np.abs(node[sparse, None] - good_pos[None, :]).argmin(axis=1)
        reference[sparse] = good_med[nearest]

    return wse - reference

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

def extract_granule_ids(granule):
    """Extract (formatted_date, cycle, pass_num, tile) from the granule name
    without downloading.

    PIXC granule names embed cycle, pass, and tile as the three tokens before
    the start timestamp, e.g. SWOT_L2_HR_PIXC_001_293_261L_20230731T163944_...
    One overpass can be split across tile boundaries (sibling granules on the
    same date, e.g. pass 571 = 260L + 261L), so the date alone does NOT
    identify a granule. Returns Nones for fields that can't be parsed.
    """
    granule_name = get_granule_name(granule)
    parts = granule_name.split("_")
    for i, part in enumerate(parts):
        if "T" in part and len(part) == 15 and part[:8].isdigit():
            date_str = part.split("T")[0]
            formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
            if i >= 3:
                return formatted_date, parts[i - 3], parts[i - 2], parts[i - 1]
            return formatted_date, None, None, None
    return None, None, None, None

def granule_csv_stem(formatted_date, cycle, pass_num, tile):
    """Checkpoint filename stem for one granule.

    Granule-keyed ({date}_gCCC_PPP_TTT) so sibling tiles of the same pass each
    get their own checkpoint instead of colliding on the calendar date. Falls
    back to the bare date if cycle/pass/tile couldn't be parsed.
    """
    if cycle is None:
        return formatted_date
    return f"{formatted_date}_g{cycle}_{pass_num}_{tile}"

def is_granule_already_processed(stem):
    """Check if a checkpoint CSV already exists for this granule."""
    csv_path = os.path.join(OUTPUT_BASE, "data", f"{stem}_data.csv")
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
    formatted_date, cycle, pass_num, tile = extract_granule_ids(granule_result)
    if formatted_date is None:
        formatted_date = "Unknown_Date"
    csv_stem = granule_csv_stem(formatted_date, cycle, pass_num, tile)

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
                # Acquisition provenance (kept in daily CSVs; pruned from master
                # by KEEP_COLUMNS). Lets the rebuild verify that Pass_Date is a
                # valid per-pass key (no multi-pass dates at this site).
                df_exact['cycle'] = cycle
                df_exact['pass_num'] = pass_num
                df_exact['tile'] = tile

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
                    # NaN flags carry no evidence either way -> keep the pixel
                    # (fillna(0) leaves the missing-cal bit unset). A bare
                    # astype(int) raises on partial NaN, and the outer handler
                    # would silently discard the whole granule.
                    qual = df_exact['geolocation_qual'].fillna(0).astype('int64')
                    xover_mask = (qual & XOVERCAL_MISSING_MASK) == 0
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

                # MAD-based outlier filtering (per-reach, residual domain)
                # Purpose: Remove anomalous WSE values (plateau artifacts, bad measurements)
                # Modified Z-scores are computed on node-median residuals, never raw WSE:
                # raw-domain MAD reads the ~66 m of real along-stream relief as spread and
                # amputated whole upstream reaches on downstream-weighted dates.
                if len(df_final) >= MIN_POINTS_FOR_MAD:
                    for reach_name in df_final['Reach_Name'].unique():
                        reach_mask = df_final['Reach_Name'] == reach_name
                        reach_rows = df_final.loc[reach_mask]

                        if len(reach_rows) >= MIN_POINTS_FOR_MAD:
                            residuals = node_median_residuals(
                                reach_rows['dist_km'].values, reach_rows['wse'].values)
                            if residuals is None:
                                tqdm.write(f"   MAD Filter ({reach_name}): Skipped (no well-populated nodes)")
                                continue

                            # Calculate outlier mask
                            keep_mask = calculate_mad_outliers(residuals, threshold=MAD_THRESHOLD)
                            outliers_removed = (~keep_mask).sum()

                            # Safety check: preserve minimum points
                            if keep_mask.sum() >= MIN_POINTS_AFTER_FILTER:
                                # Apply filter
                                reach_indices = df_final[reach_mask].index
                                indices_to_remove = reach_indices[~keep_mask]
                                df_final = df_final.drop(indices_to_remove)

                                # Log statistics
                                pct_removed = (outliers_removed / len(reach_rows)) * 100
                                tqdm.write(f"   MAD Filter ({reach_name}): {outliers_removed}/{len(reach_rows)} outliers removed ({pct_removed:.1f}%)")
                            else:
                                tqdm.write(f"   MAD Filter ({reach_name}): Skipped (would remove too many points)")

                if len(df_final) > 5:
                    all_data.append(df_final)

        if all_data:
            full_df = pd.concat(all_data, ignore_index=True)

            # NOTE: the old per-granule pixel-OLS 'slope_calc' export was removed
            # 2026-08 (code review): raw-pixel OLS is density-biased (understated
            # both gradients, roughly doubled the inter-river contrast) and was
            # superseded by the per-pass Theil-Sen reference gradient. With
            # granule-keyed checkpoints it would also have become per-TILE.

            # Save per-granule checkpoint CSV (granule-keyed: sibling tiles of
            # the same pass must not overwrite each other)
            cols_export = ['Reach_Name', 'Pass_Date', 'cycle', 'pass_num', 'tile', 'latitude', 'longitude', 'wse', 'dist_km', 'height_uncertainty', 'classification', 'height_raw', 'geoid', 'solid_tide', 'pole_tide', 'load_tide']
            final_cols = [c for c in cols_export if c in full_df.columns]
            full_df[final_cols].to_csv(os.path.join(OUTPUT_BASE, "data", f"{csv_stem}_data.csv"), index=False)

            tqdm.write(f"   ✅ {csv_stem}: Saved {len(full_df):,} points")
            return full_df
        else:
            return None

    except Exception as e:
        tqdm.write(f"   ❌ {formatted_date}: Failed - {e}")
        return None
    finally:
        if 'local_path' in locals() and os.path.exists(local_path):
            os.remove(local_path)

def _refgrad_season(month):
    """Season label for a pass month."""
    if month in REFGRAD_HIGH_FLOW_MONTHS:
        return "high_flow"
    if month in REFGRAD_LOW_FLOW_MONTHS:
        return "low_flow"
    if month in REFGRAD_OPEN_WATER_MONTHS:
        return "open_other"
    return "ice"


def compute_reference_gradient(df=None):
    """Compute the per-pass robust (Theil-Sen) reach gradient and write the artifact.

    Method (see SCIENTIFIC_METHODOLOGY.md):
      1. Per (Reach_Name, Pass_Date): aggregate WSE to REFGRAD_NODE_KM nodes
         (median WSE per node) -- the pixels->nodes step, removes density bias.
      2. Fit one reach slope per pass with the Theil-Sen estimator (cm/km). OLS is
         also stored for the decomposition/comparison view.
      3. Emit one row per pass with >= REFGRAD_MIN_NODES nodes, tagged with coverage
         (span_km, lo_km, gated) and season. `gated` marks full-river passes only
         (span >= REFGRAD_MIN_SPAN_KM AND lo_km <= REFGRAD_MAX_START_KM), so every
         pass images the same full concave profile. The dashboard filters to gated
         open-water passes and reports the MEDIAN per-pass slope as the headline gradient.

    Args:
        df: optional in-memory dataframe (the rebuilt master). If None, reads the
            master parquet (or partitions) from disk -- lets this run standalone.
    """
    if df is None:
        master = os.path.join(OUTPUT_BASE, "master_all_data.parquet")
        if os.path.exists(master):
            df = pd.read_parquet(master, columns=["Reach_Name", "Pass_Date", "dist_km", "wse"])
        else:
            parts = sorted(glob.glob(os.path.join(OUTPUT_BASE, "master_all_data_part_*.parquet")))
            if not parts:
                print("   ⚠️ No master parquet found; cannot compute reference gradient.")
                return None
            df = pd.concat(
                [pd.read_parquet(p, columns=["Reach_Name", "Pass_Date", "dist_km", "wse"]) for p in parts],
                ignore_index=True,
            )

    df = df[["Reach_Name", "Pass_Date", "dist_km", "wse"]].copy()
    df["Pass_Date"] = pd.to_datetime(df["Pass_Date"])
    df["month"] = df["Pass_Date"].dt.month

    rows = []
    for (reach, pdate), g in df.groupby(["Reach_Name", "Pass_Date"], observed=True):
        # pixels -> nodes: median WSE per REFGRAD_NODE_KM bin
        node = np.round(g["dist_km"].to_numpy() / REFGRAD_NODE_KM) * REFGRAD_NODE_KM
        nodes = pd.DataFrame({"node": node, "wse": g["wse"].to_numpy()}).groupby("node")["wse"].median()
        if len(nodes) < REFGRAD_MIN_NODES:
            continue
        x = nodes.index.to_numpy(dtype=float)
        y = nodes.to_numpy(dtype=float)
        span = float(x.max() - x.min())
        ts = stats.theilslopes(y, x)          # (slope, intercept, lo, hi) in m/km
        ols = stats.linregress(x, y)
        month = int(g["month"].iloc[0])
        rows.append({
            "Reach_Name": str(reach),
            "Pass_Date": pd.Timestamp(pdate).date(),
            "month": month,
            "season": _refgrad_season(month),
            "open_water": month in REFGRAD_OPEN_WATER_MONTHS,
            "n_nodes": int(len(x)),
            "n_pix": int(len(g)),
            "lo_km": float(x.min()),
            "hi_km": float(x.max()),
            "span_km": span,
            "theilsen_cm_km": float(ts[0] * 100.0),
            "ols_cm_km": float(ols.slope * 100.0),
            "ols_r2": float(ols.rvalue ** 2),
            "gated": span >= REFGRAD_MIN_SPAN_KM and float(x.min()) <= REFGRAD_MAX_START_KM,
        })

    if not rows:
        print("   ⚠️ No passes met the minimum-node requirement for reference gradient.")
        return None

    out = pd.DataFrame(rows)
    out.to_parquet(REFGRAD_OUTPUT, index=False)
    print(f"\n📏 Reference gradient artifact: {REFGRAD_OUTPUT} ({len(out)} passes)")
    ow = out[out["open_water"] & out["gated"]]
    for reach, grp in ow.groupby("Reach_Name", observed=True):
        med = grp["theilsen_cm_km"].abs().median()
        print(f"   {reach}: {med:.1f} cm/km (median of {len(grp)} full-coverage open-water passes)")
    return out


def rebuild_master_from_daily_csvs():
    """Rebuild master CSV/Parquet from all daily CSV files in batch_outputs/data/
    Includes automatic optimization: column pruning, dtype optimization, compression, and partitioning.
    """
    data_dir = os.path.join(OUTPUT_BASE, "data")
    csv_files = sorted([f for f in os.listdir(data_dir) if f.endswith("_data.csv")])

    if not csv_files:
        print("   ⚠️ No daily CSV files found to aggregate.")
        return

    # Guard against double-counting during the legacy -> granule-keyed
    # checkpoint migration: a legacy date-keyed CSV ({date}_data.csv) holds ONE
    # granule of that date, so if granule-keyed CSVs ({date}_gCCC_PPP_TTT_data.csv)
    # also exist for the same date, the granule-keyed set supersedes it.
    granule_keyed_dates = {f[:10] for f in csv_files if "_g" in f}
    superseded = [f for f in csv_files if "_g" not in f and f[:10] in granule_keyed_dates]
    if superseded:
        print(f"   ⚠️ Skipping {len(superseded)} legacy date-keyed CSV(s) superseded by granule-keyed checkpoints:")
        for f in superseded:
            print(f"      - {f}")
        csv_files = [f for f in csv_files if f not in set(superseded)]

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

    # Sanity check: everything downstream (reference gradient, temporal analysis,
    # dashboard) uses Pass_Date as the per-pass key. That is valid at this site
    # (CMR audit 2023-07..2026-08: zero dates with two distinct passes; co-dated
    # granules are always sibling tiles of ONE pass), but warn loudly if new data
    # ever breaks the assumption.
    if "pass_num" in final_df.columns:
        passes_per_date = final_df.dropna(subset=["pass_num"]).groupby("Pass_Date")["pass_num"].nunique()
        multi_pass_dates = passes_per_date[passes_per_date > 1]
        if len(multi_pass_dates):
            print(f"   🚨 {len(multi_pass_dates)} date(s) contain more than one SWOT pass — "
                  f"Pass_Date is NO LONGER a valid per-pass key: {list(multi_pass_dates.index)[:5]}")

    # --- QC: drop documented known-bad passes (provenance kept in daily CSVs) ---
    # Single filter point: master CSV/parquet, partitions, AND the reference-gradient
    # artifact (compute_reference_gradient receives final_df) all inherit the exclusion.
    if KNOWN_BAD_PASSES and "Pass_Date" in final_df.columns:
        bad = final_df["Pass_Date"].isin(KNOWN_BAD_PASSES)
        if bad.any():
            for d in sorted(KNOWN_BAD_PASSES):
                n = int((final_df["Pass_Date"] == d).sum())
                if n:
                    print(f"   🚫 Excluding known-bad pass {d}: {n:,} rows ({KNOWN_BAD_PASSES[d][:60]}…)")
            final_df = final_df[~bad].reset_index(drop=True)

    # --- QC: ice-season hard line (see ICE_SAFE_MONTHS) ---
    # Single filter point: master CSV/parquet, partitions, and the reference-
    # gradient artifact all inherit the cutoff. Daily CSVs keep all months.
    if ICE_SAFE_MONTHS and "Pass_Date" in final_df.columns:
        month = pd.to_datetime(final_df["Pass_Date"]).dt.month
        outside = ~month.isin(sorted(ICE_SAFE_MONTHS))
        if outside.any():
            n_dates = final_df.loc[outside, "Pass_Date"].nunique()
            print(f"   🧊 Ice-season hard line: excluding {int(outside.sum()):,} rows "
                  f"on {n_dates} dates outside months {sorted(ICE_SAFE_MONTHS)} (May-Oct)")
            final_df = final_df[~outside].reset_index(drop=True)

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

    # Clean ALL old partition files first: if the dataset shrank (e.g. QC
    # exclusions tightened), leftover higher-numbered partitions would silently
    # re-enter any consumer that globs master_all_data_part_*.parquet.
    for old_file in glob.glob(os.path.join(OUTPUT_BASE, "master_all_data_part_*.parquet")):
        os.remove(old_file)

    if num_chunks > 1:
        print(f"   ✂️  Creating {num_chunks} optimized partitions for dashboard...")

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

    # --- Reference gradient artifact (per-pass robust slope) ---
    compute_reference_gradient(final_df)

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
    ice_skipped_count = 0
    processed_count = 0

    # Use tqdm progress bar for granule processing
    for granule in tqdm(all_results, desc="Processing granules", unit="granule"):
        # Extract granule identity from metadata (without downloading).
        # Skip is keyed per GRANULE, not per date: one overpass can arrive as
        # multiple sibling tiles on the same date, and a date-keyed skip would
        # silently drop every tile after the first.
        formatted_date, cycle, pass_num, tile = extract_granule_ids(granule)

        if formatted_date:
            # Download scope = ICE_SAFE_MONTHS (decision 2026-08-14): only
            # May-Oct data can enter the analysis products, so ice-season
            # granules (~half the archive volume, ~146 GB) are not downloaded
            # at all. The rebuild-time hard line remains the enforcement point
            # for anything already on disk.
            month = int(formatted_date[5:7])
            if month not in ICE_SAFE_MONTHS:
                ice_skipped_count += 1
                continue

            stem = granule_csv_stem(formatted_date, cycle, pass_num, tile)
            if is_granule_already_processed(stem):
                tqdm.write(f"   ⏭️  Skipping {stem} (already processed)")
                skipped_count += 1
                continue

        # Process granule (download + process)
        df_result = process_granule(granule, gdf_poly)
        if df_result is not None:
            processed_count += 1

    # Always rebuild master file from ALL daily CSVs (both old and new)
    print(f"\n📊 Summary: {processed_count} new, {skipped_count} already processed, "
          f"{ice_skipped_count} outside May-Oct (not downloaded)")
    rebuild_master_from_daily_csvs()

    print(f"\n✨ Batch Complete!")

if __name__ == "__main__":
    main()
