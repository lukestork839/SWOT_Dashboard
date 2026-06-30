import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots
from scipy import stats
from scipy.ndimage import gaussian_filter1d
import numpy as np
import duckdb
import os
import glob
import gc  # Memory management
import folium
from folium import plugins
from folium.plugins import MeasureControl
from streamlit_folium import st_folium
import matplotlib.colors as mcolors
import matplotlib.cm as cm

from branca.element import MacroElement
from jinja2 import Template as JinjaTemplate

# --- CONFIGURATION ---
PAGE_TITLE = "SWOT River Dynamics: Kanektok & Uyak"
DATA_DIR = "batch_outputs"
REMOTE_PARQUET_URL = "https://github.com/lukestork839/SWOT_Dashboard/releases/download/v2.0-data/dashboard_data.parquet"
REMOTE_DEM_URL = "https://github.com/lukestork839/SWOT_Dashboard/releases/download/v2.0-data/dem_river_elevations.parquet"
REMOTE_REFGRAD_URL = "https://github.com/lukestork839/SWOT_Dashboard/releases/download/v2.0-data/reference_gradient_per_pass.parquet"
MAX_PLOT_POINTS = 15000  # Reduced for large datasets (was 25000)
MAX_BASELINE_POINTS = 30000  # Reduced for Streamlit Cloud (was 50000)
MAX_MAP_POINTS = 5000  # Strict limit for map rendering

# --- BIFURCATION POINT ---
# Where Kanektok River and Uyak Creek diverge (59°49'43.99"N, 161°22'40.00"W)
BIFURCATION_LAT = 59.828886
BIFURCATION_LON = -161.377778
BIFURCATION_DIST_KM = 2.493  # Haversine distance from confluence anchor point

# FIXED COLORS
COLOR_MAP = {
    "Kanektok_River": "firebrick",
    "Uyak_Creek": "dodgerblue"
}

# --- ANALYSIS PERIOD DEFINITIONS ---
TYPHOON_DATE = "2025-10-12"  # Typhoon Halong landfall

SEASONAL_PERIODS = [
    {"label": "2023 High Flow", "start": "2023-05-01", "end": "2023-05-31", "row": 0, "col": 0, "fallback_start": "2023-07-01", "fallback_end": "2023-08-31", "fallback_label": "2023 Earliest Available"},
    {"label": "2023 Low Flow",  "start": "2023-07-01", "end": "2023-08-31", "row": 1, "col": 0},
    {"label": "2024 High Flow", "start": "2024-05-01", "end": "2024-05-31", "row": 0, "col": 1},
    {"label": "2024 Low Flow",  "start": "2024-07-01", "end": "2024-08-31", "row": 1, "col": 1},
    {"label": "2025 High Flow", "start": "2025-05-01", "end": "2025-05-31", "row": 0, "col": 2},
    {"label": "2025 Low Flow",  "start": "2025-07-01", "end": "2025-08-31", "row": 1, "col": 2},
]

TYPHOON_PERIODS = {
    "pre_immediate":  {"label": "Pre-Storm (Aug-Sep 2025)",  "start": "2025-08-01", "end": "2025-09-30"},
    "post_immediate": {"label": "Post-Storm (Oct 15-Dec 2025)", "start": "2025-10-15", "end": "2025-12-31"},
    "pre_season":     {"label": "Pre-Storm Summer 2025",     "start": "2025-05-01", "end": "2025-08-31"},
    "post_season":    {"label": "Post-Storm Spring 2026",    "start": "2026-03-01", "end": "2026-08-31"},
}

# --- ICE SEASON DEFINITIONS (Kanektok/Uyak at ~59.8°N) ---
# SWOT PIXC has no ice classification class. Classes 3-4 exclude most ice
# (rough ice → land Class 1-2), but smooth river ice classifies as water
# (Class 3-4) and passes through quality filters during frozen months.
# Analysis of 170 passes (2023-2026) shows peak contamination Dec-Mar:
#   - Uyak Creek: 80-95% Class 4 (vs 35-55% in open water)
#   - Kanektok River: 58-77% Class 4 (wider river, less complete freeze)
# Oct-Nov are ice-free in the data; Apr-May are transitional but mostly usable.
# Ice surface elevation ≠ water surface elevation (off by ice thickness 0.5-2+ m).
ICE_AFFECTED_MONTHS = {12, 1, 2, 3}  # Dec-Mar (data-validated peak ice contamination)
OPEN_WATER_MONTHS = {4, 5, 6, 7, 8, 9, 10, 11}  # Apr-Nov (reliable for WSE analysis)


def add_bifurcation_line(fig, axis="x"):
    """Add a dashed line marking the bifurcation point on a plotly figure."""
    if axis == "x":
        fig.add_vline(
            x=BIFURCATION_DIST_KM, line_dash="dash", line_color="gray", line_width=1.5,
            annotation_text="Bifurcation", annotation_position="top",
            annotation_font_size=11, annotation_font_color="gray",
        )
    else:  # horizontal line (e.g. heatmap with distance on y-axis)
        fig.add_hline(
            y=BIFURCATION_DIST_KM, line_dash="dash", line_color="gray", line_width=1.5,
            annotation_text="Bifurcation", annotation_position="right",
            annotation_font_size=11, annotation_font_color="gray",
        )

def add_bifurcation_marker(m):
    """Add a marker for the bifurcation point on a folium map."""
    folium.Marker(
        location=[BIFURCATION_LAT, BIFURCATION_LON],
        popup=folium.Popup(
            f"<b>Bifurcation Point</b><br>"
            f"Lat: {BIFURCATION_LAT:.6f}<br>"
            f"Lon: {BIFURCATION_LON:.6f}<br>"
            f"Distance from anchor: {BIFURCATION_DIST_KM:.2f} km",
            max_width=250,
        ),
        tooltip="Bifurcation Point",
        icon=folium.Icon(color="green", icon="info-sign"),
    ).add_to(m)

st.set_page_config(page_title=PAGE_TITLE, layout="wide", page_icon="🌊")

@st.cache_data(ttl=3600)  # Cache for 1 hour
def calculate_detrending(dist_km, wse, method):
    """
    Calculate baseline and residuals for detrended profile.
    Cached to avoid recomputing on every interaction.

    Args:
        dist_km: Distance values (list/array)
        wse: Water surface elevation values (list/array)
        method: Detrending method name

    Returns:
        tuple: (baseline_pred, coeffs/None, method_name)
    """
    x_all = np.array(dist_km)
    y_all = np.array(wse)

    if method == "Linear":
        slope_manual, intercept_manual, r_value, p_value, std_err = stats.linregress(x_all, y_all)
        baseline_pred = slope_manual * x_all + intercept_manual
        coeffs = [slope_manual, intercept_manual]
        method_name = "Linear Fit"
    elif method == "Polynomial (2nd order)":
        poly = np.polynomial.Polynomial.fit(x_all, y_all, 2)
        baseline_pred = poly(x_all)
        coeffs = poly.coef
        method_name = "2nd Order Polynomial"
    elif method == "Polynomial (3rd order)":
        poly = np.polynomial.Polynomial.fit(x_all, y_all, 3)
        baseline_pred = poly(x_all)
        coeffs = poly.coef
        method_name = "3rd Order Polynomial"
    else:  # LOESS
        sorted_idx = np.argsort(x_all)
        x_sorted = x_all[sorted_idx]
        y_sorted = y_all[sorted_idx]
        sigma = len(x_all) * 0.15 / 3
        y_smooth = gaussian_filter1d(y_sorted, sigma=sigma, mode='nearest')
        baseline_pred = np.zeros_like(y_all)
        baseline_pred[sorted_idx] = y_smooth
        coeffs = None
        method_name = "LOESS (Local Regression)"

    return baseline_pred, coeffs, method_name

@st.cache_data(ttl=3600)
def calculate_slope_profile(dist_km, wse, smooth_km=2.0, n_eval=200):
    """
    Compute a smooth slope profile for a single river by:
    1. Binning raw data into regular 100m intervals (median WSE per bin)
    2. Smoothing the binned WSE with a Gaussian filter (window ~ smooth_km)
    3. Computing numerical derivative of the smoothed curve

    Args:
        dist_km: distance values for one river
        wse: WSE values for one river
        smooth_km: smoothing window in km (controls noise vs detail)
        n_eval: number of evenly-spaced output points

    Returns:
        tuple: (x_eval, slope_cm_km, y_fitted)
    """
    import pandas as pd
    x = np.array(dist_km)
    y = np.array(wse)

    # Bin into 100m intervals and take median (robust to outliers)
    bin_size = 0.1  # km
    bins = np.round(x / bin_size) * bin_size
    df = pd.DataFrame({'bin': bins, 'wse': y})
    bin_medians = df.groupby('bin')['wse'].median().sort_index()

    x_binned = bin_medians.index.values
    y_binned = bin_medians.values

    # Gaussian smoothing with sigma in physical distance units
    # sigma in bins = smooth_km / bin_size
    sigma_bins = smooth_km / bin_size
    y_smooth = gaussian_filter1d(y_binned, sigma=sigma_bins, mode='nearest')

    # Interpolate onto regular eval grid
    x_eval = np.linspace(x_binned.min(), x_binned.max(), n_eval)
    y_fitted = np.interp(x_eval, x_binned, y_smooth)

    # Numerical derivative: slope in m/km -> * 100 for cm/km
    slope_cm_km = np.gradient(y_fitted, x_eval) * 100

    return x_eval, slope_cm_km, y_fitted

@st.cache_data(ttl=3600)
def detect_anomalies_mad(data, threshold=3.5):
    """
    Detect anomalies using Modified Z-score (Median Absolute Deviation).
    Cached to avoid recomputing on every interaction.

    Args:
        data: pandas Series with metric values
        threshold: Modified Z-score threshold (default 3.5, matches pipeline)

    Returns:
        Boolean array where True = anomaly
    """
    median = data.median()
    mad = np.median(np.abs(data - median))

    if mad == 0:
        # Fallback to IQR if MAD is 0 (all values identical)
        q1, q3 = data.quantile(0.25), data.quantile(0.75)
        iqr = q3 - q1
        return (data < q1 - 1.5 * iqr) | (data > q3 + 1.5 * iqr)

    modified_z_score = 0.6745 * (data - median) / mad
    return np.abs(modified_z_score) > threshold

class VerticalColorbar(MacroElement):
    """Vertical colorbar legend as a Leaflet control on the left side of the map."""

    def __init__(self, caption, colors, vmin, vmax):
        super().__init__()
        self._name = 'VerticalColorbar'
        self.caption = caption
        self.gradient_css = ', '.join(colors)
        self.vmin = float(vmin)
        self.vmax = float(vmax)
        self.vmid = float((vmin + vmax) / 2)

        self._template = JinjaTemplate("""
            {% macro script(this, kwargs) %}
                var legend = L.control({position: 'topleft'});
                legend.onAdd = function(map) {
                    var div = L.DomUtil.create('div', 'vertical-legend');
                    div.style.marginTop = '10px';
                    div.innerHTML = '<div style="background:white;padding:6px 8px;border-radius:4px;'
                        + 'border:2px solid rgba(0,0,0,0.2);font:11px Arial,sans-serif">'
                        + '<div style="font-weight:bold;margin-bottom:4px;text-align:center">'
                        + '{{ this.caption }}</div>'
                        + '<div style="display:flex;align-items:stretch">'
                        + '<div style="background:linear-gradient(to top,{{ this.gradient_css }});'
                        + 'width:18px;height:120px;border:1px solid #ccc"></div>'
                        + '<div style="display:flex;flex-direction:column;'
                        + 'justify-content:space-between;margin-left:4px;font-size:10px">'
                        + '<span>{{ "%.1f"|format(this.vmax) }}</span>'
                        + '<span>{{ "%.1f"|format(this.vmid) }}</span>'
                        + '<span>{{ "%.1f"|format(this.vmin) }}</span>'
                        + '</div></div></div>';
                    return div;
                };
                legend.addTo({{ this._parent.get_name() }});
            {% endmacro %}
        """)

def compute_moving_average(series, window, min_periods=2):
    """
    Compute rolling moving average with edge handling.

    Args:
        series: pandas Series (time-indexed)
        window: Number of periods for rolling window
        min_periods: Minimum observations required (default 2)

    Returns:
        pandas Series with moving average values
    """
    return series.rolling(window=window, min_periods=min_periods, center=False).mean()

def query_period_data(con, period_start, period_end, selected_reaches, max_points=5000):
    """Query river data for a specific date range, with sampling if needed."""
    try:
        rivers_sql = ", ".join([f"'{r}'" for r in selected_reaches])
        where = f"WHERE Reach_Name IN ({rivers_sql}) AND CAST(Pass_Date AS DATE) >= CAST('{period_start}' AS DATE) AND CAST(Pass_Date AS DATE) <= CAST('{period_end}' AS DATE)"

        count = con.execute(f"SELECT COUNT(*) FROM river_data {where}").fetchone()[0]
        if count == 0:
            return None, None, 0

        if count > max_points:
            step = int(count / max_points)
            query = f"""SELECT * FROM (
                SELECT *, row_number() OVER (ORDER BY Reach_Name, dist_km) as rn
                FROM river_data {where}) sub WHERE rn % {step} = 0"""
        else:
            query = f"SELECT * FROM river_data {where} ORDER BY Reach_Name, dist_km"

        df = con.execute(query).fetchdf()

        # Statistics on full (unsampled) data
        stats_df = con.execute(f"""
            SELECT Reach_Name, COUNT(*) as n_points,
                   COUNT(DISTINCT Pass_Date) as n_passes,
                   AVG(wse) as mean_wse, AVG(slope_calc) as avg_slope
            FROM river_data {where} GROUP BY Reach_Name
        """).fetchdf()

        return df, stats_df, count
    except Exception:
        return None, None, 0

# Cache key includes the remote URL so cache invalidates when data source changes
@st.cache_resource
def get_database_connection(_url_version=REMOTE_PARQUET_URL):
    """
    Initialize DuckDB connection with parquet data.
    Cached as a resource to prevent reconnecting on every interaction.

    Data source priority:
      1. Full dataset partition files from SWOT_Pull.py (batch_outputs/) — local dev
      2. Remote parquet via DuckDB httpfs from GitHub Releases — Streamlit Cloud
    """
    try:
        con = duckdb.connect(database=':memory:')

        # 1. Prefer local partition files (local development)
        partition_pattern = os.path.join(DATA_DIR, "master_all_data_part_*.parquet")
        import glob
        partition_files = glob.glob(partition_pattern)

        if partition_files:
            con.execute(f"CREATE OR REPLACE VIEW river_data AS SELECT * FROM read_parquet('{partition_pattern}')")
        else:
            # 2. Read parquet remotely from GitHub Releases via DuckDB httpfs
            con.execute("INSTALL httpfs")
            con.execute("LOAD httpfs")
            con.execute(f"CREATE OR REPLACE VIEW river_data AS SELECT * FROM read_parquet('{REMOTE_PARQUET_URL}')")
            st.info("🌐 Loading data from GitHub Releases. First query may take 10-30 seconds.")

        # Load DEM data if available (same local-first / remote-fallback pattern)
        dem_local = os.path.join(DATA_DIR, "dem_river_elevations.parquet")
        if os.path.exists(dem_local):
            con.execute(f"CREATE OR REPLACE VIEW dem_data AS SELECT * FROM read_parquet('{dem_local}')")
        elif not partition_files:
            # httpfs already loaded for remote SWOT — use it for DEM too
            con.execute(f"CREATE OR REPLACE VIEW dem_data AS SELECT * FROM read_parquet('{REMOTE_DEM_URL}')")

        # Load reference-gradient artifact (per-pass robust slope; same pattern)
        refgrad_local = os.path.join(DATA_DIR, "reference_gradient_per_pass.parquet")
        if os.path.exists(refgrad_local):
            con.execute(f"CREATE OR REPLACE VIEW ref_gradient AS SELECT * FROM read_parquet('{refgrad_local}')")
        elif not partition_files:
            con.execute(f"CREATE OR REPLACE VIEW ref_gradient AS SELECT * FROM read_parquet('{REMOTE_REFGRAD_URL}')")

        # Memory optimization: Set DuckDB memory limit (recommended for Streamlit Cloud)
        con.execute("SET memory_limit='600MB'")

        return con

    except Exception as e:
        st.error(f"❌ Could not connect to data: {e}")
        st.info("💡 If running locally, run `python SWOT_Pull.py` to generate data. If on Streamlit Cloud, check that the GitHub Release exists.")
        import traceback
        st.code(traceback.format_exc())
        return None

