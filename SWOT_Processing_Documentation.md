# SWOT Data Processing Documentation
## Kanektok River - Uyak Creek Avulsion Risk Assessment

**Study Location:** Kanektok River distributary system, Alaska
**Reference Point:** 59.82463509°N, -161.33397834°W (upriver of bifurcation point where Uyak diverges from Kanektok)
**Scientific Objective:** Assess avulsion risk by comparing hydraulic gradients between parallel channels

---

## 1. Data Products & Versions

### Primary Data Product
- **Product Name:** `SWOT_L2_HR_PIXC` (High-Resolution Pixel Cloud)
- **Product Level:** Level 2 (geolocated, calibrated)
- **Spatial Resolution:** ~10-100m pixel spacing
- **Measurement Type:** Ka-band Radar Interferometry (KaRIn)

### Version Strategy
We use **Version D** exclusively — the latest science algorithm version:

| Version | Collection Name | Status | Notes |
|---------|-----------------|--------|-------|
| **Version D** | `SWOT_L2_HR_PIXC_D` | **Current recommended** | Updated algorithms, calibration, and geophysical models |
| Version C (2.0) | `SWOT_L2_HR_PIXC_2.0` | **Superseded** | Full mission archive reprocessed into Version D (early 2026) |

**Implementation:** Version D data is searched via `earthaccess` API using `short_name="SWOT_L2_HR_PIXC_D"`. Version D includes reprocessed historical data (PGD0) covering the full mission timeline from March 2023 onward, plus forward-processed data (PID0) from May 2025 onward.

---

## 2. Spatial Filtering

### Polygon-Based Clipping
**File:** `river_poly.zip` (GeoPackage format)
**CRS:** EPSG:4326 (WGS84 geographic coordinates)
**Polygons:** 2 features
- Polygon 1: Uyak Creek
- Polygon 2: Kanektok River

### Two-Stage Spatial Filter

**Stage 1 - Rough Bounding Box:**
```python
mask_rough = (
    (lon >= bounds[0] - 0.02) & (lon <= bounds[2] + 0.02) &
    (lat >= bounds[1] - 0.02) & (lat <= bounds[3] + 0.02)
)
```
- Purpose: Fast vectorized pre-filter
- Buffer: ±0.02° (~2 km) around polygon bounds

**Stage 2 - Exact Geometry Match:**
```python
gdf_temp = gpd.GeoDataFrame(df, geometry=points, crs="EPSG:4326")
df_exact = gdf_temp[gdf_temp.geometry.within(polygon)]
```
- Purpose: Precise inclusion test using Shapely `.within()` operation
- Result: Only pixels with centroids inside polygon boundaries retained

**Longitude Normalization:**
```python
lon_normalized = ((lon + 180) % 360) - 180
```
Applied when `lon > 180` to handle 180° meridian crossing issues in Alaskan coordinates.

---

## 3. Water Surface Elevation (WSE) Calculation

### Formula
```
WSE = height - geoid - solid_earth_tide - pole_tide - load_tide
```

### Variable Definitions

| SWOT Variable | Description | Model/Source | Units |
|---------------|-------------|--------------|-------|
| `height` | Ellipsoidal height (raw measurement) | KaRIn instrument | meters |
| `geoid` | Geoid undulation (EGM2008) | EGM2008 global model | meters |
| `solid_earth_tide` | Solid Earth tidal displacement | IERS conventions | meters |
| `pole_tide` | Pole tide displacement | IERS conventions | meters |
| `load_tide_fes` | Ocean/atmospheric loading tide | FES2014 model | meters |

**Note on Load Tide Variable:** Code checks for `load_tide_fes` first, with fallback to `load_tide_height` if unavailable, for backward compatibility across data versions.

### Corrections Already Applied to `height`
According to SWOT documentation, the `height` field has undergone:
- ✅ Instrument calibration
- ✅ Ionospheric delay correction
- ✅ Dry tropospheric delay correction
- ✅ Wet tropospheric delay correction
- ✅ Cross-calibration adjustments

### Corrections Applied by User (Us)
- ✅ Geoid removal (EGM2008)
- ✅ Solid Earth tide correction
- ✅ Pole tide correction
- ✅ Load tide correction

**Result:** WSE represents water surface elevation relative to the geoid (mean sea level reference).

---

## 4. Quality Filtering

