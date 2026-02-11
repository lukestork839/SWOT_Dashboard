# SWOT River Dynamics Project - Technical Notes

**Last Updated**: 2026-02-10
**Status**: Active Development
**Primary Workflow**: Lugia.py → dashboard_lugia.py (optimization now integrated!)

---

## 1. Project Overview

### Scientific Context
Analyzing the gradient and water surface elevation (WSE) profiles of two merging rivers to understand their hydraulic dynamics at their confluence.

**Study Rivers:**
- **Kanektok River**: Main stem (Reach 2)
- **Uyak Creek**: Tributary (Reach 1)
- **Location**: Alaska

**Primary Goal**: Compare the steepness (slope) of both rivers as they approach their confluence.

**Key Challenge**: **Lateral Matching** - ensuring that a point "10km upstream" on the Kanektok aligns geographically with a point "10km upstream" on the Uyak Creek.

### Data Source
- **Satellite**: NASA SWOT
- **Product**: L2 HR PIXC (High-Resolution Pixel Cloud) Vector Data
- **Format**: NetCDF files
- **Access**: NASA Earthdata via `earthaccess` API

---

## 2. Core Methodologies

### Distance Calculation (The "Confluence Anchor" Method)
We use a **Fixed Confluence Anchor Point** as the reference for all distance measurements:

```
ANCHOR_LAT = 59.826973  # North
ANCHOR_LON = -161.372337  # West
```

**Key Details:**
- **Distance Metric**: Haversine (great-circle) distance from anchor point
- **X-Axis Direction**: REVERSED in dashboard visualization
  - Left Side: ~70 km (Coast/River Mouth)
  - Right Side: 0 km (Confluence/Anchor)
- **Why?**: Ensures both rivers are measured from a common "Zero" point where they physically meet, enabling direct comparison of hydraulic gradients

### Data Version Hierarchy
SWOT provides multiple data versions with different quality levels:

```
Version D (Provisional) + Version 2.0 (Validated)
```

**Rule**: Version 2.0 takes precedence. If both exist for the same date, V2.0 overwrites V_D to correct geolocation errors.

### Quality Filtering
**Classification Filter:**
- We strictly use **Class 4** (Good water detection) points only
- Defined in `DEFAULT_CLASSES = [4]` in Lugia.py

**Cross-Track Filter:**
- Generally filtered between 10km–60km to avoid:
  - Nadir gap (center swath)
  - Edge noise (far swath edges)
- Currently handled within query logic

**Spatial Clipping:**
- Data clipped using polygon boundaries from `river_poly.zip`
- Two-stage filtering:
  1. Rough bounding box filter (±0.02° buffer)
  2. Exact geometry matching with `.within()` operation

### Water Surface Elevation (WSE) Calculation
```python
wse = height_raw - geoid - solid_earth_tide - pole_tide - load_tide
```

**Components:**
- `height_raw`: Raw satellite measurement
- `geoid`: EGM2008 geoid correction
- `solid_earth_tide`: Solid Earth tide correction (IERS)
- `pole_tide`: Pole tide correction (IERS)
- `load_tide`: Load tide correction (FES2014)

### Gradient Calculation
```python
slope_calc = slope * 100  # Convert to cm/km
```
- Derived from linear regression: `stats.linregress(dist_km, wse)`
- Expressed in cm/km for scientific comparison
- Calculated per river reach

---

## 3. Current Architecture & Workflow

