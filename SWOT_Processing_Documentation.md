# SWOT Data Processing Documentation
## Kanektok River - Uyak Creek Avulsion Risk Assessment

**Study Location:** Kanektok River distributary system, Alaska
**Reference Point:** 59.826973°N, -161.372337°W (split point where Uyak diverges from Kanektok)
**Scientific Objective:** Assess avulsion risk by comparing hydraulic gradients between parallel channels

---

## 1. Data Products & Versions

### Primary Data Product
- **Product Name:** `SWOT_L2_HR_PIXC` (High-Resolution Pixel Cloud)
- **Product Level:** Level 2 (geolocated, calibrated)
- **Spatial Resolution:** ~10-100m pixel spacing
- **Measurement Type:** Ka-band Radar Interferometry (KaRIn)

### Version Strategy
We retrieve both available versions with the following priority hierarchy:

| Version | Status | Priority | Notes |
|---------|--------|----------|-------|
| **Version 2.0** (`SWOT_L2_HR_PIXC_2.0`) | Validated | **HIGH** | Corrected geolocation errors from Version D |
| **Version D** (`SWOT_L2_HR_PIXC_D`) | Provisional | LOW | Used only when V2.0 unavailable for a given date |

**Implementation:** Both versions are searched via `earthaccess` API. When duplicate dates exist, Version 2.0 data overwrites Version D in the processing pipeline (implicit priority through concatenation order).

**Known Issue:** Data from January-May 2024 contains mixed versions due to a processing interruption. These dates require reprocessing to ensure Version 2.0 consistency.

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

**Note on Load Tide Variable:** Code checks for `load_tide_fes` first (Version 2.0), with fallback to `load_tide_height` (Version D) if unavailable.

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

### Current Implementation: Classification-Based Filter

**Filter Applied:**
```python
DEFAULT_CLASSES = [3, 4]  # Class 3: Water near land, Class 4: Open water
df_filtered = df[df['classification'].isin(DEFAULT_CLASSES)]
```

### Classification Field - VERIFIED FROM SWOT USER HANDBOOK

**Official Definitions (Table 6.1, Page 76, JPL D-109532):**

| Class | Definition | Relevant for Rivers? |
|-------|------------|---------------------|
| 1 | Land | ❌ No |
| 2 | Land near water | ❌ No |
| **3** | **Water near land** | **✅ YES** |
| **4** | **Open water** | **✅ YES** |
| 5 | Dark water | ⚠️ Lower quality |
| 6 | Low-coherence water near land | ⚠️ Lower quality |
| 7 | Open low-coherence water | ⚠️ Lower quality |

**Empirical Verification:**
- June 2025 data download (9 passes, 384,027 total pixels)
- QGIS inspection revealed Class 3 pixels with good spatial coverage in river channels
- Both Class 3 and 4 represent high-quality water detection

**NASA Standard (from tutorials):**
- `classification > 2` to select all water pixels (includes classes 3-7)

**Our Rationale for Classes 3 & 4:**
1. **Class 4 (Open water)**: Center channel, highest confidence
2. **Class 3 (Water near land)**: River edges near banks, verified as good quality in QGIS
3. **Excludes Class 5+**: Dark water and low-coherence classes may introduce noise
4. **River-appropriate**: Narrow channels naturally contain water-land boundaries
5. **Balanced approach**: Maximizes coverage while maintaining quality

**Classification Algorithm (Handbook Page 75):**
> "The classification algorithm includes automated water detection based on the surface reflectivity observed by KaRIn—water is assumed to be more reflective of radar signals than land at the wavelength and incidence angles of the KaRIn measurement."

### Additional Quality Variables Available (Not Currently Used)

| Variable | Description | Potential Use |
|----------|-------------|---------------|
| `height_uncert` | Height measurement uncertainty | Could filter pixels with uncertainty > threshold |
| `geolocation_qual` | Geolocation quality metric (0-3=good, 4+=poor) | NASA tutorials suggest `< 4` for good quality |
| `cross_track` | Cross-track distance from nadir | Could filter to 10-60 km range to avoid nadir gap and edge noise |

**Future Consideration:** May implement `geolocation_qual < 4` in addition to classification filter if data quality issues emerge.

---

## 5. Distance Calculation

### Method: Haversine Great-Circle Distance

**Reference Point (Anchor):**
- Latitude: 59.826973°N
- Longitude: -161.372337°W
- Physical Location: Split point where Uyak Creek diverges from Kanektok River

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
NASA Earthdata → earthaccess API → NetCDF download → SWOT_Pull.py
                                                         ↓
                                         Spatial clip + WSE calculation
                                                         ↓
                                         Classification filter (Class 4)
                                                         ↓
                                         Distance calculation (Haversine)
                                                         ↓
                                         Gradient calculation (linregress)
                                                         ↓
                                    Daily CSV: YYYY-MM-DD_data.csv
                                                         ↓
                                    Master CSV: master_all_data.csv
                                                         ↓
                                    optimize.py (CSV → Parquet)
                                                         ↓
                                    Parquet: master_all_data_part_*.parquet
                                                         ↓
                                    dashboard_swot.py (DuckDB + Plotly)
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
| Classification = 4 only | Empirically dominates river data; highest quality | Class > 2 (NASA standard) - may include lower quality pixels |
| Haversine distance | Appropriate for <100km distances; computationally fast | Geodesic (Vincenty) - unnecessary precision for this scale |
| Linear regression for gradient | Standard method; simple interpretation | Moving window / local gradient - adds complexity |
| Reversed x-axis | Standard convention for longitudinal profiles | Forward axis - less intuitive for river profiles |

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
- [ ] Investigate: Should we add `geolocation_qual < 4` filter for additional quality control?
- [ ] Consider: Cross-track distance filtering (10-60 km range to avoid nadir gap)

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
├── SWOT_Pull.py                    # Data ingestion & processing
├── optimize.py                 # CSV → Parquet conversion
├── dashboard_swot.py          # Interactive visualization
├── river_poly.zip              # Polygon boundaries (GeoPackage)
├── .swot_cli_config.json       # SWOT CLI configuration
├── batch_outputs/
│   ├── data/                   # Daily CSV files
│   ├── master_all_data.csv     # Combined CSV
│   └── master_all_data_part_*.parquet  # Partitioned Parquet
└── Claude/
    ├── Claude_notes.md         # Technical notes
    └── SWOT_Processing_Documentation.md  # This file
```

**Key Configuration Locations:**
- Anchor coordinates: `SWOT_Pull.py` lines 21-24
- Classification filter: `SWOT_Pull.py` line 18
- Polygon path: `SWOT_Pull.py` line 16
- Color mapping: `dashboard_swot.py` lines 16-19

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

---

**Document Version:** 2.0
**Last Updated:** 2026-02-04
**Author:** Luke (University SWOT Project)
**Verification Status:** ✅ All core processing steps verified against official SWOT User Handbook (JPL D-109532)
**Reviewer:** [Pending - SWOT Expert Review]