We apply seven sequential filters to extract only the highest-quality pixels. Since we need only a few hundred reliable points per pass for gradient calculation, we maximize strictness.

### Complete Filter Chain

| # | Filter | Criterion | Rationale |
|---|--------|-----------|-----------|
| 1 | Rough bounding box | ±0.02° buffer | Fast spatial pre-filter |
| 2 | Exact polygon clipping | `.within()` river polygon | Isolate river channel pixels |
| 3 | Cross-track distance | 10–60 km from nadir | Avoid nadir gap and far-swath noise |
| 4 | Geolocation quality | `geolocation_qual == 0` | Remove phase unwrapping errors, layover, poor geolocation |
| 5 | Classification quality | `classification_qual == 0` | Ensure classification assignment is reliable |
| 6 | Classification | Classes 3 & 4 only | Keep reliable water pixels (Table 6.1, Page 76) |
| 7 | MAD outlier filter | Modified Z-score ≤ 3.5 | Remove anomalous WSE values (per-reach) |

### PIXC Quality Flag Filters (Filters 3–5)

**Reference:** SWOT Handbook Section 3.1.26 (Good, Suspect, Degraded, and Bad Quality); PO.DAAC best practices

The L2_HR_PIXC product contains per-pixel bit-flag quality variables. A value of 0 means all quality checks passed (no flags raised). Any non-zero value indicates at least one quality concern.

```python
# Cross-track: avoid nadir gap and far-swath noise
CROSS_TRACK_MIN = 10000   # 10 km from nadir (meters)
CROSS_TRACK_MAX = 60000   # 60 km from nadir (meters)
ct_mask = (np.abs(df['cross_track']) >= CROSS_TRACK_MIN) & \
          (np.abs(df['cross_track']) <= CROSS_TRACK_MAX)

# Geolocation quality: no phase unwrapping/layover/positioning issues
geo_mask = df['geolocation_qual'] == 0

# Classification quality: classification assignment is trustworthy
cls_qual_mask = df['classification_qual'] == 0
```

**`geolocation_qual` bit flags include:** `phase_unwrapping_suspect`, `layover_significant`, `phase_noise_suspect`

**`classification_qual` bit flags include:** `no_coherent_gain`, `detected_water_but_no_prior_water`, `water_false_detection_rate_suspect`

### Classification Filter (Filter 6)

**Official Definitions (Table 6.1, Page 76, JPL D-109532):**

| Class | Definition | Our Usage |
|-------|------------|-----------|
| 1 | Land | ❌ Excluded |
| 2 | Land near water | ❌ Excluded |
| **3** | **Water near land** | **✅ Included** |
| **4** | **Open water** | **✅ Included** |
| 5 | Dark water | ❌ Excluded |
| 6 | Low-coherence water near land | ❌ Excluded |
| 7 | Open low-coherence water | ❌ Excluded |

```python
DEFAULT_CLASSES = [3, 4]
df_final = df_exact[df_exact['classification'].isin(DEFAULT_CLASSES)]
```

**Rationale:** Classes 3 & 4 represent high-quality water detection. Class 3 is critical for narrow rivers (captures near-bank measurements). Classes 5–7 are low-coherence and introduce noise. Empirically validated via QGIS inspection of June 2025 data.

### MAD Outlier Filter (Filter 7)

**Method:** Modified Z-Score using Median Absolute Deviation (Iglewicz & Hoaglin, 1993)

```python
Modified Z = 0.6745 × (WSE - median) / MAD
Outlier if |Modified Z| > 3.5
```

- Applied per-reach (independent filtering for each river)
- Minimum 10 points required; preserves minimum 5 points
- Threshold 3.5 is conservative (~3.5 sigma equivalent)

### Observed Data Reduction

Full run (July 2023 – December 2025, 295 granules):

| Metric | Value |
|--------|-------|
| **Total points (after all filters)** | 785,932 |
| **Compared to classification-only filtering** | ~88% reduction |
| **Most aggressive filter** | `geolocation_qual == 0` (retains ~4–15%) |
| **Kanektok River** | 748,767 points across 133 dates (avg 5,630/pass) |
| **Uyak Creek** | 37,165 points across 122 dates (avg 305/pass) |

---

## 5. Distance Calculation

### Method: Haversine Great-Circle Distance

