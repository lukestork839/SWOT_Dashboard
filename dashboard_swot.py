import streamlit as st
import pandas as pd
import plotly.graph_objects as go
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
# Pre-computed one-time temporal-analysis results (git-tracked, tiny). Written by
# temporal_analysis.py; the Temporal Results tab renders these directly (no on-the-fly calc).
TEMPORAL_DIR = "temporal_results"
REMOTE_PARQUET_URL = "https://github.com/lukestork839/SWOT_Dashboard/releases/download/v2.0-data/dashboard_data.parquet"
REMOTE_DEM_URL = "https://github.com/lukestork839/SWOT_Dashboard/releases/download/v2.0-data/dem_river_elevations.parquet"
REMOTE_REFGRAD_URL = "https://github.com/lukestork839/SWOT_Dashboard/releases/download/v2.0-data/reference_gradient_per_pass.parquet"
MAX_PLOT_POINTS = 15000  # Reduced for large datasets (was 25000)
MAX_BASELINE_POINTS = 30000  # Reduced for Streamlit Cloud (was 50000)
MAX_MAP_POINTS = 5000  # Strict limit for map rendering

# Residual-domain outlier flag for the Detrended Profile.
# The ingestion MAD filter (SWOT_Pull.py) runs on RAW WSE per-pass, where the
# ~70 km downstream gradient inflates the reach spread so much that its keep-band
# is ~150 m wide -- so localized spring-ice/contamination blobs (a handful of
# passes producing WSE tens of metres below the local trend) pass through and
# then dominate the detrended min/max/range. This threshold re-applies the SAME
# Modified Z-Score method (Iglewicz & Hoaglin 1993) in the DETRENDED domain,
# where residuals are ~0-centred so the flag actually isolates those points.
RESIDUAL_MAD_THRESHOLD = 3.5  # Modified Z-score, matches ingestion MAD_THRESHOLD

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

# Note: the seasonal/typhoon period definitions and ice-season constants that the
# retired live temporal tabs used now live in temporal_analysis.py, which owns the
# one-time temporal analysis. The dashboard only displays its pre-computed results.


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


def extract_selection(event):
    """Pull selected points out of a Plotly `on_select` event returned by st.plotly_chart.

    Profile data traces carry customdata = [latitude, longitude, pass_date, reach];
    trendline/legend traces have no customdata and are ignored. Returns a list of
    {lat, lon, date, reach} dicts that the Map View uses to draw highlight markers.
    Written defensively so it works whether Streamlit returns dicts or attr objects.
    """
    pts = []
    if not event:
        return pts
    sel = event.get("selection") if isinstance(event, dict) else getattr(event, "selection", None)
    if not sel:
        return pts
    points = sel.get("points", []) if isinstance(sel, dict) else getattr(sel, "points", [])
    for p in points:
        cd = p.get("customdata") if isinstance(p, dict) else getattr(p, "customdata", None)
        if not cd or len(cd) < 2:
            continue
        try:
            pts.append({
                "lat": float(cd[0]),
                "lon": float(cd[1]),
                "date": str(cd[2]) if len(cd) > 2 else "",
                "reach": str(cd[3]) if len(cd) > 3 else "",
            })
        except (TypeError, ValueError):
            continue
    return pts


st.set_page_config(page_title=PAGE_TITLE, layout="wide", page_icon="🌊")

@st.cache_data(ttl=86400)  # Cache for 24h (data is release-static; redeploys clear caches)
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


def flag_residual_outliers(residuals, threshold=RESIDUAL_MAD_THRESHOLD):
    """Flag detrended residuals as outliers via the Modified Z-Score (MAD-based).

    Same estimator as the ingestion filter (calculate_mad_outliers in SWOT_Pull.py):
    Modified Z = 0.6745 * (x - median) / MAD, flagged when |Z| > threshold. The
    difference is the DOMAIN: applied here to residuals (data minus baseline), not
    raw WSE, so the trend no longer inflates the spread and the flag isolates the
    genuinely anomalous points instead of being masked by the downstream gradient.

    Returns a boolean array (True = outlier) aligned to `residuals`. Nothing is
    deleted -- callers decide how to present flagged points.
    """
    r = np.asarray(residuals, dtype=float)
    if len(r) == 0:
        return np.zeros(0, dtype=bool)
    median = np.median(r)
    mad = np.median(np.abs(r - median))
    if mad == 0:  # degenerate spread -> flag nothing
        return np.zeros(len(r), dtype=bool)
    modified_z = 0.6745 * (r - median) / mad
    return np.abs(modified_z) > threshold