### Directory Structure (Updated 2026-02-10)
```
SWOT/
├── Lugia.py                    # Main data ingestion + optimization pipeline
├── dashboard_lugia.py          # Streamlit visualization dashboard
├── requirements.txt            # Python dependencies
├── river_poly.zip              # Polygon boundaries (2 reaches)
├── .swot_cli_config.json       # SWOT CLI configuration
├── batch_outputs/              # Processed data directory
│   ├── data/                   # Daily CSV files (YYYY-MM-DD_data.csv)
│   ├── geopackages/            # Spatial exports (not actively used)
│   ├── graphs/                 # Generated plots (not actively used)
│   ├── master_all_data.csv     # Combined dataset (CSV format)
│   ├── master_all_data.parquet # Optimized single parquet file
│   └── master_all_data_part_*.parquet  # Optimized partitions for dashboard
├── Claude/                     # Project documentation
│   └── Claude_notes.md         # This file
├── old_stuff/                  # Archive of deprecated code
│   ├── 2025/                   # Old 2025 versions
│   ├── optimize.py             # Now integrated into Lugia.py (2026-02-10)
│   ├── finish_job.py           # Post-processing utility
│   ├── split_parquet.py        # Parquet splitting utility
│   ├── profile_Polywhirl.py    # Legacy profiling script
│   ├── Dashboard_V1/           # Old dashboard version
│   ├── Streamlit/              # Old Streamlit version with .git
│   ├── Streamlit.zip           # Archive
│   └── temp_swot_batch/        # Old temp download directory
└── README.md                   # Project documentation
```

### Pipeline: Two-Stage Workflow (Streamlined 2026-02-10)

#### Stage 1: Data Ingestion (`Lugia.py`)
**Purpose**: Download and process raw SWOT satellite data

**Process:**
1. Authenticate with NASA Earthdata (`earthaccess.login()`)
2. Prompt user for date range (start/end dates)
3. Search for SWOT data:
   - `SWOT_L2_HR_PIXC_D` (Provisional)
   - `SWOT_L2_HR_PIXC_2.0` (Validated)
4. **Check for existing daily CSVs** (Resume capability)
   - Extract date from granule metadata without downloading
   - Skip granules with existing `YYYY-MM-DD_data.csv` files
   - Only download/process new or missing dates
5. Load polygon boundaries from `river_poly.zip`
6. For each granule (if not already processed):
   - Download NetCDF file to `temp_swot_batch/` (temporary)
   - Extract pixel cloud data from NetCDF
   - Normalize longitude (handle 180° meridian)
   - Apply rough bounding box filter (±0.02°)
   - Convert to GeoDataFrame and apply exact polygon clipping
   - Calculate WSE with geoid + tide corrections
   - Calculate distance from confluence anchor (Haversine)
   - Filter for Classes 3-7
   - Calculate slope per reach
   - Export daily CSV to `batch_outputs/data/`
   - Clean up temp NetCDF file
7. **Rebuild master files** from ALL daily CSVs (both old and new)
8. Create master CSV: `master_all_data.csv`
9. Create master Parquet: `master_all_data.parquet`

**Key Functions:**
- `haversine_vectorized()`: Calculates great-circle distance from anchor
- `normalize_longitude()`: Handles 180° meridian crossing
- `resolve_poly_name()`: Maps polygon IDs to river names
- `process_granule()`: Main processing logic per satellite pass
- `extract_date_from_granule()`: Extracts date from metadata without downloading
- `is_date_already_processed()`: Checks if daily CSV exists for a date
- `rebuild_master_from_daily_csvs()`: Aggregates all daily CSVs into master files

**Resumable Download Feature (Added 2026-02-10):**
- ✅ **Fault-tolerant**: Survives internet interruptions, power loss, crashes
- ✅ **Checkpoint system**: Each daily CSV acts as a save point
- ✅ **No redundant work**: Skips already-downloaded dates
- ✅ **Progress visibility**: Shows which dates are skipped vs. processed (with tqdm progress bars)
- ✅ **Always consistent**: Master file rebuilt from complete dataset each run

**Integrated Optimization (Added 2026-02-10):**
- ✅ **Automatic optimization**: No separate script needed
- ✅ **Data type optimization**: float64→float32 (50% size reduction)
- ✅ **Categorical encoding**: Reach_Name stored efficiently
- ✅ **Column pruning**: Keeps only dashboard-essential columns
- ✅ **Smart partitioning**: Splits into 100k-row chunks for dashboard performance
- ✅ **ZSTD compression**: Maximum compression for Parquet files

**Outputs:**
- `batch_outputs/data/YYYY-MM-DD_data.csv` (one per date - checkpoints)
- `batch_outputs/master_all_data.csv` (complete dataset, all columns)
- `batch_outputs/master_all_data.parquet` (optimized single file)
- `batch_outputs/master_all_data_part_*.parquet` (optimized partitions for dashboard)

