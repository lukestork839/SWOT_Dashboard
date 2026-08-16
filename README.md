# SWOT River Dynamics Dashboard

### 🌊 [**Launch the live dashboard →**](https://swotdashboard.streamlit.app/)

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Streamlit](https://img.shields.io/badge/Streamlit-Live%20Dashboard-FF4B4B.svg)](https://swotdashboard.streamlit.app/)

Interactive visualization of NASA SWOT satellite data for two Alaskan rivers (Kanektok River and Uyak Creek), comparing hydraulic gradients to assess avulsion risk.

---

## Quick Start

```bash
git clone https://github.com/lukestork839/SWOT_Dashboard.git
cd SWOT_Dashboard
```

**One-command setup** (creates a virtual environment, installs dependencies, and launches the dashboard):

| Platform | Command |
|----------|---------|
| **Windows** | Double-click `setup.bat` or run it in PowerShell |
| **Linux/Mac** | `./setup.sh` |

**Or manually:**

```bash
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows

python -m pip install -r requirements-full.txt   # Full deps (ingestion + dashboard)
# Or: pip install -r requirements.txt             # Dashboard-only deps
streamlit run dashboard_swot.py
```

Open `http://localhost:8501` in your browser. Without local data, the dashboard loads a remote dataset (May 2025 onward, ~2.6M points) from GitHub Releases via DuckDB. Run `SWOT_Pull.py` to download the full archive locally.

---

## Project Overview

This project has two main components:

```
SWOT_Pull.py ──► batch_outputs/ ──► dashboard_swot.py
(download)        (parquet files)     (visualization)
```

1. **`SWOT_Pull.py`** downloads raw SWOT satellite data from NASA, applies quality filters, computes Water Surface Elevation (WSE), and outputs optimized parquet files.
2. **`dashboard_swot.py`** reads those parquet files and presents an interactive Streamlit dashboard.

You only need step 2 to explore the dashboard. Step 1 is for downloading your own data.

### Data Loading Priority

The dashboard looks for data in this order:

**SWOT Data:**
1. **Full dataset** -- `batch_outputs/master_all_data_part_*.parquet` (created by `SWOT_Pull.py`, local development)
2. **Remote parquet** -- Read directly from GitHub Releases via DuckDB `httpfs` (Streamlit Cloud deployment)

**DEM Data:**
1. **Full DEM dataset** -- `batch_outputs/dem_river_elevations.parquet` (created by `DEM_Pull.py`, local development)
2. **Remote DEM parquet** -- Read from GitHub Releases via DuckDB `httpfs` (Streamlit Cloud deployment)

Both datasets use the same DuckDB httpfs pattern: locally, DuckDB reads from disk; on Streamlit Cloud, it reads remotely from GitHub Releases. DEM profile statistics (medians, percentiles) are computed exactly from all 2.5M points via SQL; map points use `SAMPLE 15000` for rendering performance.

---

## Downloading Full Data

The online dashboard serves ice-safe (May-Oct) data from May 2025 onward (~2.6M points, 50 pass dates). To download the complete SWOT archive (July 2023 onwards) for local use, you need a free NASA Earthdata account.

### 1. Create a NASA Earthdata Account

Register at https://urs.earthdata.nasa.gov/ (free, takes ~2 minutes).

### 2. Run the Ingestion Script

```bash
python SWOT_Pull.py
```

You'll be prompted for:
- **Start date** (YYYY-MM-DD): e.g., `2023-07-01` (SWOT launched July 2023)
- **End date** (YYYY-MM-DD): e.g., `2026-01-01`

On first run, `earthaccess` will prompt for your NASA Earthdata credentials and cache them locally.

### 3. What It Does

For each satellite pass in your date range:

1. Checks if that **granule** is already processed (skips if so -- **resumable**; checkpoints are granule-keyed, so sibling tiles on the same calendar day are never dropped)
2. Downloads the SWOT NetCDF file (~500 MB each, temporary)
3. Extracts pixel cloud data within the river polygon boundaries (`river_poly.zip`)
4. Applies the quality filter chain (see [Scientific Methodology](#scientific-methodology))
5. Computes WSE with geoid and tide corrections
6. Computes distance from the anchor point (Haversine)
7. Saves a granule CSV checkpoint to `batch_outputs/data/YYYY-MM-DD_gCCC_PPP_TTT_data.csv` (cycle / pass / tile in the name)
8. Deletes the temporary NetCDF file

After processing all passes, it rebuilds the master files (applying the May-Oct ice-season and known-bad-pass gates from `qc_registry.py` -- excluded dates remain available as daily CSVs):
- `batch_outputs/master_all_data.csv` -- full dataset (all columns)
- `batch_outputs/master_all_data.parquet` -- optimized single file
- `batch_outputs/master_all_data_part_*.parquet` -- partitioned for dashboard performance

**Typical runtime:** ~2-4 hours for the full 2023-present archive (depends on internet speed). The script is fully resumable -- if interrupted, just run it again and it picks up where it left off.

### 4. Rebuild Without Re-downloading

If you change column settings or want to regenerate master files from existing daily CSVs without re-downloading:

```bash
python rebuild_master.py
```

---

## Dashboard Features

### Analysis Tabs

The dashboard organizes analysis into top-level tabs and nested "More Tabs":

**Top-level:**

| Tab | What It Shows |
|-----|---------------|
| **Gradient Profile** | WSE vs. distance scatter with binned-median profile lines. (The headline steepness number is the per-pass Theil–Sen reference gradient on the **Hydraulic Gradient** tab, not an OLS trendline.) Supports **box-select → Map View highlight** (see below). |
| **Hydraulic Gradient** | The authoritative reach gradient: per-pass Theil–Sen slopes on 1 km node medians, median across coverage-gated open-water passes, with the per-pass distribution. |
| **Fine-Scale Slope** | 0.5–4 km resolution slope profiles computed within each pass (stage constant) then aggregated — resolves the near-bifurcation structure the reach average hides. |
| **Detrended Profile** | Removes the large-scale elevation trend (Relative Elevation Model) with a 2nd-order polynomial baseline fit to both rivers. Reveals subtle systematic differences between rivers. Statistics are reported as robust measures (median, MAD-based robust SD, P1/P99); a residual-domain outlier flag (Modified Z-Score > 3.5, per river) omits localized contamination from the plot and mean/SD without deleting it. Supports **box-select → Map View highlight** (see below). |
| **Map View** | Interactive Folium map with multiple basemaps (satellite, terrain, etc.), measuring tools for distance/area, and color-by options (river name, WSE, classification, detrended residual, interval slope). Shows points **box-selected on a profile** as yellow-outlined markers. |

> **Profile → Map cross-highlight:** on the **Gradient Profile** or **Detrended Profile**, drag a box (or lasso) around points of interest. Those exact points are outlined in yellow (keeping their river color) on the **Map View**, which auto-zooms to them so you can see where along the river they sit. Selections from both profiles combine; a **Clear highlight** button on the map resets them. Requires `streamlit>=1.49`.

**DEM Data tab** (with subtabs):

| Tab | What It Shows |
|-----|---------------|
| **Terrain Profile** | Median ArcticDEM elevation along each river corridor with linear regression trendlines (cm/km, R²). |
| **Elevation Difference** | Kanektok minus Uyak terrain elevation per 0.5 km bin -- analogous to alluvial ridge height (Slingerland & Smith, 1998). |
| **Terrain Slope** | Local terrain gradient along each corridor (Gaussian-smoothed numerical derivative). |
| **Detrended Profile** | Removes regional downstream gradient (2nd-order polynomial) to reveal where each corridor sits above or below the trend. |
| **Map View** | Interactive Folium map of DEM elevation points. Color by river name or elevation (viridis). Basemap toggle, measurement tools. |
| **Cross-Sections** | DEM arc cross-sections at 0.5 km radii from the anchor with SWOT stage overlays, superelevation metrics, and the ADCP-informed channel bed. |

See [DEM Elevation Comparison](#dem-elevation-comparison) for methodology.

**SWOT nested tabs:**

| Tab | What It Shows |
|-----|---------------|
| **Elevation Difference** | Direct Kanektok minus Uyak WSE comparison in 100m distance bins. Shows which river is higher at each point. |
| **Slope Profile** | How steepness varies along each river. Uses Gaussian-smoothed binned medians with numerical derivative. |
| **Raw Data** | Table view of the data with CSV export. |
| **Temporal Results** | Read-only display of the one-time temporal-stability analysis (seasonal, interannual, and pre/post-Typhoon Halong). Shows the control-chart time series, stage-invariance scatter, distribution comparisons, and the interim typhoon spatial-delta, plus result tables. Rendered from pre-computed files — no on-the-fly computation. |

The former interactive **Temporal Evolution**, **Seasonal Comparison**, and **Typhoon Impact** tabs (density-biased, per-selection) have been retired. Their questions are now answered by a single, methodology-locked one-time analysis (`temporal_analysis.py`), whose results the **Temporal Results** tab displays. See [`TEMPORAL_ANALYSIS.md`](TEMPORAL_ANALYSIS.md) for the full write-up. Because the results are pre-computed (git-tracked in `temporal_results/`), this tab is available on both the local and the deployed Streamlit Cloud dashboard.

### Controls

There is no sidebar. Satellite passes are chosen on the **welcome page** (quick
presets or an explicit checklist); both rivers are always analyzed together, and
the detrending baseline is fixed (2nd-order polynomial). Map display options
(color-by metric, basemap style) live on the Map View tab itself.

---

## Scientific Methodology

### WSE Formula

```
WSE = height - geoid - solid_earth_tide - pole_tide - load_tide
```

All corrections verified against the SWOT Science Data Products User Handbook (JPL D-109532, Section 11.3). Field-validated with RTK GPS in November 2025 at Quinhagak, Alaska.

| Correction | Model | Typical Magnitude |
|------------|-------|-------------------|
| Geoid | EGM2008 | ~13.3 m (at study site) |
| Solid Earth Tide | IERS | ~0.024 m |
| Pole Tide | IERS | ~0.002 m |
| Load Tide | FES2014 | ~0.001 m |

### Quality Filter Chain (Applied in Order)

| # | Filter | Criterion | Purpose |
|---|--------|-----------|---------|
| 1 | Bounding box | +/- 0.02 deg buffer | Fast spatial pre-filter |
| 2 | Polygon clipping | `.within()` against `river_poly.zip` | Exact river boundaries |
| 3 | Cross-track distance | 10-60 km from nadir | Avoids nadir gap and far-swath noise |
| 4 | Crossover calibration | Bit 23 of `geolocation_qual` = 0 | Excludes pixels without crossover correction (meter-scale errors) |
| 5 | Classification | Classes 3 and 4 only | Keeps high-quality water pixels (Handbook Table 6.1) |
| 6 | MAD outlier removal | Modified Z-score <= 3.5, per-reach, on **1 km node-median residuals** | Removes anomalous WSE measurements without touching the river's real along-stream relief |
| 7 | Ice-season + bad-pass gate | Month in May-Oct and pass not in `KNOWN_BAD_PASSES` (`qc_registry.py`) | Excludes ice-affected passes from the master (winter/shoulder data stays in the daily CSVs) |

**Note on the MAD domain (revised Aug 2026):** the filter subtracts each pixel's 1 km node-median WSE before screening, so it only ever sees within-node scatter. The previous raw-WSE version read the ~66 m of real downstream relief as spread — it both let localized contamination through *and* amputated legitimate upstream reaches on dates where pixel density was downstream-weighted. The Detrended Profile tab additionally applies a display-layer Modified Z-Score flag on its residuals (no data deleted).

**Pending expert review:** `geolocation_qual` and `classification_qual` bit-mask filters are implemented but disabled. They remove nearly all data for narrow rivers (~50-100m wide) like Uyak Creek due to land/water mixing effects. See `SCIENTIFIC_METHODOLOGY.md` for the full PIXC quality flag reference.

### Distance Calculation

All measurements referenced to a common anchor point using Haversine great-circle distance:

```python
ANCHOR_LAT = 59.82463509   # just upriver of the bifurcation
ANCHOR_LON = -161.33397834
```

Convention: 0 km = anchor point (~2.5 km upriver of the bifurcation), ~36 km = coast. X-axis is reversed in all plots (coast on left, anchor point on right).

### Ice Season Awareness

At ~59.8N, smooth river ice passes through the Class 3-4 quality filter and is misclassified as water -- Uyak Creek shows 80-95% Class 4 pixels during peak freeze (vs 35-55% in open water), inflating WSE by 0.5-2+ m. An empirical audit of the full archive (Aug 2026) found April breakup contamination **every** year, consistently clean October data, and the first freeze-up signal in mid-November.

- The pipeline therefore enforces a **hard May-Oct line at ingestion** (`qc_registry.ICE_SAFE_MONTHS`): the master files and all analyses contain only ice-safe months
- Winter/shoulder passes are still downloaded and preserved in the daily CSVs (not deleted) for potential ice studies
- The dashboard additionally shows a warning banner if winter dates ever appear in a selection
- Uyak Creek (narrow, shallow) freezes more completely than Kanektok River (wider, deeper)

### DEM Elevation Comparison

The dashboard includes a DEM comparison tab that overlays ArcticDEM V4 terrain elevation with SWOT water surface measurements. This provides an independent elevation reference and enables analysis of channel geometry (bank height, floodplain relief).

**Data source:** ArcticDEM V4 2m mosaic ([UMN/PGC](https://www.pgc.umn.edu/data/arcticdem/)), exported via Google Earth Engine and sampled at 10m resolution within the river polygons. The extraction script is `DEM_Pull.py`.

**Vertical datum alignment:** ArcticDEM reports elevations as WGS84 ellipsoidal heights, while SWOT WSE is orthometric (referenced to the EGM2008 geoid). The raw offset between the two datums is approximately 13.2-13.8m across the study area. `DEM_Pull.py` corrects for this by subtracting the EGM2008 geoid undulation from each DEM pixel, using a spatially-varying geoid surface interpolated from the per-pixel geoid values in the SWOT data (the same EGM2008 values used in the SWOT WSE calculation). This places both datasets on the same vertical datum.

**Validation:** The ArcticDEM V4 was independently validated against NOAA 2024 QL1 LiDAR (11 pts/m, 0.05m vertical RMSE) for the Quinhagak area, achieving 0.50m RMSE on vegetated pixels -- confirming near bare-earth accuracy in this low-stature tundra/shrub environment. See the companion ArcticDEM project for full validation methodology.

For the complete scientific documentation, see:
- [`SCIENTIFIC_METHODOLOGY.md`](SCIENTIFIC_METHODOLOGY.md) -- verification, quality flag reference, calibration results
- [`SWOT_Processing_Documentation.md`](SWOT_Processing_Documentation.md) -- detailed technical processing documentation

---

## Project Structure

```
SWOT_Dashboard/
├── setup.bat                        # One-command setup for Windows
├── setup.sh                         # One-command setup for Linux/Mac
├── SWOT_Pull.py                     # Data ingestion: NASA download + processing pipeline
├── DEM_Pull.py                      # ArcticDEM extraction: GEE download + geoid correction
├── dashboard_swot.py                # Visualization: Streamlit dashboard (~2500 lines)
├── qc_registry.py                   # Single source: ice-safe months (May-Oct) + known-bad passes
├── rebuild_master.py                # Utility: rebuild master parquets from granule CSVs
├── requirements.txt                 # Dashboard dependencies (used by Streamlit Cloud)
├── requirements-full.txt            # Full dependencies including ingestion pipeline
├── river_poly.zip                   # River boundary polygons (GeoPackage format)
├── batch_outputs/                   # Full dataset directory (gitignored, created by SWOT_Pull.py)
│   ├── data/                        #   Granule CSV checkpoints (YYYY-MM-DD_gCCC_PPP_TTT_data.csv)
│   ├── master_all_data.csv          #   Combined dataset, all columns
│   ├── master_all_data.parquet      #   Single optimized parquet
│   ├── master_all_data_part_*.parquet  # Partitioned for dashboard performance
│   ├── arcticdem_rivers.tif         #   ArcticDEM V4 clipped to study area (from DEM_Pull.py)
│   └── dem_river_elevations.parquet #   DEM elevations within river polygons (geoid-corrected)
├── .streamlit/
│   └── config.toml                  # Streamlit server/theme configuration
├── SCIENTIFIC_METHODOLOGY.md        # Complete scientific verification document
├── SWOT_Processing_Documentation.md # Detailed technical processing docs
└── README.md                        # This file
```

---

## Tech Stack

| Component | Library | Purpose |
|-----------|---------|---------|
| Satellite data access | `earthaccess` | NASA Earthdata authentication and download |
| NetCDF reading | `xarray`, `netCDF4` | Read SWOT HDF5/NetCDF files |
| Data processing | `pandas`, `numpy`, `scipy` | Tabular data, math, linear regression |
| Spatial operations | `geopandas`, `shapely` | Polygon clipping, coordinate transforms |
| Dashboard framework | `streamlit` | Web UI with interactive widgets |
| Charts | `plotly` | Interactive scatter, line, heatmap plots |
| Maps | `folium`, `streamlit-folium` | Interactive maps with measuring tools |
| Database | `duckdb` | In-memory SQL queries on parquet files |
| Progress bars | `tqdm` | Progress feedback during long downloads |

---

## Configuration Reference

### `SWOT_Pull.py` Settings

All configurable constants are at the top of `SWOT_Pull.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `POLYGON_PATH` | `river_poly.zip` (relative) | Path to river boundary polygons |
| `ANCHOR_LAT/LON` | 59.825, -161.334 | Anchor point for distance calculation |
| `DEFAULT_CLASSES` | `[3, 4]` | SWOT classification classes to keep |
| `CROSS_TRACK_MIN/MAX` | 10,000 / 60,000 m | Cross-track distance filter range |
| `XOVERCAL_MISSING_MASK` | Bit 23 (8388608) | Crossover calibration missing flag |
| `MAD_THRESHOLD` | 3.5 | Modified Z-score threshold for outlier detection |
| `MAD_NODE_KM` | 1.0 | Node size for the residual reference profile (matches the reference gradient) |
| `MIN_POINTS_FOR_MAD` | 10 | Minimum points to apply MAD filter |
| `KEEP_COLUMNS` | (see code) | Columns preserved in output parquets |
| `ROWS_PER_CHUNK` | 100,000 | Rows per partition file |
| `NAME_MAPPING` | `{1: Uyak, 2: Kanektok}` | Polygon ID to river name mapping |

### `dashboard_swot.py` Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `DATA_DIR` | `batch_outputs` | Directory for full dataset (local dev) |
| `REMOTE_PARQUET_URL` | GitHub Release URL | Remote SWOT parquet for Streamlit Cloud |
| `REMOTE_DEM_URL` | GitHub Release URL | Remote DEM parquet for Streamlit Cloud |
| `MAX_PLOT_POINTS` | 15,000 | Max points rendered in scatter plots |
| `MAX_BASELINE_POINTS` | 30,000 | Max points for detrending baseline fit |
| `MAX_MAP_POINTS` | 5,000 | Max points rendered on Folium map |
| `BIFURCATION_LAT` | 59.828886 | Latitude of river bifurcation point |
| `BIFURCATION_LON` | -161.377778 | Longitude of river bifurcation point |
| `BIFURCATION_DIST_KM` | 2.493 | Distance from anchor point to bifurcation |

---

## Adapting for Your Own Rivers

To use this framework for a different study area:

1. **Create river polygons** -- Use QGIS or similar to draw polygon boundaries around your rivers. Save as a GeoPackage or Shapefile in EPSG:4326 (WGS84). Zip the result and replace `river_poly.zip`.

2. **Update `SWOT_Pull.py`**:
   - Set `ANCHOR_LAT`/`ANCHOR_LON` to your reference point
   - Update `NAME_MAPPING` with your river names and polygon IDs
   - Adjust `CROSS_TRACK_MIN/MAX` if needed for your study area geometry

3. **Run the pipeline**:
   ```bash
   python SWOT_Pull.py
   # Enter your date range
   ```

4. **Launch the dashboard**:
   ```bash
   streamlit run dashboard_swot.py
   ```
   The dashboard auto-detects river names from the data -- no dashboard code changes needed.

**Note:** The dashboard color mapping (`COLOR_MAP` in `dashboard_swot.py`) defaults to Kanektok/Uyak colors. Update this dict if you want specific colors for your rivers. If your river names aren't in the map, the dashboard falls back to black.

---

## Troubleshooting

### Windows: `python` or `pip` not recognized

Python is installed but Windows can't find it. Try these in order:

1. Open Start Menu, search **"Manage app execution aliases"**, turn OFF `python.exe` and `python3.exe`
2. Use `python -m pip` instead of `pip` directly
3. If Python isn't installed: download from https://www.python.org/downloads/ and **check "Add python.exe to PATH"** during install

### `earthaccess` authentication fails

On first run, `earthaccess.login()` will prompt for your NASA Earthdata username and password. Credentials are cached in `~/.netrc`. If authentication fails:
- Verify your account at https://urs.earthdata.nasa.gov/
- Delete `~/.netrc` and try again
- Check that you've accepted the SWOT data EULA on the Earthdata website

### Dashboard shows "No data found"

The dashboard requires at least one data source. Check:
1. If running locally, does `batch_outputs/master_all_data_part_*.parquet` exist? (Run `SWOT_Pull.py` first.)
2. If on Streamlit Cloud, check that the GitHub Release at `v2.0-data` exists and contains the parquet file.

### Streamlit port already in use

```bash
streamlit run dashboard_swot.py --server.port 8502
```

### `geopandas` or `shapely` installation issues

These packages have C dependencies. If `pip install` fails:
```bash
# Ubuntu/Debian
sudo apt-get install libgdal-dev libspatialindex-dev

# macOS
brew install gdal spatialindex

# Or use conda instead of pip
conda install -c conda-forge geopandas
```

### Map tab is slow or crashes

The Folium map renders individual circle markers in Python, which is expensive. The dashboard limits map points to 5,000 (configurable via `MAX_MAP_POINTS`). If it's still slow, reduce this value.

### Download interrupted mid-run

Just run `SWOT_Pull.py` again with the same date range. It checks for existing granule CSVs and skips already-processed granules automatically.

---

## Citation

**SWOT Mission:**
- NASA SWOT Mission: https://swot.jpl.nasa.gov/
- JPL D-109532: SWOT Science Data Products User Handbook (May 2024)

**This Repository:**
- Luke Stork (2026). SWOT River Dynamics Dashboard. GitHub: https://github.com/lukestork839/SWOT_Dashboard

---

## License

MIT License -- SWOT data is publicly available through NASA Earthdata.