@st.cache_data(ttl=3600)
def load_dem_profile(_con):
    """Compute exact DEM bin profile from full dataset via DuckDB.
    Returns DataFrame with columns: Reach_Name, dist_bin, wse_median, wse_p10, wse_p25, wse_p75, wse_p90
    """
    try:
        return _con.execute("""
            SELECT Reach_Name,
                   ROUND(dist_km / 0.5) * 0.5 AS dist_bin,
                   MEDIAN(wse) AS wse_median,
                   PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY wse) AS wse_p10,
                   PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY wse) AS wse_p25,
                   PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY wse) AS wse_p75,
                   PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY wse) AS wse_p90
            FROM dem_data
            GROUP BY Reach_Name, ROUND(dist_km / 0.5) * 0.5
            ORDER BY Reach_Name, dist_bin
        """).fetchdf()
    except Exception:
        return None

@st.cache_data(ttl=3600)
def load_dem_points(_con):
    """Load sampled DEM points for map visualization via DuckDB."""
    try:
        return _con.execute("""
            SELECT Reach_Name, dist_km, wse, latitude, longitude
            FROM dem_data
            USING SAMPLE 15000
        """).fetchdf()
    except Exception:
        return None


@st.cache_data(ttl=3600)
def load_reference_gradient(_con):
    """Load the per-pass reference-gradient artifact (one row per reach x pass).

    Columns: Reach_Name, Pass_Date, month, season, open_water, n_nodes, n_pix,
    lo_km, hi_km, span_km, theilsen_cm_km, ols_cm_km, ols_r2, gated.
    Returns None if the artifact is not available.
    """
    try:
        return _con.execute("SELECT * FROM ref_gradient").fetchdf()
    except Exception:
        return None


@st.cache_data(ttl=3600)
def load_refgrad_decomposition(_con):
    """Pooled-OLS gradient (open-water) on raw pixels [A] vs on 1km nodes [B].

    Computed server-side via DuckDB regr_slope (no data pulled to python). Used by
    the decomposition expander to show that removing point-density bias is the
    dominant correction over the old trendline. Returns None on failure.
    """
    try:
        a = _con.execute("""
            SELECT Reach_Name, ABS(regr_slope(wse, dist_km)) * 100 AS pooled_raw
            FROM river_data
            WHERE EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) IN (4,5,6,7,8,9,10,11)
            GROUP BY Reach_Name
        """).fetchdf()
        b = _con.execute("""
            WITH nodes AS (
                SELECT Reach_Name, ROUND(dist_km / 1.0) * 1.0 AS node, MEDIAN(wse) AS wse
                FROM river_data
                WHERE EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) IN (4,5,6,7,8,9,10,11)
                GROUP BY Reach_Name, node
            )
            SELECT Reach_Name, ABS(regr_slope(wse, node)) * 100 AS pooled_nodes
            FROM nodes GROUP BY Reach_Name
        """).fetchdf()
        return a.merge(b, on="Reach_Name")
    except Exception:
        return None


@st.cache_data(ttl=3600)
def load_metadata(_con):
    """Return (all_pass_dates, available_reaches) from the database."""
    date_range = _con.execute("SELECT MIN(Pass_Date), MAX(Pass_Date) FROM river_data").fetchone()
    if date_range is None or date_range[0] is None:
        return None, None

    pass_dates_df = _con.execute("""
        SELECT DISTINCT CAST(Pass_Date AS DATE) as pass_date
        FROM river_data
        ORDER BY pass_date DESC
    """).fetchdf()
    all_pass_dates = pass_dates_df['pass_date'].tolist()
    available_reaches = _con.execute("SELECT DISTINCT Reach_Name FROM river_data").fetchdf()['Reach_Name'].tolist()
    return all_pass_dates, available_reaches


def _is_ice(d):
    """Check if a date falls in the ice-affected season (Dec-Mar)."""
    return d.month in (12, 1, 2, 3)


def _select_passes(all_pass_dates, n):
    """Set the first n pass checkboxes to True, rest to False."""
    for i, d in enumerate(all_pass_dates):
        st.session_state[f"pass_{d}"] = i < n
    st.session_state.pass_defaults_initialized = True


def render_pass_checklist(all_pass_dates):
    """Render pass selection checkboxes with ice labels and quick-select buttons."""
    RECENT_COUNT = 5

    # Initialize defaults if needed
    if "pass_defaults_initialized" not in st.session_state:
        _select_passes(all_pass_dates, n=4)

    # Select All / Clear All
    col1, col2 = st.columns(2)
    if col1.button("Select All (non-ice)", use_container_width=True):
        for d in all_pass_dates:
            st.session_state[f"pass_{d}"] = not _is_ice(d)
    if col2.button("Clear All", use_container_width=True):
        for d in all_pass_dates:
            st.session_state[f"pass_{d}"] = False

    # Recent passes
    recent_dates = all_pass_dates[:RECENT_COUNT]
    older_dates = all_pass_dates[RECENT_COUNT:]

    st.caption("Recent passes:")
    for d in recent_dates:
        label = d.strftime("%b %d, %Y")
        if _is_ice(d):
            label += " ❄️ ice"
        st.checkbox(label, key=f"pass_{d}")

    # Older passes in expander
    if older_dates:
        with st.expander(f"Older passes ({len(older_dates)} more)"):
            for d in older_dates:
                label = d.strftime("%b %d, %Y")
                if _is_ice(d):
                    label += " ❄️ ice"
                st.checkbox(label, key=f"pass_{d}")


def render_welcome(all_pass_dates):
    """Render the welcome/configuration page."""

    # Banner image with overlaid title
    st.markdown("""
    <div style="position: relative; width: 100%; margin-bottom: 1rem;">
        <img src="app/static/rivers_overhead.jpg" style="width: 100%; height: 200px; object-fit: cover; border-radius: 8px; filter: brightness(0.7);">
        <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); text-align: center; width: 100%;">
            <h1 style="color: white; margin: 0; text-shadow: 2px 2px 8px rgba(0,0,0,0.7); font-size: 2.5rem;">Welcome to the SWOT Dashboard</h1>
            <p style="color: rgba(255,255,255,0.9); margin: 0.3rem 0 0 0; text-shadow: 1px 1px 4px rgba(0,0,0,0.7); font-size: 1.1rem;">Kanektok River & Uyak Creek — Satellite River Monitoring</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    This tool uses a NASA satellite called **SWOT** to watch the **Kanektok River** and
    **Uyak Creek** from space. Every time the satellite flies over, it measures the height
    of the water along each river. By comparing these measurements over time, we can see
    how the rivers are changing and whether one river might be shifting its path toward
    the other.
    """)

    st.divider()

    # Quick Start — hero button
    if st.button("Quick Start — View Latest Data", type="primary", use_container_width=True):
        _select_passes(all_pass_dates, n=4)
        st.session_state.page = "dashboard"
        st.rerun()
    st.caption("Loads the 4 most recent satellite passes and opens the dashboard.")

    st.divider()

    # Configure Passes — secondary option below
    with st.expander("Choose Specific Dates"):
        st.caption("Pick exactly which satellite passes to include in your analysis.")
        render_pass_checklist(all_pass_dates)

        selected = [d for d in all_pass_dates if st.session_state.get(f"pass_{d}", False)]
        st.caption(f"{len(selected)} passes selected")

        if st.button("Launch Dashboard", type="primary"):
            if not selected:
                st.warning("Please select at least one pass.")
            else:
                st.session_state.page = "dashboard"
                st.rerun()

    with st.expander("How does the satellite work?"):
        st.markdown("""
        - **SWOT** (Surface Water and Ocean Topography) orbits Earth and measures the
          height of rivers, lakes, and oceans using radar. It can see both rivers at once.
        - Each **pass** is one flyover. The satellite measures water height at thousands of
          points along the river, giving us a detailed picture of the water surface.
        - During **winter** (Dec-Mar), river ice can fool the satellite into reading the top
          of the ice instead of the water underneath. These dates are marked with ❄️ so you
          know to be careful with that data.
        """)