#### Stage 2: Visualization (`dashboard_lugia.py`)
**Purpose**: Interactive Streamlit dashboard for data exploration

**Framework:**
- **Frontend**: Streamlit (web interface)
- **Backend**: DuckDB (in-memory SQL database)
- **Plotting**: Plotly (interactive charts)

**Key Features:**
1. **Date Range Slider**: Filter by satellite pass dates
2. **River Selection**: Analyze individual or both rivers
3. **Tabs**:
   - **Gradient Profile**: WSE vs distance scatter with trendlines
   - **Map View**: Geographic visualization (Mapbox)
   - **Raw Data**: Table view with CSV export

**Performance Optimizations:**
- **Systematic Sampling**: When points > 25,000
  - Takes every Nth point for visualization
  - Uses `row_number() OVER (ORDER BY Reach_Name, dist_km, Pass_Date)`
  - Prevents browser lag
- **Full Data Statistics**: Summary stats calculated on 100% of data
  - Separate SQL query for accuracy
  - Shown in table above plots

**Stability Features:**
- `st.form`: Prevents app crashes during slider drag
- User must click "Update Analysis" button to refresh
- Prevents continuous re-queries during interaction

**Visual Details:**
- **X-Axis**: Reversed (`autorange="reversed"`) to show Coast → Confluence
- **Colors**:
  - Kanektok River: `firebrick`
  - Uyak Creek: `dodgerblue`
- **Trendlines**: Dashed lines with slope displayed in legend

**Database Connection:**
```python
parquet_pattern = "batch_outputs/master_all_data_part_*.parquet"
con.execute(f"CREATE OR REPLACE VIEW river_data AS SELECT * FROM read_parquet('{parquet_pattern}')")
```

---

## 4. Key Variables & Data Schema

| Variable | Description | Units | Source |
|----------|-------------|-------|--------|
| `latitude` | Latitude coordinate | degrees | SWOT pixel_cloud |
| `longitude` | Longitude coordinate (normalized) | degrees | SWOT pixel_cloud |
| `height_raw` | Raw height measurement | meters | SWOT `height` |
| `classification` | Quality class (4 = good water) | integer | SWOT `classification` |
| `geoid` | Geoid correction (EGM2008) | meters | SWOT `geoid` |
| `solid_tide` | Solid Earth tide | meters | SWOT `solid_earth_tide` |
| `pole_tide` | Pole tide | meters | SWOT `pole_tide` |
| `load_tide` | Load tide (FES2014) | meters | SWOT `load_tide_fes` |
| `height_uncertainty` | Measurement uncertainty | meters | SWOT `height_uncert` |
| `wse` | **Water Surface Elevation** | meters | **Calculated** |
| `dist_km` | **Distance from confluence anchor** | kilometers | **Calculated** |
| `slope_calc` | **River gradient** | cm/km | **Calculated** |
| `Reach_Name` | River identifier | string | **Mapped** |
| `Pass_Date` | Satellite overpass date | YYYY-MM-DD | **Parsed** |

**Key Calculated Fields:**
```python
wse = height_raw - geoid - solid_tide - pole_tide - load_tide
dist_km = haversine(lat, lon, ANCHOR_LAT, ANCHOR_LON)
slope_calc = stats.linregress(dist_km, wse).slope * 100
```

---

## 5. Known Issues & Status

### Data Consistency Issue
**Problem**: Processing crash occurred halfway through a 2-year batch run.

**Current State:**
- **Part 1 (Jan 2024 - May 2024)**: Mixed/provisional data (contains Version D)
- **Part 2 (May 2024 - Present)**: Successfully processed with V2.0 priority

**Impact**: Part 1 may have geolocation errors from Version D data

**Resolution Plan**: Re-run Part 1 processing to force-upgrade to Version 2.0

**Update (2026-02-10)**: Now easier to reprocess with resumable download feature! Can safely re-run Jan-May 2024 without risk of interruption causing data loss.

### Distance Logic
**Status**: ✅ Complete and verified
- Confluence Anchor method fully implemented
- All data now uses consistent Haversine distance from anchor
- No more mixed distance calculation methods

