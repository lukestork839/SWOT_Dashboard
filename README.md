# SWOT River Dynamics Dashboard

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Project Overview

This project analyzes NASA SWOT (Surface Water and Ocean Topography) satellite data to study the hydraulic dynamics of two Alaskan rivers: the **Kanektok River** and **Uyak Creek**. The primary scientific goal is to compare gradient profiles and water surface elevations (WSE) to assess **avulsion risk** at their confluence.

### Study Area
- **Location**: Alaska, USA
- **Primary River**: Kanektok River (main stem, Reach 2)
- **Distributary**: Uyak Creek (branch, Reach 1)
- **Confluence Anchor**: 59.826973°N, -161.372337°W

### Scientific Objective
Compare hydraulic gradients between parallel river channels to assess avulsion risk. If the distributary channel (Uyak Creek) develops a steeper gradient than the main stem, it could divert more flow and increase the likelihood of permanent channel switching (avulsion).

## Key Features

✅ **Resumable Downloads** - Fault-tolerant ingestion survives interruptions
✅ **Automatic Optimization** - Data automatically optimized for dashboard performance
✅ **Progress Tracking** - Real-time progress bars with ETA
✅ **Interactive Dashboard** - Streamlit-based visualization with filtering
✅ **Verified Processing** - All corrections verified against SWOT User Handbook

## Data Source

- **Satellite**: NASA SWOT (launched December 2022)
- **Product**: L2 HR PIXC (High-Resolution Pixel Cloud) Vector Data
- **Versions**:
  - Version D (Provisional) - used when V2.0 unavailable
  - Version 2.0 (Validated) - **preferred**, fixes geolocation errors
- **Quality Filter**: Classes 3 & 4 (water near land + open water)
- **Access**: NASA Earthdata via `earthaccess` Python API

## Quick Start

### 1. Installation

```bash
# Clone repository
git clone https://github.com/lukestork839/SWOT_Dashboard.git
cd SWOT_Dashboard

# Install dependencies
pip install -r requirements.txt
```

### 2. NASA Earthdata Account
Register for a free account at: https://urs.earthdata.nasa.gov/

### 3. Run Data Ingestion

```bash
python Lugia.py
# Enter start date (YYYY-MM-DD)
# Enter end date (YYYY-MM-DD)
```

**Features:**
- Downloads SWOT data for date range
- Skips already-processed dates (resumable!)
- Calculates WSE with geoid + tide corrections
- Automatically creates optimized parquet files
- Shows progress bars with ETA

### 4. Launch Dashboard

```bash
streamlit run dashboard_lugia.py
```

Open browser to `http://localhost:8501`

## Project Structure

```
SWOT_Dashboard/
├── Lugia.py                    # Main data ingestion + optimization pipeline
├── dashboard_lugia.py          # Streamlit interactive dashboard
├── requirements.txt            # Python dependencies
├── river_poly.zip              # Polygon boundaries (2 river reaches)
├── .swot_cli_config.json       # SWOT CLI configuration
├── README.md                   # This file
├── SWOT_Processing_Documentation.md  # Detailed technical documentation
├── batch_outputs/              # Data directory (gitignored)
│   ├── data/                   # Daily CSV checkpoints
│   ├── master_all_data.csv     # Combined dataset
│   └── master_all_data_part_*.parquet  # Optimized partitions
├── Claude/                     # Development notes
│   ├── Claude_notes.md         # Detailed workflow documentation
│   └── Verification_Summary.md # Processing verification summary
└── old_stuff/                  # Deprecated scripts (archived)
```

## Core Methodology

### Distance Calculation (Confluence Anchor Method)
All measurements use a **fixed confluence anchor point**:
- **Anchor Coordinates**: 59.826973°N, -161.372337°W
- **Distance Metric**: Haversine (great-circle) distance
- **Convention**: 0 km = confluence, ~70 km = coast
- **Purpose**: Ensures both rivers measured from common reference point

### Water Surface Elevation (WSE)
```
WSE = height - geoid - solid_earth_tide - pole_tide - load_tide
```

**Components:**
- `height`: Raw satellite measurement (ellipsoidal height)
- `geoid`: EGM2008 geoid correction
- `solid_earth_tide`: Solid Earth tidal displacement (IERS)
- `pole_tide`: Pole tide correction (IERS)
- `load_tide`: Ocean/atmospheric loading (FES2014)

### Gradient Calculation
Linear regression of WSE vs. distance, expressed in **cm/km** for scientific comparison.