def render_dashboard(con, all_pass_dates, available_reaches):
    """Render the main dashboard with all charts and analysis."""
    # --- Top bar ---
    top_left, top_right = st.columns([4, 1])
    with top_left:
        st.title(PAGE_TITLE)
    with top_right:
        if st.button("Return to Homepage"):
            # Clear cached dataframes but preserve pass selection
            for key in ["viz_df", "stats_df", "count", "where_clause",
                        "selected_pass_dates", "selected_reaches", "detrend_method",
                        "metrics_calculated", "temporal_df", "temporal_where",
                        "heatmap_df", "heatmap_where",
                        "dist_evolution_df", "elev_diff_df"]:
                st.session_state.pop(key, None)
            st.session_state.page = "welcome"
            st.rerun()

    # Always include both rivers
    selected_reaches = available_reaches

    # Read pass selection from session state
    selected_pass_dates = sorted(
        d for d in all_pass_dates if st.session_state.get(f"pass_{d}", False)
    )

    if not selected_pass_dates:
        st.warning("No passes selected. Please return to the homepage to select passes.")
        st.stop()

    # Show selected date range below title
    first_date = min(selected_pass_dates).strftime("%b %d, %Y")
    last_date = max(selected_pass_dates).strftime("%b %d, %Y")
    n_passes = len(selected_pass_dates)
    if n_passes == 1:
        date_label = f"Viewing 1 pass: {first_date}"
    elif first_date == last_date:
        date_label = f"Viewing {n_passes} passes: {first_date}"
    else:
        date_label = f"Viewing {n_passes} passes: {first_date} — {last_date}"
    st.markdown(f"**{date_label}**")

    # Hardcoded detrending method
    detrend_method = "Polynomial (2nd order)"

    # Display theme (light mode default)
    plotly_template = "plotly_white"

    # --- DATA LOADING WITH CACHING ---
    if "viz_df" not in st.session_state:
        # FILTER DATA
        rivers_sql = "'" + "','".join(selected_reaches) + "'"
        dates_sql = ",".join(f"CAST('{d}' AS DATE)" for d in selected_pass_dates)

        # Base conditions (explicit CAST needed for DuckDB httpfs DATE filtering)
        where_clause = f"""
            WHERE Reach_Name IN ({rivers_sql})
            AND CAST(Pass_Date AS DATE) IN ({dates_sql})
        """

        # Warn if any selected passes are in ice season
        ice_selected = [d for d in selected_pass_dates if d.month in (12, 1, 2, 3)]
        if ice_selected:
            ice_labels = ", ".join(d.strftime("%b %d, %Y") for d in ice_selected)
            st.warning(
                f"**Ice season data included** ({ice_labels}). "
                "Smooth river ice passes SWOT Class 3-4 filters, "
                "producing WSE readings 0.5-2+ m above the true water surface. "
                "Uyak Creek is most affected (narrow channel freezes completely). "
                "Use caution when interpreting winter data."
            )

        # Check total count first (with timeout protection)
        try:
            with st.spinner("Querying database..."):
                count = con.execute(f"SELECT COUNT(*) FROM river_data {where_clause}").fetchone()[0]
        except Exception as e:
            st.error(f"Query failed: {e}")
            st.stop()

        if count == 0:
            st.warning("No data matches your selection.")
            st.stop()

        # --- SCIENTIFIC DOWNSAMPLING ---
        if count > MAX_PLOT_POINTS:
            step_size = int(count / MAX_PLOT_POINTS)

            query_viz = f"""
                SELECT * FROM (
                    SELECT *, row_number() OVER (ORDER BY Reach_Name, dist_km, Pass_Date) as rn
                    FROM river_data {where_clause}
                ) sub
                WHERE rn % {step_size} = 0
            """

            viz_df = con.execute(query_viz).fetchdf()
            st.toast(f"Systematic Sampling: Showing 1 out of every {step_size} points.", icon="📉")
        else:
            query_viz = f"SELECT * FROM river_data {where_clause} ORDER BY Reach_Name, dist_km"
            viz_df = con.execute(query_viz).fetchdf()

        # --- STATISTICS (ALWAYS USE FULL DATA) ---
        # Distance-weighted avg: bin by 1km, take median per bin, then average bins.
        # This prevents uneven spatial sampling from biasing the mean WSE.
        stats_query = f"""
            WITH binned AS (
                SELECT Reach_Name,
                       ROUND(dist_km) AS dist_bin,
                       MEDIAN(wse) AS bin_wse,
                       MEDIAN(slope_calc) AS bin_slope
                FROM river_data {where_clause}
                GROUP BY Reach_Name, ROUND(dist_km)
            )
            SELECT Reach_Name,
                   AVG(bin_wse) AS avg_wse,
                   AVG(bin_slope) AS avg_slope
            FROM binned
            GROUP BY Reach_Name
        """
        stats_df = con.execute(stats_query).fetchdf()

        # Store in session state for reuse
        st.session_state.viz_df = viz_df
        st.session_state.stats_df = stats_df
        st.session_state.count = count
        st.session_state.selected_reaches = selected_reaches
        st.session_state.selected_pass_dates = selected_pass_dates
        st.session_state.detrend_method = detrend_method
        st.session_state.where_clause = where_clause
    else:
        # Use cached data (instant - no database query!)
        viz_df = st.session_state.viz_df
        stats_df = st.session_state.stats_df
        count = st.session_state.count
        selected_reaches = st.session_state.selected_reaches
        selected_pass_dates = st.session_state.selected_pass_dates
        detrend_method = st.session_state.detrend_method
        where_clause = st.session_state.where_clause

    # --- CALCULATE ADVANCED METRICS FOR MAP VISUALIZATION ---
    # Only calculate when data is reloaded (not when just changing map display settings)
    if "metrics_calculated" not in st.session_state or st.session_state.metrics_calculated != detrend_method:
        # 1. Calculate Detrended Residuals (using cached function for performance)
        baseline_pred, _, _ = calculate_detrending(
            viz_df['dist_km'].tolist(),
            viz_df['wse'].tolist(),
            detrend_method
        )
        viz_df['detrended_residual'] = viz_df['wse'].values - baseline_pred

        # 2. Calculate smoothed slopes (same method as Slope Profile tab)
        # Bin to 100m medians, Gaussian smooth (2km window), interpolate back to each point
        viz_df['interval_slope'] = 0.0
        for reach in viz_df['Reach_Name'].unique():
            reach_mask = viz_df['Reach_Name'] == reach
            reach_data = viz_df[reach_mask]
            if len(reach_data) < 10:
                continue
            x_eval, slope_cm_km, _ = calculate_slope_profile(
                reach_data['dist_km'].tolist(),
                reach_data['wse'].tolist()
            )
            # Interpolate smoothed slope onto each point's actual dist_km
            point_slopes = np.interp(reach_data['dist_km'].values, x_eval, slope_cm_km)
            viz_df.loc[reach_mask, 'interval_slope'] = point_slopes

        # Update session state
        st.session_state.viz_df = viz_df
        st.session_state.metrics_calculated = detrend_method

    # --- TABS ---
    # Load DEM data via DuckDB (cached, exact statistics from full dataset)
    dem_profile = load_dem_profile(con)
    dem_points = load_dem_points(con)

    main_swot, main_dem = st.tabs(["📡 SWOT Data", "🏔️ DEM Data"])

    # Local-only tabs: Temporal Evolution, Seasonal Comparison, Typhoon Impact
    # These require the full local dataset and are hidden on Streamlit Cloud
    is_local = bool(glob.glob(os.path.join(DATA_DIR, "master_all_data_part_*.parquet")))

    with main_swot:
        swot_tab_names = [
            "📈 Gradient Profile", "📏 Hydraulic Gradient", "🎯 Detrended Profile", "🗺️ Map View",
            "🔀 Elevation Difference", "📐 Slope Profile", "📄 Raw Data",
        ]
        if is_local:
            swot_tab_names += ["⏳ Temporal Evolution", "📊 Seasonal Comparison", "🌊 Typhoon Impact"]

        swot_tabs = st.tabs(swot_tab_names)
        tab1, tab_grad, tab3, tab5, tab2, tab4, tab6 = swot_tabs[:7]
        if is_local:
            tab7, tab8, tab9 = swot_tabs[7:]

    with tab1:
        st.subheader("River Profile")
        
        fig = go.Figure()

        # Draw Kanektok first so Uyak layers on top
        plot_order = sorted(selected_reaches, key=lambda r: r == "Uyak_Creek")
        for reach in plot_order:
            reach_data = viz_df[viz_df['Reach_Name'] == reach]
            if len(reach_data) == 0:
                continue
            line_color = COLOR_MAP.get(reach, "black")

            # Solid legend marker (invisible data, shown in legend)
            fig.add_trace(go.Scatter(
                x=[None], y=[None],
                mode='markers',
                name=reach,
                marker=dict(color=line_color, size=8, opacity=1.0),
                legendgroup=reach,
            ))
            # Scatter points (translucent data, hidden from legend)
            fig.add_trace(go.Scatter(
                x=reach_data['dist_km'],
                y=reach_data['wse'],
                mode='markers',
                marker=dict(color=line_color, size=5, opacity=0.3),
                legendgroup=reach,
                showlegend=False,
                hovertemplate='<b>' + reach + '</b><br>'
                              'Distance: %{x:.2f} km<br>'
                              'WSE: %{y:.2f} m<br>'
                              '<extra></extra>'
            ))

            # Trendlines: linear (existing) + 2nd-order polynomial (test overlay)
            if len(reach_data) >= 5:
                slope, intercept, r, _, _ = stats.linregress(reach_data['dist_km'], reach_data['wse'])
                slope_cm = abs(slope * 100)
                x_range = np.linspace(reach_data['dist_km'].min(), reach_data['dist_km'].max(), 100)
                y_range = intercept + slope * x_range

                fig.add_trace(go.Scatter(
                    x=x_range,
                    y=y_range,
                    mode='lines',
                    name=f"{reach} Linear Trend: {slope_cm:.1f} cm/km",
                    line=dict(color=line_color, width=4, dash='dash')
                ))

                # 2nd-order polynomial fit (same curve shape as the Detrended tab baseline)
                poly = np.polynomial.Polynomial.fit(reach_data['dist_km'], reach_data['wse'], 2)
                fig.add_trace(go.Scatter(
                    x=x_range,
                    y=poly(x_range),
                    mode='lines',
                    name=f"{reach} Poly Trend (2nd order)",
                    line=dict(color=line_color, width=3, dash='dot')
                ))

        fig.update_layout(
            xaxis_title="Distance from Anchor Point (km)",
            yaxis_title="Water Surface Elevation (m)",
        )

        # 🔄 REVERSE THE X-AXIS HERE
        fig.update_xaxes(autorange="reversed")

        fig.update_layout(height=600, template=plotly_template)
        add_bifurcation_line(fig)
        st.plotly_chart(fig, width="stretch", theme=None)

        # Add interpretation guide
        with st.expander("How to read this graph"):
            st.markdown("""
            **What this shows:** the height of the water surface along each river — from
            the coast on the left, back to where the two rivers meet on the right.

            - **Left–right**: how far up the river you are, in kilometers. The coast/river
              mouth is on the left (~70 km); the point where the rivers meet is on the right (0 km).
            - **Up–down**: how high the water sits above sea level, in meters.
            - **Dots**: individual measurements from the satellite.
            - **Dashed line**: the river's average slope — how steeply the water drops as it
              flows downhill, shown as centimeters of drop per kilometer (cm/km).

            **What to look for:**
            - A **steeper slope** (bigger cm/km) means the water drops faster and flows with more force.
            - If one river sits **higher** than the other along the same stretch, it has more
              potential to spill over and shift its path toward the lower one.
            - The **spread of the dots** shows natural differences between satellite passes and water levels.

            **Tip:** the other tabs go deeper —
            - *Hydraulic Gradient* gives each river's single best average slope.
            - *Elevation Difference* shows which river is higher at each point.
            - *Detrended Profile* removes the overall downhill slope to reveal subtle differences.
            - *Slope Profile* shows how the steepness changes along the river.

            ― Technical details ―
            Heights are orthometric, relative to the EGM2008 geoid. The dashed line is an
            ordinary least-squares (OLS) linear fit; its slope is shown in the legend in cm/km.
            For the density-de-biased, robust characteristic slope, see the Hydraulic Gradient tab.
            """)

    with tab_grad:
        st.subheader("Reference Hydraulic Gradient")
        ref_df = load_reference_gradient(con)

        if ref_df is None or len(ref_df) == 0:
            st.info(
                "Reference gradient data not available. If running locally, run `SWOT_Pull.py` "
                "(it writes `reference_gradient_per_pass.parquet` automatically at the end of a pull)."
            )
        else:
            ow = ref_df[(ref_df["open_water"]) & (ref_df["gated"])].copy()
            ow["abs_slope"] = ow["theilsen_cm_km"].abs()

            st.markdown(
                "**Median of per-pass robust (Theil–Sen) slopes over the full open-water record (Apr–Nov).** "
                "This is a characteristic property of each river: it is computed from *all* qualifying open-water "
                "passes and does **not** change with the pass selection above — nor is it the slope of any single "
                "line drawn on the Gradient Profile chart."
            )

            grad_order = sorted(selected_reaches, key=lambda r: r == "Uyak_Creek")

            # --- Headline metrics (one per river) ---
            mcols = st.columns(len(grad_order))
            for i, reach in enumerate(grad_order):
                d = ow[ow["Reach_Name"] == reach]
                if len(d) == 0:
                    mcols[i].metric(reach.replace("_", " "), "—")
                    continue
                mcols[i].metric(
                    reach.replace("_", " "),
                    f"{d['abs_slope'].median():.1f} cm/km",
                    help=(f"Median of {len(d)} full-coverage open-water passes · "
                          f"IQR {d['abs_slope'].quantile(0.25):.1f}–{d['abs_slope'].quantile(0.75):.1f} cm/km"),
                )

            # --- Per-pass distribution: every pass as a jittered dot, with a bold
            #     median line and a shaded middle-50% (IQR) band. Clearer than a box
            #     plot here — Kanektok's IQR is so small a box collapses to a line. ---
            fig_g = go.Figure()
            rng = np.random.default_rng(42)  # fixed seed -> jitter is stable across reruns
            xpos = {}
            for xi, reach in enumerate(grad_order):
                d = ow[ow["Reach_Name"] == reach]
                if len(d) == 0:
                    continue
                xpos[reach] = xi
                color = COLOR_MAP.get(reach, "black")
                vals = d["abs_slope"].to_numpy()
                q25, med, q75 = np.percentile(vals, [25, 50, 75])

                # shaded middle-50% (IQR) band
                fig_g.add_shape(type="rect", x0=xi - 0.30, x1=xi + 0.30, y0=q25, y1=q75,
                                fillcolor=color, opacity=0.12, line_width=0, layer="below")
                # bold median line = the headline value
                fig_g.add_shape(type="line", x0=xi - 0.36, x1=xi + 0.36, y0=med, y1=med,
                                line=dict(color=color, width=3))
                # every pass as a jittered dot
                jitter = rng.uniform(-0.16, 0.16, size=len(vals))
                fig_g.add_trace(go.Scatter(
                    x=xi + jitter, y=vals, mode="markers",
                    marker=dict(color=color, size=5, opacity=0.45),
                    name=reach.replace("_", " "),
                    hovertemplate="%{y:.1f} cm/km<extra></extra>",
                ))
            fig_g.update_layout(
                yaxis_title="Per-pass gradient (cm/km)",
                height=520, template=plotly_template, showlegend=False,
                title="Distribution of per-pass robust slopes (each dot = one satellite pass)",
                xaxis=dict(tickmode="array", tickvals=list(xpos.values()),
                           ticktext=[r.replace("_", " ") for r in xpos],
                           range=[-0.6, len(xpos) - 0.4]),
            )
            st.plotly_chart(fig_g, use_container_width=True, theme=None)
            st.caption("Each dot is one satellite pass. The **line** marks the typical value (median); "
                       "the **shaded band** covers the middle 50% of passes. A tighter band means a more "
                       "consistent river.")

            # --- Methodology ---
            with st.expander("How this number is calculated"):
                st.markdown("""
                For **each satellite pass**:
                1. Water-surface elevations are aggregated to **1 km nodes** (median WSE per node).
                   This removes along-stream point-density bias before fitting.
                2. A single reach slope is fit with the **Theil–Sen estimator** (median of all
                   pairwise slopes) — robust to outliers, unlike ordinary least squares.

                We keep only passes that image the **full river** — at least **8 nodes**, a span of
                **≥ 30 km**, and a start within **3 km of the confluence**. This matters because both
                rivers are steep near the confluence and gentle toward the mouth, so a pass that only
                catches part of the river reports a misleadingly different slope. Only the
                **open-water season (Apr–Nov)** is used — winter ice inflates WSE by 0.5–2+ m.

                The headline value is the **median of those per-pass slopes** across all qualifying
                passes. See `SCIENTIFIC_METHODOLOGY.md` → *Reference Gradient (Per-Pass Robust
                Regression)* for the full verification.
                """)

            # --- Optional decomposition: why this differs from the visual trendline ---
            with st.expander("Why this differs from the Gradient Profile trendline"):
                decomp = load_refgrad_decomposition(con)
                if decomp is None:
                    st.caption("Decomposition unavailable for the current data source.")
                else:
                    rows = []
                    for reach in grad_order:
                        d = ow[ow["Reach_Name"] == reach]
                        dd = decomp[decomp["Reach_Name"] == reach]
                        if len(d) == 0 or len(dd) == 0:
                            continue
                        rows.append({
                            "River": reach.replace("_", " "),
                            "[A] pooled OLS, raw pixels": dd["pooled_raw"].iloc[0],
                            "[B] pooled OLS, 1km nodes": dd["pooled_nodes"].iloc[0],
                            "[C] per-pass OLS, mean": d["ols_cm_km"].abs().mean(),
                            "[D] per-pass Theil–Sen, mean": d["abs_slope"].mean(),
                            "[D′] Theil–Sen, median (reference)": d["abs_slope"].median(),
                        })
                    if rows:
                        st.dataframe(
                            pd.DataFrame(rows).style.format({c: "{:.1f}" for c in rows[0] if c != "River"}),
                            width="stretch", hide_index=True,
                        )
                    st.caption(
                        "[A] is the old Gradient Profile trendline (density-biased — dense downstream "
                        "pixels flatten it). [A]→[B] removing that bias is the dominant correction; "
                        "per-pass averaging and the robust estimator are smaller refinements."
                    )

    with main_dem:
        if dem_profile is None:
            st.warning("No DEM data available. If running locally, run `DEM_Pull.py` first.")
        else:
            dem_tab1, dem_tab2, dem_tab3, dem_tab4, dem_tab5 = st.tabs([
                "📈 Terrain Profile", "🔀 Elevation Difference",
                "📐 Terrain Slope", "🎯 Detrended Profile", "🗺️ Map View"
            ])

            plot_order = sorted(selected_reaches, key=lambda r: r == "Uyak_Creek")

            with dem_tab1:
                st.subheader("ArcticDEM Terrain Profile")
                fig_dem = go.Figure()

                for reach in plot_order:
                    line_color = COLOR_MAP.get(reach, "black")
                    dem_reach = dem_profile[dem_profile["Reach_Name"] == reach].sort_values("dist_bin")
                    if len(dem_reach) == 0:
                        continue

                    fig_dem.add_trace(go.Scatter(
                        x=dem_reach["dist_bin"],
                        y=dem_reach["wse_median"],
                        mode="lines",
                        name=reach,
                        line=dict(color=line_color, width=3),
                        legendgroup=reach,
                        hovertemplate=(
                            f"<b>{reach}</b><br>"
                            "Distance: %{x:.1f} km<br>"
                            "Median Elevation: %{y:.1f} m<br>"
                            "<extra></extra>"
                        ),
                    ))

                    if len(dem_reach) >= 5:
                        slope_val, intercept_val, r_val, _, _ = stats.linregress(
                            dem_reach["dist_bin"], dem_reach["wse_median"]
                        )
                        slope_cm = abs(slope_val * 100)
                        r_sq = r_val ** 2
                        x_range = np.linspace(dem_reach["dist_bin"].min(), dem_reach["dist_bin"].max(), 100)
                        fig_dem.add_trace(go.Scatter(
                            x=x_range,
                            y=intercept_val + slope_val * x_range,
                            mode="lines",
                            name=f"{reach} Linear Trend: {slope_cm:.1f} cm/km (R\u00b2={r_sq:.3f})",
                            line=dict(color=line_color, width=3, dash="dash"),
                            legendgroup=reach,
                        ))

                        # 2nd-order polynomial fit (same curve shape as the Detrended tab baseline)
                        poly = np.polynomial.Polynomial.fit(
                            dem_reach["dist_bin"], dem_reach["wse_median"], 2
                        )
                        poly_pred = poly(dem_reach["dist_bin"].values)
                        ss_res = np.sum((dem_reach["wse_median"].values - poly_pred) ** 2)
                        ss_tot = np.sum((dem_reach["wse_median"].values - dem_reach["wse_median"].mean()) ** 2)
                        poly_r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
                        fig_dem.add_trace(go.Scatter(
                            x=x_range,
                            y=poly(x_range),
                            mode="lines",
                            name=f"{reach} Poly Trend (2nd order, R\u00b2={poly_r2:.3f})",
                            line=dict(color=line_color, width=3, dash="dot"),
                            legendgroup=reach,
                        ))

                fig_dem.update_layout(
                    xaxis_title="Distance from Confluence Anchor (km)",
                    yaxis_title="Terrain Elevation (m, EGM2008)",
                    height=600, template=plotly_template,
                )
                fig_dem.update_xaxes(autorange="reversed")
                add_bifurcation_line(fig_dem)
                st.plotly_chart(fig_dem, use_container_width=True, theme=None)

                with st.expander("How to read this graph"):
                    st.markdown("""
                    **What this shows:** the shape of the *land* along each river \u2014 the
                    elevation of the river valley floor, measured from satellite imagery
                    rather than from the water.

                    - **Solid lines**: the ground elevation along each river (averaged in 0.5 km steps).
                    - **Dashed lines**: each river's average land slope, in cm of drop per km.
                    - The **R\u00b2** number (0 to 1) says how straight the slope is. Close to 1
                      means the river drops at a steady rate; lower means it curves \u2014 usually
                      steeper near the top and gentler near the coast.

                    \u2015 Technical details \u2015
                    Terrain is the median ArcticDEM V4 (2 m mosaic, 10 m export) elevation within
                    the river polygons, in EGM2008 orthometric heights, LiDAR-validated (RMSE 0.50 m).
                    Dashed line is an OLS linear fit; lower R\u00b2 reflects profile concavity
                    (Hack, 1957; Flint, 1974).
                    """)

            with dem_tab2:
                st.subheader("Terrain Elevation Difference: Kanektok \u2212 Uyak")

                if "Kanektok_River" not in dem_profile["Reach_Name"].values or "Uyak_Creek" not in dem_profile["Reach_Name"].values:
                    st.warning("Both rivers are required for this analysis.")
                else:
                    kan_dem = dem_profile[dem_profile["Reach_Name"] == "Kanektok_River"][["dist_bin", "wse_median"]].rename(
                        columns={"wse_median": "kan_median"})
                    uyak_dem = dem_profile[dem_profile["Reach_Name"] == "Uyak_Creek"][["dist_bin", "wse_median"]].rename(
                        columns={"wse_median": "uyak_median"})
                    diff_dem = kan_dem.merge(uyak_dem, on="dist_bin", how="inner")
                    diff_dem["diff"] = diff_dem["kan_median"] - diff_dem["uyak_median"]

                    fig_diff = go.Figure()
                    fig_diff.add_trace(go.Scatter(
                        x=diff_dem["dist_bin"], y=diff_dem["diff"],
                        mode="lines+markers", name="Kanektok \u2212 Uyak",
                        line=dict(color="mediumpurple", width=2), marker=dict(size=4),
                        fill="tozeroy", fillcolor="rgba(147,112,219,0.15)",
                        hovertemplate="Distance: %{x:.1f} km<br>Difference: %{y:.1f} m<br><extra></extra>",
                    ))
                    fig_diff.add_hline(y=0, line_dash="dot", line_color="gray")
                    fig_diff.update_layout(
                        xaxis_title="Distance from Confluence Anchor (km)",
                        yaxis_title="Elevation Difference (m)",
                        height=500, template=plotly_template,
                    )
                    fig_diff.update_xaxes(autorange="reversed")
                    add_bifurcation_line(fig_diff)
                    st.plotly_chart(fig_diff, use_container_width=True, theme=None)

                    with st.expander("How to read this graph"):
                        st.markdown("""
                        **What this shows:** how much higher one river valley sits than the
                        other at each point along their length.

                        - **Above zero**: the Kanektok valley floor is higher here.
                        - **Below zero**: the Uyak valley floor is higher here.
                        - When one river sits higher than its neighbor, gravity gives its water
                          a reason to spill over and shift toward the lower one \u2014 a key warning
                          sign for a river changing its path.

                        \u2015 Technical details \u2015
                        Difference of median terrain elevation between the two river corridors per
                        0.5 km bin. Analogous to *alluvial ridge height* (Slingerland & Smith, 1998);
                        Gearon et al. (2024, *Nature*) use similar metrics to predict avulsion likelihood.
                        """)

            with dem_tab3:
                st.subheader("Terrain Slope Profile")
                fig_slope = go.Figure()

                for reach in plot_order:
                    dem_reach = dem_profile[dem_profile["Reach_Name"] == reach].sort_values("dist_bin")
                    if len(dem_reach) < 3:
                        continue
                    line_color = COLOR_MAP.get(reach, "black")
                    dist_vals = dem_reach["dist_bin"].values
                    elev_vals = dem_reach["wse_median"].values
                    raw_slope = np.gradient(elev_vals, dist_vals) * 100
                    smoothed_slope = gaussian_filter1d(raw_slope, sigma=3)

                    fig_slope.add_trace(go.Scatter(
                        x=dist_vals, y=np.abs(smoothed_slope),
                        mode="lines", name=reach,
                        line=dict(color=line_color, width=2.5),
                        hovertemplate=f"<b>{reach}</b><br>Distance: %{{x:.1f}} km<br>Slope: %{{y:.1f}} cm/km<br><extra></extra>",
                    ))

                fig_slope.update_layout(
                    xaxis_title="Distance from Confluence Anchor (km)",
                    yaxis_title="Terrain Slope (cm/km)",
                    height=500, template=plotly_template,
                )
                fig_slope.update_xaxes(autorange="reversed")
                add_bifurcation_line(fig_slope)
                st.plotly_chart(fig_slope, use_container_width=True, theme=None)

                with st.expander("How to read this graph"):
                    st.markdown("""
                    **What this shows:** how steep the land is at each point along the river,
                    instead of one average slope for the whole river.

                    - **Higher line** = steeper ground there = faster, more forceful flow.
                    - Where the two rivers differ in steepness tells you which one is more
                      likely to erode and shift its path.

                    ― Technical details ―
                    Local terrain gradient = numerical derivative (central differences) of the
                    binned median elevation, smoothed with a Gaussian filter (1.5 km window).
                    """)

            with dem_tab4:
                st.subheader("Detrended Terrain Profile")

                all_dist = dem_profile["dist_bin"].values
                all_elev = dem_profile["wse_median"].values
                poly_baseline = np.polynomial.Polynomial.fit(all_dist, all_elev, 2)

                fig_detrend = go.Figure()
                for reach in plot_order:
                    dem_reach = dem_profile[dem_profile["Reach_Name"] == reach].sort_values("dist_bin")
                    if len(dem_reach) == 0:
                        continue
                    line_color = COLOR_MAP.get(reach, "black")
                    residuals = dem_reach["wse_median"].values - poly_baseline(dem_reach["dist_bin"].values)

                    fig_detrend.add_trace(go.Scatter(
                        x=dem_reach["dist_bin"], y=residuals,
                        mode="lines", name=reach,
                        line=dict(color=line_color, width=2.5),
                        hovertemplate=f"<b>{reach}</b><br>Distance: %{{x:.1f}} km<br>Residual: %{{y:.2f}} m<br><extra></extra>",
                    ))

                fig_detrend.add_hline(y=0, line_dash="dot", line_color="gray")
                fig_detrend.update_layout(
                    xaxis_title="Distance from Confluence Anchor (km)",
                    yaxis_title="Detrended Elevation (m)",
                    height=500, template=plotly_template,
                )
                fig_detrend.update_xaxes(autorange="reversed")
                add_bifurcation_line(fig_detrend)
                st.plotly_chart(fig_detrend, use_container_width=True, theme=None)

                with st.expander("How to read this graph"):
                    st.markdown("""
                    **What this shows:** the same terrain, but with the overall downhill slope
                    removed \u2014 like tilting the whole picture flat so small bumps stand out.

                    - The flat zero line is the expected smooth downhill shape both rivers share.
                    - **Above the line**: this river's valley sits higher than expected here.
                    - **Below the line**: it sits lower than expected.
                    - A river that stays **above** the line is riding high on its own built-up
                      bed (a "perched" channel) \u2014 one of the main conditions that lets a river
                      jump to a new path.

                    \u2015 Technical details \u2015
                    Baseline is a 2nd-order polynomial fit to both rivers combined, capturing the
                    expected concave-up profile (Flint, 1974). Residuals = terrain minus baseline.
                    Perched channels are a known avulsion precondition (Slingerland & Smith, 1998).
                    """)

            with dem_tab5:
                @st.fragment
                def render_dem_map():
                    st.subheader("DEM Elevation Point Map")

                    ctrl1, ctrl2, ctrl3 = st.columns([2, 2, 2])
                    with ctrl1:
                        dem_color_by = st.selectbox(
                            "Color by:", options=["River Name", "Elevation (m)"],
                            key="dem_map_color_by"
                        )
                    with ctrl2:
                        dem_basemap = st.selectbox(
                            "Basemap:", options=["OpenStreetMap", "Satellite (ESRI)"],
                            index=1, key="dem_basemap_style"
                        )
                    with ctrl3:
                        dem_opacity = st.slider(
                            "Point Opacity:", min_value=0.1, max_value=1.0,
                            value=0.7, step=0.1, key="dem_point_opacity"
                        )

                    if dem_points is None:
                        st.warning("DEM point data not available for map.")
                        return
                    map_df = dem_points[dem_points["Reach_Name"].isin(selected_reaches)]

                    center_lat = map_df["latitude"].mean()
                    center_lon = map_df["longitude"].mean()

                    basemap_tiles = {"OpenStreetMap": "OpenStreetMap", "Satellite (ESRI)": "Esri WorldImagery"}
                    m = folium.Map(
                        location=[center_lat, center_lon],
                        zoom_start=10, tiles=basemap_tiles.get(dem_basemap, "Esri WorldImagery"),
                        control_scale=True
                    )
                    plugins.MeasureControl(
                        position="topleft",
                        primary_length_unit="kilometers", secondary_length_unit="meters",
                        primary_area_unit="sqkilometers", secondary_area_unit="acres"
                    ).add_to(m)

                    if dem_color_by == "River Name":
                        for reach_name, color in COLOR_MAP.items():
                            reach_data = map_df[map_df["Reach_Name"] == reach_name]
                            if len(reach_data) == 0:
                                continue

                            features = [
                                {
                                    "type": "Feature",
                                    "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                                    "properties": {
                                        "River": reach_name,
                                        "Elevation": f"{wse:.2f} m",
                                        "Distance": f"{dist:.1f} km",
                                    }
                                }
                                for lon, lat, wse, dist in zip(
                                    reach_data["longitude"], reach_data["latitude"],
                                    reach_data["wse"], reach_data["dist_km"]
                                )
                            ]

                            folium.GeoJson(
                                {"type": "FeatureCollection", "features": features},
                                name=reach_name,
                                marker=folium.CircleMarker(radius=3, weight=0, fill=True, fill_opacity=dem_opacity),
                                style_function=lambda x, c=color: {"fillColor": c, "color": c},
                                popup=folium.GeoJsonPopup(
                                    fields=["River", "Elevation", "Distance"],
                                    aliases=["River", "Elevation", "Distance"],
                                ),
                            ).add_to(m)

                    else:  # Elevation (m)
                        vmin = float(map_df["wse"].min())
                        vmax = float(map_df["wse"].max())
                        colormap_fn = cm.get_cmap("viridis")
                        norm = mcolors.Normalize(vmin=vmin, vmax=vmax)

                        rgba_array = colormap_fn(norm(map_df["wse"].values))
                        hex_colors = [mcolors.rgb2hex(rgba[:3]) for rgba in rgba_array]

                        features = [
                            {
                                "type": "Feature",
                                "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                                "properties": {
                                    "color": color, "River": reach,
                                    "Elevation": f"{wse:.2f} m",
                                    "Distance": f"{dist:.1f} km",
                                }
                            }
                            for lon, lat, color, reach, wse, dist in zip(
                                map_df["longitude"], map_df["latitude"], hex_colors,
                                map_df["Reach_Name"], map_df["wse"], map_df["dist_km"]
                            )
                        ]

                        folium.GeoJson(
                            {"type": "FeatureCollection", "features": features},
                            name="DEM Elevation",
                            marker=folium.CircleMarker(radius=3, weight=0, fill=True, fill_opacity=dem_opacity),
                            style_function=lambda x: {
                                "fillColor": x["properties"]["color"],
                                "color": x["properties"]["color"],
                            },
                            popup=folium.GeoJsonPopup(
                                fields=["River", "Elevation", "Distance"],
                                aliases=["River", "Elevation", "Distance"],
                            ),
                        ).add_to(m)

                        VerticalColorbar(
                            caption="Elevation (m)",
                            colors=["#440154", "#31688e", "#35b779", "#fde725"],
                            vmin=vmin, vmax=vmax,
                        ).add_to(m)

                    add_bifurcation_marker(m)
                    folium.LayerControl().add_to(m)
                    st_folium(m, width=1400, height=600, key="dem_river_map", returned_objects=[])

                    with st.expander("How to read this map"):
                        st.markdown("""
                        **What this shows:** every patch of land along the rivers, placed on a
                        real map and colored by how high it is.

                        - **By river**: Kanektok (red) vs Uyak (blue).
                        - **By elevation**: purple is low ground, yellow is high ground.
                        - **Click any point** to see its exact height and distance.
                        - Use the ruler tool (top-left) to measure distances and areas.

                        ― Technical details ―
                        Each point is a 10 m ArcticDEM V4 pixel within the river polygons,
                        in EGM2008 orthometric heights.
                        """)

                render_dem_map()

            # --- DEM SUMMARY STATISTICS ---
            st.divider()
            st.subheader("DEM Summary Statistics")

            dem_summary = []
            for reach in selected_reaches:
                rp = dem_profile[dem_profile["Reach_Name"] == reach]
                slope_val = np.nan
                if len(rp) >= 5:
                    slope_val, _, _, _, _ = stats.linregress(rp["dist_bin"], rp["wse_median"])
                dem_summary.append({
                    "River Name": reach,
                    "Avg Elevation (m)": rp["wse_median"].mean(),
                    "Avg Gradient (cm/km)": abs(slope_val) * 100,
                })

            summary_df = pd.DataFrame(dem_summary)
            st.dataframe(
                summary_df.style.format({
                    "Avg Elevation (m)": "{:.2f}",
                    "Avg Gradient (cm/km)": "{:.2f}",
                }),
                width="stretch", hide_index=True
            )

            with st.expander("Where this data comes from"):
                st.markdown("""
                The land-elevation data is a high-detail terrain map of the Arctic built from
                satellite photos (ArcticDEM). We line its heights up with the same sea-level
                reference the SWOT water data uses, so the two can be compared directly. It has
                been checked against aircraft laser surveys and is accurate to about half a meter.

                \u2015 Technical details \u2015
                - **Source:** ArcticDEM V4 2 m mosaic (Polar Geospatial Center), exported at 10 m via Google Earth Engine.
                - **Vertical datum:** EGM2008 orthometric heights; geoid correction applied using
                  spatially-interpolated undulation values (~13.2\u201313.8 m at the study site) to match the SWOT datum.
                - **Statistics:** profile stats computed from all ~2.5M pixels via DuckDB (exact bin
                  medians/percentiles). Map shows a random sample of 15,000 points for performance.
                  Summary stats use distance-weighted averaging (0.5 km bin medians).
                - **Validation:** independently validated against NOAA QL1 LiDAR (RMSE 0.50 m).
                """)

    with tab2:
        st.subheader("Elevation Difference: Kanektok - Uyak")

        # Check if both rivers are selected
        if len(selected_reaches) != 2:
            st.warning("⚠️ This analysis requires both rivers to be selected. Please select both Kanektok River and Uyak Creek.")
        else:
            # Query to bin distances and calculate average WSE per river
            diff_query = f"""
                WITH binned_data AS (
                    SELECT
                        ROUND(dist_km / 0.1) * 0.1 AS dist_bin,
                        Reach_Name,
                        AVG(wse) AS avg_wse,
                        COUNT(*) AS point_count
                    FROM river_data
                    {where_clause}
                    GROUP BY dist_bin, Reach_Name
                ),
                kanektok AS (
                    SELECT
                        dist_bin,
                        avg_wse as kanektok_wse,
                        point_count as kanektok_count
                    FROM binned_data
                    WHERE Reach_Name = 'Kanektok_River'
                ),
                uyak AS (
                    SELECT
                        dist_bin,
                        avg_wse as uyak_wse,
                        point_count as uyak_count
                    FROM binned_data
                    WHERE Reach_Name = 'Uyak_Creek'
                )
                SELECT
                    k.dist_bin,
                    k.kanektok_wse,
                    u.uyak_wse,
                    k.kanektok_wse - u.uyak_wse AS elevation_diff,
                    k.kanektok_count,
                    u.uyak_count
                FROM kanektok k
                INNER JOIN uyak u ON k.dist_bin = u.dist_bin
                ORDER BY k.dist_bin
            """

            try:
                diff_df = con.execute(diff_query).fetchdf()

                if len(diff_df) == 0:
                    st.warning("No overlapping distance bins found between the two rivers.")
                else:
                    # Create the elevation difference plot
                    fig_diff = go.Figure()

                    # Add the elevation difference line
                    fig_diff.add_trace(go.Scatter(
                        x=diff_df['dist_bin'],
                        y=diff_df['elevation_diff'],
                        mode='lines+markers',
                        name='Kanektok - Uyak',
                        line=dict(color='darkgreen', width=3),
                        marker=dict(size=5),
                        hovertemplate='<b>Distance</b>: %{x:.2f} km<br>' +
                                      '<b>Elevation Diff</b>: %{y:.3f} m<br>' +
                                      '<extra></extra>'
                    ))

                    # Add zero reference line
                    fig_diff.add_hline(
                        y=0,
                        line_dash="dash",
                        line_color="gray",
                        annotation_text="Equal Elevation",
                        annotation_position="right"
                    )

                    # Update layout
                    fig_diff.update_layout(
                        xaxis_title="Distance from Anchor Point (km)",
                        yaxis_title="Elevation Difference (m)",
                        height=600,
                        template=plotly_template,
                        hovermode='x unified'
                    )

                    # Reverse x-axis to match other plots (Coast on left, Confluence on right)
                    fig_diff.update_xaxes(autorange="reversed")
                    add_bifurcation_line(fig_diff)

                    st.plotly_chart(fig_diff, width="stretch", theme=None)

                    # Add interpretation guide
                    with st.expander("How to read this graph"):
                        st.markdown("""
                        **What this shows:** which river's *water* sits higher at each point
                        along the way.

                        - **Above zero**: Kanektok's water is higher here.
                        - **Below zero**: Uyak's water is higher here.
                        - **On the zero line**: the two are at the same height.

                        ― Technical details ―
                        Water heights are averaged in 100 m bins, then differenced (Kanektok − Uyak).
                        """)

                    # Show summary statistics
                    max_abs_idx = diff_df['elevation_diff'].abs().idxmax()
                    max_abs_diff = diff_df.loc[max_abs_idx, 'elevation_diff']
                    max_kanektok = diff_df['elevation_diff'].max()  # Most positive = Kanektok highest above Uyak
                    max_uyak = diff_df['elevation_diff'].min()      # Most negative = Uyak highest above Kanektok

                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Average Difference", f"{diff_df['elevation_diff'].mean():.3f} m")
                    col2.metric("Max |Difference|", f"{max_abs_diff:.3f} m",
                                help="Largest absolute elevation difference (positive = Kanektok higher, negative = Uyak higher)")
                    col3.metric("Kanektok Max Above", f"+{max_kanektok:.3f} m",
                                help="Greatest elevation where Kanektok is above Uyak")
                    col4.metric("Uyak Max Above", f"{max_uyak:.3f} m",
                                help="Greatest elevation where Uyak is above Kanektok")

            except Exception as e:
                st.error(f"Error calculating elevation difference: {e}")

    with tab3:
        st.subheader("Detrended Elevation Profile")

        # Helper function for LOESS smoothing
        def loess_smooth(x, y, frac=0.1):
            """Simple LOESS-like smoothing using weighted moving average"""
            from scipy.ndimage import gaussian_filter1d

            # Sort by x
            sorted_idx = np.argsort(x)
            x_sorted = x[sorted_idx]
            y_sorted = y[sorted_idx]

            # Use Gaussian smoothing as approximation of LOESS
            # Sigma controls smoothness (larger = smoother)
            sigma = len(x) * frac / 3
            y_smooth = gaussian_filter1d(y_sorted, sigma=sigma, mode='nearest')

            # Map back to original order
            y_result = np.zeros_like(y)
            y_result[sorted_idx] = y_smooth

            return y_result

        try:
            # Get dataset for baseline (with memory-safe limit for Streamlit Cloud)
            # Check total count first
            count_query = f"SELECT COUNT(*) FROM river_data {where_clause}"
            total_count = con.execute(count_query).fetchone()[0]

            # Use sampling if dataset is too large (prevents memory issues)
            if total_count > MAX_BASELINE_POINTS:
                st.info(f"📊 Using {MAX_BASELINE_POINTS:,} sampled points for baseline fitting (out of {total_count:,} total) to optimize performance.")
                baseline_query = f"""
                    SELECT * FROM (
                        SELECT dist_km, wse, Reach_Name,
                               row_number() OVER (ORDER BY RANDOM()) as rn
                        FROM river_data
                        {where_clause}
                    ) sub
                    WHERE rn <= {MAX_BASELINE_POINTS}
                    ORDER BY dist_km
                """
            else:
                baseline_query = f"""
                    SELECT dist_km, wse, Reach_Name
                    FROM river_data
                    {where_clause}
                    ORDER BY dist_km
                """

            baseline_df = con.execute(baseline_query).fetchdf()

            if len(baseline_df) == 0:
                st.warning("No data available for detrending analysis.")
            else:
                # Use cached detrending function for performance
                baseline_pred, coeffs, method_name = calculate_detrending(
                    baseline_df['dist_km'].tolist(),
                    baseline_df['wse'].tolist(),
                    detrend_method
                )

                # Calculate residuals
                baseline_df['residual'] = baseline_df['wse'].values - baseline_pred
                baseline_df['baseline'] = baseline_pred

                # Clean up memory after large operations
                gc.collect()

                # Check detrending quality
                overall_mean_residual = baseline_df['residual'].mean()
                overall_std_residual = baseline_df['residual'].std()

                # Warning if only one river selected (detrending works best with both)
                num_rivers = baseline_df['Reach_Name'].nunique()
                if num_rivers == 1:
                    st.warning("⚠️ **Single river selected**: Detrending works best when BOTH rivers are selected. The baseline is currently fit to only one river, which may leave systematic patterns in the residuals.")

                # Sample for visualization if needed
                if len(baseline_df) > MAX_PLOT_POINTS:
                    step_size = int(len(baseline_df) / MAX_PLOT_POINTS)
                    plot_df = baseline_df.iloc[::step_size].copy()
                    st.info(f"📉 Showing 1 out of every {step_size} points for visualization.")
                else:
                    plot_df = baseline_df

                # Create detrended plot
                fig_detrend = go.Figure()

                # Plot residuals for each river (Uyak on top)
                for reach in sorted(selected_reaches, key=lambda r: r == "Uyak_Creek"):
                    reach_data = plot_df[plot_df['Reach_Name'] == reach]
                    if len(reach_data) == 0:
                        continue

                    line_color = COLOR_MAP.get(reach, "black")

                    # Solid legend marker
                    fig_detrend.add_trace(go.Scatter(
                        x=[None], y=[None],
                        mode='markers',
                        name=reach,
                        marker=dict(color=line_color, size=8, opacity=1.0),
                        legendgroup=reach,
                    ))
                    # Translucent data points (hidden from legend)
                    fig_detrend.add_trace(go.Scatter(
                        x=reach_data['dist_km'],
                        y=reach_data['residual'],
                        mode='markers',
                        marker=dict(color=line_color, size=3, opacity=0.4),
                        legendgroup=reach,
                        showlegend=False,
                        hovertemplate='<b>' + reach + '</b><br>' +
                                      'Distance: %{x:.2f} km<br>' +
                                      'Residual: %{y:.3f} m<br>' +
                                      '<extra></extra>'
                    ))

                # Add zero reference line
                fig_detrend.add_hline(
                    y=0,
                    line_dash="dash",
                    line_color="gray",
                    line_width=2,
                    annotation_text="Baseline Trend",
                    annotation_position="right"
                )

                # Update layout
                fig_detrend.update_layout(
                    xaxis_title="Distance from Anchor Point (km)",
                    yaxis_title=f"Residual Elevation (m) - Detrended using {method_name}",
                    height=600,
                    template=plotly_template,
                    hovermode='closest',
                    showlegend=True
                )

                # Reverse x-axis to match other plots
                fig_detrend.update_xaxes(autorange="reversed")
                add_bifurcation_line(fig_detrend)

                st.plotly_chart(fig_detrend, width="stretch", theme=None)

                # Show fit quality metrics
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Overall Mean Residual", f"{overall_mean_residual:.4f} m",
                             help="Should be close to 0.000 for a good fit")
                with col2:
                    st.metric("Residual Std Dev", f"{overall_std_residual:.3f} m",
                             help="Measures spread of residuals around baseline")
                with col3:
                    st.metric("Rivers in Baseline Fit", num_rivers,
                             help="Detrending works best when both rivers are included")

                # Diagnostic warning if residuals show systematic bias
                if abs(overall_mean_residual) > 0.5:
                    st.error(f"""
                    🔴 **Poor Fit Detected**: Overall mean residual is {overall_mean_residual:.2f}m (should be ~0).

                    **Possible causes:**
                    - Only one river selected (try selecting both)
                    - Wrong detrending method for your data shape
                    - Data has extreme outliers

                    **Try:** Switch to "Linear" or "LOESS" detrending method.
                    """)

                # Add interpretation guide
                with st.expander("How to read this graph"):
                    st.markdown(f"""
                    **What this shows:** the water profile with its overall downhill slope
                    removed — like flattening the picture so small ups and downs stand out.

                    - The flat zero line is the river's expected smooth trend.
                    - **Above the line**: the water is higher than expected here.
                    - **Below the line**: it's lower than expected.
                    - This makes subtle differences between the two rivers easy to see.

                    **What to look for:**
                    - A steady gap between the two rivers means one consistently sits higher than the other.
                    - A river that stays above the line is steeper than average; below the line, gentler.

                    **Is it working?** The dots should scatter evenly around zero with no leftover
                    tilt. If you still see a clear up- or down-slope, the chosen baseline shape
                    doesn't fit this data well — try a different one below.

                    ― Technical details ―
                    Baseline = {method_name} fit through all points of the selected river(s);
                    the plot shows the residuals (data minus baseline). Mean residual ≈ 0 when the fit is appropriate.
                    """)

                # Method-specific guidance
                method_guidance = {
                    "Linear": """
                        **Using Linear Baseline:**
                        - Shows how rivers deviate from a constant slope
                        - Large residuals suggest curved river profile
                        - If both rivers show similar curve patterns, try Polynomial
                        """,
                    "2nd Order Polynomial": """
                        **Using 2nd Order Polynomial Baseline:**
                        - Captures gentle curvature in river profiles
                        - Most rivers show this type of gradual downstream slope change
                        - Residuals show deviations from this smooth curve
                        - Best for highlighting systematic differences between rivers
                        """,
                    "3rd Order Polynomial": """
                        **Using 3rd Order Polynomial Baseline:**
                        - Can capture more complex profile shapes (inflection points)
                        - Useful if rivers have distinct reaches (steep→gentle→steep)
                        - May reduce residuals by fitting more closely to data
                        - Watch for overfitting if residuals become very small
                        """,
                    "LOESS (Local Regression)": """
                        **Using LOESS Baseline:**
                        - Adapts smoothly to local variations in the data
                        - Most flexible - follows overall trend without rigid shape
                        - Good for complex profiles or when other methods leave patterns
                        - Residuals primarily show differences between rivers, not profile shape
                        """
                }

                st.success(method_guidance.get(method_name, ""))

                # Show statistics per river
                st.subheader("Detrended Elevation Statistics")

                stats_data = []
                for reach in selected_reaches:
                    reach_data = baseline_df[baseline_df['Reach_Name'] == reach]
                    if len(reach_data) > 0:
                        residuals = reach_data['residual']
                        stats_data.append({
                            "River": reach,
                            "Mean Residual (m)": residuals.mean(),
                            "Std Dev (m)": residuals.std(),
                            "Min Residual (m)": residuals.min(),
                            "Max Residual (m)": residuals.max(),
                            "Range (m)": residuals.max() - residuals.min()
                        })

                if stats_data:
                    stats_summary = pd.DataFrame(stats_data)
                    st.dataframe(
                        stats_summary.style.format({
                            "Mean Residual (m)": "{:.3f}",
                            "Std Dev (m)": "{:.3f}",
                            "Min Residual (m)": "{:.3f}",
                            "Max Residual (m)": "{:.3f}",
                            "Range (m)": "{:.3f}"
                        }),
                        width="stretch",
                        hide_index=True
                    )

                # Optional: Show baseline trend curve
                with st.expander("📊 Show Baseline Trend Curve"):
                    # Sample the baseline for plotting
                    baseline_plot_df = baseline_df.sort_values('dist_km')
                    if len(baseline_plot_df) > 1000:
                        baseline_plot_df = baseline_plot_df.iloc[::len(baseline_plot_df)//1000]

                    fig_baseline = go.Figure()

                    # Add all original data points
                    for reach in selected_reaches:
                        reach_data = plot_df[plot_df['Reach_Name'] == reach]
                        line_color = COLOR_MAP.get(reach, "black")
                        fig_baseline.add_trace(go.Scatter(
                            x=reach_data['dist_km'],
                            y=reach_data['wse'],
                            mode='markers',
                            name=reach,
                            marker=dict(color=line_color, size=3, opacity=0.3)
                        ))

                    # Add baseline curve
                    fig_baseline.add_trace(go.Scatter(
                        x=baseline_plot_df['dist_km'],
                        y=baseline_plot_df['baseline'],
                        mode='lines',
                        name='Baseline Trend',
                        line=dict(color='black', width=3, dash='dash')
                    ))

                    fig_baseline.update_layout(
                        xaxis_title="Distance from Anchor Point (km)",
                        yaxis_title="Water Surface Elevation (m)",
                        height=500,
                        template=plotly_template,
                        title=f"Original Data with {method_name} Baseline"
                    )

                    fig_baseline.update_xaxes(autorange="reversed")
                    add_bifurcation_line(fig_baseline)
                    st.plotly_chart(fig_baseline, width="stretch", theme=None)

        except Exception as e:
            st.error(f"Error calculating detrended profile: {e}")
            import traceback
            st.code(traceback.format_exc())

    with tab4:
        st.subheader("Slope Profile")

        # Query raw data per river
        slope_query = f"""
            SELECT dist_km, wse, Reach_Name
            FROM river_data
            {where_clause}
            ORDER BY Reach_Name, dist_km
        """

        try:
            slope_raw_df = con.execute(slope_query).fetchdf()

            if len(slope_raw_df) == 0:
                st.warning("No data available for the selected filters.")
            else:
                fig_slopes = go.Figure()
                slope_stats = []

                for reach in selected_reaches:
                    reach_data = slope_raw_df[slope_raw_df['Reach_Name'] == reach]
                    if len(reach_data) < 10:
                        st.warning(f"Insufficient data for {reach} ({len(reach_data)} points). Need at least 10.")
                        continue

                    x_eval, slope_cm_km, y_fitted = calculate_slope_profile(
                        reach_data['dist_km'].tolist(),
                        reach_data['wse'].tolist()
                    )

                    line_color = COLOR_MAP.get(reach, "black")
                    abs_slope = np.abs(slope_cm_km)

                    fig_slopes.add_trace(go.Scatter(
                        x=x_eval,
                        y=abs_slope,
                        mode='lines',
                        name=reach,
                        line=dict(color=line_color, width=3),
                        hovertemplate='<b>' + reach + '</b><br>' +
                                      'Distance: %{x:.2f} km<br>' +
                                      'Slope: %{y:.1f} cm/km<br>' +
                                      '<extra></extra>'
                    ))

                    slope_stats.append({
                        "River": reach,
                        "Mean Slope (cm/km)": abs_slope.mean(),
                        "Max Slope (cm/km)": abs_slope.max(),
                        "Min Slope (cm/km)": abs_slope.min(),
                        "Slope at Coast (cm/km)": abs_slope[0],
                        "Slope at Confluence (cm/km)": abs_slope[-1],
                        "Points Used": len(reach_data)
                    })

                fig_slopes.update_layout(
                    xaxis_title="Distance from Anchor Point (km)",
                    yaxis_title="Slope (cm/km)",
                    height=600,
                    template=plotly_template,
                    hovermode='x unified',
                    showlegend=True
                )
                fig_slopes.update_xaxes(autorange="reversed")
                add_bifurcation_line(fig_slopes)

                st.plotly_chart(fig_slopes, width="stretch", theme=None)

                with st.expander("How to read this graph"):
                    st.markdown("""
                    **What this shows:** how the *water's* steepness changes along the river,
                    instead of one average slope for the whole thing.

                    - **Higher line** = steeper water surface there = faster, more forceful flow.
                    - Compare the two rivers to spot where one is clearly steeper than the other.

                    ― Technical details ―
                    WSE binned to 100 m medians, smoothed with a 2 km Gaussian window; slope is
                    the derivative of the smoothed elevation profile (cm/km).
                    """)

                if slope_stats:
                    st.subheader("Slope Profile Statistics")
                    stats_summary = pd.DataFrame(slope_stats)
                    st.dataframe(
                        stats_summary.style.format({
                            "Mean Slope (cm/km)": "{:.1f}",
                            "Max Slope (cm/km)": "{:.1f}",
                            "Min Slope (cm/km)": "{:.1f}",
                            "Slope at Coast (cm/km)": "{:.1f}",
                            "Slope at Confluence (cm/km)": "{:.1f}",
                        }),
                        width="stretch",
                        hide_index=True
                    )

        except Exception as e:
            st.error(f"Error calculating slope profile: {e}")

    with tab5:
        @st.fragment
        def render_map():
            st.subheader("Satellite Data Point Locations")

            # --- Map display controls (inside fragment for isolated reruns) ---
            ctrl1, ctrl2, ctrl3 = st.columns(3)
            with ctrl1:
                map_color_by = st.selectbox(
                    "Color Points By:",
                    options=["River Name", "Classification", "Detrended Residual (m)", "Interval Slope (cm/km)"],
                    index=0, key="map_color_by"
                )
            with ctrl2:
                basemap_style = st.selectbox(
                    "Basemap Style:",
                    options=["OpenStreetMap", "Satellite (ESRI)"],
                    index=1, key="basemap_style"
                )
            with ctrl3:
                point_opacity = st.slider(
                    "Point Opacity:", min_value=0.1, max_value=1.0,
                    value=0.7, step=0.1, key="point_opacity"
                )

            # Sample data if too large
            if len(viz_df) > MAX_MAP_POINTS:
                map_df = viz_df.sample(MAX_MAP_POINTS)
                st.info(f"📍 Showing {MAX_MAP_POINTS:,} sampled points (out of {len(viz_df):,}) for map performance.")
            else:
                map_df = viz_df

            center_lat = map_df['latitude'].mean()
            center_lon = map_df['longitude'].mean()

            basemap_tiles = {"OpenStreetMap": "OpenStreetMap", "Satellite (ESRI)": "Esri WorldImagery"}
            selected_tiles = basemap_tiles.get(basemap_style, "Esri WorldImagery")

            m = folium.Map(
                location=[center_lat, center_lon],
                zoom_start=10, tiles=selected_tiles, control_scale=True
            )

            plugins.MeasureControl(
                position='topleft',
                primary_length_unit='kilometers', secondary_length_unit='meters',
                primary_area_unit='sqkilometers', secondary_area_unit='acres'
            ).add_to(m)

            # Configure coloring based on user selection
            if map_color_by == "River Name":
                for reach_name, color in COLOR_MAP.items():
                    reach_data = map_df[map_df['Reach_Name'] == reach_name]
                    if len(reach_data) == 0:
                        continue

                    features = [
                        {
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                            "properties": {
                                "River": reach_name, "WSE": f"{wse:.2f} m",
                                "Date": str(date), "Class": int(cls),
                            }
                        }
                        for lon, lat, wse, date, cls in zip(
                            reach_data['longitude'], reach_data['latitude'],
                            reach_data['wse'], reach_data['Pass_Date'],
                            reach_data['classification']
                        )
                    ]

                    folium.GeoJson(
                        {"type": "FeatureCollection", "features": features},
                        name=reach_name,
                        marker=folium.CircleMarker(radius=3, weight=0, fill=True, fill_opacity=point_opacity),
                        style_function=lambda x, c=color: {'fillColor': c, 'color': c},
                        popup=folium.GeoJsonPopup(
                            fields=['River', 'WSE', 'Date', 'Class'],
                            aliases=['River', 'WSE', 'Date', 'Class'],
                        ),
                    ).add_to(m)

            elif map_color_by == "Classification":
                class_colors = {
                    3: "#FFA500", 4: "#00CED1", 5: "#90EE90",
                    6: "#FFB6C1", 7: "#DDA0DD"
                }

                for class_val, color in class_colors.items():
                    class_data = map_df[map_df['classification'] == class_val]
                    if len(class_data) == 0:
                        continue

                    features = [
                        {
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                            "properties": {
                                "River": reach, "WSE": f"{wse:.2f} m",
                                "Date": str(date), "Class": int(class_val),
                            }
                        }
                        for lon, lat, reach, wse, date in zip(
                            class_data['longitude'], class_data['latitude'],
                            class_data['Reach_Name'], class_data['wse'],
                            class_data['Pass_Date']
                        )
                    ]

                    folium.GeoJson(
                        {"type": "FeatureCollection", "features": features},
                        name=f"Class {class_val}",
                        marker=folium.CircleMarker(radius=3, weight=0, fill=True, fill_opacity=point_opacity),
                        style_function=lambda x, c=color: {'fillColor': c, 'color': c},
                        popup=folium.GeoJsonPopup(
                            fields=['River', 'WSE', 'Date', 'Class'],
                            aliases=['River', 'WSE', 'Date', 'Class'],
                        ),
                    ).add_to(m)

            elif map_color_by == "Detrended Residual (m)":
                # Fixed scale: -3 to 3m, positive=blue (above baseline), negative=red (below)
                res_bound = 3.0
                colormap_fn = cm.get_cmap('RdBu')
                norm = mcolors.Normalize(vmin=-res_bound, vmax=res_bound, clip=True)

                # Vectorized color computation
                rgba_array = colormap_fn(norm(map_df['detrended_residual'].values))
                hex_colors = [mcolors.rgb2hex(rgba[:3]) for rgba in rgba_array]

                features = [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                        "properties": {
                            "color": color, "River": reach,
                            "Residual": f"{res:+.3f} m", "WSE": f"{wse:.2f} m",
                            "Date": str(date),
                        }
                    }
                    for lon, lat, color, reach, res, wse, date in zip(
                        map_df['longitude'], map_df['latitude'], hex_colors,
                        map_df['Reach_Name'], map_df['detrended_residual'],
                        map_df['wse'], map_df['Pass_Date']
                    )
                ]

                folium.GeoJson(
                    {"type": "FeatureCollection", "features": features},
                    name="Detrended Residual",
                    marker=folium.CircleMarker(radius=3, weight=0, fill=True, fill_opacity=point_opacity),
                    style_function=lambda x: {
                        'fillColor': x['properties']['color'],
                        'color': x['properties']['color'],
                    },
                    popup=folium.GeoJsonPopup(
                        fields=['River', 'Residual', 'WSE', 'Date'],
                        aliases=['River', 'Residual', 'WSE', 'Date'],
                    ),
                ).add_to(m)

                VerticalColorbar(
                    caption='Residual (m)',
                    colors=['#b2182b', '#f4a582', '#f7f7f7', '#92c5de', '#2166ac'],
                    vmin=-res_bound,
                    vmax=res_bound,
                ).add_to(m)

            elif map_color_by == "Interval Slope (cm/km)":
                slope_min = float(map_df['interval_slope'].abs().min())
                slope_max = float(map_df['interval_slope'].abs().max())
                colormap_fn = cm.get_cmap('YlOrRd')
                norm = mcolors.Normalize(vmin=slope_min, vmax=slope_max)

                # Vectorized color computation
                abs_slopes = map_df['interval_slope'].abs().values
                rgba_array = colormap_fn(norm(abs_slopes))
                hex_colors = [mcolors.rgb2hex(rgba[:3]) for rgba in rgba_array]

                features = [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                        "properties": {
                            "color": color, "River": reach,
                            "Slope": f"{slope:.2f} cm/km", "WSE": f"{wse:.2f} m",
                            "Date": str(date),
                        }
                    }
                    for lon, lat, color, reach, slope, wse, date in zip(
                        map_df['longitude'], map_df['latitude'], hex_colors,
                        map_df['Reach_Name'], abs_slopes,
                        map_df['wse'], map_df['Pass_Date']
                    )
                ]

                folium.GeoJson(
                    {"type": "FeatureCollection", "features": features},
                    name="Interval Slope",
                    marker=folium.CircleMarker(radius=3, weight=0, fill=True, fill_opacity=point_opacity),
                    style_function=lambda x: {
                        'fillColor': x['properties']['color'],
                        'color': x['properties']['color'],
                    },
                    popup=folium.GeoJsonPopup(
                        fields=['River', 'Slope', 'WSE', 'Date'],
                        aliases=['River', 'Slope', 'WSE', 'Date'],
                    ),
                ).add_to(m)

                VerticalColorbar(
                    caption='Slope (cm/km)',
                    colors=['#ffffb2', '#fd8d3c', '#bd0026'],
                    vmin=slope_min,
                    vmax=slope_max,
                ).add_to(m)

            # Add layer control (toggle layers on/off)
            add_bifurcation_marker(m)
            folium.LayerControl().add_to(m)

            st_folium(
                m, width=1400, height=600,
                key="river_map", returned_objects=[]
            )

            # Interpretation guides
            if map_color_by == "Detrended Residual (m)":
                st.info("""
                **Color Interpretation - Detrended Residual (2nd Order Polynomial):**
                - **Blue**: Points ABOVE the baseline trend (higher than expected elevation)
                - **Red**: Points BELOW the baseline trend (lower than expected elevation)
                - **White**: Points exactly on the baseline

                **What this shows:**
                - Spatial patterns of elevation deviations from the overall river profile
                - Blue clusters = river sits higher than expected at that distance
                - Red clusters = river sits lower than expected at that distance
                """)
            elif map_color_by == "Interval Slope (cm/km)":
                st.info("""
                **Color Interpretation - Interval Slope:**
                - **Yellow**: Gentle slopes (low gradient)
                - **Orange**: Moderate slopes
                - **Red**: Steep slopes (high gradient)

                **What this shows:**
                - Segment-by-segment steepness (100m intervals)
                - Red areas = higher energy, faster flow potential
                - Yellow areas = lower energy, slower flow
                """)

        render_map()

    with tab6:
        st.subheader("Data Inspector")
        st.dataframe(viz_df.head(1000), width="stretch")
        st.caption(f"Showing first 1000 rows of visualization sample.")

        csv = viz_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "⬇️ Download Sample Data as CSV",
            csv,
            "swot_sample_data.csv",
            "text/csv",
            key='download-csv'
        )

    # === LOCAL-ONLY TABS (Temporal, Seasonal, Typhoon) ===
    # These tabs only appear when running locally (is_local=True).
    # When remote, we skip these blocks entirely.
    if is_local:

     with tab7:
        st.subheader("⏳ Temporal Evolution Analysis")

        st.info("""
        **Purpose:** Track how river metrics evolve over time to identify trends, seasonal patterns, and anomalies.

        **Data:** Monthly averages from satellite passes across the full date range.

        **Ice season note:** At this latitude (~59.8°N), Oct-May data may include ice-affected measurements.
        Open-water season (Jun-Sep) is most reliable for WSE analysis. See Seasonal Comparison tab for details.
        """)

        # User controls
        col1, col2 = st.columns(2)

        with col1:
            # Future: Add aggregation level selector (per-pass, monthly, seasonal)
            st.markdown("**Temporal Aggregation:** Monthly averages")

        with col2:
            ma_window = st.selectbox(
                "Moving Average Window:",
                options=[3, 6, 12],
                index=1,  # Default 6
                help="Number of consecutive months to average for trendline smoothing"
            )

        show_moving_avg = st.checkbox(
            "Show Moving Average Trendlines",
            value=True,
            help="Overlay smoothed trends on time series plots"
        )

        # Check session state cache
        if "temporal_df" not in st.session_state or st.session_state.get("temporal_where") != where_clause:
            with st.spinner("Computing temporal metrics..."):
                # Query for monthly aggregated metrics
                monthly_query = f"""
                WITH monthly_passes AS (
                    SELECT
                        DATE_TRUNC('month', CAST(Pass_Date AS DATE)) AS month,
                        Pass_Date,
                        Reach_Name,
                        AVG(wse) AS avg_wse_per_pass,
                        STDDEV(wse) AS std_wse_per_pass,
                        AVG(ABS(slope_calc)) AS avg_gradient_per_pass,
                        STDDEV(slope_calc) AS std_gradient_per_pass,
                        COUNT(*) AS point_count
                    FROM river_data
                    {where_clause}
                    GROUP BY month, Pass_Date, Reach_Name
                )
                SELECT
                    month,
                    Pass_Date,
                    Reach_Name,
                    AVG(avg_wse_per_pass) AS monthly_avg_wse,
                    AVG(std_wse_per_pass) AS monthly_wse_std,
                    AVG(avg_gradient_per_pass) AS monthly_avg_gradient,
                    AVG(std_gradient_per_pass) AS monthly_gradient_std,
                    COUNT(DISTINCT Pass_Date) AS passes_in_month,
                    SUM(point_count) AS total_points
                FROM monthly_passes
                GROUP BY month, Pass_Date, Reach_Name
                ORDER BY Pass_Date, Reach_Name
                """

                temporal_df = con.execute(monthly_query).fetchdf()
                st.session_state.temporal_df = temporal_df
                st.session_state.temporal_where = where_clause

                # Query for WSE evolution at specific distances
                # Note: This cross-join query can fail over httpfs (remote parquet)
                try:
                    dist_evolution_query = f"""
                    WITH distance_targets AS (
                        SELECT * FROM (VALUES (10.0), (20.0), (30.0), (40.0), (50.0), (60.0)) AS t(target_dist)
                    ),
                    nearest_points AS (
                        SELECT
                            DATE_TRUNC('month', CAST(Pass_Date AS DATE)) AS month,
                            Pass_Date,
                            Reach_Name,
                            dist_km,
                            wse,
                            dt.target_dist,
                            ABS(dist_km - dt.target_dist) AS dist_diff,
                            ROW_NUMBER() OVER (
                                PARTITION BY Pass_Date, Reach_Name, dt.target_dist
                                ORDER BY ABS(dist_km - dt.target_dist)
                            ) AS rn
                        FROM river_data, distance_targets dt
                        {where_clause}
                    )
                    SELECT
                        month,
                        Pass_Date,
                        Reach_Name,
                        target_dist,
                        AVG(wse) AS wse_at_distance,
                        COUNT(*) AS sample_size
                    FROM nearest_points
                    WHERE rn <= 5
                      AND dist_diff < 0.5
                    GROUP BY month, Pass_Date, Reach_Name, target_dist
                    ORDER BY Pass_Date, target_dist, Reach_Name
                    """

                    dist_evolution_df = con.execute(dist_evolution_query).fetchdf()
                    st.session_state.dist_evolution_df = dist_evolution_df
                except Exception:
                    st.session_state.dist_evolution_df = pd.DataFrame()

                # Query for elevation difference over time (only if both rivers selected)
                try:
                    if len(selected_reaches) == 2:
                        elev_diff_query = f"""
                        WITH binned_wse AS (
                            SELECT
                                DATE_TRUNC('month', CAST(Pass_Date AS DATE)) AS month,
                                Pass_Date,
                                ROUND(dist_km / 0.5) * 0.5 AS dist_bin,
                                Reach_Name,
                                AVG(wse) AS avg_wse
                            FROM river_data
                            {where_clause}
                            GROUP BY month, Pass_Date, dist_bin, Reach_Name
                            HAVING COUNT(*) >= 3
                        ),
                        kanektok AS (
                            SELECT month, Pass_Date, dist_bin, avg_wse AS k_wse
                            FROM binned_wse WHERE Reach_Name = 'Kanektok_River'
                        ),
                        uyak AS (
                            SELECT month, Pass_Date, dist_bin, avg_wse AS u_wse
                            FROM binned_wse WHERE Reach_Name = 'Uyak_Creek'
                        )
                        SELECT
                            k.month,
                            k.Pass_Date,
                            AVG(k.k_wse - u.u_wse) AS avg_elev_diff,
                            STDDEV(k.k_wse - u.u_wse) AS std_elev_diff,
                            COUNT(*) AS overlap_bins
                        FROM kanektok k
                        JOIN uyak u ON k.Pass_Date = u.Pass_Date AND k.dist_bin = u.dist_bin
                        GROUP BY k.month, k.Pass_Date
                        ORDER BY k.Pass_Date
                        """

                        elev_diff_df = con.execute(elev_diff_query).fetchdf()
                        st.session_state.elev_diff_df = elev_diff_df
                except Exception:
                    pass
        else:
            temporal_df = st.session_state.temporal_df
            dist_evolution_df = st.session_state.dist_evolution_df
            if len(selected_reaches) == 2 and "elev_diff_df" in st.session_state:
                elev_diff_df = st.session_state.elev_diff_df

        # === TIME SERIES VISUALIZATIONS ===
        st.markdown("### 1. Time Series: Key Metrics")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### Average WSE per Pass")

            fig_wse = go.Figure()

            for reach in selected_reaches:
                reach_data = temporal_df[temporal_df['Reach_Name'] == reach].sort_values('Pass_Date')

                # Raw monthly data
                fig_wse.add_trace(go.Scatter(
                    x=reach_data['Pass_Date'],
                    y=reach_data['monthly_avg_wse'],
                    mode='markers+lines',
                    name=reach,
                    marker=dict(size=6, color=COLOR_MAP[reach]),
                    line=dict(width=1.5, color=COLOR_MAP[reach]),
                    hovertemplate='<b>%{fullData.name}</b><br>' +
                                  'Date: %{x|%Y-%m-%d}<br>' +
                                  'Avg WSE: %{y:.2f} m<br>' +
                                  '<extra></extra>',
                    connectgaps=False
                ))

                # Moving average overlay
                if show_moving_avg and len(reach_data) >= ma_window:
                    ma_series = reach_data.set_index('Pass_Date')['monthly_avg_wse']
                    ma_values = compute_moving_average(ma_series, window=ma_window)

                    fig_wse.add_trace(go.Scatter(
                        x=ma_values.index,
                        y=ma_values.values,
                        mode='lines',
                        name=f"{reach} ({ma_window}-month MA)",
                        line=dict(width=3, color=COLOR_MAP[reach], dash='dash'),
                        opacity=0.8,
                        hovertemplate=f'<b>Moving Avg ({ma_window})</b><br>' +
                                      'WSE: %{y:.2f} m<br>' +
                                      '<extra></extra>'
                    ))

            fig_wse.update_layout(
                xaxis_title="Date",
                yaxis_title="Water Surface Elevation (m)",
                height=400,
                template=plotly_template,
                hovermode='x unified',
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )

            st.plotly_chart(fig_wse, width='stretch', theme=None)

        with col2:
            st.markdown("#### Average Gradient per Pass")

            fig_grad = go.Figure()

            for reach in selected_reaches:
                reach_data = temporal_df[temporal_df['Reach_Name'] == reach].sort_values('Pass_Date')

                fig_grad.add_trace(go.Scatter(
                    x=reach_data['Pass_Date'],
                    y=reach_data['monthly_avg_gradient'],
                    mode='markers+lines',
                    name=reach,
                    marker=dict(size=6, color=COLOR_MAP[reach]),
                    line=dict(width=1.5, color=COLOR_MAP[reach]),
                    hovertemplate='<b>%{fullData.name}</b><br>' +
                                  'Date: %{x|%Y-%m-%d}<br>' +
                                  'Gradient: %{y:.2f} cm/km<br>' +
                                  '<extra></extra>',
                    connectgaps=False
                ))

                if show_moving_avg and len(reach_data) >= ma_window:
                    ma_series = reach_data.set_index('Pass_Date')['monthly_avg_gradient']
                    ma_values = compute_moving_average(ma_series, window=ma_window)

                    fig_grad.add_trace(go.Scatter(
                        x=ma_values.index,
                        y=ma_values.values,
                        mode='lines',
                        name=f"{reach} ({ma_window}-month MA)",
                        line=dict(width=3, color=COLOR_MAP[reach], dash='dash'),
                        opacity=0.8
                    ))

            fig_grad.update_layout(
                xaxis_title="Date",
                yaxis_title="Hydraulic Gradient (cm/km)",
                height=400,
                template=plotly_template,
                hovermode='x unified'
            )

            st.plotly_chart(fig_grad, width='stretch', theme=None)

        # Second row: WSE at specific distances and elevation difference
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### WSE Evolution at Fixed Distances")

            dist_evolution_df = st.session_state.get("dist_evolution_df", pd.DataFrame())
            if len(dist_evolution_df) == 0:
                st.info("WSE at fixed distances not available (query too complex for remote data).")
            else:
                fig_dist = go.Figure()

                for reach in selected_reaches:
                    for target_dist in [10, 20, 30, 40, 50, 60]:
                        subset = dist_evolution_df[
                        (dist_evolution_df['Reach_Name'] == reach) &
                        (dist_evolution_df['target_dist'] == target_dist)
                    ].sort_values('Pass_Date')

                    if len(subset) == 0:
                        continue

                    # Opacity varies with distance (closer = more opaque)
                    opacity = 1.0 - (target_dist / 70) * 0.5

                    fig_dist.add_trace(go.Scatter(
                        x=subset['Pass_Date'],
                        y=subset['wse_at_distance'],
                        mode='lines',
                        name=f"{reach} @ {int(target_dist)}km",
                        line=dict(width=2, color=COLOR_MAP[reach]),
                        opacity=opacity,
                        hovertemplate=f'<b>{reach} @ {int(target_dist)}km</b><br>' +
                                      'Date: %{x|%Y-%m-%d}<br>' +
                                      'WSE: %{y:.2f} m<br>' +
                                      '<extra></extra>',
                        connectgaps=False,
                        legendgroup=reach
                    ))

                fig_dist.update_layout(
                    xaxis_title="Date",
                    yaxis_title="Water Surface Elevation (m)",
                    height=400,
                    template=plotly_template,
                    hovermode='x unified'
                )

                st.plotly_chart(fig_dist, width='stretch', theme=None)

        with col2:
            st.markdown("#### Elevation Difference Over Time")

            if len(selected_reaches) == 2 and "elev_diff_df" in st.session_state:
                elev_diff_df = st.session_state.elev_diff_df
                fig_diff = go.Figure()

                elev_diff_sorted = elev_diff_df.sort_values('Pass_Date')

                # Main trend line with error bars
                fig_diff.add_trace(go.Scatter(
                    x=elev_diff_sorted['Pass_Date'],
                    y=elev_diff_sorted['avg_elev_diff'],
                    mode='markers+lines',
                    name='Kanektok - Uyak',
                    marker=dict(size=6, color='darkgreen'),
                    line=dict(width=2, color='darkgreen'),
                    error_y=dict(
                        type='data',
                        array=elev_diff_sorted['std_elev_diff'],
                        visible=True,
                        color='lightgray',
                        thickness=1
                    ),
                    hovertemplate='<b>Elevation Difference</b><br>' +
                                  'Date: %{x|%Y-%m-%d}<br>' +
                                  'Diff: %{y:.3f} m<br>' +
                                  '<extra></extra>'
                ))

                # Zero reference line
                fig_diff.add_hline(
                    y=0,
                    line_dash="dash",
                    line_color="gray",
                    line_width=1,
                    annotation_text="Equal Elevation",
                    annotation_position="bottom right"
                )

                # Moving average
                if show_moving_avg and len(elev_diff_sorted) >= ma_window:
                    ma_series = elev_diff_sorted.set_index('Pass_Date')['avg_elev_diff']
                    ma_values = compute_moving_average(ma_series, window=ma_window)

                    fig_diff.add_trace(go.Scatter(
                        x=ma_values.index,
                        y=ma_values.values,
                        mode='lines',
                        name=f'{ma_window}-month MA',
                        line=dict(width=3, color='darkgreen', dash='dot')
                    ))

                fig_diff.update_layout(
                    xaxis_title="Date",
                    yaxis_title="Elevation Difference (m)",
                    height=400,
                    template=plotly_template,
                    hovermode='x unified'
                )

                st.plotly_chart(fig_diff, width='stretch', theme=None)
            else:
                st.warning("⚠️ Elevation difference requires both rivers to be selected.")

        # === ANOMALY DETECTION ===
        with st.expander("🚨 Anomaly Detection", expanded=False):
            st.markdown("""
            **What this does:** automatically flags satellite passes that look unusual — where
            the water height or slope is far from what's typical. An odd pass can mean either a
            measurement glitch or a real, dramatic event (like a flood). It's a way to catch
            dates worth a closer look.

            ― Technical details ―
            Modified Z-score using MAD (median absolute deviation), threshold 3.5 (matches the
            data-pipeline filtering). Flags passes where monthly-average WSE or gradient deviate
            significantly from the typical value.
            """)

            # Detect anomalies for each river and metric
            anomalies_list = []

            for reach in selected_reaches:
                reach_data = temporal_df[temporal_df['Reach_Name'] == reach].copy()

                if len(reach_data) == 0:
                    continue

                # Detect WSE anomalies
                reach_data['is_anomaly_wse'] = detect_anomalies_mad(
                    reach_data['monthly_avg_wse'],
                    threshold=3.5
                )

                # Detect gradient anomalies
                reach_data['is_anomaly_gradient'] = detect_anomalies_mad(
                    reach_data['monthly_avg_gradient'],
                    threshold=3.5
                )

                # Mark as anomalous if either metric is anomalous
                reach_data['is_anomaly'] = (
                    reach_data['is_anomaly_wse'] | reach_data['is_anomaly_gradient']
                )

                anomalies_list.append(reach_data[reach_data['is_anomaly']])

            if anomalies_list:
                anomaly_df = pd.concat(anomalies_list, ignore_index=True)
            else:
                anomaly_df = pd.DataFrame()

            if len(anomaly_df) > 0:
                st.warning(f"⚠️ Detected {len(anomaly_df)} anomalous passes")

                st.dataframe(
                    anomaly_df[[
                        'Pass_Date', 'Reach_Name', 'monthly_avg_wse',
                        'monthly_avg_gradient', 'is_anomaly_wse', 'is_anomaly_gradient'
                    ]].style.format({
                        'monthly_avg_wse': '{:.2f} m',
                        'monthly_avg_gradient': '{:.2f} cm/km'
                    }),
                    width='stretch'
                )
            else:
                st.success("✅ No anomalies detected in selected data")

        # === HEATMAP SECTION ===
        with st.expander("📊 Heatmap: Distance × Time Evolution", expanded=False):
            st.markdown("""
            **What this shows:** the whole river over the whole time period in one picture.
            Each column is a month, each row is a spot along the river, and the **color** is the
            water height there. It lets you spot patterns — for example, whether the upstream
            end rises and falls differently from the coast over the seasons.

            - **Left–right:** month.
            - **Up–down:** distance along the river (km from where the rivers meet).
            - **Color:** average water height (m).
            """)

            # Query for heatmap (only run when section expanded)
            if "heatmap_df" not in st.session_state or st.session_state.get("heatmap_where") != where_clause:
                with st.spinner("Computing heatmap data..."):
                    heatmap_query = f"""
                    WITH binned_data AS (
                        SELECT
                            DATE_TRUNC('month', CAST(Pass_Date AS DATE)) AS month,
                            ROUND(dist_km / 1.0) * 1.0 AS dist_bin,
                            Reach_Name,
                            AVG(wse) AS avg_wse,
                            COUNT(*) AS point_count
                        FROM river_data
                        {where_clause}
                        GROUP BY month, dist_bin, Reach_Name
                        HAVING COUNT(*) >= 3
                    )
                    SELECT month, dist_bin, Reach_Name, avg_wse, point_count
                    FROM binned_data
                    ORDER BY Reach_Name, month, dist_bin
                    """

                    heatmap_df = con.execute(heatmap_query).fetchdf()
                    st.session_state.heatmap_df = heatmap_df
                    st.session_state.heatmap_where = where_clause
            else:
                heatmap_df = st.session_state.heatmap_df

            for reach in selected_reaches:
                reach_heatmap = heatmap_df[heatmap_df['Reach_Name'] == reach]

                if len(reach_heatmap) == 0:
                    st.warning(f"No heatmap data for {reach}")
                    continue

                # Pivot to matrix format
                pivot_data = reach_heatmap.pivot_table(
                    index='dist_bin',
                    columns='month',
                    values='avg_wse',
                    aggfunc='mean'
                )

                fig_heat = go.Figure(data=go.Heatmap(
                    z=pivot_data.values,
                    x=pivot_data.columns,
                    y=pivot_data.index,
                    colorscale='Viridis',
                    colorbar=dict(title="WSE (m)"),
                    hovertemplate='Month: %{x|%Y-%m}<br>' +
                                  'Distance: %{y:.0f} km<br>' +
                                  'Avg WSE: %{z:.2f} m<br>' +
                                  '<extra></extra>'
                ))

                fig_heat.update_layout(
                    title=f"{reach} - Water Surface Elevation Heatmap",
                    xaxis_title="Month",
                    yaxis_title="Distance from Confluence (km)",
                    height=500,
                    template=plotly_template
                )

                # Reverse Y-axis (coast at top, confluence at bottom)
                fig_heat.update_yaxes(autorange="reversed")
                add_bifurcation_line(fig_heat, axis="y")

                st.plotly_chart(fig_heat, width='stretch', theme=None)

        # === SUMMARY STATISTICS ===
        st.markdown("### Summary Statistics")

        # Calculate temporal trends
        summary_stats = []

        for reach in selected_reaches:
            reach_data = temporal_df[temporal_df['Reach_Name'] == reach].sort_values('Pass_Date')

            if len(reach_data) > 0:
                # Calculate linear trend
                days_elapsed = (pd.to_datetime(reach_data['Pass_Date']) - pd.to_datetime(reach_data['Pass_Date'].min())).dt.days

                wse_trend, wse_intercept, wse_r, wse_p, _ = stats.linregress(days_elapsed, reach_data['monthly_avg_wse'])
                grad_trend, grad_intercept, grad_r, grad_p, _ = stats.linregress(days_elapsed, reach_data['monthly_avg_gradient'])

                summary_stats.append({
                    'River': reach,
                    'Passes': len(reach_data),
                    'Avg WSE (m)': reach_data['monthly_avg_wse'].mean(),
                    'WSE Trend (m/year)': wse_trend * 365,
                    'WSE R²': wse_r**2,
                    'Avg Gradient (cm/km)': reach_data['monthly_avg_gradient'].mean(),
                    'Gradient Trend (cm/km/year)': grad_trend * 365
                })

        summary_df = pd.DataFrame(summary_stats)

        st.dataframe(
            summary_df.style.format({
                'Avg WSE (m)': '{:.2f}',
                'WSE Trend (m/year)': '{:.4f}',
                'WSE R²': '{:.3f}',
                'Avg Gradient (cm/km)': '{:.2f}',
                'Gradient Trend (cm/km/year)': '{:.4f}'
            }),
            width='stretch'
        )

        with st.expander("How to read these numbers"):
            st.markdown("""
            - **Water-level trend:** positive means the water is rising over time; negative means it's dropping.
            - **Slope trend:** whether the river is getting steeper or gentler over time.
            - **R²** (0 to 1): how clear the trend is. Close to 1 is a steady, reliable trend;
              close to 0 means the values jump around a lot.
            """)

     # === TAB 8: SEASONAL COMPARISON ===
     with tab8:
        st.subheader("Seasonal Comparison: High Flow vs Low Flow (2023-2025)")
        st.caption("Top row: High flow (May). Bottom row: Low flow (July-August). Each panel compares both rivers.")

        # Build subplot titles in grid order (row-major: left-to-right, top-to-bottom)
        # make_subplots assigns titles as (1,1),(1,2),(1,3),(2,1),(2,2),(2,3)
        title_grid = [[None]*3 for _ in range(2)]
        for p in SEASONAL_PERIODS:
            title_grid[p["row"]][p["col"]] = p["label"]
        grid_ordered_titles = [title_grid[r][c] for r in range(2) for c in range(3)]

        fig_seasonal = make_subplots(
            rows=2, cols=3,
            subplot_titles=grid_ordered_titles,
            shared_yaxes=True, horizontal_spacing=0.04, vertical_spacing=0.08
        )

        summary_rows = []

        for period in SEASONAL_PERIODS:
            row, col = period["row"] + 1, period["col"] + 1  # Plotly 1-indexed
            df_period, stats_period, period_count = query_period_data(con, period["start"], period["end"], selected_reaches)

            used_label = period["label"]

            # Handle May 2023 fallback
            if df_period is None and "fallback_start" in period:
                df_period, stats_period, period_count = query_period_data(con, period["fallback_start"], period["fallback_end"], selected_reaches)
                if df_period is not None:
                    used_label = period.get("fallback_label", period["label"])
                    # Update subplot title annotation
                    for ann in fig_seasonal.layout.annotations:
                        if ann.text == period["label"]:
                            ann.text = used_label

            if df_period is None:
                fig_seasonal.add_annotation(
                    text="No data available",
                    xref=f"x{'' if (row == 1 and col == 1) else (col + (row - 1) * 3)}",
                    yref=f"y{'' if (row == 1 and col == 1) else (col + (row - 1) * 3)}",
                    x=0.5, y=0.5, xanchor="center", yanchor="middle",
                    showarrow=False, font=dict(size=14, color="gray"),
                    row=row, col=col
                )
                continue

            for reach in selected_reaches:
                reach_df = df_period[df_period['Reach_Name'] == reach]
                if len(reach_df) == 0:
                    continue

                fig_seasonal.add_trace(go.Scatter(
                    x=reach_df['dist_km'], y=reach_df['wse'],
                    mode='markers',
                    marker=dict(color=COLOR_MAP.get(reach, "black"), size=3, opacity=0.3),
                    name=reach,
                    showlegend=(row == 1 and col == 1),
                    legendgroup=reach,
                ), row=row, col=col)

                # Trendline
                if len(reach_df) >= 5:
                    slope, intercept, r_val, _, _ = stats.linregress(reach_df['dist_km'], reach_df['wse'])
                    x_range = np.linspace(reach_df['dist_km'].min(), reach_df['dist_km'].max(), 50)
                    fig_seasonal.add_trace(go.Scatter(
                        x=x_range, y=intercept + slope * x_range,
                        mode='lines',
                        line=dict(color=COLOR_MAP.get(reach, "black"), width=3, dash='dash'),
                        name=f"{reach} {abs(slope * 100):.1f} cm/km",
                        showlegend=False,
                    ), row=row, col=col)

                    # Collect for summary table
                    reach_stats_row = stats_period[stats_period['Reach_Name'] == reach]
                    n_passes = int(reach_stats_row['n_passes'].iloc[0]) if len(reach_stats_row) > 0 else 0
                    summary_rows.append({
                        "Period": used_label, "River": reach,
                        "Slope (cm/km)": round(abs(slope * 100), 2),
                        "R²": round(r_val**2, 3),
                        "Points": period_count, "Passes": n_passes
                    })

            fig_seasonal.update_xaxes(autorange="reversed", row=row, col=col)

        fig_seasonal.update_layout(
            height=800, template=plotly_template,
            title_text="Seasonal WSE Profiles: High Flow (May) vs Low Flow (Jul-Aug)"
        )
        add_bifurcation_line(fig_seasonal)
        st.plotly_chart(fig_seasonal, width='stretch', theme=None)

        # Summary statistics table
        if summary_rows:
            st.subheader("Slope Summary")
            st.dataframe(pd.DataFrame(summary_rows), width='stretch', hide_index=True)

        st.info("""**How to read this:** Each panel shows WSE vs distance for both rivers.
        Top row = high flow (May), bottom row = low flow (July-August).
        Dashed lines show linear trendlines with slope values.
        Steeper slopes indicate faster-flowing reaches. Compare slopes between years to detect changes.""")

        st.warning("""**Ice Season Note:** May panels (top row) fall within the spring break-up period
        (Apr-May) for rivers at this latitude (~59.8°N). Some SWOT measurements may reflect
        ice surface elevation rather than open water, which would be 0.5-2+ m higher than true WSE.
        The PIXC classification filter (Classes 3-4) excludes most ice pixels, but partially frozen
        surfaces during break-up may still pass. July-August panels (bottom row) are fully within
        the open-water season and are the most reliable for gradient comparison.""")

     # === TAB 9: TYPHOON IMPACT ===
     with tab9:
        st.subheader("Typhoon Halong Impact Analysis (October 12-14, 2025)")
        st.caption("Compare river profiles before and after Typhoon Halong struck Quinhagak, Alaska, eroding ~60 feet of shoreline.")

        # Build rivers_sql for this tab scope
        rivers_sql_tab9 = ", ".join([f"'{r}'" for r in selected_reaches])

        st.info("""**How we do this fairly:** rivers naturally rise and fall with the seasons, so to
        see what the *storm* actually changed we compare the **same season** in two different years —
        Summer 2025 (before) vs Summer 2026 (after). Comparing summer to winter would be misleading,
        because in winter the satellite reads the ice surface and the heights look 0.5–2+ m too high.""")

        # --- Section A: Same-Season Comparison (PRIMARY) ---
        st.markdown("### Same-Season Comparison (Summer 2025 vs Summer 2026)")

        pre_s = TYPHOON_PERIODS["pre_season"]
        post_s = TYPHOON_PERIODS["post_season"]

        df_pre_s, stats_pre_s, n_pre_s = query_period_data(con, pre_s["start"], pre_s["end"], selected_reaches)
        df_post_s, stats_post_s, n_post_s = query_period_data(con, post_s["start"], post_s["end"], selected_reaches)

        if df_pre_s is not None and df_post_s is not None and n_post_s > 0:
            fig_season = make_subplots(
                rows=1, cols=2,
                subplot_titles=[pre_s["label"], post_s["label"]],
                shared_yaxes=True, horizontal_spacing=0.06
            )

            season_slope_changes = {}
            for panel_idx, (df_panel, label) in enumerate([(df_pre_s, "pre"), (df_post_s, "post")], 1):
                for reach in selected_reaches:
                    reach_df = df_panel[df_panel['Reach_Name'] == reach]
                    if len(reach_df) < 5:
                        continue

                    fig_season.add_trace(go.Scatter(
                        x=reach_df['dist_km'], y=reach_df['wse'],
                        mode='markers',
                        marker=dict(color=COLOR_MAP.get(reach, "black"), size=3, opacity=0.3),
                        name=reach,
                        showlegend=(panel_idx == 1),
                        legendgroup=reach,
                    ), row=1, col=panel_idx)

                    slope, intercept, _, _, _ = stats.linregress(reach_df['dist_km'], reach_df['wse'])
                    season_slope_changes.setdefault(reach, {})[label] = slope * 100
                    x_range = np.linspace(reach_df['dist_km'].min(), reach_df['dist_km'].max(), 50)
                    fig_season.add_trace(go.Scatter(
                        x=x_range, y=intercept + slope * x_range,
                        mode='lines',
                        line=dict(color=COLOR_MAP.get(reach, "black"), width=3, dash='dash'),
                        name=f"{abs(slope * 100):.1f} cm/km",
                        showlegend=False,
                    ), row=1, col=panel_idx)

                fig_season.update_xaxes(autorange="reversed", row=1, col=panel_idx)

            fig_season.update_layout(height=500, template=plotly_template,
                                     title_text="Same-Season Comparison: Summer 2025 vs Summer 2026")
            add_bifurcation_line(fig_season)
            st.plotly_chart(fig_season, width='stretch', theme=None)

            # Slope change metrics
            cols = st.columns(len(season_slope_changes))
            for i, (reach, slopes) in enumerate(season_slope_changes.items()):
                if "pre" in slopes and "post" in slopes:
                    change = abs(slopes["post"]) - abs(slopes["pre"])
                    cols[i].metric(
                        f"{reach} Slope",
                        f"{abs(slopes['post']):.2f} cm/km",
                        delta=f"{change:+.2f} cm/km vs pre-storm"
                    )

            # Binned elevation change using same-season data
            st.markdown("---")
            st.markdown("### Elevation Change by Distance (Same-Season)")
            try:
                change_query = f"""
                    WITH pre AS (
                        SELECT ROUND(dist_km / 0.5) * 0.5 AS dist_bin, Reach_Name, AVG(wse) AS pre_wse
                        FROM river_data WHERE CAST(Pass_Date AS DATE) >= CAST('{pre_s["start"]}' AS DATE) AND CAST(Pass_Date AS DATE) <= CAST('{pre_s["end"]}' AS DATE)
                        AND Reach_Name IN ({rivers_sql_tab9})
                        GROUP BY dist_bin, Reach_Name HAVING COUNT(*) >= 3
                    ),
                    post AS (
                        SELECT ROUND(dist_km / 0.5) * 0.5 AS dist_bin, Reach_Name, AVG(wse) AS post_wse
                        FROM river_data WHERE CAST(Pass_Date AS DATE) >= CAST('{post_s["start"]}' AS DATE) AND CAST(Pass_Date AS DATE) <= CAST('{post_s["end"]}' AS DATE)
                        AND Reach_Name IN ({rivers_sql_tab9})
                        GROUP BY dist_bin, Reach_Name HAVING COUNT(*) >= 3
                    )
                    SELECT pre.dist_bin, pre.Reach_Name, pre.pre_wse, post.post_wse,
                           post.post_wse - pre.pre_wse AS wse_change
                    FROM pre INNER JOIN post ON pre.dist_bin = post.dist_bin AND pre.Reach_Name = post.Reach_Name
                    ORDER BY pre.Reach_Name, pre.dist_bin
                """
                change_df = con.execute(change_query).fetchdf()

                if len(change_df) > 0:
                    fig_change = px.line(change_df, x="dist_bin", y="wse_change",
                                        color="Reach_Name", color_discrete_map=COLOR_MAP)
                    fig_change.add_hline(y=0, line_dash="dash", line_color="gray")
                    fig_change.update_xaxes(autorange="reversed")
                    fig_change.update_layout(
                        height=400, template=plotly_template,
                        yaxis_title="WSE Change (m)", xaxis_title="Distance from Anchor Point (km)",
                        title_text="Summer 2026 minus Summer 2025 WSE"
                    )
                    add_bifurcation_line(fig_change)
                    st.plotly_chart(fig_change, width='stretch', theme=None)
                    st.caption("Above zero = water height rose after the storm; below zero = it dropped. "
                               "Measured in 500 m steps (min. 3 points each); comparing the same season avoids ice errors.")
                else:
                    st.info("Not enough overlapping distance bins between pre- and post-storm seasons.")
            except Exception as e:
                st.error(f"Error computing elevation change: {e}")

        else:
            st.info("""**Open-water post-storm data not yet available.**

As of May 2026, Alaska rivers are just beginning breakup. The open-water same-season
comparison (Summer 2025 vs Summer 2026) will become available once SWOT captures
June-August 2026 data. Re-run `SWOT_Pull.py` after June 2026 to populate this section.""")

            # --- Interim: Same-Month Year-over-Year (ice-season, but matched conditions) ---
            # Find the latest month we have in both pre- and post-typhoon years
            try:
                interim_query = """
                    SELECT EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) AS mo,
                           EXTRACT(YEAR FROM CAST(Pass_Date AS DATE)) AS yr,
                           COUNT(*) AS pts, COUNT(DISTINCT Pass_Date) AS passes
                    FROM river_data
                    WHERE EXTRACT(YEAR FROM CAST(Pass_Date AS DATE)) IN (2025, 2026)
                      AND EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) <= 5
                    GROUP BY yr, mo
                    HAVING COUNT(DISTINCT Pass_Date) >= 3
                    ORDER BY yr, mo
                """
                interim_df = con.execute(interim_query).fetchdf()

                # Find months present in both years
                months_2025 = set(interim_df[interim_df['yr'] == 2025]['mo'].astype(int))
                months_2026 = set(interim_df[interim_df['yr'] == 2026]['mo'].astype(int))
                shared_months = sorted(months_2025 & months_2026, reverse=True)

                if shared_months:
                    # Use the latest shared month for the best interim comparison
                    compare_month = shared_months[0]
                    month_name = ["", "Jan", "Feb", "Mar", "Apr", "May"][compare_month]

                    st.markdown(f"### Interim Comparison: {month_name} 2025 vs {month_name} 2026 (same-month, year-over-year)")
                    st.warning(f"""**Interim analysis — interpret with caution.** {month_name} falls within the
                    ice/break-up season at this latitude. Both years are compared under the **same seasonal
                    conditions**, so ice artifacts should be similar and largely cancel out when comparing
                    **slopes** (gradients). However, absolute WSE values will be affected by ice thickness
                    and are not reliable. **Focus on slope changes, not WSE changes.** This will be replaced
                    by the open-water comparison once summer 2026 data is available.""")

                    pre_interim_start = f"2025-{compare_month:02d}-01"
                    pre_interim_end = f"2025-{compare_month:02d}-28"
                    post_interim_start = f"2026-{compare_month:02d}-01"
                    post_interim_end = f"2026-{compare_month:02d}-28"

                    df_pre_int, stats_pre_int, n_pre_int = query_period_data(con, pre_interim_start, pre_interim_end, selected_reaches)
                    df_post_int, stats_post_int, n_post_int = query_period_data(con, post_interim_start, post_interim_end, selected_reaches)

                    if df_pre_int is not None and df_post_int is not None:
                        fig_interim = make_subplots(
                            rows=1, cols=2,
                            subplot_titles=[f"{month_name} 2025 (Pre-Storm)", f"{month_name} 2026 (Post-Storm)"],
                            shared_yaxes=True, horizontal_spacing=0.06
                        )

                        interim_slope_changes = {}
                        for panel_idx, (df_panel, label) in enumerate([(df_pre_int, "pre"), (df_post_int, "post")], 1):
                            for reach in selected_reaches:
                                reach_df = df_panel[df_panel['Reach_Name'] == reach]
                                if len(reach_df) < 5:
                                    continue

                                fig_interim.add_trace(go.Scatter(
                                    x=reach_df['dist_km'], y=reach_df['wse'],
                                    mode='markers',
                                    marker=dict(color=COLOR_MAP.get(reach, "black"), size=3, opacity=0.3),
                                    name=reach,
                                    showlegend=(panel_idx == 1),
                                    legendgroup=reach,
                                ), row=1, col=panel_idx)

                                slope, intercept, _, _, _ = stats.linregress(reach_df['dist_km'], reach_df['wse'])
                                interim_slope_changes.setdefault(reach, {})[label] = slope * 100
                                x_range = np.linspace(reach_df['dist_km'].min(), reach_df['dist_km'].max(), 50)
                                fig_interim.add_trace(go.Scatter(
                                    x=x_range, y=intercept + slope * x_range,
                                    mode='lines',
                                    line=dict(color=COLOR_MAP.get(reach, "black"), width=3, dash='dash'),
                                    name=f"{abs(slope * 100):.1f} cm/km",
                                    showlegend=False,
                                ), row=1, col=panel_idx)

                            fig_interim.update_xaxes(autorange="reversed", row=1, col=panel_idx)

                        fig_interim.update_layout(height=500, template=plotly_template,
                                                  title_text=f"Same-Month Comparison: {month_name} 2025 vs {month_name} 2026")
                        add_bifurcation_line(fig_interim)
                        st.plotly_chart(fig_interim, width='stretch', theme=None)

                        # Slope change metrics
                        cols = st.columns(len(interim_slope_changes))
                        for i, (reach, slopes) in enumerate(interim_slope_changes.items()):
                            if "pre" in slopes and "post" in slopes:
                                change = abs(slopes["post"]) - abs(slopes["pre"])
                                cols[i].metric(
                                    f"{reach} Slope",
                                    f"{abs(slopes['post']):.2f} cm/km",
                                    delta=f"{change:+.2f} cm/km vs pre-storm"
                                )

            except Exception as e:
                st.error(f"Error computing interim comparison: {e}")

        # --- Section B: Immediate Before/After (ice-contaminated, for reference only) ---
        st.markdown("---")
        with st.expander("Immediate Before/After (Aug-Sep vs Oct-Dec 2025) — ice-contaminated, use with caution"):
            st.error("""**Warning — river ice makes this comparison unreliable.** It puts open-water
            months (Aug–Sep) next to freeze-up months (Oct–Dec). When the river is frozen, the
            satellite reads the **top of the ice, not the water below**, so the later heights are
            likely **too high by 0.5–2+ meters**. Our filters remove most ice, but partly-frozen
            surfaces can slip through. **Do not use these slope changes to judge storm impact.**
            Use the same-season comparison above instead.""")

            pre = TYPHOON_PERIODS["pre_immediate"]
            post = TYPHOON_PERIODS["post_immediate"]

            df_pre, stats_pre, n_pre = query_period_data(con, pre["start"], pre["end"], selected_reaches)
            df_post, stats_post, n_post = query_period_data(con, post["start"], post["end"], selected_reaches)

            if df_pre is not None and df_post is not None:
                fig_imm = make_subplots(
                    rows=1, cols=2,
                    subplot_titles=[pre["label"], post["label"]],
                    shared_yaxes=True, horizontal_spacing=0.06
                )

                slope_changes = {}
                for panel_idx, (df_panel, label) in enumerate([(df_pre, "pre"), (df_post, "post")], 1):
                    for reach in selected_reaches:
                        reach_df = df_panel[df_panel['Reach_Name'] == reach]
                        if len(reach_df) < 5:
                            continue

                        fig_imm.add_trace(go.Scatter(
                            x=reach_df['dist_km'], y=reach_df['wse'],
                            mode='markers',
                            marker=dict(color=COLOR_MAP.get(reach, "black"), size=3, opacity=0.3),
                            name=reach,
                            showlegend=(panel_idx == 1),
                            legendgroup=reach,
                        ), row=1, col=panel_idx)

                        slope, intercept, _, _, _ = stats.linregress(reach_df['dist_km'], reach_df['wse'])
                        slope_changes.setdefault(reach, {})[label] = slope * 100
                        x_range = np.linspace(reach_df['dist_km'].min(), reach_df['dist_km'].max(), 50)
                        fig_imm.add_trace(go.Scatter(
                            x=x_range, y=intercept + slope * x_range,
                            mode='lines',
                            line=dict(color=COLOR_MAP.get(reach, "black"), width=3, dash='dash'),
                            name=f"{abs(slope * 100):.1f} cm/km",
                            showlegend=False,
                        ), row=1, col=panel_idx)

                    fig_imm.update_xaxes(autorange="reversed", row=1, col=panel_idx)

                fig_imm.update_layout(height=500, template=plotly_template)
                add_bifurcation_line(fig_imm)
                st.plotly_chart(fig_imm, width='stretch', theme=None)

                # Slope change metrics
                cols = st.columns(len(slope_changes))
                for i, (reach, slopes) in enumerate(slope_changes.items()):
                    if "pre" in slopes and "post" in slopes:
                        change = abs(slopes["post"]) - abs(slopes["pre"])
                        cols[i].metric(
                            f"{reach} Slope",
                            f"{abs(slopes['post']):.2f} cm/km",
                            delta=f"{change:+.2f} cm/km vs pre-storm"
                        )
            elif df_pre is not None:
                st.warning("No post-storm data available for Oct-Dec 2025.")
            else:
                st.warning("Insufficient data for immediate before/after comparison.")

    # --- SUMMARY STATS & DATA INFO (inside SWOT tab) ---
    with main_swot:
        st.divider()
        st.subheader("Summary Statistics")

        col1, col2, col3 = st.columns(3)
        col1.metric("Passes Analyzed", viz_df['Pass_Date'].nunique())
        col2.metric("Total Data Points", f"{count:,}")
        col3.metric("Visualization Sample", f"{len(viz_df):,}")

        # Gradient is intentionally NOT shown here: a per-selection average is
        # density-biased and conflates passes at different stages. The authoritative
        # gradient lives in the "Hydraulic Gradient" tab (per-pass robust, full record).
        display_stats = stats_df[["Reach_Name", "avg_wse"]].copy()
        display_stats = display_stats.rename(columns={
            "Reach_Name": "River Name",
            "avg_wse": "Avg WSE (m)",
        })
        st.dataframe(
            display_stats.style.format({"Avg WSE (m)": "{:.2f}"}),
            width='stretch',
            hide_index=True
        )
        st.caption("River gradient is reported in the **📏 Hydraulic Gradient** tab "
                   "(per-pass robust slope over the full open-water record), not as a per-selection average.")

        with st.expander("How these numbers are made (and cleaned)"):
            st.markdown("""
            **Average water height:** the satellite collects far more points in some stretches
            than others, so a plain average would be lopsided. Instead we split the river into
            1 km steps, take the typical value in each step, and weight every step equally — so
            the result reflects the whole river fairly, not just the busiest stretch.

            **River slope** is kept out of this table on purpose: a quick average over your
            selected passes is biased the same lopsided way. The trustworthy slope lives in the
            **📏 Hydraulic Gradient** tab.

            **Cleaning:** we keep only the satellite's high-quality water readings and
            automatically drop a few extreme outliers before any of this is computed.

            ― Technical details ―
            - **Avg WSE:** distance-weighted average — 1 km bins, median per bin, bins averaged
              equally — to remove along-stream point-density bias (swath geometry, river width, classification rate).
            - **Gradient:** reported in the Hydraulic Gradient tab as a per-pass robust (Theil–Sen)
              slope over the full open-water record (median across passes); a per-selection average is density-biased.
            - **Filtering:** SWOT Classes 3–4 (high-quality water pixels); MAD-based outlier
              removal (modified Z-score threshold 3.5), per-reach at ingestion.

            See `SCIENTIFIC_METHODOLOGY.md` for the complete methodology.
            """)


def main():
    con = get_database_connection()
    if not con:
        st.error("Failed to initialize database connection.")
        st.stop()

    # Load metadata (cached)
    try:
        with st.spinner("Loading data metadata..."):
            all_pass_dates, available_reaches = load_metadata(con)
            if all_pass_dates is None:
                st.error("No data found. Please run SWOT_Pull.py first to generate data.")
                st.stop()
    except Exception as e:
        st.error(f"Could not read metadata: {e}")
        st.stop()

    # Page router
    if "page" not in st.session_state:
        st.session_state.page = "welcome"

    if st.session_state.page == "welcome":
        render_welcome(all_pass_dates)
    else:
        render_dashboard(con, all_pass_dates, available_reaches)


if __name__ == "__main__":
    main()