**Reference Point (Anchor):**
- Latitude: 59.82463509°N
- Longitude: -161.33397834°W
- Physical Location: Upriver of bifurcation point where Uyak Creek diverges from Kanektok River

**Formula Implementation:**
```python
def haversine_vectorized(lat1, lon1, lat2, lon2):
    R = 6371.0  # Earth radius in km

    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)

    a = np.sin(dphi/2)**2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda/2)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))

    return R * c
```

**Key Properties:**
- Spherical Earth approximation (appropriate for <100 km distances)
- Great-circle distance (shortest path on sphere surface)
- Vectorized using NumPy for computational efficiency

**Distance Convention:**
- **0 km** = Split point (upriver, inland)
- **~70 km** = Ocean entry (downriver, coast)
- Both channels measured from same reference point (enables direct comparison)

---

## 6. Gradient Calculation

### Method: Linear Regression (Ordinary Least Squares)

**Per-Reach Calculation:**
```python
from scipy import stats

for reach_name in ['Uyak_Creek', 'Kanektok_River']:
    subset = df[df['Reach_Name'] == reach_name]
    slope, intercept, r_value, p_value, std_err = stats.linregress(
        subset['dist_km'],
        subset['wse']
    )
    slope_cm_per_km = slope * 100  # Convert m/km to cm/km
```

**Units Convention:**
- **Input:** WSE in meters, distance in kilometers
- **Output:** Gradient in **cm/km** (centimeters per kilometer)
- **Interpretation:** Positive slope = downstream increase in WSE (unusual), negative slope = normal downstream decrease

**Statistical Properties:**
- Model: WSE = slope × distance + intercept
- Each satellite pass provides independent gradient estimate
- Temporal averaging across multiple passes reduces measurement noise

---

## 6.5 DEM Elevation Comparison

### Data Source & Extraction

ArcticDEM V4 2m mosaic (Polar Geospatial Center, University of Minnesota) is used as an independent terrain elevation reference. The extraction pipeline (`DEM_Pull.py`):

1. **Export:** Downloads a GeoTIFF from Google Earth Engine, clipped to the river polygon bounding box with a ~500m buffer, resampled to 10m resolution
2. **Sample:** Uses rasterio to mask the GeoTIFF to each river polygon, extracting elevation and coordinates for every pixel within the polygon boundaries
3. **Geoid correction:** Converts WGS84 ellipsoidal heights to EGM2008 orthometric heights (see below)
4. **Distance:** Calculates Haversine distance from the confluence anchor (same function as `SWOT_Pull.py`)
5. **Output:** `batch_outputs/dem_river_elevations.parquet` with columns matching the SWOT schema (`Reach_Name`, `dist_km`, `wse`, `latitude`, `longitude`)

### Vertical Datum Alignment

ArcticDEM native heights are WGS84 ellipsoidal. SWOT WSE is orthometric (EGM2008 geoid-referenced). The geoid-ellipsoid separation at the study site is ~13.2–13.8m, varying spatially over the 35 km river extent.

The correction uses the EGM2008 geoid values already stored in the SWOT daily CSVs (the same values subtracted during WSE calculation). These are binned to a ~0.005° grid and interpolated with `scipy.interpolate.LinearNDInterpolator` to create a continuous geoid surface. Each DEM pixel is corrected:

```
dem_orthometric = dem_ellipsoidal − geoid_undulation(lat, lon)
```

This ensures the DEM and SWOT datasets are on identical vertical datums.

### Dashboard Data Loading

The dashboard loads DEM data via DuckDB queries, using the same httpfs pattern as the SWOT data:

- **Local development:** DuckDB reads `batch_outputs/dem_river_elevations.parquet` from disk
- **Streamlit Cloud:** DuckDB reads the same file remotely from GitHub Release `v2.0-data` via httpfs

Two cached query functions provide the data:

1. **`load_dem_profile()`** — SQL aggregation computing exact MEDIAN and PERCENTILE_CONT (p10/p25/p75/p90) per 0.5 km bin from all ~2.5M rows. Returns 142 rows used by profile subtabs (1–4) and summary statistics. Zero sampling error.
2. **`load_dem_points()`** — SQL `USING SAMPLE 15000` for the map view. Provides spatially representative point coverage for rendering.

### Dashboard Analyses

The DEM Data tab contains five subtabs plus a summary statistics section:

