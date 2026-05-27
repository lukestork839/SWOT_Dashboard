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
REMOTE_PARQUET_URL = "https://github.com/lukestork839/SWOT_Dashboard/releases/download/v2.0-data/swot_apr_jul_2025_2026.parquet"
MAX_PLOT_POINTS = 15000  # Reduced for large datasets (was 25000)
MAX_BASELINE_POINTS = 30000  # Reduced for Streamlit Cloud (was 50000)
MAX_MAP_POINTS = 5000  # Strict limit for map rendering

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
ICE_SEASONS = {
    "frozen": {"months": [12, 1, 2, 3], "label": "Frozen (Dec-Mar)", "severity": "warning"},
}
ICE_AFFECTED_MONTHS = {12, 1, 2, 3}  # Dec-Mar (data-validated peak ice contamination)
OPEN_WATER_MONTHS = {4, 5, 6, 7, 8, 9, 10, 11}  # Apr-Nov (reliable for WSE analysis)

def get_ice_warning(start_date_str, end_date_str):
    """Check if a date range overlaps with ice-affected months.
    Returns (severity, message) or (None, None) if fully open water."""
    start = pd.to_datetime(start_date_str)
    end = pd.to_datetime(end_date_str)
    # Collect all months spanned
    months_spanned = set()
    current = start.replace(day=1)
    while current <= end:
        months_spanned.add(current.month)
        current += pd.DateOffset(months=1)

    ice_months = months_spanned & ICE_AFFECTED_MONTHS
    if not ice_months:
        return None, None

    # Determine which ice seasons are hit
    hit_seasons = []
    for season_key, season in ICE_SEASONS.items():
        if ice_months & set(season["months"]):
            hit_seasons.append(season)

    # Use the most severe level
    severity = "warning" if any(s["severity"] == "warning" for s in hit_seasons) else "caution"
    season_labels = ", ".join(s["label"] for s in hit_seasons)
    return severity, season_labels

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

        # Memory optimization: Set DuckDB memory limit (recommended for Streamlit Cloud)
        con.execute("SET memory_limit='600MB'")

        return con

    except Exception as e:
        st.error(f"❌ Could not connect to data: {e}")
        st.info("💡 If running locally, run `python SWOT_Pull.py` to generate data. If on Streamlit Cloud, check that the GitHub Release exists.")
        import traceback
        st.code(traceback.format_exc())
        return None