---

## 6. Technical Stack

### Python Packages
```
earthaccess      # NASA Earthdata authentication & download
xarray           # NetCDF data reading
pandas           # Data manipulation
geopandas        # Spatial data operations
numpy            # Numerical operations
matplotlib       # Static plotting (legacy)
scipy            # Statistical analysis (linregress)
streamlit        # Web dashboard framework
plotly           # Interactive plotting
duckdb           # In-memory SQL database
```

### External Dependencies
- NASA Earthdata account (free at https://urs.earthdata.nasa.gov/)
- Python 3.8+
- Sufficient storage for NetCDF files (temporary, ~500MB each)

---

## 7. Name Mapping & Legacy Code

### River Naming Convention
```python
NAME_MAPPING = {
    1: "Uyak_Creek",
    2: "Kanektok_River"
}
```
- Defined in `Lugia.py` lines 27-30
- Maps polygon IDs from `river_poly.zip` to readable names

### Legacy Naming ("Polywhirl" Era)
**Historical Context**: Earlier versions used Pokemon-themed naming:
- "Polywhirl" = Old processing script
- "Lugia" = Current processing script (legendary upgrade!)

**Why Changed**: Professor preferred more systematic naming for production

**Archive Location**: All old "Polywhirl" code moved to `old_stuff/`

---

## 8. Professor Requirements & Preferences

### Confirmed Working Workflow
✅ **Current Best Practice** (Updated 2026-02-10):
1. Download and process data using `Lugia.py` (optimization now automatic!)
2. Display data using `dashboard_lugia.py` (Streamlit)

### Scientific Accuracy Priority
- Statistics must use 100% of data (not sampled)
- Visualization can be sampled for performance
- Slope calculations must be reproducible
- Distance measurements must be consistent across all dates

### Visualization Requirements
- X-axis MUST be reversed (Coast on left, Confluence on right)
- Colors must be consistent across all plots
- Both rivers must be comparable on same scale
- Trendlines must show absolute slope values (steepness)

---

## 9. Session History

### 2026-02-02: Directory Organization & Documentation
**Actions Taken:**
1. ✅ Cleaned up root directory structure
2. ✅ Moved deprecated files to `old_stuff/`:
   - `finish_job.py`, `split_parquet.py`, `profile_Polywhirl.py`
   - `Dashboard_V1/`, `Streamlit/`, `Streamlit.zip`
   - `temp_swot_batch/`
3. ✅ Created comprehensive `README.md`
4. ✅ Updated and reformatted this technical notes file

**Current Clean Structure (Updated 2026-02-10):**
- 2 active Python scripts (`Lugia.py`, `dashboard_lugia.py`)
- 1 requirements file (`requirements.txt`)
- 1 data directory (`batch_outputs/`)
- 1 configuration file (`.swot_cli_config.json`)
- 1 polygon boundary file (`river_poly.zip`)
- 1 documentation folder (`Claude/`)
- 1 archive folder (`old_stuff/`)

### 2026-02-10: Resumable Download Implementation
**Problem Addressed:**
- Download interruptions (internet loss, crashes) required starting from scratch
- No checkpoint system for long batch runs
- Redundant downloading of already-processed dates

**Actions Taken:**
1. ✅ Added `extract_date_from_granule()`: Extracts date from metadata without downloading
2. ✅ Added `is_date_already_processed()`: Checks for existing daily CSVs
3. ✅ Added `rebuild_master_from_daily_csvs()`: Aggregates all daily CSVs into master files
4. ✅ Modified main loop: Skips already-processed dates, shows progress
5. ✅ Updated documentation in Claude notes

**Benefits:**
- **Fault-tolerant**: Survives internet interruptions and crashes
- **Incremental progress**: Each daily CSV is a checkpoint
- **No wasted bandwidth**: Skips previously downloaded dates
- **Always consistent**: Master file rebuilt from complete dataset
- **Progress visibility**: Clear indication of skipped vs. processed dates

**Technical Details:**
- Daily CSVs now serve as checkpoint files
- Date extraction from granule metadata (no download needed for check)
- Master files rebuilt on every run from ALL daily CSVs
- Compatible with existing workflow (backward compatible)

### 2026-02-10: Integrated Optimization & Progress Bars
**Problem Addressed:**
- Separate `optimize.py` script was an extra manual step
- No visual feedback during long processing runs
- Missing dependency documentation

**Actions Taken:**
1. ✅ Created `requirements.txt` with all project dependencies
2. ✅ Added `tqdm` progress bars to Lugia.py for:
   - Granule processing loop (shows ETA and speed)
   - CSV aggregation during rebuild
   - Partition creation
3. ✅ Integrated all optimization logic from `optimize.py` into `rebuild_master_from_daily_csvs()`:
   - Column pruning (keep only dashboard-essential columns)
   - Data type optimization (float64→float32, categorical encoding)
   - ZSTD compression
   - Automatic partitioning (100k rows per chunk)
4. ✅ Moved `optimize.py` to `old_stuff/` (no longer needed)
5. ✅ Updated documentation to reflect streamlined 2-stage workflow

**Benefits:**
- **Simplified workflow**: Just run `Lugia.py` and you're done
- **Better UX**: Progress bars show completion status and time estimates
- **Always optimized**: Dashboard-ready files created automatically
- **No manual steps**: Can't forget to run optimization
- **Easy setup**: `pip install -r requirements.txt`

**Technical Details:**
- Optimization now runs as final step of `rebuild_master_from_daily_csvs()`
- Creates both unoptimized CSV (compatibility) and optimized Parquet partitions
- Uses same optimization strategy as old `optimize.py` but fully integrated
- Progress bars use `tqdm.write()` to prevent bar corruption

---

## 10. Quick Reference Commands

### Run Data Ingestion (with automatic optimization)
```bash
python Lugia.py
# Prompts for: Start Date (YYYY-MM-DD), End Date (YYYY-MM-DD)
# Automatically creates optimized parquet files ready for dashboard
```

### Launch Dashboard
```bash
streamlit run dashboard_lugia.py
```

### Check Data Size
```bash
ls -lh batch_outputs/*.parquet
ls -lh batch_outputs/*.csv
```

### Count Data Points
```bash
# If using DuckDB CLI:
duckdb -c "SELECT COUNT(*) FROM 'batch_outputs/master_all_data_part_*.parquet'"
```

---

## 11. Future Considerations

### Completed Improvements
- ✅ **Resumable downloads** (2026-02-10): Checkpoint system implemented
- ✅ **Progress bars** (2026-02-10): Added tqdm for better UX
- ✅ **Integrated optimization** (2026-02-10): No separate optimize.py needed
- ✅ **Requirements.txt** (2026-02-10): Dependency management

### Potential Improvements (Not Confirmed)
- Automate Version 2.0 priority checking
- Add height_uncertainty filtering thresholds
- Implement cross-track filtering in Lugia.py (currently in dashboard)
- Create automated re-processing script for Part 1 data
- Add data quality metrics dashboard
- Export high-resolution plots for publications

### Questions for User
- Python version requirements?
- Should create `requirements.txt`?
- GitHub integration needs (`.gitignore`)?
- Typical date range for analysis?
- Any additional professor requirements?

---

## 12. Important File Locations

### Configuration
- **Anchor Point**: `Lugia.py` lines 21-24
- **Name Mapping**: `Lugia.py` lines 27-30
- **Color Mapping**: `dashboard_lugia.py` lines 16-19
- **Max Plot Points**: `dashboard_lugia.py` line 13

### Data Paths
- **Polygon Boundaries**: `/home/luke/University/SWOT/river_poly.zip`
- **Output Directory**: `batch_outputs/`
- **Temp Downloads**: `temp_swot_batch/` (auto-created, then deleted)

### Critical Code Sections
- **Distance Calculation**: `Lugia.py` lines 46-61 (`haversine_vectorized`)
- **WSE Calculation**: `Lugia.py` line 157
- **Slope Calculation**: `Lugia.py` lines 180-184
- **Dashboard Sampling**: `dashboard_lugia.py` lines 98-117
- **X-Axis Reversal**: `dashboard_lugia.py` line 197

---

*End of Technical Notes*