## Dashboard Features

### Interactive Controls
- **Date Range Slider**: Filter satellite passes by date
- **River Selection**: Analyze individual rivers or both
- **Multi-tab Interface**: Gradient profile, map view, raw data

### Visualizations
1. **Gradient Profile**: WSE vs. distance scatter plot
   - Linear regression trendlines
   - Slope displayed in cm/km
   - X-axis reversed (coast → confluence)
2. **Map View**: Geographic visualization
   - Mapbox satellite basemap
   - Color-coded by river
3. **Data Inspector**: Tabular view with CSV export

### Performance Optimizations
- **Systematic Sampling**: For datasets > 25,000 points
- **Full Statistics**: Calculations use 100% of data (not sampled)
- **DuckDB Backend**: Fast in-memory SQL queries

## Data Variables

| Variable | Description | Units |
|----------|-------------|-------|
| `wse` | Water Surface Elevation (corrected) | meters (m) |
| `dist_km` | Distance from confluence anchor | kilometers (km) |
| `slope_calc` | River gradient | cm/km |
| `latitude` / `longitude` | Coordinates | degrees |
| `height_uncertainty` | SWOT measurement uncertainty | meters (m) |
| `Pass_Date` | Satellite overpass date | YYYY-MM-DD |
| `Reach_Name` | River identifier | string |

## Configuration

### River Polygons
`river_poly.zip` contains GeoPackage boundaries:
- **Polygon 1**: Uyak Creek
- **Polygon 2**: Kanektok River

### Quality Filters
- **Classifications**: 3 (water near land), 4 (open water)
- **Verified**: QGIS inspection + SWOT Handbook cross-reference
- **Excludes**: Classes 5-7 (dark water, low-coherence)

### Anchor Point
Defined in `Lugia.py`:
```python
ANCHOR_LAT = 59.826973
ANCHOR_LON = -161.372337
```

## Requirements

### Python Version
- Python 3.8 or higher

### Dependencies
See `requirements.txt`. Key packages:
- `earthaccess` - NASA Earthdata authentication
- `xarray` - NetCDF data handling
- `pandas` / `geopandas` - Data manipulation
- `streamlit` - Dashboard framework
- `plotly` - Interactive plotting
- `duckdb` - SQL database
- `tqdm` - Progress bars

## Known Issues & Future Work

### Data Reprocessing Needed
- **Issue**: Jan-May 2024 data contains mixed versions (V_D + V2.0)
- **Impact**: Potential geolocation errors in early 2024 data
- **Resolution**: Re-run Lugia.py for Jan-May 2024 (now easier with resumable downloads!)

### Potential Enhancements
- Add uncertainty propagation using `height_uncert` field
- Implement cross-track filtering (10-60 km range)
- Temporal analysis: how gradients change over time
- Cross-validation with USGS gauge data

## Scientific Context

### Why This Matters
River avulsion (permanent channel switching) is a major hazard:
- Changes flood risk patterns
- Impacts infrastructure and communities
- Alters ecosystem dynamics
- Affects sediment transport

By comparing gradients between parallel channels, we can assess which channel is hydraulically favored and predict potential channel switching.

### SWOT Mission
Launched December 2022, SWOT uses Ka-band Radar Interferometry (KaRIn) to measure water surface elevations with:
- **Spatial Resolution**: ~10-100m pixel spacing
- **Vertical Accuracy**: ~10cm for rivers
- **Coverage**: Narrow rivers previously invisible to satellites

## Documentation

- **`Claude/Claude_notes.md`**: Detailed workflow and development history
- **`Claude/Verification_Summary.md`**: Processing verification against NASA handbook
- **`SWOT_Processing_Documentation.md`**: Complete technical documentation with citations

## Verification

All processing steps verified against:
- **SWOT Science Data Products User Handbook** (JPL D-109532, May 2024)
- Empirical validation via QGIS inspection
- Statistical consistency checks

## Authors & Acknowledgments

- **Developer**: Luke Stork
- **Data Source**: NASA SWOT Mission
- **Geoid Model**: EGM2008
- **Tide Models**: FES2014 (Load), IERS (Solid Earth & Pole)

## License

This project is licensed under the MIT License. SWOT data is publicly available through NASA Earthdata.

## Citation

If you use this code or approach in your research, please cite:
- NASA SWOT Mission: https://swot.jpl.nasa.gov/
- This repository: https://github.com/lukestork839/SWOT_Dashboard

---

**Last Updated**: February 10, 2026
**Status**: Active Development