def main():
    con = get_database_connection()
    if not con:
        st.error("❌ Failed to initialize database connection.")
        st.stop()

    st.sidebar.title("🌊 Analysis Controls")

    # 1. Get Metadata (with loading indicator for large datasets)
    try:
        with st.spinner("Loading data metadata..."):
            date_range = con.execute("SELECT MIN(Pass_Date), MAX(Pass_Date) FROM river_data").fetchone()
            if date_range is None or date_range[0] is None:
                st.error("❌ No data found in parquet files. Please run SWOT_Pull.py first to generate data.")
                st.stop()

            min_date = pd.to_datetime(date_range[0])
            max_date = pd.to_datetime(date_range[1])
            available_reaches = con.execute("SELECT DISTINCT Reach_Name FROM river_data").fetchdf()['Reach_Name'].tolist()
    except Exception as e:
        st.error(f"❌ Could not read metadata: {e}")
        st.info("💡 If running locally, run `python SWOT_Pull.py` to generate data. If on Streamlit Cloud, check GitHub Release data.")
        st.stop()
        
    # --- FORM CONTROLS ---
    with st.sidebar.form("analysis_form"):
        st.write("### 1. Select Time & Rivers")

        start_date, end_date = st.slider(
            "Time Frame:",
            min_value=min_date.date(),
            max_value=max_date.date(),
            value=(min_date.date(), max_date.date())
        )

        exclude_ice = st.checkbox(
            "Exclude ice season (Dec-Mar)",
            value=True,
            help="Smooth river ice passes SWOT Class 3-4 filters during Dec-Mar, producing elevated WSE readings (0.5-2+ m above true water surface)."
        )

        selected_reaches = st.multiselect(
            "Select Rivers:",
            available_reaches,
            default=available_reaches
        )

        submitted = st.form_submit_button("🔄 Update Analysis")

    # Hardcoded detrending method
    detrend_method = "Polynomial (2nd order)"

    # Display theme (light mode default)
    plotly_template = "plotly_white"


    # --- DATA LOADING WITH CACHING ---
    # Only reload data when form is submitted OR when data is not yet loaded
    if submitted or "viz_df" not in st.session_state:
        if not selected_reaches:
            st.warning("Please select at least one river.")
            st.stop()

        # 3. FILTER DATA
        rivers_sql = "'" + "','".join(selected_reaches) + "'"

        # Base conditions (explicit CAST needed for DuckDB httpfs DATE filtering)
        where_clause = f"""
            WHERE Reach_Name IN ({rivers_sql})
            AND CAST(Pass_Date AS DATE) >= CAST('{start_date}' AS DATE)
            AND CAST(Pass_Date AS DATE) <= CAST('{end_date}' AS DATE)
        """

        # Ice season filtering (Dec-Mar: smooth ice passes Class 3-4 filters)
        if exclude_ice:
            where_clause += "\n            AND MONTH(CAST(Pass_Date AS DATE)) NOT IN (12, 1, 2, 3)"
        else:
            severity, season_labels = get_ice_warning(str(start_date), str(end_date))
            if severity:
                st.warning(
                    "**Ice season data included.** Your date range spans "
                    f"{season_labels}. Smooth river ice passes SWOT Class 3-4 filters, "
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
            st.warning("⚠️ No data matches your selection.")
            st.stop()

        # --- SCIENTIFIC DOWNSAMPLING ---
        if count > MAX_PLOT_POINTS:
            step_size = int(count / MAX_PLOT_POINTS)

            # SCIENTIFIC QUERY: Sort by Location/Time, then take every Nth row
            query_viz = f"""
                SELECT * FROM (
                    SELECT *, row_number() OVER (ORDER BY Reach_Name, dist_km, Pass_Date) as rn
                    FROM river_data {where_clause}
                ) sub
                WHERE rn % {step_size} = 0
            """

            viz_df = con.execute(query_viz).fetchdf()

            if submitted:
                st.toast(f"ℹ️ Systematic Sampling: Showing 1 out of every {step_size} points.", icon="📉")
        else:
            query_viz = f"SELECT * FROM river_data {where_clause} ORDER BY Reach_Name, dist_km"
            viz_df = con.execute(query_viz).fetchdf()

        # --- STATISTICS (ALWAYS USE FULL DATA) ---
        stats_query = f"""
            SELECT Reach_Name,
                   AVG(wse) as avg_wse,
                   AVG(slope_calc) as avg_slope
            FROM river_data {where_clause}
            GROUP BY Reach_Name
        """
        stats_df = con.execute(stats_query).fetchdf()

        # Store in session state for reuse when map settings change
        st.session_state.viz_df = viz_df
        st.session_state.stats_df = stats_df
        st.session_state.count = count
        st.session_state.selected_reaches = selected_reaches
        st.session_state.start_date = start_date
        st.session_state.end_date = end_date
        st.session_state.detrend_method = detrend_method
        st.session_state.where_clause = where_clause
        st.session_state.exclude_ice = exclude_ice
    else:
        # Use cached data (instant - no database query!)
        viz_df = st.session_state.viz_df
        stats_df = st.session_state.stats_df
        count = st.session_state.count
        selected_reaches = st.session_state.selected_reaches
        start_date = st.session_state.start_date
        end_date = st.session_state.end_date
        detrend_method = st.session_state.detrend_method
        where_clause = st.session_state.where_clause

    # --- MAIN PAGE ---
    st.title(PAGE_TITLE)

    col1, col2, col3 = st.columns(3)
    col1.metric("Passes Analyzed", viz_df['Pass_Date'].nunique())
    col2.metric("Total Data Points", f"{count:,}")
    col3.metric("Visualization Sample", f"{len(viz_df):,}") 

    # --- SUMMARY STATS TABLE ---
    st.subheader("Summary Stats (Calculated on 100% of Data)")

    # Clean up the slope presentation (absolute value for readability)
    display_stats = stats_df.copy()
    display_stats['avg_slope'] = display_stats['avg_slope'].abs()

    display_stats = display_stats.rename(columns={
        "Reach_Name": "River Name",
        "avg_wse": "Avg WSE (m)",
        "avg_slope": "Avg Gradient (cm/km)"
    })

    st.dataframe(
        display_stats.style.format({"Avg WSE (m)": "{:.2f}", "Avg Gradient (cm/km)": "{:.2f}"}),
        width='stretch',
        hide_index=True
    )

    # Display data quality information
    st.info("""
    **Data Quality Filtering Applied:**
    - **Classification:** SWOT Classes 3-4 (high-quality water pixels)
    - **Outlier Removal:** MAD-based filtering (Modified Z-score threshold 3.5)
    - **Applied:** Per-reach during data ingestion
    - **Purpose:** Remove plateau artifacts and anomalous measurements

    See `SCIENTIFIC_METHODOLOGY.md` for complete methodology.
    """)

    # --- CALCULATE ADVANCED METRICS FOR MAP VISUALIZATION ---
    # Only calculate when data is reloaded (not when just changing map display settings)
    if submitted or "metrics_calculated" not in st.session_state or st.session_state.metrics_calculated != detrend_method:
        # 1. Calculate Detrended Residuals (using cached function for performance)
        baseline_pred, _, _ = calculate_detrending(
            viz_df['dist_km'].tolist(),
            viz_df['wse'].tolist(),
            detrend_method
        )
        viz_df['detrended_residual'] = viz_df['wse'].values - baseline_pred

        # 2. Calculate Interval Slopes (100m bins)
        viz_df['dist_bin'] = (viz_df['dist_km'] / 0.1).round() * 0.1

        # Calculate mean WSE per bin per river
        bin_means = viz_df.groupby(['Reach_Name', 'dist_bin'])['wse'].mean().reset_index()
        bin_means = bin_means.sort_values(['Reach_Name', 'dist_bin'])

        # Calculate slope between consecutive bins
        bin_means['prev_wse'] = bin_means.groupby('Reach_Name')['wse'].shift(1)
        bin_means['prev_dist'] = bin_means.groupby('Reach_Name')['dist_bin'].shift(1)
        bin_means['interval_slope'] = ((bin_means['wse'] - bin_means['prev_wse']) /
                                         (bin_means['dist_bin'] - bin_means['prev_dist'])) * 100

        # Merge back to viz_df
        viz_df = viz_df.merge(
            bin_means[['Reach_Name', 'dist_bin', 'interval_slope']],
            on=['Reach_Name', 'dist_bin'],
            how='left'
        )

        # Fill NaN slopes with 0 for visualization
        viz_df['interval_slope'] = viz_df['interval_slope'].fillna(0)

        # Update session state
        st.session_state.viz_df = viz_df
        st.session_state.metrics_calculated = detrend_method

    # --- TABS ---
    tab1, tab3, tab5, tab_pocketed = st.tabs([
        "📈 Gradient Profile", "🎯 Detrended Profile", "🗺️ Map View", "📂 More Tabs"
    ])

    with tab1:
        st.subheader(f"River Profile ({start_date} to {end_date})")
        
        fig = go.Figure()

        for reach in selected_reaches:
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

            # Trendline
            if len(reach_data) >= 5:
                slope, intercept, r, _, _ = stats.linregress(reach_data['dist_km'], reach_data['wse'])
                slope_cm = abs(slope * 100)
                x_range = np.linspace(reach_data['dist_km'].min(), reach_data['dist_km'].max(), 100)
                y_range = intercept + slope * x_range

                fig.add_trace(go.Scatter(
                    x=x_range,
                    y=y_range,
                    mode='lines',
                    name=f"{reach} Trend: {slope_cm:.1f} cm/km",
                    line=dict(color=line_color, width=4, dash='dash')
                ))

        fig.update_layout(
            xaxis_title="Distance from Anchor Point (km)",
            yaxis_title="Water Surface Elevation (m)",
        )

        # 🔄 REVERSE THE X-AXIS HERE
        fig.update_xaxes(autorange="reversed")

        fig.update_layout(height=600, template=plotly_template)
        st.plotly_chart(fig, width="stretch", theme=None)

        # Add interpretation guide
        st.info("""
        **How to Read This Graph:**
        - **X-axis (reversed)**: Distance from confluence anchor point
          - Left (high values): Coast/River mouth (~70 km)
          - Right (0 km): Confluence where rivers meet
        - **Y-axis**: Water surface elevation above EGM2008 geoid (meters)
        - **Points**: Individual SWOT measurements (semi-transparent)
        - **Dashed lines**: Linear regression trendlines showing average gradient
        - **Gradient values**: Shown in legend as cm/km (steepness)

        **What to look for:**
        - **Steeper gradient** (higher cm/km) = Faster elevation drop = More hydraulic energy
        - **River comparison**: If one river is consistently higher, it has hydraulic advantage
        - **Scatter width**: Natural variation from different satellite passes and water levels
        - **Trend line slope**: Overall average gradient - steeper = greater avulsion risk

        💡 **Tip**: Use the other tabs for detailed comparisons!
        - "Elevation Difference" shows which river is higher at each distance
        - "Detrended Profile" removes overall slope to highlight subtle differences
        - "Slope Profile" shows how steepness varies along the river
        """)

    with tab_pocketed:
        tab2, tab4, tab6, tab7, tab8, tab9 = st.tabs([
            "🔀 Elevation Difference", "📐 Slope Profile", "📄 Raw Data",
            "⏳ Temporal Evolution", "📊 Seasonal Comparison", "🌊 Typhoon Impact"
        ])

    with tab2:
        st.subheader(f"Elevation Difference: Kanektok - Uyak ({start_date} to {end_date})")

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

                    st.plotly_chart(fig_diff, width="stretch", theme=None)

                    # Add interpretation guide
                    st.info("""
                    **How to Read This Graph:**
                    - **Positive values** (above zero): Kanektok River has higher water surface elevation
                    - **Negative values** (below zero): Uyak Creek has higher water surface elevation
                    - **Zero line**: Rivers have equal elevation
                    - Data is binned every 100 meters and averaged for clarity
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
        st.subheader(f"Detrended Elevation Profile ({start_date} to {end_date})")

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

                # Plot residuals for each river
                for reach in selected_reaches:
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
                st.info(f"""
                **How to Read This Graph (Relative Elevation Model):**
                - **Baseline**: {method_name} fitted through all data points from selected river(s)
                - **Y-axis = 0**: Points exactly on the baseline trend
                - **Positive values**: Water surface elevation is HIGHER than the baseline
                - **Negative values**: Water surface elevation is LOWER than the baseline
                - **Purpose**: Removes the large-scale elevation drop, revealing subtle differences between rivers

                **Expected pattern if detrending is working correctly:**
                - Residuals should **scatter around zero** with no systematic slope
                - Overall mean residual should be close to 0.000m
                - If you still see a clear upward or downward trend, the baseline method doesn't fit your data well

                **What to look for (when properly detrended):**
                - Consistent separation between rivers indicates systematic elevation differences
                - River consistently above baseline = higher gradient/steeper than average
                - River consistently below baseline = lower gradient/gentler than average
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
                    st.plotly_chart(fig_baseline, width="stretch", theme=None)

        except Exception as e:
            st.error(f"Error calculating detrended profile: {e}")
            import traceback
            st.code(traceback.format_exc())

    with tab4:
        st.subheader(f"Slope Profile ({start_date} to {end_date})")

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

                st.plotly_chart(fig_slopes, width="stretch", theme=None)

                st.info("""
                **How to Read This Graph:**
                - Shows how river steepness varies along its length
                - Raw WSE data is binned (100m medians) then smoothed with a 2km Gaussian window
                - Slope is the derivative of the smoothed elevation profile
                - **Higher values** = Steeper gradient (more hydraulic energy)
                - Compare rivers to identify where one is significantly steeper
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

    with tab7:
        st.subheader(f"⏳ Temporal Evolution Analysis ({start_date} to {end_date})")

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
        if submitted or "temporal_df" not in st.session_state or st.session_state.get("temporal_where") != where_clause:
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
            **Method:** Modified Z-Score with MAD (Median Absolute Deviation)
            - **Threshold:** 3.5 (matches data pipeline filtering)
            - **Detection:** Flags passes where WSE or gradient deviate significantly from typical values
            - **Purpose:** Identify potential measurement errors or extreme hydrologic events
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
            **Visualization:** 2D color plot showing WSE across both space (distance) and time (months)
            - **X-axis:** Month
            - **Y-axis:** Distance from confluence (km)
            - **Color:** Average WSE (m)
            - **Use:** Identify spatial-temporal patterns (e.g., upstream vs downstream changes over time)
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

        st.info("""
        **Interpretation Guide:**
        - **WSE Trend:** Positive = water level increasing, Negative = water level decreasing
        - **R²:** Closer to 1.0 = stronger linear trend, Closer to 0 = more variability
        - **Gradient Trend:** Change in river steepness over time
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

        st.info("""**Methodology:** To isolate geomorphic changes caused by the typhoon from seasonal WSE
        variation, this analysis compares the **same season** before and after the storm (Summer 2025 vs
        Summer 2026). Comparing open-water months to freeze-up months would introduce a 0.5-2+ m ice
        artifact — SWOT measures ice surface elevation, not water beneath the ice.""")

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
                    st.plotly_chart(fig_change, width='stretch', theme=None)
                    st.caption("Positive = WSE increased post-storm. Negative = WSE decreased. 500m bins, min 3 points per bin. Same-season comparison eliminates ice artifacts.")
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
            st.error("""**Ice Contamination Warning:** This comparison is between open-water (Aug-Sep) and
            freeze-up/frozen (Oct-Dec) periods. Post-storm WSE values are likely **artificially elevated
            by 0.5-2+ meters** because SWOT measures ice surface, not water beneath it. The PIXC
            classification filter (Classes 3-4) excludes most ice but partially frozen surfaces may
            still pass. **Do not use these slope changes to draw conclusions about storm impact.**
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

if __name__ == "__main__":
    main()