@st.cache_data(ttl=86400)
def load_detrend_frame(_con, where_clause, detrend_method):
    """Fetch + detrend the profile data ONCE per (passes, method) and cache it.

    Caching is essential for the profile→map selection: st.cache_data returns identical
    content across reruns, so the detrended figure is byte-stable and Streamlit keeps the
    chart's box-selection through the on_select rerun. Previously the frame was re-queried
    (with a non-deterministic sample) every rerun, which changed the figure and made the
    selection — and the map highlight — vanish. Returns (baseline_df, method_name, total_count).
    """
    total_count = _con.execute(f"SELECT COUNT(*) FROM river_data {where_clause}").fetchone()[0]
    order_cols = "Reach_Name, dist_km, Pass_Date, latitude, longitude"
    if total_count > MAX_BASELINE_POINTS:
        step = max(1, total_count // MAX_BASELINE_POINTS)
        query = f"""
            SELECT dist_km, wse, Reach_Name, latitude, longitude, Pass_Date FROM (
                SELECT dist_km, wse, Reach_Name, latitude, longitude, Pass_Date,
                       row_number() OVER (ORDER BY {order_cols}) AS rn
                FROM river_data {where_clause}
            ) sub WHERE rn % {step} = 0 ORDER BY {order_cols}
        """
    else:
        query = (f"SELECT dist_km, wse, Reach_Name, latitude, longitude, Pass_Date "
                 f"FROM river_data {where_clause} ORDER BY {order_cols}")
    bdf = _con.execute(query).fetchdf()
    if len(bdf) == 0:
        return bdf, None, total_count
    baseline_pred, _coeffs, method_name = calculate_detrending(
        bdf['dist_km'].tolist(), bdf['wse'].tolist(), detrend_method)
    bdf['residual'] = bdf['wse'].values - baseline_pred
    bdf['baseline'] = baseline_pred
    return bdf, method_name, total_count


@st.cache_data(ttl=86400)
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

# Cache key includes the remote URL so the cached connection invalidates when the data
# source changes. NOTE: the parameter must NOT start with an underscore — Streamlit excludes
# underscore-prefixed args from the cache key, which would silently disable this busting.
@st.cache_resource
def get_database_connection(url_version=REMOTE_PARQUET_URL):
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

@st.cache_data(ttl=86400)
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

@st.cache_data(ttl=86400)
def load_dem_points(_con):
    """Load sampled DEM points for map visualization via DuckDB."""
    try:
        return _con.execute("""
            SELECT Reach_Name, dist_km, wse, latitude, longitude
            FROM dem_data
            USING SAMPLE 15000 ROWS (reservoir, 42)
        """).fetchdf()
    except Exception:
        return None


@st.cache_data(ttl=86400)
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


@st.cache_data(ttl=86400)
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


@st.cache_data(ttl=86400)
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


@st.cache_data(ttl=86400)
def load_temporal_results():
    """Load the pre-computed one-time temporal-analysis artifacts.

    Returns a dict {results, metrics, q3_curve} or None if the files are absent.
    These are static outputs of temporal_analysis.py (git-tracked in temporal_results/),
    so the tab renders identically on local and Streamlit Cloud with zero computation.
    """
    import json
    j = os.path.join(TEMPORAL_DIR, "temporal_analysis_results.json")
    m = os.path.join(TEMPORAL_DIR, "temporal_metrics_per_pass.parquet")
    c = os.path.join(TEMPORAL_DIR, "temporal_q3_profile.parquet")
    if not (os.path.exists(j) and os.path.exists(m)):
        return None
    try:
        with open(j) as f:
            results = json.load(f)
        # Read parquet via DuckDB (same pattern as the rest of the app) so we don't
        # depend on pyarrow/fastparquet, which are not in requirements.txt.
        con = duckdb.connect()
        metrics = con.execute(f"SELECT * FROM read_parquet('{m}')").fetchdf()
        metrics["date"] = pd.to_datetime(metrics["date"])
        q3_curve = (con.execute(f"SELECT * FROM read_parquet('{c}')").fetchdf()
                    if os.path.exists(c) else pd.DataFrame())
        con.close()
        return {"results": results, "metrics": metrics, "q3_curve": q3_curve}
    except Exception as e:
        st.warning(f"Could not load temporal results: {e}")
        return None


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
            # Clear cached dataframes + the pinned pass selection and any map highlights,
            # so the welcome-page checkboxes become authoritative again on next launch.
            # (pass_{date} widget states are preserved so the checkboxes still reflect the
            # last choice.)
            for key in ["viz_df", "viz_sig", "stats_df", "count", "where_clause",
                        "selected_pass_dates", "confirmed_pass_dates", "selected_reaches",
                        "detrend_method", "metrics_calculated",
                        "sel_grad", "sel_detr"]:
                st.session_state.pop(key, None)
            st.session_state.page = "welcome"
            st.rerun()

    # Always include both rivers
    selected_reaches = available_reaches

    # Read pass selection from session state.
    # The pass_{date} checkboxes live only on the welcome page, so their widget-keyed
    # state can be garbage-collected by Streamlit once those widgets stop rendering
    # (e.g. on the extra reruns from chart on_select / the map fragment / st.rerun).
    # To stay robust, mirror the selection into a plain (non-widget) key and fall back
    # to it whenever the widget keys have been cleaned up.
    selected_pass_dates = sorted(
        d for d in all_pass_dates if st.session_state.get(f"pass_{d}", False)
    )
    if selected_pass_dates:
        st.session_state["confirmed_pass_dates"] = selected_pass_dates
    else:
        selected_pass_dates = st.session_state.get("confirmed_pass_dates", [])

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
    # Rebuild the cached frame whenever the selection (rivers, passes, method) changes —
    # not merely when it's absent — so the charts can never lag behind the header date
    # label. str() the dates so the signature is hashable/stable across reruns.
    selection_sig = (
        tuple(selected_reaches),
        tuple(str(d) for d in selected_pass_dates),
        detrend_method,
    )
    if "viz_df" not in st.session_state or st.session_state.get("viz_sig") != selection_sig:
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
        st.session_state.viz_sig = selection_sig
        # Selection changed → drop the derived-metrics flag so the block below recomputes
        # detrended_residual / interval_slope on the freshly loaded frame (otherwise it is
        # keyed only on the hardcoded detrend_method and would skip, leaving stale columns).
        st.session_state.pop("metrics_calculated", None)
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

    with main_swot:
        # Spatial tabs (interactive, per-selection) + one static Temporal Results tab.
        # The live per-pass temporal/seasonal/typhoon tabs were retired in favour of the
        # one-time analysis (temporal_analysis.py); the Temporal Results tab shows those
        # pre-computed conclusions and is available on both local and Streamlit Cloud.
        swot_tab_names = [
            "📈 Gradient Profile", "📏 Hydraulic Gradient", "🎯 Detrended Profile", "🗺️ Map View",
            "🔀 Elevation Difference", "📐 Slope Profile", "📄 Raw Data", "⏳ Temporal Results",
        ]
        swot_tabs = st.tabs(swot_tab_names)
        tab1, tab_grad, tab3, tab5, tab2, tab4, tab6, tab_temporal = swot_tabs

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
            # Scatter points (translucent data, hidden from legend).
            # customdata carries [lat, lon, date, reach] so a lasso/box selection here
            # can be highlighted on the Map View tab (see extract_selection / tab5).
            cd = np.column_stack([
                reach_data['latitude'].to_numpy(),
                reach_data['longitude'].to_numpy(),
                reach_data['Pass_Date'].astype(str).to_numpy(),
                np.full(len(reach_data), reach),
            ])
            fig.add_trace(go.Scatter(
                x=reach_data['dist_km'],
                y=reach_data['wse'],
                mode='markers',
                marker=dict(color=line_color, size=5, opacity=0.3),
                legendgroup=reach,
                showlegend=False,
                customdata=cd,
                hovertemplate='<b>' + reach + '</b><br>'
                              'Distance: %{x:.2f} km<br>'
                              'WSE: %{y:.2f} m<br>'
                              'Pass: %{customdata[2]}<br>'
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

        fig.update_layout(height=600, template=plotly_template, dragmode="select")
        add_bifurcation_line(fig)
        st.caption("🔦 **Link to map:** drag a box around points here — they'll be highlighted "
                   "(yellow outline) on the **🗺️ Map View** tab so you can see where they are on "
                   "the river. Switch back to zoom/pan with the toolbar at the top-right of the chart.")
        grad_event = st.plotly_chart(
            fig, width="stretch", theme=None,
            on_select="rerun", selection_mode=("points", "box"),
            key=f"grad_profile_select_{st.session_state.get('sel_ver', 0)}",
        )
        st.session_state["sel_grad"] = extract_selection(grad_event)

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
            # Fetch + detrend ONCE per (passes, method); cached so the figure is stable
            # across reruns and the chart's box-selection survives (see load_detrend_frame).
            baseline_df, method_name, total_count = load_detrend_frame(
                con, where_clause, detrend_method)
            if total_count > MAX_BASELINE_POINTS:
                st.info(f"📊 Baseline fit on ~{MAX_BASELINE_POINTS:,} systematically sampled "
                        f"points (of {total_count:,} total) for performance.")

            if len(baseline_df) == 0:
                st.warning("No data available for detrending analysis.")
            else:
                # Flag residual-domain outliers (per-reach), matching the ingestion
                # Modified Z-Score method but applied to residuals rather than raw WSE.
                # These are localized contamination (e.g. spring-ice blobs) that the
                # raw-WSE ingestion MAD cannot catch; flagging (not deleting) them keeps
                # the stats table and plot readable without discarding data silently.
                baseline_df = baseline_df.copy()
                baseline_df['residual_outlier'] = False
                for _reach in baseline_df['Reach_Name'].unique():
                    _mask = baseline_df['Reach_Name'] == _reach
                    _flags = flag_residual_outliers(baseline_df.loc[_mask, 'residual'].values)
                    baseline_df.loc[_mask, 'residual_outlier'] = _flags
                n_flagged = int(baseline_df['residual_outlier'].sum())
                pct_flagged = 100 * n_flagged / len(baseline_df)

                # Fit-quality metrics use the CLEAN (non-flagged) residuals so a handful
                # of contaminated points can't dominate the mean/spread shown to the user.
                clean_df = baseline_df[~baseline_df['residual_outlier']]

                # Check detrending quality (robust to flagged outliers)
                overall_mean_residual = clean_df['residual'].mean()
                overall_std_residual = clean_df['residual'].std()

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

                # Plot residuals for each river (Uyak on top). Flagged residual
                # outliers are omitted from the traces so the y-axis auto-scales to the
                # real signal instead of being stretched by a few contaminated points;
                # they remain in baseline_df and the Raw Data tab (nothing is deleted).
                for reach in sorted(selected_reaches, key=lambda r: r == "Uyak_Creek"):
                    reach_data = plot_df[(plot_df['Reach_Name'] == reach)
                                         & (~plot_df['residual_outlier'])]
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
                    # Translucent data points (hidden from legend).
                    # customdata = [lat, lon, date, reach] so a box-selection here can be
                    # highlighted on the Map View tab (same mechanism as the Gradient Profile).
                    cd = np.column_stack([
                        reach_data['latitude'].to_numpy(),
                        reach_data['longitude'].to_numpy(),
                        reach_data['Pass_Date'].astype(str).to_numpy(),
                        np.full(len(reach_data), reach),
                    ])
                    fig_detrend.add_trace(go.Scatter(
                        x=reach_data['dist_km'],
                        y=reach_data['residual'],
                        mode='markers',
                        marker=dict(color=line_color, size=3, opacity=0.4),
                        legendgroup=reach,
                        showlegend=False,
                        customdata=cd,
                        hovertemplate='<b>' + reach + '</b><br>' +
                                      'Distance: %{x:.2f} km<br>' +
                                      'Residual: %{y:.3f} m<br>' +
                                      'Pass: %{customdata[2]}<br>' +
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
                fig_detrend.update_layout(dragmode="select")
                add_bifurcation_line(fig_detrend)

                st.caption("🔦 **Link to map:** drag a box around points here — they'll be "
                           "highlighted (yellow outline) on the **🗺️ Map View** tab. Switch back "
                           "to zoom/pan with the toolbar at the top-right of the chart.")
                if n_flagged > 0:
                    st.caption(f"⚠️ **{n_flagged:,} point(s) ({pct_flagged:.3f}%)** flagged as "
                               f"residual outliers (Modified Z-Score > {RESIDUAL_MAD_THRESHOLD}, "
                               "per river) and omitted from this view so the axis reflects the "
                               "real signal. These are localized contamination (e.g. spring ice) "
                               "that the raw-WSE ingestion filter cannot catch. They are **not "
                               "deleted** — they remain in the data and the Raw Data tab.")
                detr_event = st.plotly_chart(
                    fig_detrend, width="stretch", theme=None,
                    on_select="rerun", selection_mode=("points", "box"),
                    key=f"detrend_select_{st.session_state.get('sel_ver', 0)}",
                )
                st.session_state["sel_detr"] = extract_selection(detr_event)

                # Show fit quality metrics
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Overall Mean Residual", f"{overall_mean_residual:.4f} m",
                             help="Mean of non-flagged residuals; should be close to 0.000 for a good fit")
                with col2:
                    st.metric("Residual Std Dev", f"{overall_std_residual:.3f} m",
                             help="Spread of non-flagged residuals around baseline (flagged outliers excluded)")
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

                # Robust statistics. Min/Max/Range are non-robust by construction (a
                # single contaminated pixel sets them), so they are replaced by robust
                # dispersion measures computed over ALL residuals: the median, a
                # MAD-based robust standard deviation (1.4826 * MAD, the normal-
                # consistent estimator), and the 1st/99th percentiles. Mean and Std Dev
                # are retained for continuity but computed on the non-flagged residuals
                # so they are not distorted by flagged outliers. "N Flagged" reports how
                # many points exceeded the residual Modified Z-Score threshold.
                stats_data = []
                for reach in selected_reaches:
                    reach_all = baseline_df[baseline_df['Reach_Name'] == reach]
                    if len(reach_all) == 0:
                        continue
                    residuals_all = reach_all['residual']
                    residuals_clean = reach_all.loc[~reach_all['residual_outlier'], 'residual']
                    med = residuals_all.median()
                    robust_sd = 1.4826 * (residuals_all - med).abs().median()
                    stats_data.append({
                        "River": reach,
                        "Median (m)": med,
                        "Robust SD (m)": robust_sd,
                        "P1 (m)": residuals_all.quantile(0.01),
                        "P99 (m)": residuals_all.quantile(0.99),
                        "Mean (m)": residuals_clean.mean(),
                        "Std Dev (m)": residuals_clean.std(),
                        "N Flagged": int(reach_all['residual_outlier'].sum()),
                    })

                if stats_data:
                    stats_summary = pd.DataFrame(stats_data)
                    st.dataframe(
                        stats_summary.style.format({
                            "Median (m)": "{:.3f}",
                            "Robust SD (m)": "{:.3f}",
                            "P1 (m)": "{:.3f}",
                            "P99 (m)": "{:.3f}",
                            "Mean (m)": "{:.3f}",
                            "Std Dev (m)": "{:.3f}",
                            "N Flagged": "{:,d}",
                        }),
                        width="stretch",
                        hide_index=True
                    )
                    st.caption(
                        "**Median / Robust SD (1.4826·MAD) / P1 / P99** are outlier-resistant "
                        "measures over all residuals. **Mean / Std Dev** exclude points flagged "
                        f"by the residual Modified Z-Score (> {RESIDUAL_MAD_THRESHOLD}). "
                        "**N Flagged** counts those points, retained in the data but excluded here "
                        "and from the plot. Min/Max/Range were removed: a single contaminated "
                        "pixel sets them, so they misrepresented the detrended spread."
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

            # Sample data if too large. Seed the sample so the plotted points stay put
            # across the fragment's reruns (opacity/basemap/color-by changes) instead of
            # jittering to a new random subset each interaction.
            if len(viz_df) > MAX_MAP_POINTS:
                map_df = viz_df.sample(MAX_MAP_POINTS, random_state=42)
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

            # --- Highlight points box-selected on a profile tab (Gradient/Detrended) ---
            # Union of both charts' selections so either (or both) can drive the highlight.
            highlight_pts = (st.session_state.get("sel_grad", [])
                             + st.session_state.get("sel_detr", []))
            if highlight_pts:
                hl_group = folium.FeatureGroup(name="🔦 Selected from profile", show=True)
                for pt in highlight_pts:
                    label = " · ".join(x for x in (pt.get("reach", "").replace("_", " "),
                                                   pt.get("date", "")) if x)
                    reach_color = COLOR_MAP.get(pt.get("reach", ""), "gray")
                    folium.CircleMarker(
                        location=[pt["lat"], pt["lon"]],
                        radius=7,
                        color="yellow", weight=3, opacity=0.6,   # yellow outline at 60%
                        fill=True, fill_color=reach_color, fill_opacity=1.0,  # keep original river color inside
                        popup=folium.Popup(f"Selected point<br>{label}", max_width=250),
                        tooltip="Selected from profile",
                    ).add_to(hl_group)
                hl_group.add_to(m)
                # zoom to the highlighted points so the user lands on that stretch of river
                lats = [p["lat"] for p in highlight_pts]
                lons = [p["lon"] for p in highlight_pts]
                lat_min, lat_max = min(lats), max(lats)
                lon_min, lon_max = min(lons), max(lons)
                # pad a degenerate (single-point / tight-cluster) box so fit_bounds doesn't over-zoom
                if lat_max - lat_min < 1e-3:
                    lat_min -= 1e-3; lat_max += 1e-3
                if lon_max - lon_min < 1e-3:
                    lon_min -= 1e-3; lon_max += 1e-3
                m.fit_bounds([[lat_min, lon_min], [lat_max, lon_max]], padding=(40, 40))

            # Add layer control (toggle layers on/off)
            add_bifurcation_marker(m)
            folium.LayerControl().add_to(m)

            if highlight_pts:
                c_msg, c_btn = st.columns([3, 1])
                c_msg.success(f"🔦 **{len(highlight_pts)} point(s) highlighted** from your profile "
                              "selection (yellow outlines). The map has zoomed to them.")
                if c_btn.button("Clear highlight", use_container_width=True, key="clear_highlight"):
                    st.session_state["sel_ver"] = st.session_state.get("sel_ver", 0) + 1
                    st.session_state["sel_grad"] = []
                    st.session_state["sel_detr"] = []
                    st.rerun()

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

    # === TEMPORAL RESULTS TAB (static, one-time analysis; local + Streamlit Cloud) ===
    with tab_temporal:
        st.subheader("⏳ Is the River Changing Over Time?")
        temporal = load_temporal_results()
        if temporal is None:
            st.info(
                "Temporal-analysis results not found. Generate them with "
                "`python3 temporal_analysis.py` (writes to `temporal_results/`)."
            )
        else:
            results = temporal["results"]
            metrics = temporal["metrics"]
            q3_curve = temporal["q3_curve"]
            method = results["method"]
            record = results["record"]

            DISP = {"Kanektok_River": "Kanektok River", "Uyak_Creek": "Uyak Creek"}
            REACH_ORDER = ["Kanektok_River", "Uyak_Creek"]

            def _fmt_p(p):
                if p is None or (isinstance(p, float) and np.isnan(p)):
                    return "n/a (n<3)"
                return f"{p:.3f}" + (" *" if p < 0.05 else "")

            q1_slope = {r["reach"]: r for r in results["Q1_seasonal"]
                        if r["question"] == "Q1_slope_pooled"}
            q3p = {r["reach"]: r for r in results["Q3_profile"]}

            st.markdown(
                "This page asks a simple question: **are these two rivers changing over "
                "time?** We look three ways — from spring to late summer, from one year to the "
                "next, and before vs. after Typhoon Halong. The answers were worked out once, "
                "off-line, using the same fair method as the river-steepness page: it measures "
                "the whole river evenly, so a satellite pass that only caught part of the river "
                "can't tip the results. Nothing here is re-calculated on the fly."
            )
            st.success(
                "**Bottom line — both rivers are holding steady.** How steeply the river drops "
                "has barely changed from spring to late summer, from year to year, or across "
                "Typhoon Halong. The water level moves around a little, but only as much as it "
                "normally does from one year to the next — and **we see no sign of the typhoon "
                "changing the river upstream** (the storm check is still preliminary — see the "
                "note on the last chart)."
            )
            st.markdown(
                f"- **Spring vs. late summer:** the river's steepness barely moves "
                f"(a change of {q1_slope['Kanektok_River']['dslope_cm_km']:+.1f} cm/km on "
                f"Kanektok and {q1_slope['Uyak_Creek']['dslope_cm_km']:+.1f} on Uyak, against "
                f"an overall drop of about 195 cm/km — too small to matter). The water level "
                f"rises and falls only about 0.2–0.5 m, and which season is higher flips from "
                f"year to year.\n"
                f"- **Year to year (summer 2024 vs. 2025):** both rivers steady — the steepness "
                f"change is tiny, and the water level shifts only about 0.2 m (Kanektok) to "
                f"0.5 m (Uyak).\n"
                f"- **Typhoon Halong (preliminary):** upriver, the water level changed only "
                f"{q3p['Kanektok_River']['median_dwse_m']:+.2f} m (Kanektok) and "
                f"{q3p['Uyak_Creek']['median_dwse_m']:+.2f} m (Uyak) — within the normal "
                f"year-to-year range. The storm's damage was along the coast, not up the river."
            )
            st.caption(
                "Two terms to know: the river's **steepness** (how far the water surface drops "
                "for every kilometer downstream — about 195 cm, roughly 6 feet, per km on these "
                "rivers) is labeled **Hydraulic Gradient** on the charts; the **water level** is "
                "labeled **Water Surface Elevation**. "
                "Full write-up, method checks, and limitations: "
                "`TEMPORAL_ANALYSIS.md` · `SCIENTIFIC_METHODOLOGY.md`."
            )
            st.divider()

            # ---------- FIGURE 3: control chart (time series with event markers) ----------
            st.markdown("#### Chart 1 — The whole record, with the big events marked")
            st.caption(
                "Each dot is one satellite pass from 2023 to 2026. The top shows how high the "
                "water sat; the bottom shows how steeply the river dropped. If the typhoon had "
                "reshaped the river, you'd see the dots jump up or down at the dashed line and "
                "stay there. They don't — after the storm the river just goes back to its usual "
                "pattern."
            )
            fig_ts = make_subplots(
                rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.09,
                subplot_titles=("Water Surface Elevation at 15 km (m)",
                                "Hydraulic Gradient (cm/km)"),
            )
            for reach in REACH_ORDER:
                d = metrics[metrics["reach"] == reach].sort_values("date")
                color = COLOR_MAP.get(reach, "black")
                fig_ts.add_trace(go.Scatter(
                    x=d["date"], y=d["wse_ref_m"], mode="markers", name=DISP[reach],
                    legendgroup=reach, marker=dict(color=color, size=6, opacity=0.8),
                    hovertemplate="%{x|%b %d, %Y}<br>WSE " + "%{y:.2f} m<extra></extra>",
                ), row=1, col=1)
                fig_ts.add_trace(go.Scatter(
                    x=d["date"], y=d["slope_cm_km"], mode="markers", name=DISP[reach],
                    legendgroup=reach, showlegend=False,
                    marker=dict(color=color, size=6, opacity=0.8),
                    hovertemplate="%{x|%b %d, %Y}<br>slope " + "%{y:.0f} cm/km<extra></extra>",
                ), row=2, col=1)
            # winter ice bands (no open-water data in the gated set) — explains the gaps
            for x0, x1 in [("2023-12-01", "2024-03-31"), ("2024-12-01", "2025-03-31"),
                           ("2025-12-01", "2026-03-31")]:
                fig_ts.add_vrect(x0=x0, x1=x1, fillcolor="lightsteelblue", opacity=0.25,
                                 line_width=0, row="all")
            # typhoon landfall
            fig_ts.add_vline(x=method["typhoon_date"], line_dash="dash", line_color="black",
                             line_width=1.5, row="all")
            fig_ts.add_annotation(x=method["typhoon_date"], yref="paper", y=1.0,
                                  text="Typhoon Halong", showarrow=False, xanchor="left",
                                  font=dict(size=11, color="black"))
            fig_ts.update_layout(height=620, template=plotly_template,
                                 legend=dict(orientation="h", yanchor="bottom", y=1.06))
            fig_ts.update_xaxes(title_text="Date", row=2, col=1)
            st.plotly_chart(fig_ts, width="stretch", theme=None)
            st.caption("The pale blue stripes are winter (Dec–Mar), when the rivers freeze and "
                       "the satellite can't get a clean water reading — so there are no dots "
                       "there. That's expected, not missing data.")
            st.divider()

            # ---------- FIGURE 1: stage-invariance scatter ----------
            st.markdown("#### Chart 2 — Steepness stays the same whether the water is high or low")
            st.caption(
                "Each dot is one satellite pass. On a lot of rivers the steepness changes a lot "
                "when the water rises or drops. Here the dots form a flat band — this river "
                "drops just as steeply at high water as at low water. That's why it's fair to "
                "combine passes from different seasons and years when we talk about steepness."
            )
            fig_si = go.Figure()
            corr_txt = []
            for reach in REACH_ORDER:
                d = metrics[metrics["reach"] == reach]
                color = COLOR_MAP.get(reach, "black")
                fig_si.add_trace(go.Scatter(
                    x=d["wse_ref_m"], y=d["slope_cm_km"], mode="markers", name=DISP[reach],
                    marker=dict(color=color, size=8, opacity=0.55),
                    customdata=d["date"].dt.strftime("%b %d, %Y"),
                    hovertemplate=(f"<b>{DISP[reach]}</b><br>Pass: %{{customdata}}<br>"
                                   "WSE %{x:.2f} m<br>slope %{y:.0f} cm/km<extra></extra>"),
                ))
                med = float(d["slope_cm_km"].median())
                r = float(np.corrcoef(d["wse_ref_m"], d["slope_cm_km"])[0, 1])
                fig_si.add_hline(y=med, line_dash="dot", line_color=color, opacity=0.7)
                corr_txt.append(f"{DISP[reach]}: usually about {med:.0f} cm/km")
            fig_si.update_layout(
                height=460, template=plotly_template,
                xaxis_title="Water Surface Elevation at 15 km (m)",
                yaxis_title="Hydraulic Gradient (cm/km)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig_si, width="stretch", theme=None)
            st.caption("The dotted line is each river's usual steepness.  " +
                       "  ·  ".join(corr_txt) +
                       ".  Because the bands are flat, the water level has almost no effect on "
                       "how steeply the river drops.")
            st.divider()

            # ---------- FIGURE 4: distribution swarms ----------
            st.markdown("#### Chart 3 — Why we say \"no real change\": the groups overlap")
            st.caption(
                "Each box shows the range of the individual passes, and the dots are the passes "
                "themselves. When two boxes cover the same ground, there's no real difference "
                "between them. This is the plain-language version of the \"no real change\" "
                "notes in the tables further down."
            )
            colA, colB = st.columns(2)
            with colA:
                mA = metrics[metrics["month"].isin([5, 7, 8])].copy()
                mA["season"] = np.where(mA["month"] == 5, "Spring (May)", "Late summer (Jul–Aug)")
                fig_sa = go.Figure()
                for reach in REACH_ORDER:
                    d = mA[mA["reach"] == reach]
                    fig_sa.add_trace(go.Box(
                        x=d["season"], y=d["slope_cm_km"], name=DISP[reach],
                        marker_color=COLOR_MAP.get(reach, "black"),
                        boxpoints="all", jitter=0.5, pointpos=0,
                    ))
                fig_sa.update_layout(
                    height=430, template=plotly_template, boxmode="group",
                    title="Hydraulic Gradient: spring vs. late summer",
                    yaxis_title="Hydraulic Gradient (cm/km)",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02),
                )
                fig_sa.update_xaxes(categoryorder="array",
                                    categoryarray=["Spring (May)", "Late summer (Jul–Aug)"])
                st.plotly_chart(fig_sa, width="stretch", theme=None)
            with colB:
                mB = metrics[(metrics["month"].isin([7, 8])) &
                             (metrics["year"].isin([2024, 2025]))].copy()
                mB["yr"] = mB["year"].astype(str)
                fig_sb = go.Figure()
                for reach in REACH_ORDER:
                    d = mB[mB["reach"] == reach]
                    fig_sb.add_trace(go.Box(
                        x=d["yr"], y=d["wse_ref_m"], name=DISP[reach],
                        marker_color=COLOR_MAP.get(reach, "black"),
                        boxpoints="all", jitter=0.5, pointpos=0, showlegend=False,
                    ))
                fig_sb.update_layout(
                    height=430, template=plotly_template, boxmode="group",
                    title="Water Surface Elevation: 2024 vs. 2025 (late summer)",
                    yaxis_title="Water Surface Elevation at 15 km (m)", xaxis_title="Year",
                )
                st.plotly_chart(fig_sb, width="stretch", theme=None)
            st.divider()

            # ---------- FIGURE 2: spatial delta (typhoon, interim) ----------
            st.markdown("#### Chart 4 — Did the typhoon change any spot along the river? (preliminary)")
            st.warning(
                "**Still preliminary.** This compares June 2025 with June 2026, and we only "
                "have 2–3 clean passes per river for those months. Treat it as a strong hint, "
                "not a final answer — we'll know for sure once the summer 2026 data comes in."
            )
            st.caption(
                "This line shows how much the water level changed at each point along the river "
                "(June 2026 compared with June 2025). If the storm had scoured out the riverbed "
                "or dumped a pile of gravel somewhere, you'd see a sharp spike or dip at that "
                "spot. Instead the line stays flat and hugs zero — no spot along the river shows "
                "a storm scar."
            )
            if len(q3_curve):
                fig_d = go.Figure()
                for reach in REACH_ORDER:
                    d = q3_curve[q3_curve["reach"] == reach].sort_values("dist_km")
                    if not len(d):
                        continue
                    color = COLOR_MAP.get(reach, "black")
                    fig_d.add_trace(go.Scatter(
                        x=d["dist_km"], y=d["dwse"], mode="lines+markers", name=DISP[reach],
                        marker=dict(color=color, size=5),
                        line=dict(color=color, width=1.5),
                        hovertemplate="%{x:.1f} km<br>ΔWSE %{y:+.2f} m<extra></extra>",
                    ))
                fig_d.add_hline(y=0, line_color="black", line_width=1)
                add_bifurcation_line(fig_d, axis="x")
                fig_d.update_layout(
                    height=440, template=plotly_template,
                    xaxis_title="Distance from Confluence (km)",
                    yaxis_title="Change in Water Surface Elevation, Jun 2026 − Jun 2025 (m)",
                    yaxis_range=[-0.5, 0.5],
                    legend=dict(orientation="h", yanchor="bottom", y=1.02),
                )
                st.plotly_chart(fig_d, width="stretch", theme=None)
            else:
                st.info("Not enough matching June passes to draw this chart yet.")
            st.divider()

            # ---------- TABLES (secondary, in expanders) ----------
            st.markdown("#### The numbers behind the charts")
            st.caption("Open any section for the exact figures. Click a header to expand it.")

            with st.expander("Spring vs. late summer (May high water vs. Jul–Aug low water)"):
                rows = [{
                    "River": DISP[r["reach"]], "Passes May": r["n_high"],
                    "Passes Jul–Aug": r["n_low"],
                    "Steepness May (cm/km)": round(r["slope_high"], 1),
                    "Steepness Jul–Aug (cm/km)": round(r["slope_low"], 1),
                    "Change (cm/km)": r["dslope_cm_km"], "p-value": _fmt_p(r["p_slope"]),
                } for r in results["Q1_seasonal"] if r["question"] == "Q1_slope_pooled"]
                st.markdown("**Steepness (all years combined — it doesn't change with season):**")
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
                rows = [{
                    "River": DISP[r["reach"]], "Year": r["year"],
                    "Water level May (m)": round(r["wse_high"], 2),
                    "Water level Jul–Aug (m)": round(r["wse_low"], 2),
                    "Change (m)": r["dwse_m"], "p-value": _fmt_p(r["p_wse"]),
                } for r in results["Q1_seasonal"] if r["question"] == "Q1_wse_seasonal"]
                st.markdown("**Water level (shown per year — this is what rises and falls with flow):**")
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
                st.caption("The water level goes up and down a little, and which season is "
                           "higher flips from year to year — that's ordinary flow variation, not "
                           "the river steadily changing. (A p-value below 0.05, marked *, is the "
                           "statistician's flag that a difference is probably not just chance.)")

            with st.expander("Year to year (summer 2024 vs. 2025 — the normal yardstick)"):
                rows = [{
                    "River": DISP[r["reach"]],
                    "Steepness 2024 (cm/km)": round(r["slope_2024"], 1),
                    "Steepness 2025 (cm/km)": round(r["slope_2025"], 1),
                    "Change (cm/km)": r["dslope_cm_km"], "p-value (steepness)": _fmt_p(r["p_slope"]),
                    "Water level 2024 (m)": round(r["wse_2024"], 2),
                    "Water level 2025 (m)": round(r["wse_2025"], 2),
                    "Change (m)": r["dwse_m"], "p-value (level)": _fmt_p(r["p_wse"]),
                } for r in results["Q2_interannual"]]
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
                st.caption("Steepness is measured over the whole ice-free year; water level is "
                           "compared in the same season (late summer). Kanektok's water-level "
                           "change shows up as \"significant\" only because its readings are so "
                           "consistent — the change itself (about 0.2 m, roughly 8 inches) is far "
                           "too small to notice on the ground. A result can be statistically "
                           "\"significant\" and still be too tiny to matter.")

            with st.expander("Typhoon Halong (June 2025 vs. June 2026 — preliminary)"):
                rows = [{
                    "River": DISP[r["reach"]], "Passes 2025": r["n_2025"],
                    "Passes 2026": r["n_2026"],
                    "Water level 2025 (m)": round(r["wse_2025"], 2),
                    "Water level 2026 (m)": round(r["wse_2026"], 2),
                    "Change (m)": r["dwse_m"], "Normal year-to-year change (m)": r["baseline_dwse_m"],
                    "Within normal?": "yes" if r["wse_vs_baseline"] == "within" else r["wse_vs_baseline"],
                    "Steepness change (cm/km)": r["dslope_cm_km"], "p-value (level)": _fmt_p(r["p_wse"]),
                } for r in results["Q3_typhoon"]]
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
                rows = [{
                    "River": DISP[r["reach"]], "Points compared": r["n_bins"],
                    "Typical change (m)": r["median_dwse_m"],
                    "Lower river (≤18 km)": r["downstream_dwse_m"],
                    "Upper river (>18 km)": r["upstream_dwse_m"],
                } for r in results["Q3_profile"]]
                st.markdown("**Change at each point along the river:**")
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
                st.caption("The change around the storm stays inside the normal year-to-year "
                           "range, and it's flat all along the river — no upstream storm scar. "
                           "Preliminary until the summer 2026 (Jul–Aug) data comes in.")

            st.caption(
                f"**Where the numbers come from.** Satellite record {record['date_min']} – "
                f"{record['date_max']}; {record['n_passes_fit']} passes measured, and the "
                f"{record['n_full_coverage_open_water']} that caught the whole river in the "
                f"ice-free season were used here. Technical detail — steepness: "
                f"{method['slope_estimator']}; water level: {method['level_metric']}; "
                f"a pass qualifies with ≥{method['min_nodes']} points, spanning "
                f"≥{method['min_span_km']:.0f} km and starting within "
                f"{method['max_start_km']:.0f} km of the mouth, in months "
                f"{method['open_water_months']}. Generated by temporal_analysis.py."
            )

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
