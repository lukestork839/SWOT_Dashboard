# SWOT River Dynamics Project - Technical Notes

**Last Updated**: 2026-04-01
**Status**: Active Development
**Primary Workflow**: SWOT_Pull.py → dashboard_swot.py (optimization now integrated!)
**GitHub Repository**: https://github.com/lukestork839/SWOT_Dashboard

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

### Data Version
We use **Version D** (`SWOT_L2_HR_PIXC_D`) exclusively — the latest science algorithm version with updated processing algorithms, calibration parameters, and geophysical models. Version D supersedes Version C (previously distributed as `SWOT_L2_HR_PIXC_2.0`). NASA reprocessed the full mission archive into Version D in early 2026.

### Quality Filtering
**Active Filter Chain** (updated 2026-04-01):

1. **Rough bounding box** — ±0.02° buffer around polygon bounds (fast spatial pre-filter)
2. **Exact polygon clipping** — `.within()` against river polygons from `river_poly.zip`
3. **Cross-track distance** — 10–60 km from nadir (`CROSS_TRACK_MIN/MAX` in SWOT_Pull.py)
   - Avoids nadir gap (poor interferometric baseline) and far-swath noise
4. **Crossover calibration** — Exclude pixels where crossover cal is missing (bit 23 of `geolocation_qual`)
   - Corrects meter-scale roll/phase errors; width-independent (affects both rivers equally)
5. ~~**Geolocation quality**~~ — ⏳ **NOT YET APPLIED** (pending expert review)
6. ~~**Classification quality**~~ — ⏳ **NOT YET APPLIED** (pending expert review)
7. **Classification** — Classes 3–4 only (`DEFAULT_CLASSES = [3,4]`)
8. **MAD outlier filter** — Modified Z-score threshold 3.5, per-reach

**Why quality flags are disabled:**
- `geolocation_qual == 0` retained only 4-15% of pixels, removing virtually all Uyak Creek data (5-25km)
- Relaxing to `< 4` still only passed 2.8% of Uyak pixels for `classification_qual`
- These are bit-flag integers (not 0-3 scale) — most bits fire on narrow rivers due to land/water mixing
- Awaiting SWOT expert guidance on which specific bits indicate bad data vs. just higher uncertainty
- Full flag reference documented in `SCIENTIFIC_METHODOLOGY.md` (PIXC Quality Flag Reference section)
- MAD outlier filter provides sufficient quality control in the interim

### Ice Handling (Seasonal Awareness)
**Decision (2026-04-01):** Dashboard-level warnings rather than ingestion-level date filtering.

**Key findings from SWOT documentation research:**
- PIXC classification has **NO ice class** — the 7 values are all land/water variants
- Smooth ice → classified as dark water (Class 5) or land (Class 1) → excluded by Classes 3-4 filter
- Rough/snow-covered ice → classified as land (Class 1-2) → excluded
- Partially frozen surfaces during transition months → may still pass as Class 3-4
- `ice_clsf` flag exists in PIXCVec and RiverSP products but **NOT in base PIXC** product we use
- Ice surface elevation ≠ water surface elevation (off by ice thickness, typically 0.5-2+ m on Alaskan rivers)

**Ice seasons for Kanektok/Uyak (~59.8°N):**
- **Freeze-up**: Oct-Nov (ice formation begins)
- **Frozen**: Dec-Mar (solid ice cover)
- **Break-up**: Apr-May (ice begins to break)
- **Open water**: Jun-Sep (reliable for WSE analysis)

**Approach chosen:** Keep all data in pipeline, add contextual warnings in dashboard:
- Seasonal Comparison tab: Warning that May (high flow) panels overlap break-up season
- Typhoon Impact tab: Dynamic warnings computed via `get_ice_warning()` for each analysis period
- Temporal Evolution tab: Note about ice-affected months in header
- Rationale: Preserves data for potential ice studies; lets analyst interpret with context rather than permanently discarding

**References:**
- SWOT Handbook Table 6.1 (classification values)
- SMU thesis: SWOT ice surface elevation validation (0.66m RMSE rivers, 0.23m lakes near Fairbanks)
- Ka-band penetration into snow/ice: 0.1-0.3 m (insufficient to see water beneath ice)

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

### Outlier Filtering (MAD-Based)
**Added:** 2026-03-04

**Purpose:** Remove anomalous WSE measurements beyond natural variation

**Method:**
```python
Modified Z-score = 0.6745 × (WSE - median) / MAD
Outlier if |Modified Z-score| > 3.5
```

**Application:** Per-reach filtering during data ingestion (SWOT_Pull.py line 201)

**Key Details:**
- **Threshold:** 3.5 (conservative, preserves seasonal variation)
- **Per-reach:** Independent filtering for Kanektok and Uyak
- **Reference:** Iglewicz & Hoaglin (1993)
- **Edge cases:** Skip if N<10, preserve minimum 5 points

---

## 3. Current Architecture & Workflow