| Analysis | Method | Scientific Basis |
|----------|--------|-----------------|
| **Terrain Profile** | Median elevation per 0.5 km bin + linear regression (with R²) | Standard longitudinal profile analysis |
| **Elevation Difference** | Per-bin Kanektok median − Uyak median | Alluvial ridge height (Slingerland & Smith, 1998) |
| **Terrain Slope** | Central-difference numerical gradient, Gaussian-smoothed (σ = 1.5 km) | Local gradient analysis |
| **Detrended Profile** | Residuals from 2nd-order polynomial fit to both rivers | Concave-up profile assumption (Hack, 1957; Flint, 1974) |
| **Map View** | Folium map with elevation or river-name coloring | Spatial data exploration |
| **Summary Stats** | Distance-weighted bin medians averaged per river | Same methodology as SWOT summary stats |

All profile charts include a dashed vertical line at 2.493 km marking the **bifurcation point** — where Uyak Creek diverges from Kanektok River (59°49'43.99"N, 161°22'40.00"W). Both map views display a green marker pin at this location.

### Interpretation

The DEM captures terrain surface elevation within the river polygons — this includes channel banks, exposed bars, and near-channel floodplain, not just the water surface. The analyses are designed around the Slingerland & Smith (1998) avulsion framework, where cross-corridor elevation differences and slope ratios are first-order controls on channel switching. Gearon et al. (2024) validated this approach globally, showing topographic metrics alone can predict avulsion likelihood.

---

## 7. Visualization & Analysis

### Dashboard: Streamlit + DuckDB + Plotly

**Data Backend:**
```python
# DuckDB query on partitioned Parquet files
parquet_pattern = "batch_outputs/master_all_data_part_*.parquet"
con.execute(f"""
    CREATE OR REPLACE VIEW river_data AS
    SELECT * FROM read_parquet('{parquet_pattern}')
""")
```

**Performance Optimization:**

| Data Size | Strategy | Rationale |
|-----------|----------|-----------|
| ≤ 25,000 points | Plot all data | Browser can handle without lag |
| > 25,000 points | Systematic sampling for visualization | Prevents browser performance issues |
| All sizes | Full data for statistics | Ensures accuracy of gradient calculations |

**Systematic Sampling Method:**
```sql
ROW_NUMBER() OVER (ORDER BY Reach_Name, dist_km, Pass_Date) AS row_num
WHERE MOD(row_num, sample_interval) = 0
```
- Preserves spatial distribution
- Maintains temporal coverage
- Deterministic (reproducible)

### Plot Configuration

**Gradient Profile (Primary Analysis Plot):**
```
X-axis: Distance from split (km) - REVERSED (coast on left, split on right)
Y-axis: Water Surface Elevation (m above geoid)
Colors: Uyak Creek = dodgerblue, Kanektok River = firebrick
Trendlines: Linear regression (dashed lines) with slope displayed in legend
```

**X-Axis Reversal Rationale:**
- Visual convention: Coast (downstream) on left, headwaters (upstream) on right
- Matches intuitive reading direction for longitudinal river profiles
- Implemented via: `fig.update_xaxes(autorange="reversed")`

**Map View:**
- Base layer: Mapbox satellite imagery
- Points colored by reach
- Shows geographic distribution of measurements
- Validates polygon clipping accuracy

---

## 8. Data Provenance & Reproducibility

### Complete Processing Chain

```
NASA Earthdata → earthaccess API → SWOT_L2_HR_PIXC_D (Version D)
         ↓
SWOT_Pull.py: Download NetCDF → Extract pixel_cloud variables
         ↓
Spatial filtering (bounding box → exact polygon clipping)
         ↓
WSE calculation + distance from confluence (Haversine)
         ↓
PIXC quality filters (cross-track → geolocation_qual → classification_qual)
         ↓
Classification filter (Classes 3-4)
         ↓
MAD outlier filter (per-reach, threshold 3.5)
         ↓
Gradient calculation (scipy.stats.linregress)
         ↓
Daily CSV: batch_outputs/data/YYYY-MM-DD_data.csv
         ↓
Rebuild master: master_all_data.csv + optimized Parquet partitions
         ↓
dashboard_swot.py (DuckDB + Plotly + Folium)
```

### Output Data Schema

| Column | Type | Units | Description |
|--------|------|-------|-------------|
| `Reach_Name` | string | - | "Uyak_Creek" or "Kanektok_River" |
| `Pass_Date` | date | YYYY-MM-DD | Satellite overpass date |
| `latitude` | float | degrees | WGS84 latitude |
| `longitude` | float | degrees | WGS84 longitude |
| `wse` | float | meters | Water surface elevation (geoid-relative) |
| `dist_km` | float | kilometers | Distance from split point |
| `slope_calc` | float | cm/km | River gradient (from linear regression) |
| `height_uncertainty` | float | meters | SWOT measurement uncertainty |

**File Format:** Apache Parquet (columnar, compressed, partitioned for GitHub size limits)

---

## 9. Key Decisions & Assumptions

### Decisions

| Decision | Rationale | Alternative Considered |
|----------|-----------|------------------------|
| Version D only | Latest science algorithms; full mission reprocessed | Version C (2.0) — superseded, no longer recommended |
| PIXC quality flags == 0 | Strictest filtering; we need few points not many | `geolocation_qual < 4` (less strict) — retains more uncertain pixels |
| Classification = 3 & 4 | High-quality water classes; validated in QGIS | Class > 2 (NASA standard) — may include lower quality pixels |
| MAD threshold 3.5 | Conservative; standard in hydrology literature | IQR — less robust for non-symmetric distributions |
| Haversine distance | Appropriate for <100km distances; computationally fast | Geodesic (Vincenty) — unnecessary precision for this scale |
| Linear regression for gradient | Standard method; simple interpretation | Moving window / local gradient — adds complexity |
| Reversed x-axis | Standard convention for longitudinal profiles | Forward axis — less intuitive for river profiles |

### Assumptions

1. **Spherical Earth:** Haversine assumes perfect sphere (error <0.5% at high latitudes)
2. **Steady Flow:** Gradient calculations assume each pass represents quasi-steady conditions
3. **Single Reference:** All measurements from one anchor point (ignores along-channel path differences)
4. **Linear Gradient:** Regression assumes constant slope (real rivers have variable gradients)

---

## 10. Verification Status & Remaining Validation Steps

### ✅ VERIFIED FROM SWOT USER HANDBOOK (JPL D-109532)
- [x] **Classification definitions**: Table 6.1 (Page 76) confirms Class 3 = Water near land, Class 4 = Open water
- [x] **Geoid correction**: EGM2008 model (Section 11.3.1, Page 185)
- [x] **Solid Earth tide**: Provided in KaRIn HR products (Section 11.3.4.1, Page 188)
- [x] **Load tide**: Provided in KaRIn HR products (Section 11.3.4.1, Page 189)
- [x] **Pole tide**: Provided in KaRIn HR products (Section 11.3.4.2, Page 190)
- [x] **WSE formula**: Confirmed correct (height - geoid - tides)
- [x] **Classes 3 & 4 selection**: Verified via QGIS inspection of June 2025 data

### Remaining Validation Steps
- [x] ~~Investigate: Should we add `geolocation_qual` filter~~ → Implemented: `geolocation_qual == 0` (strictest)
- [x] ~~Consider: Cross-track distance filtering~~ → Implemented: 10-60 km range
- [x] ~~Classification quality filter~~ → Implemented: `classification_qual == 0`

### Cross-Validation
- [ ] Compare SWOT gradients to:
  - USGS gauge data (if available)
  - DEM-derived slopes
  - Historical river surveys
- [ ] Check temporal consistency: Do gradients change seasonally or remain stable?

### Uncertainty Quantification
- [ ] Propagate `height_uncert` through WSE calculation
- [ ] Assess regression uncertainty (confidence intervals on slope estimates)
- [ ] Evaluate impact of sampling density on gradient estimates

---

## 11. Software Environment

### Dependencies
```
earthaccess >= 0.5.0      # NASA Earthdata authentication & download
xarray >= 2023.0.0        # NetCDF data handling
pandas >= 2.0.0           # Tabular data manipulation
geopandas >= 0.13.0       # Spatial data operations
numpy >= 1.24.0           # Numerical computing
scipy >= 1.10.0           # Statistical functions (linregress)
streamlit >= 1.28.0       # Dashboard framework
plotly >= 5.17.0          # Interactive plotting
duckdb >= 0.9.0           # In-memory SQL database
```

### System Requirements
- Python 3.8+
- NASA Earthdata account (free registration)
- ~500 MB free space per downloaded granule (temporary)
- ~1 GB space for processed Parquet files

---

## 12. Codebase Structure

```
SWOT/
├── SWOT_Pull.py               # Data ingestion, processing & optimization
├── dashboard_swot.py          # Interactive Streamlit visualization
├── river_poly.zip             # Polygon boundaries (GeoPackage)
├── .swot_cli_config.json      # SWOT CLI configuration
├── batch_outputs/
│   ├── data/                  # Daily CSV files (checkpoints)
│   ├── master_all_data.csv    # Combined CSV
│   └── master_all_data_part_*.parquet  # Optimized partitions for dashboard
└── docs/
    ├── development_notes.md   # Development history & technical notes
    └── SWOT_Handbook.pdf      # NASA reference document
```

**Key Configuration Locations:**
- Anchor coordinates: `SWOT_Pull.py` lines 40-41
- Classification filter: `SWOT_Pull.py` line 21
- PIXC quality filter config: `SWOT_Pull.py` lines 23-25
- MAD outlier config: `SWOT_Pull.py` lines 27-29
- Polygon path: `SWOT_Pull.py` line 19

---

## 13. Verification Against Official SWOT Documentation

**Primary Reference:** SWOT Science Data Products User Handbook (JPL D-109532, Initial Release, May 2, 2024)

### Verified Sections

| Processing Step | Our Implementation | Handbook Reference | Status |
|-----------------|-------------------|-------------------|--------|
| **Classification Filter** | Classes 3 & 4 | Table 6.1, Page 76 | ✅ VERIFIED |
| **Geoid Correction** | EGM2008 from `geoid` field | Section 11.3.1, Pages 185-186 | ✅ VERIFIED |
| **Solid Earth Tide** | Subtract `solid_earth_tide` | Section 11.3.4.1, Page 188 | ✅ VERIFIED |
| **Load Tide** | Subtract `load_tide_fes` | Section 11.3.4.1, Page 189 | ✅ VERIFIED |
| **Pole Tide** | Subtract `pole_tide` | Section 11.3.4.2, Page 190 | ✅ VERIFIED |
| **WSE Formula** | height - geoid - tides | Sections 11.3.1, 11.3.4 | ✅ VERIFIED |
| **Product Type** | L2_HR_PIXC | Section 6.11, Pages 75-78 | ✅ VERIFIED |

### Key Handbook Quotes Supporting Our Processing

**On Geoid (Page 185-186):**
> "The geoid serves as the reference surface for the water surface elevations reported in the KaRIn HR products."

**On Tides for KaRIn HR Products (Page 188-189):**
> "KaRIn HR products use the same models to provide the solid Earth tide height and the load tide height."

> "All provide a model for the solid Earth tide height."

> "All provide models for the load tide height that are consistent with the ocean tide models adopted for the SWOT ocean products."

**On Classification (Page 75):**
> "The classification algorithm includes automated water detection based on the surface reflectivity observed by KaRIn—water is assumed to be more reflective of radar signals than land."

**On PIXC Product Intent (Page 77):**
> "The intent of the L2_HR_PIXC product is to provide HR information that abstracts some of the engineering details of the implementation of the KaRIn instrument but that remains close to the fundamental measurements of the instrument."

---

## 14. References & Documentation

- **SWOT Mission:** https://swot.jpl.nasa.gov/
- **PO.DAAC Portal:** https://podaac.jpl.nasa.gov/SWOT
- **User Handbook:** JPL D-109532 (SWOT Science Data Products User Handbook, May 2, 2024)
- **Cookbook:** https://podaac.github.io/tutorials/quarto_text/SWOT.html
- **earthaccess Docs:** https://earthaccess.readthedocs.io/
- **ArcticDEM V4:** Porter et al., ArcticDEM V4, Harvard Dataverse, 2023. https://doi.org/10.7910/DVN/3VDC4T
- **Google Earth Engine:** Gorelick et al., "Google Earth Engine: Planetary-scale geospatial analysis for everyone," *Remote Sensing of Environment*, 2017.

---

**Document Version:** 3.1
**Last Updated:** 2026-05-28
**Author:** Luke (University SWOT Project)
**Verification Status:** ✅ All core processing steps verified against official SWOT User Handbook (JPL D-109532)
**Reviewer:** [Pending - SWOT Expert Review]