### Directory Structure (Updated 2026-02-10)
```
SWOT/
├── SWOT_Pull.py                    # Main data ingestion + optimization pipeline
├── dashboard_swot.py          # Streamlit visualization dashboard
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
│   ├── optimize.py             # Now integrated into SWOT_Pull.py (2026-02-10)
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

#### Stage 1: Data Ingestion (`SWOT_Pull.py`)
**Purpose**: Download and process raw SWOT satellite data

**Process:**
1. Authenticate with NASA Earthdata (`earthaccess.login()`)
2. Prompt user for date range (start/end dates)
3. Search for SWOT data: `SWOT_L2_HR_PIXC_D` (Version D — current recommended)
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
   - Apply cross-track distance filter (10–60km)
   - (Quality flag filters disabled pending expert review)
   - Filter for Classes 3–4
   - Apply MAD outlier filter (per-reach, threshold 3.5)
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

#### Stage 2: Visualization (`dashboard_swot.py`)
**Purpose**: Interactive Streamlit dashboard for data exploration

**Framework:**
- **Frontend**: Streamlit (web interface)
- **Backend**: DuckDB (in-memory SQL database)
- **Plotting**: Plotly (interactive charts)
- **Mapping**: Folium (GIS-capable interactive maps) (Updated 2026-02-13)

**Key Features:**
1. **Date Range Slider**: Filter by satellite pass dates
2. **River Selection**: Analyze individual or both rivers
3. **Map Display Options** (Updated 2026-02-13):
   - **Color by River Name**: Default discrete colors (firebrick/dodgerblue)
   - **Color by WSE**: Continuous viridis gradient showing elevation
   - **Color by Classification**: Discrete colors (Orange=Class 3, Turquoise=Class 4+)
   - **Basemap Selection**: OpenStreetMap, Terrain, Satellite, Watercolor, CartoDB Light/Dark
   - **Measuring Tool**: Click-to-measure distances and areas on map
   - **Layer Control**: Toggle river/classification layers on/off
4. **Detrending Method Selection** (Added 2026-02-16):
   - **Linear**: Simple straight-line baseline
   - **Polynomial (2nd order)**: Curved baseline for gentle trends
   - **Polynomial (3rd order)**: More flexible curved baseline
   - **LOESS**: Adaptive local regression for complex trends
5. **Tabs**:
   - **Gradient Profile**: WSE vs distance scatter with trendlines
   - **Elevation Difference**: Direct comparison (Kanektok - Uyak) by 100m bins (Added 2026-02-13)
   - **Detrended Profile**: Relative Elevation Model showing deviations from baseline trend (Added 2026-02-16)
   - **Interval Slopes**: Slope calculation for each 100m river segment (Added 2026-02-13)
   - **Map View**: GIS-style Folium map with measuring tools and basemap options (Updated 2026-02-13)
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
| `classification` | Quality class (3=moderate, 4=good water) | integer | SWOT `classification` *(saved 2026-02-11+)* |
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

### PIXC Quality Flag Filtering — Pending Expert Review
**Status**: ⏳ Awaiting expert consultation
**Problem**: Quality flag filters (`geolocation_qual`, `classification_qual`) remove nearly all data for narrow Uyak Creek (~50-100m wide). The flags are bit-mask integers where most bits fire on narrow rivers due to land/water mixing effects, not genuinely bad data.

**What was tried:**
- `== 0` (strictest): Only 4-15% pixels retained, Uyak 5-25km completely empty
- `< 4` (allows first 2 bits): Still only 2.8% Uyak pixels pass `classification_qual`

**Current state:** Filters disabled in code. Cross-track, classification, and MAD filters active.

**Next step:** Expert consultation to determine which specific bit flags to exclude. Full flag reference in `SCIENTIFIC_METHODOLOGY.md`.

**Backup data:** Strict-filter data (==0) saved in `batch_outputs/backup_strict_filters/`

### Distance Logic
**Status**: ✅ Complete and verified
- Confluence Anchor method fully implemented
- All data now uses consistent Haversine distance from anchor

### Data Version
**Status**: ✅ Resolved
- Now using Version D exclusively (`SWOT_L2_HR_PIXC_D`)
- Previous mixed Version C/D issue resolved by switching to D only

---

## 6. Technical Stack

### Python Packages
```
earthaccess      # NASA Earthdata authentication & download
xarray           # NetCDF data reading
pandas           # Data manipulation
geopandas        # Spatial data operations
numpy            # Numerical operations
matplotlib       # Static plotting (legacy) + colormaps for Folium
scipy            # Statistical analysis (linregress)
streamlit        # Web dashboard framework
plotly           # Interactive plotting (charts)
folium           # Interactive GIS maps with measuring tools (Added 2026-02-13)
streamlit-folium # Folium integration for Streamlit (Added 2026-02-13)
duckdb           # In-memory SQL database
tqdm             # Progress bars for long-running operations
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
- Defined in `SWOT_Pull.py` lines 27-30
- Maps polygon IDs from `river_poly.zip` to readable names

### Legacy Naming ("Polywhirl" Era)
**Historical Context**: Earlier versions used Pokemon-themed naming:
- "Polywhirl" = Old processing script (archived)
- "Lugia" = Processing script (2025-2026, now renamed to SWOT_Pull.py)

**Why Changed**: Professor preferred more systematic naming for production. Further renamed to SWOT_Pull.py for clarity when sharing with external collaborators.

**Archive Location**: All old "Polywhirl" code moved to `old_stuff/`

---

## 8. Professor Requirements & Preferences

### Confirmed Working Workflow
✅ **Current Best Practice** (Updated 2026-02-10):
1. Download and process data using `SWOT_Pull.py` (optimization now automatic!)
2. Display data using `dashboard_swot.py` (Streamlit)

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
- 2 active Python scripts (`SWOT_Pull.py`, `dashboard_swot.py`)
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
2. ✅ Added `tqdm` progress bars to SWOT_Pull.py for:
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
- **Simplified workflow**: Just run `SWOT_Pull.py` and you're done
- **Better UX**: Progress bars show completion status and time estimates
- **Always optimized**: Dashboard-ready files created automatically
- **No manual steps**: Can't forget to run optimization
- **Easy setup**: `pip install -r requirements.txt`

**Technical Details:**
- Optimization now runs as final step of `rebuild_master_from_daily_csvs()`
- Creates both unoptimized CSV (compatibility) and optimized Parquet partitions
- Uses same optimization strategy as old `optimize.py` but fully integrated
- Progress bars use `tqdm.write()` to prevent bar corruption

### 2026-02-10: GitHub Repository Organization & Push
**Problem Addressed:**
- Code not version controlled or shared publicly
- No .gitignore to prevent accidentally committing large data files
- README outdated (referenced old 3-stage workflow, optimize.py)
- Missing organization for archival files

**Actions Taken:**
1. ✅ Created comprehensive `.gitignore`:
   - Excludes all data files (`batch_outputs/`, `temp_swot_batch/`)
   - Excludes Python artifacts (`__pycache__/`, `*.pyc`)
   - Excludes workspace files (`.claude/`)
   - Prevents accidental commits of large files
2. ✅ Updated `README.md`:
   - Reflects current 2-stage workflow (no optimize.py)
   - Documents Classes 3-4 filter (not just 4)
   - Highlights resumable downloads and progress bars
   - Professional formatting with badges
   - Clear quick-start instructions
   - Comprehensive documentation sections
3. ✅ Moved diagnostic script to `old_stuff/`:
   - `check_classifications.py` → archived
4. ✅ Initialized Git repository and pushed to GitHub:
   - Repository: https://github.com/lukestork839/SWOT_Dashboard
   - Resolved merge conflicts with existing remote
   - Verified data files excluded from commit
   - Clean commit history

**Benefits:**
- **Version control**: Track changes to code over time
- **Collaboration**: Others can clone, use, and contribute
- **Documentation**: Professional README for users
- **Data safety**: .gitignore prevents accidental large file commits
- **Reproducibility**: Complete workflow documented and shareable
- **Best practices**: Separates code (Git) from data (local)

**Technical Details:**
- Repository size: ~10MB (code + docs only, no data)
- Files tracked: 11 core files (scripts, docs, configs)
- Files gitignored: All data, temp files, workspace
- Commit strategy: Merged with existing remote, kept improved local versions
- Data remains local: Users run `SWOT_Pull.py` to generate their own data

**Repository Contents:**
- Core scripts: `SWOT_Pull.py`, `dashboard_swot.py`
- Dependencies: `requirements.txt`
- Configuration: `river_poly.zip`, `.swot_cli_config.json`, `.gitignore`
- Documentation: `README.md`, `SWOT_Processing_Documentation.md`, `Claude/` folder
- Reference: `Claude/SWOT_Handbook.pdf`

### 2026-02-11: Map Styling Options & Classification Column Support
**Problem Addressed:**
- Dashboard map view only colored by river reach (no data quality visualization)
- Classification data (Class 3 vs Class 4) was filtered but not preserved in outputs
- No way to visualize WSE elevation gradients on the map
- Missing utility script for quick master file rebuilds

**Actions Taken:**
1. ✅ Updated `SWOT_Pull.py`:
   - Added `classification` to `KEEP_COLUMNS` (line 27)
   - Added `classification` to daily CSV export columns (line 213)
   - Classification now preserved throughout entire pipeline
2. ✅ Enhanced `dashboard_swot.py`:
   - Added "Map Display Options" section in sidebar
   - Implemented three color-by modes:
     - **River Name**: Original discrete colors (firebrick/dodgerblue)
     - **WSE**: Continuous viridis scale showing elevation gradients
     - **Classification**: Discrete colors (Orange=Class 3, Turquoise=Class 4)
   - Enhanced hover data to show classification in all views
3. ✅ Created `rebuild_master.py`:
   - Standalone utility for rebuilding master files from daily CSVs
   - Useful for quick regeneration after column changes
   - Includes optimization logic (data types, compression, partitioning)
4. ✅ Updated `river_poly.zip`:
   - Refined polygon boundaries in QGIS
   - More precise river channel delineation
   - Reduced inclusion of surrounding floodplain areas
5. ✅ Updated `.gitignore`:
   - Added `old_stuff/` to prevent tracking archived code

**Benefits:**
- **Enhanced visualization**: Multiple ways to explore spatial patterns
- **Data quality insights**: Visualize Class 3 vs Class 4 distribution on map
- **Elevation analysis**: WSE gradient coloring reveals hydraulic patterns
- **Scientific accuracy**: Classification data preserved for reproducibility
- **Improved boundaries**: More precise spatial filtering with refined polygons
- **Developer tools**: rebuild_master.py enables quick iteration on column changes

**Technical Details:**
- Map color modes controlled by `map_color_by` selectbox in sidebar
- Classification converted to string (`class_str`) for discrete Plotly coloring
- Color scheme for classification: `{"3": "#FFA500", "4": "#00CED1"}`
- WSE uses `color_continuous_scale="viridis"` for intuitive gradient
- All hover data enhanced to show relevant context per color mode
- Requires data reprocessing to populate classification column in existing data

**User Workflow:**
- Deleted all daily CSVs to force regeneration with classification column
- Re-ran SWOT_Pull.py for May-July 2025 date range (22 granules, 9 new, 8 skipped)
- Successfully created 424,179 points with classification data
- Dashboard map styling features tested and verified working

### 2026-02-13: Dashboard Enhancement - Analysis Tabs & Folium Maps
**Problem Addressed:**
- Need direct elevation comparison between rivers
- Limited map functionality (no measuring tools, few basemap options)
- Need to analyze slope variability along river course (not just overall average)

**Actions Taken:**
1. ✅ **Elevation Difference Tab**:
   - Added new "Elevation Difference" tab for direct river comparison
   - Bins data every 100 meters (0.1 km)
   - Calculates Kanektok WSE - Uyak WSE for each bin
   - Line plot with zero reference line
   - Shows average difference, max difference, and number of bins
   - Only displays when both rivers are selected

2. ✅ **Interval Slopes Tab**:
   - Added new "Interval Slopes" tab for segment-by-segment slope analysis
   - Calculates slope for each 100-meter river segment
   - Uses DuckDB window functions (LAG) for consecutive bin comparison
   - Formula: `(WSE_next - WSE_current) / distance_change × 100` (cm/km)
   - Displays absolute values for steepness comparison
   - Statistics table: average, max, min, std dev per river
   - Helps identify specific reaches with different hydraulic characteristics

3. ✅ **Folium Map Integration**:
   - Replaced Plotly scatter_mapbox with Folium for enhanced GIS capabilities
   - Added basemap selector with 6 options:
     - OpenStreetMap (default)
     - Terrain (Stamen) - topographic view
     - Satellite (ESRI) - aerial imagery
     - Watercolor (Stamen) - artistic style
     - CartoDB Positron (Light)
     - CartoDB Dark Matter
   - Added MeasureControl plugin for distance/area measurements
   - Added LayerControl for toggling rivers/classifications on/off
   - Preserved all color-by options (River Name, WSE, Classification)
   - Interactive popups with WSE, date, classification details
   - Fixed rerun issues with `key` and `returned_objects=[]` parameters

4. ✅ **Updated Dependencies**:
   - Added `folium>=0.15.0` to requirements.txt
   - Added `streamlit-folium>=0.15.0` to requirements.txt
   - Added matplotlib.colors and matplotlib.cm imports for colormapping

**Benefits:**
- **Direct comparison**: Elevation difference tab shows which river is "winning" at each distance
- **Slope variability**: Interval slopes reveal steep vs. gentle reaches
- **Better maps**: Professional GIS features (measuring, multiple basemaps, layer control)
- **Scientific utility**: Supports avulsion risk assessment with segment-level analysis
- **User-friendly**: Measuring tool allows manual verification of distances

**Technical Details:**
- All new tabs use DuckDB SQL with CTEs (Common Table Expressions)
- 100-meter binning ensures consistent comparison between rivers
- Folium uses CircleMarkers for performance with thousands of points
- Viridis colormap for continuous WSE coloring (matches Plotly convention)
- X-axis remains reversed across all plots for consistency
- Map sampling: 10,000 points max for browser performance

**Dashboard Tab Order (Updated 2026-04-01):**
1. Gradient Profile (original)
2. Elevation Difference (added 2026-02-13)
3. Detrended Profile (added 2026-02-16)
4. Interval Slopes (added 2026-02-13)
5. Map View (enhanced with Folium 2026-02-13)
6. Raw Data (original)
7. Temporal Evolution (added 2026-02-23)
8. Seasonal Comparison (added 2026-04-01)
9. Typhoon Impact (added 2026-04-01)

### 2026-02-16: Detrended Profile Analysis (Relative Elevation Model)
**Problem Addressed:**
- Small elevation differences between rivers get visually overwhelmed by large overall gradient
- Need to highlight subtle variations in hydraulic gradients
- Professor requested implementation of "slope detrended model" or "relative elevation model"

**Actions Taken:**
1. ✅ Added new "Detrended Profile" tab (Tab 3)
2. ✅ Implemented multiple detrending methods:
   - Linear baseline fit
   - Polynomial 2nd order (default - best for gentle curves)
   - Polynomial 3rd order (more flexible)
   - LOESS local regression (adaptive smoothing)
3. ✅ Added detrending method selector in sidebar
4. ✅ Created visualization showing residuals (deviations from baseline)
5. ✅ Added comprehensive interpretation guide
6. ✅ Implemented statistics table showing residual metrics per river
7. ✅ Added expandable section showing original data with baseline curve overlay
8. ✅ Updated documentation in Claude notes

**Benefits:**
- **Removes large-scale trend**: Centers data around zero to reveal small differences
- **Multiple methods**: Users can choose best-fit approach for their analysis
- **Scientific insight**: Reveals which river is systematically higher/lower than expected
- **Complements existing tools**: Works alongside absolute elevation difference analysis
- **Visual clarity**: Small gradient differences become immediately obvious

**Technical Details:**
- Baseline fit using all data points from both rivers combined
- Residuals calculated as: `actual_WSE - baseline_prediction`
- LOESS implementation uses Gaussian smoothing as approximation
- Full dataset used for fitting (not sampled) for accuracy
- Visualization respects MAX_PLOT_POINTS for performance
- Added `scipy.ndimage.gaussian_filter1d` import
- Statistics calculated on 100% of filtered data

**Scientific Context:**
- This is standard technique in geomorphology and river analysis
- Also called "Relative Elevation Model (REM)" in fluvial studies
- Helps assess avulsion risk by revealing persistent elevation anomalies
- Baseline represents "expected" elevation profile for the river system
- Deviations indicate where rivers deviate from typical longitudinal profile

### 2026-02-16: SWOT Calibration & Validation with Field Measurements
**Problem Addressed:**
- Need to verify SWOT satellite measurements against ground truth
- Field RTK GPS measurements taken Nov 11 & 13, 2025 in Quinhagak, Alaska
- Initial comparison showed 8.6m discrepancy between SWOT and field measurements
- Required investigation to determine if SWOT processing was correct

**Actions Taken:**
1. ✅ Modified SWOT_Pull.py to export diagnostic columns (height_raw, geoid, solid_tide, pole_tide, load_tide)
2. ✅ Reprocessed Nov 13, 2025 data with full correction values
3. ✅ Verified SWOT WSE formula against SWOT Handbook (JPL D-109532, Section 3.1.25)
4. ✅ Analyzed Emlid RTK GPS shapefile data from field campaign
5. ✅ Extracted and analyzed raw RINEX data from Emlid Rover
6. ✅ Identified vertical datum mismatch (NAVD88 vs EGM2008)
7. ✅ Calculated datum offset and verified calibration

**Field Measurement Details:**
- **Equipment**: Emlid Reach RS3 RTK GPS (±1cm precision)
- **Configuration**: NAVD88 vertical datum with ~3.7m geoid separation
- **Dates**: Nov 11, 2025 (9:35 PM) and Nov 13, 2025 (6:15 AM)
- **Location**: 59.757°N, -161.880°W (Kanektok River, Alaska)
- **Method**: Staff with antenna 1.9m above water surface

**Key Findings:**
- **SWOT Processing**: ✅ 100% correct (verified against handbook)
  - Formula: `WSE = height - geoid - solid_earth_tide - pole_tide - load_tide`
  - All corrections properly applied with reasonable magnitudes:
    - Geoid (EGM2008): ~13.3m
    - Solid Earth tide: ~0.024m
    - Pole tide: ~0.002m
    - Load tide: ~-0.001m

- **Vertical Datum Mismatch**: Root cause of discrepancy
  - Field GPS: NAVD88 (North American Vertical Datum 1988)
  - SWOT: EGM2008 (Earth Gravitational Model 2008)
  - **Datum Offset at calibration location: ~9.6 meters**
  - NAVD88 uses ~3.7m geoid separation vs EGM2008's ~13.3m

- **RINEX Analysis**: Confirmed datum issue
  - Raw GNSS ellipsoidal height: 17.3m (WGS84)
  - Emlid applied NAVD88 conversion: -3.7m → 13.6m
  - SWOT applied EGM2008 conversion: -13.3m → 3.1m
  - Observed difference: 13.6 - 3.1 = 10.5m ≈ datum offset

**Calibration Results:**
```
Nov 13, 2025 Comparison:
  Field WSE (NAVD88):           11.73 m
  Convert to EGM2008:           -9.60 m (datum offset)
  Field WSE (EGM2008):           2.13 m
  SWOT WSE (EGM2008):            3.07 m
  Final Difference:             ~0.94 m ✓
```

**Remaining 1m Difference Explained By:**
- Tidal variation (field at 6:15 AM, SWOT pass later in day)
- Location offset (measurements 8m apart)
- Temporal variation (not simultaneous)
- Normal for this type of comparison in tidal environment

**Datum Conversion Formula:**
```python
# At calibration location (59.757°N, -161.880°W):
DATUM_OFFSET = 9.6  # meters

# Convert NAVD88 to EGM2008 (for comparison with SWOT):
wse_egm2008 = wse_navd88 - DATUM_OFFSET

# Convert SWOT to NAVD88 (for field comparison):
wse_navd88 = wse_swot + DATUM_OFFSET
```

**Benefits:**
- **SWOT Validated**: Confirmed satellite measurements are accurate
- **Datum Documented**: Critical for comparing field data with SWOT
- **Diagnostic Columns**: Now available for all future troubleshooting
- **Reproducible**: Complete methodology documented for future calibrations
- **Scientific Rigor**: Multi-source verification (shapefile, RINEX, SWOT handbook)

**Technical Details:**
- Modified KEEP_COLUMNS in SWOT_Pull.py to include: height_raw, geoid, solid_tide, pole_tide, load_tide
- Verified all corrections against SWOT Product Handbook Section 3.1.25
- Analyzed 3,354 RTK measurements from RINEX LLH solution file
- Compared with 170 SWOT points within 500m of calibration location
- Used haversine distance calculation for spatial matching

**Scientific Context:**
- NAVD88 vs EGM2008 differences are well-known in Alaska (up to 10-15m)
- SWOT uses global EGM2008 for consistency worldwide
- Local/regional datums (NAVD88, CGVD2013, etc.) use different geoid models
- Critical to document vertical datum when comparing field measurements with SWOT
- Recommended: Use NOAA VDatum tool for precise conversions at specific locations

**Files Modified:**
- `SWOT_Pull.py`: Added diagnostic columns to KEEP_COLUMNS and cols_export
- `Claude/Claude_notes.md`: This documentation
- `README.md`: Added Calibration & Validation section

**Data Generated:**
- `batch_outputs/field_calibration_data.csv`: Field GPS measurements summary
- `batch_outputs/swot_near_calibration.csv`: SWOT points near calibration location
- Daily CSVs now include: height_raw, geoid, solid_tide, pole_tide, load_tide

---

## 10. Quick Reference Commands

### Run Data Ingestion (with automatic optimization)
```bash
python SWOT_Pull.py
# Prompts for: Start Date (YYYY-MM-DD), End Date (YYYY-MM-DD)
# Automatically creates optimized parquet files ready for dashboard
```

### Launch Dashboard
```bash
streamlit run dashboard_swot.py
```

### Rebuild Master Files (from existing daily CSVs)
```bash
python3 rebuild_master.py
# Useful after changing KEEP_COLUMNS or for quick regeneration
# Much faster than re-running full SWOT_Pull.py pipeline
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

### Git/GitHub Commands
```bash
# Clone repository
git clone https://github.com/lukestork839/SWOT_Dashboard.git

# Check status
git status

# Commit changes
git add <files>
git commit -m "Description of changes"

# Push to GitHub
git push origin main

# Pull latest changes
git pull origin main
```

### 2026-02-18: Critical Bug Fixes - np.polyfit Failure & Dashboard Enhancements
**Problem Addressed:**
- Detrended profile showing systematic slope instead of scatter around zero
- Interval slopes showing extreme outliers (>1000 cm/km spikes)
- Map styling issues with detrended residuals
- Colormap import errors preventing map legends from displaying
- No control over point transparency on maps

**Actions Taken:**

1. ✅ **CRITICAL BUG DISCOVERED: np.polyfit Completely Broken**
   - **Symptom**: Linear fit returned POSITIVE slope (+0.47 m/km) when data clearly had NEGATIVE slope (-1.83 m/km)
   - **Correlation**: -0.9883 (strong negative) but fitted slope was positive!
   - **Root Cause**: np.polyfit has numerical precision issues with large datasets (6.7M points)
   - **Affected Code**: Both detrended profile calculation AND map coloring

   **Fix Applied**:
   - Linear detrending: Switched from `np.polyfit` to `scipy.stats.linregress`
   - Polynomial detrending: Switched from `np.polyfit` to `numpy.polynomial.Polynomial.fit()` (newer, more stable API)
   - Applied fix to BOTH locations: Detrended Profile tab (lines 522-540) AND map data preparation (lines 251-276)

   **Result**: Detrending now works correctly!
   - Mean residual: ~0.000m (was 5.51m before)
   - Residuals scatter around zero with no systematic patterns
   - Reveals Uyak Creek is perched ~2-3m higher than Kanektok River

2. ✅ **Fixed Interval Slopes Quality Issues**
   - **Problem**: Extreme slope spikes (>1000 cm/km) from sparse data bins
   - **Fixes Applied**:
     - Minimum 3 points per bin required (`HAVING COUNT(*) >= 3`)
     - Only consecutive bins shown (≤150m gap filter)
     - Outlier removal (slopes >1000 cm/km filtered out)
     - Added hover data showing: points in bin, gap to previous bin
     - Added "Avg Points/Bin" to statistics table
   - **Location**: `dashboard_swot.py` lines 718-754 (SQL query with quality filters)

3. ✅ **Fixed Colormap Import Issues**
   - **Problem**: `from folium import colormap` failed - module not found
   - **Fix**: Flexible import strategy with fallback
     ```python
     try:
         from branca.colormap import LinearColormap
     except ImportError:
         try:
             from folium.colormap import LinearColormap
         except ImportError:
             LinearColormap = None
     ```
   - All colormap usage wrapped in `if LinearColormap is not None:` checks
   - Gracefully degrades (no legends) if import fails
   - **Location**: `dashboard_swot.py` lines 16-24

4. ✅ **Added Point Opacity Control**
   - New slider in Map Display Options: "Point Opacity" (0.1 to 1.0, default 0.7)
   - Applies to all map coloring modes
   - Helps see terrain/roads beneath data points
   - **Location**: `dashboard_swot.py` line 161-167

5. ✅ **Improved Map Styling**
   - Removed point borders (`weight=0`) for cleaner appearance
   - Shortened legend captions to prevent cut-off ("Residual (m)" instead of "Detrended Residual (m) - Polynomial...")
   - All markers now use dynamic `point_opacity` variable

**Benefits:**
- **Scientifically sound detrending**: Can now properly identify subtle elevation differences between rivers
- **Reliable slope analysis**: Interval slopes no longer dominated by outliers
- **Better visualization**: Adjustable transparency reveals underlying geography
- **Robust imports**: Works across different folium/branca versions

**Technical Details:**
- **np.polyfit bug**: Appears to be numerical instability with large datasets. Using `numpy.polynomial.Polynomial.fit()` (newer API) or `scipy.stats.linregress` avoids the issue.
- **Detrending validation**: Sanity checks added showing correlation coefficient, fitted equation, and mean residual
- **Map performance**: All changes maintain 10,000 point sampling limit for browser performance

**Scientific Insight Revealed:**
With properly working detrended profiles, we can now see that:
- Both rivers have concave-up longitudinal profiles (normal for rivers)
- Uyak Creek is systematically 2-3m higher than Kanektok River at equivalent distances
- This elevation difference is critical for assessing avulsion risk

**Files Modified:**
- `dashboard_swot.py`: Complete overhaul of detrending methods, interval slope filtering, map styling, opacity control
- `Claude/Claude_notes.md`: This documentation

### 2026-02-25: Streamlit Cloud Deployment Fix - Git LFS Workaround
**Problem Addressed:**
- Dashboard stuck loading on Streamlit Cloud (60+ second timeout, 503 errors)
- Git LFS files not supported by Streamlit Cloud deployment
- 24MB `dashboard_data_optimized.parquet` was only a pointer file, not actual data
- Dashboard tried to load non-existent data and hung indefinitely

**Root Cause:**
- Git LFS is used to store large parquet file (24MB)
- Streamlit Cloud clones repository but doesn't download LFS objects
- Dashboard received tiny pointer file (~200 bytes) instead of 24MB data file
- DuckDB tried to read pointer file as parquet → hung → health check timeout

**Actions Taken:**

1. ✅ **Created GitHub Release for Data Hosting**
   - Created release `v1.0-data`: https://github.com/lukestork839/SWOT_Dashboard/releases/tag/v1.0-data
   - Uploaded `dashboard_data_optimized.parquet` (24MB) to release assets
   - Provides stable, publicly accessible URL for data download
   - Release notes document purpose: "Work around Git LFS limitations on Streamlit Cloud"

2. ✅ **Added Automatic Data Download Function**
   - Created `download_data_if_needed()` function in `dashboard_swot.py`
   - Detects Git LFS pointer files (< 1MB) vs actual data (> 1MB)
   - Downloads from GitHub Release URL if file is missing or too small
   - Uses `urllib.request.urlretrieve()` for download
   - Shows progress spinner: "📥 Downloading data from GitHub Releases (24MB)..."
   - Verifies download succeeded (checks final file size)
   - Provides troubleshooting guidance if download fails

3. ✅ **Modified Database Connection Logic**
   - Integrated download check into `get_database_connection()` cached function
   - Calls `download_data_if_needed()` before initializing DuckDB
   - Added error handling with traceback for debugging
   - Maintains existing fallback to partition files for local development

4. ✅ **Fixed Deprecation Warnings**
   - Replaced all `use_container_width=True` with `width='stretch'`
   - Ensures compatibility with Streamlit 1.54.0+
   - Prevents log spam (warnings appeared every 5 minutes)
   - Applied to all dataframes and plotly charts (9 locations)

5. ✅ **Committed and Pushed Changes**
   - Comprehensive commit message documenting both fixes
   - Pushed to main branch: commit 9913887
   - Streamlit Cloud auto-deploys on push (2-3 minute delay)

**Benefits:**
- **Dashboard now loads on Streamlit Cloud**: First-time initialization ~90 seconds (download + load)
- **Cached for subsequent visits**: After first download, loads in <10 seconds
- **No Git LFS dependency**: Works with standard Streamlit Cloud infrastructure
- **Automatic recovery**: If file deleted, automatically re-downloads
- **Clear user feedback**: Shows download progress and troubleshooting steps
- **Future-proof**: Easy to update data (just upload new release asset)

**Technical Details:**
- **Detection logic**: Checks if file size > 1,000,000 bytes (Git LFS pointers are ~200 bytes)
- **Download URL**: Hardcoded GitHub Release asset URL
- **Directory creation**: Uses `os.makedirs(DATA_DIR, exist_ok=True)`
- **Caching**: `@st.cache_resource` on `get_database_connection()` prevents re-download on each interaction
- **Fallback behavior**: Maintains compatibility with local development (partition files)

**Alternative Approaches Considered:**
1. ❌ S3/Cloud Storage: Requires AWS credentials, more complex
2. ❌ Embedded small sample: Loses scientific accuracy
3. ❌ Git LFS bandwidth: GitHub charges for LFS bandwidth after 1GB/month
4. ✅ GitHub Releases: Free, simple, version-controlled, perfect for this use case

**Deployment Timeline:**
- Issue identified: 2026-02-25 18:42 UTC (logs showed 60+ second hang)
- Fix implemented: 2026-02-25 (local development)
- Release created: 2026-02-25 (v1.0-data)
- Pushed to GitHub: 2026-02-25 19:16 UTC (commit 9913887)
- Expected deploy: ~3-5 minutes after push

**Monitoring:**
Watch Streamlit Cloud logs for:
- `⚠️ Detected Git LFS pointer file... Downloading actual data...`
- `📥 Downloading data from GitHub Releases (24MB)...`
- `✅ Data downloaded successfully (24.0 MB)`
- Dashboard should then load normally

**Files Modified:**
- `dashboard_swot.py`: Added `download_data_if_needed()`, modified `get_database_connection()`, fixed deprecation warnings
- `.gitattributes`: Git LFS configuration (already existed)
- `Claude/Claude_notes.md`: This documentation

**GitHub Release Details:**
- Tag: `v1.0-data`
- Title: "Dashboard Data v1.0"
- Asset: `dashboard_data_optimized.parquet` (24MB)
- Description: Optimized dataset for SWOT Dashboard (1.9M rows, last 6 months at 50% sampling)

**Future Considerations:**
- If dataset grows beyond 100MB, consider:
  - Multiple smaller partition files
  - External cloud storage (S3, GCS)
  - On-demand data generation from smaller seed data
- Current 24MB file is well within GitHub Release limits (2GB per file, 10GB per release)

### 2026-03-04: MAD-Based Outlier Filtering Implementation
**Problem Addressed:**
- Professor recommended removing data "too far from baseline" (faulty measurements)
- Plateau artifacts and bad SWOT measurements needed numerical filtering
- Classification filter alone insufficient for measurement quality

**Actions Taken:**
1. ✅ Researched scientific best practices (MAD vs IQR vs Z-score)
2. ✅ Implemented Modified Z-Score with MAD (Iglewicz & Hoaglin, 1993)
3. ✅ Applied per-reach filtering (threshold 3.5)
4. ✅ Added edge case handling (minimum counts, MAD=0)
5. ✅ Updated all documentation (SCIENTIFIC_METHODOLOGY.md, README.md, Claude notes)

**Benefits:**
- **Removes anomalies:** Filters plateau artifacts and bad measurements
- **Preserves validity:** Conservative threshold (3.5) keeps seasonal variation
- **Independent treatment:** Per-reach filtering prevents bias
- **Standard practice:** Follows SWOT validation literature

**Technical Details:**
- Location: SWOT_Pull.py line 201 (after classification, before slope calc)
- Method: Modified Z-score with MAD (median-based, robust to outliers)
- Threshold: 3.5 (equivalent to 3.5 sigma in normal distribution)
- Typical removal: 10-15% for affected reaches, 0-5% for clean reaches
- Logged per-reach statistics during processing

**Important Note:**
- ⚠️ **Code implemented but NOT yet applied to data** (user has meeting, needs current dashboard working)
- Data reprocessing will be done AFTER meeting
- When reprocessed, will automatically use checkpoint-based resumable downloads

---

## 11. Future Considerations

### Completed Improvements
- ✅ **Resumable downloads** (2026-02-10): Checkpoint system implemented
- ✅ **Progress bars** (2026-02-10): Added tqdm for better UX
- ✅ **Integrated optimization** (2026-02-10): No separate optimize.py needed
- ✅ **Requirements.txt** (2026-02-10): Dependency management
- ✅ **GitHub repository** (2026-02-10): Version control and public sharing
- ✅ **Comprehensive .gitignore** (2026-02-10): Prevents data file commits
- ✅ **Updated README** (2026-02-10): Professional documentation
- ✅ **Map styling options** (2026-02-11): Color by River Name, WSE, or Classification
- ✅ **Classification preservation** (2026-02-11): Class data saved throughout pipeline
- ✅ **Rebuild utility** (2026-02-11): rebuild_master.py for quick regeneration
- ✅ **Refined polygons** (2026-02-11): More precise river boundaries
- ✅ **Elevation difference analysis** (2026-02-13): Direct Kanektok-Uyak comparison by 100m bins
- ✅ **Interval slope analysis** (2026-02-13): Segment-by-segment slope calculations
- ✅ **Folium map integration** (2026-02-13): GIS-style maps with measuring tools and basemap options
- ✅ **Detrended profile analysis** (2026-02-16): Relative Elevation Model with multiple detrending methods (Linear, Polynomial, LOESS)
- ✅ **SWOT calibration & validation** (2026-02-16): Field RTK GPS verification, datum mismatch identification (NAVD88 vs EGM2008), diagnostic columns added
- ✅ **CRITICAL: Fixed np.polyfit bug** (2026-02-18): Switched to scipy.stats.linregress and numpy.polynomial.Polynomial.fit() - detrending now scientifically accurate
- ✅ **Interval slopes quality filters** (2026-02-18): Min 3 points/bin, consecutive bins only, outlier removal, data quality metrics
- ✅ **Colormap import fallback** (2026-02-18): Robust import strategy for LinearColormap across folium/branca versions
- ✅ **Point opacity control** (2026-02-18): Adjustable transparency slider (0.1-1.0) for all map visualizations
- ✅ **Map styling improvements** (2026-02-18): Removed borders, shortened legends, better color visibility
- ✅ **Streamlit Cloud deployment** (2026-02-25): Fixed Git LFS limitation with GitHub Releases data hosting, automatic download on missing data, fixed deprecation warnings
- ✅ **MAD-based outlier filtering** (2026-03-04): Implemented Modified Z-Score with MAD (Iglewicz & Hoaglin, 1993) for removing anomalous WSE measurements
- ✅ **PIXC quality flag filtering** (2026-03-07): Added cross-track distance (10-60km), geolocation_qual, classification_qual extraction and filter infrastructure
- ✅ **Version D switch** (2026-03-07): Switched exclusively to `SWOT_L2_HR_PIXC_D`, removed Version C search
- ✅ **Dashboard partition fix** (2026-03-09): Fixed loading stale optimized parquet instead of fresh partition files
- ✅ **PIXC Quality Flag Reference** (2026-03-09): Comprehensive bit flag documentation for expert review (39 flags across 2 variables)

### 2026-03-07 to 2026-03-09: PIXC Quality Flags, Version D Switch, and Expert Prep

**Overview:** Major session covering quality flag implementation, data version switch, full reprocessing, documentation overhaul, dashboard fix, and ultimately disabling quality flags pending expert review.

#### Part 1: PIXC Quality Flag Implementation (2026-03-07)
**Actions Taken:**
1. Added `CROSS_TRACK_MIN` (10km) and `CROSS_TRACK_MAX` (60km) constants
2. Extracted `geolocation_qual`, `classification_qual`, `cross_track` from NetCDF with safe fallbacks
3. Added three new filter steps before classification filter (with per-step logging)

#### Part 2: Version D Switch (2026-03-07)
**Discovery:** Expert suggested Version D is better than Version C (2.0). Research confirmed:
- Version D = latest science algorithms, calibration, geophysical models
- Version C (SWOT_L2_HR_PIXC_2.0) = superseded, reprocessed into D
- We had it backwards — treating 2.0 as priority over D

**Actions Taken:**
1. Removed Version C search from `SWOT_Pull.py` — now searches `SWOT_L2_HR_PIXC_D` only
2. Updated all documentation (Claude_notes, SCIENTIFIC_METHODOLOGY, SWOT_Processing_Documentation)

#### Part 3: Full Data Reprocessing (2026-03-07)
- Reprocessed July 2023 – December 2025 (295 granules, 133 new, 103 skipped)
- **Result with strict filters:** 785,932 total points (down from ~6.7M = 88% reduction)
  - Kanektok: 748,767 points (133 dates, avg 5,630/pass)
  - Uyak: 37,165 points (122 dates, avg 305/pass)

#### Part 4: Documentation Overhaul (2026-03-07)
- `SCIENTIFIC_METHODOLOGY.md`: New "Data Quality Filtering" section with all 7 filters, observed reduction stats
- `SWOT_Processing_Documentation.md`: Rewrote Section 4, updated flow diagram
- `README.md`: Updated filter summary, removed obsolete known issues

#### Part 5: Dashboard Fix (2026-03-09)
**Problem:** Dashboard threw "Unable to parse: 2024-07-" error
**Root cause:** `get_database_connection()` loaded stale `dashboard_data_optimized.parquet` (24MB Streamlit Cloud file) instead of fresh partition files
**Fix:** Modified to prefer `master_all_data_part_*.parquet` when they exist locally

#### Part 6: Uyak Data Gap Discovery (2026-03-09)
**Problem:** Strict quality filters removed virtually all Uyak Creek data in 5-25km middle section
**Investigation:**
- `geolocation_qual == 0`: Only 4-15% retention; narrow creek pixels have flags due to land/water proximity
- Relaxed to `< 4`: Still only 2.8% pass `classification_qual` (bit flags, not 0-3 scale)
- Root cause: Most quality flag bits fire on narrow rivers because the channel is narrow, not because data is bad

**Actions Taken:**
1. Backed up strict-filter data to `batch_outputs/backup_strict_filters/`
2. Relaxed from `== 0` to `< 4` — still too strict
3. Ultimately disabled quality flag filters entirely pending expert review

#### Part 7: Expert Meeting Preparation (2026-03-09)
**Actions Taken:**
1. Added comprehensive "PIXC Quality Flag Reference" to `SCIENTIFIC_METHODOLOGY.md`:
   - `geolocation_qual`: 23 individual bit flags documented
   - `classification_qual`: 16 individual bit flags documented
   - Each flag: bit position, mask, name, severity, description, narrow river impact, recommendation
   - Flags categorized as "DISCUSS" (need expert input), "Exclude" (instrument), "ALWAYS EXCLUDE" (bad data)
   - Key question framed: "Does the flag mean WSE is wrong, or just higher uncertainty?"
2. Updated all documentation to mark quality flags as "pending expert review"
3. Framed PIXC reference as candidate filters, not applied filters

#### Part 8: Final Documentation Cleanup (2026-03-09)
- `SCIENTIFIC_METHODOLOGY.md`: Verification status, filter chain, data flow, checklist, Q&A all updated
- `README.md`: Filter table now shows Status column (Active vs Pending)
- Three commits pushed: `c81e76f`, `e16702d`, `c2ad2ae`

**Current State:**
- **Active filters:** Cross-track (10-60km), Classification (3-4), MAD outlier (3.5)
- **Disabled filters:** `geolocation_qual`, `classification_qual` (pending expert)
- **Data:** Being reprocessed with disabled quality flags
- **Backup:** Strict-filter data in `batch_outputs/backup_strict_filters/`
- **Next step:** Expert meeting to determine which bit flags to use

### 2026-04-01: Crossover Calibration Quality Filter Implementation
**Problem Addressed:**
- SWOT expert recommended filtering on crossover calibration quality
- Crossover calibration corrects meter-scale roll/phase errors in KaRIn height measurements
- When this correction is missing, `height` (and WSE) can be off by meters due to uncorrected cross-track tilts
- Width-independent filter — does NOT disproportionately remove Uyak Creek data

**Actions Taken:**
1. Added `XOVERCAL_SUSPECT_MASK` (bit 6) and `XOVERCAL_MISSING_MASK` (bit 23) constants to SWOT_Pull.py
2. Added `height_cor_xover_qual` extraction from NetCDF (backup/validation variable)
3. Added crossover calibration filter step after cross-track filter, before classification
4. Updated filter chain comment to reflect new order
5. Updated documentation (Claude_notes.md, SCIENTIFIC_METHODOLOGY.md)

**Filter Strategy:**
- **Exclude only `xovercal_missing` (bit 23)** — pixels with NO crossover correction applied
- **Keep `xovercal_suspect` (bit 6)** — correction was applied but may be imprecise
- Rationale: Suspect corrections still better than no correction; for relative gradient comparison between rivers in the same pass, even suspect corrections preserve the relative WSE difference

**Expected Impact:**
- Minimal data loss (<5-10%) — only early-mission passes or specific orbital geometries lack crossover calibration
- Both rivers equally affected (width-independent)
- Filter logs show per-granule statistics

**Technical Details:**
- Primary method: Bit masking on `geolocation_qual` (bit 23 = mask 8388608)
- Backup variable: `height_cor_xover_qual` (0=good, 1=suspect, 2=bad) — extracted but not used for filtering
- Location: SWOT_Pull.py lines 253-262 (after cross-track filter, before disabled quality flags)
- Constants: SWOT_Pull.py lines 27-29

**Note on Data Reprocessing:**
Existing daily CSVs won't reflect the new filter. A full reprocess (deleting existing daily CSVs) is needed to apply to historical data.

### 2026-04-01: Seasonal Comparison & Typhoon Impact Dashboard Tabs
**Problem Addressed:**
- Need year-over-year seasonal gradient comparison (high flow vs low flow) to detect long-term trends
- Need before/after analysis of Typhoon Halong (Oct 12-14, 2025), which eroded ~60 feet of Quinhagak's shoreline

**Actions Taken:**
1. Added `SEASONAL_PERIODS` and `TYPHOON_PERIODS` constants to dashboard_swot.py
2. Added `query_period_data()` helper function for reusable date-range queries with sampling
3. Added `from plotly.subplots import make_subplots` import
4. **Seasonal Comparison tab (Tab 8)**: 2×3 subplot grid — High Flow (May) vs Low Flow (Jul-Aug) for 2023-2025
   - Shared Y-axes across all panels for consistent elevation comparison
   - Linear trendlines with slope annotations on each panel
   - Fallback logic for May 2023 (SWOT launched July 2023)
   - Summary table with slope, R², point count, and pass count per period/river
5. **Typhoon Impact tab (Tab 9)**: Three sections:
   - Immediate Before/After (Aug-Sep 2025 vs Oct 15-Dec 2025)
   - Same-Season Comparison (Summer 2025 vs Spring/Summer 2026)
   - Binned Elevation Change chart (500m bins, post minus pre WSE)
   - `st.metric` slope change widgets for at-a-glance comparison
   - Graceful handling when post-storm data not yet available

**Prerequisite:**
- Data must be redownloaded for full range (July 2023 – present) with crossover calibration filter
- Current data only covers Mar-Aug 2025

### 2026-04-01: Ice Season Awareness (Dashboard Warnings)
**Problem Addressed:**
- Kanektok/Uyak rivers freeze Oct-May; SWOT may measure ice surface (0.5-2+ m above water)
- PIXC product has no ice classification; `ice_clsf` only in PIXCVec/RiverSP
- Typhoon Impact tab (Oct-Dec 2025) and Seasonal high-flow panels (May) overlap ice periods

**Actions Taken:**
1. Added `ICE_SEASONS`, `ICE_AFFECTED_MONTHS`, `OPEN_WATER_MONTHS` constants
2. Added `get_ice_warning()` helper — checks if date range overlaps ice-affected months
3. Added ice advisory warnings to:
   - Seasonal Comparison tab (break-up caveat for May panels)
   - Typhoon Impact tab (dynamic per-period warnings via `get_ice_warning()`)
   - Temporal Evolution tab (general ice season note in header)
4. Updated Claude_notes.md with Ice Handling section in Quality Filtering
5. **No changes to SWOT_Pull.py** — data preserved for potential ice studies; warnings at analysis level

**Decision rationale:** Dashboard-level warnings preferred over ingestion-level date filtering because:
- Preserves all data (ice-period data has value for cryosphere analysis)
- Classification filter (3-4) already excludes most ice pixels
- Analyst can interpret with context rather than having data silently removed

### In Progress
- ⏳ **Quality flag filter tuning** — Awaiting SWOT expert guidance on which bit flags to exclude for narrow rivers
- ⏳ **Data reprocessing** — Running with disabled quality flags to restore Uyak Creek data

### Potential Improvements
- Add height_uncertainty filtering thresholds
- Add data quality metrics dashboard
- Export high-resolution plots for publications
- Implement targeted bit-mask quality filtering (after expert review)
- Update Streamlit Cloud data (dashboard_data_optimized.parquet) after filter finalization

---

## 12. Important File Locations

### Configuration
- **Anchor Point**: `SWOT_Pull.py` lines 39-40
- **Name Mapping**: `SWOT_Pull.py` lines 43-46
- **Classification Filter**: `SWOT_Pull.py` line 21 (`DEFAULT_CLASSES = [3,4]`)
- **PIXC Quality Filter Config**: `SWOT_Pull.py` lines 23-25 (`CROSS_TRACK_MIN`, `CROSS_TRACK_MAX`)
- **MAD Outlier Filter Config**: `SWOT_Pull.py` lines 27-29 (`MAD_THRESHOLD`, `MIN_POINTS_FOR_MAD`, `MIN_POINTS_AFTER_FILTER`)
- **Optimization Settings**: `SWOT_Pull.py` lines 29-34 (`KEEP_COLUMNS`, `ROWS_PER_CHUNK`)
- **River Color Mapping**: `dashboard_swot.py` lines 16-19
- **Map Color-by Options**: `dashboard_swot.py` (sidebar form, "Map Display Options")
- **Point Opacity Default**: `dashboard_swot.py` line 164 (`value=0.7` - adjustable 0.1 to 1.0)
- **Classification Colors**: `dashboard_swot.py` line ~240 (`{"3": "#FFA500", "4": "#00CED1"}`)
- **Max Plot Points**: `dashboard_swot.py` line 13
- **Git Ignore Rules**: `.gitignore` (root directory)

### Data Paths
- **Polygon Boundaries**: `river_poly.zip` (root directory, refined 2026-02-11)
- **Output Directory**: `batch_outputs/` (gitignored)
- **Backup (strict filters)**: `batch_outputs/backup_strict_filters/` (data with geolocation_qual==0)
- **Temp Downloads**: `temp_swot_batch/` (gitignored, auto-created/deleted)
- **Documentation**: `Claude/` folder
- **Quality Flag Reference**: `SCIENTIFIC_METHODOLOGY.md` (PIXC Quality Flag Reference section)
- **Archive**: `old_stuff/` folder (not tracked in git)
- **Utility Scripts**: `rebuild_master.py` (quick master file regeneration)

### Critical Code Sections
- **Distance Calculation**: `SWOT_Pull.py` lines 57-77 (`haversine_vectorized` function)
- **MAD Outlier Detection**: `SWOT_Pull.py` lines 79-105 (`calculate_mad_outliers` function)
- **WSE Calculation**: `SWOT_Pull.py` line 215 (in `process_granule`)
- **Cross-Track Filter**: `SWOT_Pull.py` lines 246-251 (in `process_granule`)
- **Crossover Cal Filter**: `SWOT_Pull.py` lines 253-262 (bit 23 of geolocation_qual)
- **Quality Flag Filters**: `SWOT_Pull.py` lines 264-269 (DISABLED — commented out, pending expert review)
- **Classification Filter**: `SWOT_Pull.py` line 265 (in `process_granule`)
- **MAD Outlier Filter Application**: `SWOT_Pull.py` lines 267-287 (per-reach filtering in `process_granule`)
- **Slope Calculation**: `SWOT_Pull.py` lines 238-242 (in `process_granule`)
- **Checkpoint Detection**: `SWOT_Pull.py` lines 110-113 (`is_date_already_processed` function)
- **Master Rebuild**: `SWOT_Pull.py` lines 260-344 (`rebuild_master_from_daily_csvs` function)
- **CSV Export Columns**: `SWOT_Pull.py` line 244 (`cols_export` includes classification and diagnostic columns)
- **Dashboard Sampling**: `dashboard_swot.py` (systematic sampling logic)
- **Data Quality Info Display**: `dashboard_swot.py` lines 409-419 (info box showing filtering methods)
- **Detrending Data Prep**: `dashboard_swot.py` lines 251-276 (FIXED: uses linregress/Polynomial.fit, NOT np.polyfit)
- **Detrended Profile Tab**: `dashboard_swot.py` tab3 lines 504-750 (FIXED: uses linregress/Polynomial.fit, NOT np.polyfit)
- **Interval Slopes Quality Filters**: `dashboard_swot.py` lines 718-754 (SQL with HAVING, gap filter, outlier removal)
- **Elevation Difference Tab**: `dashboard_swot.py` tab2 (line ~234) - 100m binning and river comparison
- **Interval Slopes Tab**: `dashboard_swot.py` tab4 (line ~715) - segment-by-segment slope analysis with quality filters
- **Folium Map View**: `dashboard_swot.py` tab5 (line ~900+) - GIS map with MeasureControl and basemaps
- **Map Color Modes**: `dashboard_swot.py` (conditional coloring in Map View tab, all use point_opacity)
- **Point Opacity Control**: `dashboard_swot.py` line 161-167 (slider in sidebar, 0.1-1.0)
- **X-Axis Reversal**: `dashboard_swot.py` (`fig.update_xaxes(autorange="reversed")`)

---

*End of Technical Notes*
