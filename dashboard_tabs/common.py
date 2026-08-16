"""Shared layer for the dashboard apps: presentation constants, plot/map
helpers, and the Streamlit cache wrappers around swot_core computations.

Every tab module in this package renders from a TabContext built by the
entrypoint (dashboard_swot.py today; dashboard_village.py joins in the split's
final PR). Science lives in swot_core; this module only adds Streamlit
concerns on top of it.
"""
import streamlit as st
import pandas as pd
import duckdb
import os
import folium

from branca.element import MacroElement
from jinja2 import Template as JinjaTemplate

# All SCIENCE (constants + computations) comes from the shared swot_core package —
# one implementation for this app, the village app, and the thesis figures. This
# module only adds Streamlit concerns: caching wrappers, widgets, presentation.
from swot_core import stats as core_stats
from swot_core.config import (
    REMOTE_PARQUET_URL, REMOTE_DEM_URL, REMOTE_REFGRAD_URL,
    BIFURCATION_LAT, BIFURCATION_LON, BIFURCATION_DIST_KM,
    COLOR_MAP, RESIDUAL_MAD_THRESHOLD,
)
from swot_core.stats import (
    flag_residual_outliers,
    round_half_away,
    fine_aggregate as _fine_aggregate,
    fine_window_coverage as _fine_window_coverage,
    fine_window_slope as _fine_window_slope,
)

# Names imported above purely for re-export: the tab modules (and, via
# dashboard_swot, tools/regression_gate.py) import these from here so the whole
# Streamlit layer has a single import surface over swot_core.
__all__ = [
    "RESIDUAL_MAD_THRESHOLD", "flag_residual_outliers", "round_half_away",
    "_fine_aggregate", "_fine_window_coverage", "_fine_window_slope",
]

from dataclasses import dataclass
from typing import Any


@dataclass
class TabContext:
    """Per-selection state built once by the entrypoint's preamble and passed
    explicitly to every tab renderer (no ambient-local closure capture).

    `con` is the shared DuckDB connection; `viz_df` is the (possibly sampled)
    visualization frame with derived metric columns; `where_clause` is the
    selection's SQL filter and doubles as a cache key, so it must be passed
    through unmodified.
    """
    con: Any
    viz_df: Any
    selected_reaches: Any
    detrend_method: str
    where_clause: str
    plotly_template: str
    dem_profile: Any
    dem_points: Any


# --- CONFIGURATION (presentation layer only) ---
PAGE_TITLE = "SWOT River Dynamics: Kanektok & Uyak"
DATA_DIR = "batch_outputs"
# Pre-computed one-time temporal-analysis results (git-tracked, tiny). Written by
# temporal_analysis.py; the Temporal Results tab renders these directly (no on-the-fly calc).
TEMPORAL_DIR = "temporal_results"
MAX_PLOT_POINTS = 15000  # Reduced for large datasets (was 25000)
MAX_BASELINE_POINTS = 30000  # Reduced for Streamlit Cloud (was 50000)
MAX_MAP_POINTS = 5000  # Strict limit for map rendering

# Gradient Profile tab: density-de-biased profile line. Bin distance to nodes and
# take the MEDIAN WSE per node (each along-stream location weighted equally,
# regardless of point density) instead of an OLS fit through the raw point cloud.
PROFILE_NODE_KM = 0.5       # distance-bin width for the binned-median profile line
PROFILE_BAND = (5, 95)      # percentile band shown around the median profile

# RESIDUAL_MAD_THRESHOLD, the bifurcation coordinates, and COLOR_MAP are imported
# from swot_core.config above — shared with the village app and thesis figures.

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



@st.cache_data(ttl=86400)  # Cache for 24h (data is release-static; redeploys clear caches)
def calculate_detrending(dist_km, wse, method):
    """Cached wrapper around swot_core.stats.calculate_detrending.

    Returns (baseline_pred, coeffs, method_name); see the core docstring. The
    UI exposes only the 2nd-order polynomial; unknown methods raise in the core
    (the old silent LOESS fallthrough was retired).
    """
    return core_stats.calculate_detrending(dist_km, wse, method)


# flag_residual_outliers is imported from swot_core.stats (uncached — it's a
# cheap numpy pass; the expensive fetch above it is what gets cached).


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
    if len(bdf) < 3:
        # Degenerate input: a 2nd-order fit needs >= 3 points; below that
        # calculate_detrending would crash or return garbage.
        return bdf, None, total_count
    baseline_pred, _coeffs, method_name = calculate_detrending(
        bdf['dist_km'].tolist(), bdf['wse'].tolist(), detrend_method)
    bdf['residual'] = bdf['wse'].values - baseline_pred
    bdf['baseline'] = baseline_pred
    return bdf, method_name, total_count


@st.cache_data(ttl=86400)
def calculate_slope_profile(dist_km, wse, smooth_km=2.0, n_eval=200):
    """Cached wrapper around swot_core.stats.calculate_slope_profile.

    Pooled-pass slope profile: 100 m binned medians, NaN-aware Gaussian
    smoothing (honest gaps), numerical derivative. Returns
    (x_eval, slope_cm_km, y_fitted); see the core docstring for the method.
    """
    return core_stats.calculate_slope_profile(dist_km, wse, smooth_km, n_eval)


# ---------------------------------------------------------------------------
# FINE-SCALE SLOPE (per-pass then aggregate) -- Fine-Scale Slope tab
# ---------------------------------------------------------------------------
# The legacy Slope Profile tab (calculate_slope_profile) POOLS all passes before
# differencing, which mixes stage differences into the slope and forces a coarse
# 2 km Gaussian (sigma -> ~4.7 km FWHM). The fine-scale method computes the slope
# WITHIN each pass (stage is constant within a pass), then aggregates the median
# across passes with a robust band -- so we can resolve backwater-scale (~0.5 km)
# structure near the bifurcation. The math (FINE_* base constants, the sliding
# Theil-Sen sweep, per-pass gridding, aggregation, window stats) lives in
# swot_core.stats, imported at the top of this file. Below are the UI-facing
# control constants: fixed tab settings and temporal grouping definitions.

# Resolution and reach extent are FIXED rather than exposed as sliders -- both have a
# single defensible value, and leaving them adjustable invited readings that disagree
# with thesis Figure 9 for no scientific gain:
#   * 0.5 km is the backwater length scale here (L_b ~ depth/slope ~ 2 m / 0.00195),
#     i.e. the scale an avulsion slope-advantage would act on. The resolution sweep
#     showed it is comfortably resolvable (SNR ~20 Kanektok / ~15 Uyak).
#   * 34 km trims the tidal mouth: cross-pass WSE spread only rises in the final
#     ~1-2 km at each outlet (see coastal_noise_diagnostic.py), and that tail is far
#     downstream of the bifurcation, so cutting it costs nothing.
FINE_RES_KM = 0.5
FINE_XMAX_KM = 34.0

# The temporal views condense a stretch of river to one slope per pass. Both the
# stretch and the pass-quality gate are fixed at their defensible values (sweep run
# 2026-08-04 over the full local archive):
#   * 1-5 km brackets the bifurcation (2.5 km) and is FOUR times the 0.5 km fitting
#     kernel. Narrower windows are unsafe: at 2-3 km (two kernel widths) the measured
#     advantage inverts to -6 cm/km, an artifact of where the bifurcation step falls
#     relative to the window edges rather than a real reversal.
#   * 80 % coverage is where the answer stabilises -- 50 % -> 80 % moves the paired
#     advantage +30 -> +25 cm/km (partial-coverage Uyak passes were biasing Uyak's
#     slope low), while 80 % -> 95 % does not move it at all. It costs passes mainly
#     on the Uyak (90 -> 42; Kanektok 123 -> 89), which is the point: those are the
#     passes that only clipped the window.
FINE_WINDOW_KM = (1.0, 5.0)
FINE_MIN_COVERAGE = 0.80


# _fine_slope_theilsen and _fine_regular_grid are imported from swot_core.stats
# (as fine_slope_theilsen / fine_regular_grid) at the top of this file.


# Period bins for the temporal fine-scale views. These MIRROR the flow-regime
# definitions in temporal_analysis.py (HIGH_FLOW_MONTHS = May freshet,
# LOW_FLOW_MONTHS = Jul-Aug baseflow) so a fine-scale seasonal contrast is directly
# comparable to the Q1/Q2 conclusions in TEMPORAL_ANALYSIS.md. Order = display order.
FINE_SEASONS = [
    ("Freshet (May)", {5}),
    ("Baseflow (Jul–Aug)", {7, 8}),
    ("Shoulder (Apr, Jun, Sep–Nov)", {4, 6, 9, 10, 11}),
    ("Ice (Dec–Mar)", {12, 1, 2, 3}),
]
FINE_GROUP_MODES = ["Year", "Season", "Month", "Individual pass"]
FINE_MAX_PERIOD_LINES = 24      # cap overlaid period profiles (guards 'Individual pass')


@st.cache_data(ttl=86400, show_spinner=False)
def compute_finescale_pass_matrix(_con, url_version, where_clause, res_km, xmax):
    """Per-pass fine-scale slope MATRIX for each river (robust sliding Theil-Sen).

    This is the expensive step: one Theil-Sen sweep per pass. It deliberately stops
    BEFORE aggregating, returning the full (grid x pass) matrix plus the pass dates,
    so every temporal regrouping (year / season / month / individual pass) and every
    coverage gate is a free numpy operation on the cached matrix rather than a
    re-query + re-fit. Aggregate with `_fine_aggregate`.

    Returns {reach: dict(grid, mat, passes, n_passes)} where `mat` holds SIGNED
    slopes (cm/km, negative = downhill) on a 0.1 km grid, NaN where a pass did not
    image that bin. Cached on the selection + controls; `url_version` keys the cache
    to the deployed data version (same idiom as other loaders).
    """
    return core_stats.fine_pass_matrix(_con, where_clause, res_km, xmax)


def _fine_group_passes(passes, mode):
    """Group pass dates into ordered periods -> [(label, positional indices), ...].

    Seasons follow FINE_SEASONS (temporal_analysis.py flow regimes); Year/Month/
    Individual pass are self-explanatory. Groups come back in chronological (or
    seasonal) display order, not alphabetical.
    """
    ts = pd.to_datetime(pd.Series(list(passes)))
    if mode == "Year":
        key, lab = ts.dt.year, ts.dt.year.astype(str)
    elif mode == "Month":
        key, lab = ts.dt.month, ts.dt.strftime("%b")
    elif mode == "Season":
        month = ts.dt.month
        key = pd.Series(len(FINE_SEASONS), index=ts.index)
        lab = pd.Series("Unclassified", index=ts.index)
        for i, (name, months) in enumerate(FINE_SEASONS):
            sel = month.isin(months)
            key[sel], lab[sel] = i, name
    else:  # Individual pass
        key, lab = ts, ts.dt.strftime("%Y-%m-%d")
    g = pd.DataFrame({"key": key, "lab": lab})
    groups = [(name, sub.index.to_numpy()) for name, sub in g.groupby("lab", sort=False)]
    groups.sort(key=lambda item: g.loc[item[1], "key"].iloc[0])
    return groups


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

@st.cache_data(ttl=3600, show_spinner=False)
def get_data_version():
    """Fingerprint of the ACTIVE data source — the cache-busting key.

    The deployment strategy keeps the release-asset URL stable and swaps the
    file behind it, so the URL itself can never bust a cache (the old
    url_version=URL scheme was a constant). Local dev: newest mtime + total
    size of the partition files. Cloud: the asset's ETag/Last-Modified from a
    HEAD request. The 1 h TTL means a redeployed asset is picked up within an
    hour with no code change; on probe failure fall back to the URL (old
    behavior, stale-but-functional).
    """
    import glob
    parts = glob.glob(os.path.join(DATA_DIR, "master_all_data_part_*.parquet"))
    if parts:
        newest = max(os.path.getmtime(p) for p in parts)
        total = sum(os.path.getsize(p) for p in parts)
        return f"local:{len(parts)}:{int(newest)}:{total}"
    try:
        import requests
        r = requests.head(REMOTE_PARQUET_URL, allow_redirects=True, timeout=10)
        tag = r.headers.get("ETag") or r.headers.get("Last-Modified") or ""
        size = r.headers.get("Content-Length", "")
        if tag or size:
            return f"remote:{tag}:{size}"
    except Exception:
        pass
    return REMOTE_PARQUET_URL


# Cache key = get_data_version() fingerprint so the cached connection invalidates when
# the data behind the stable release URL changes. NOTE: the parameter must NOT start
# with an underscore — Streamlit excludes underscore-prefixed args from the cache key,
# which would silently disable this busting.
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


# --- DEM CROSS-SECTION ARTIFACTS (produced by DEM_Transects/build_arc_B.py) ---
# The two parquets that drive the Cross-Sections tab are committed under DEM_Transects/data/, so the
# tab works on the hosted app; a local build also drops scratch copies in outputs/ (fallback below).
# See DEM_Transects/AVULSION_ANALYSIS.md.
# NOTE: paths anchor to the REPO ROOT (one level above this package) — this module
# moved from the root dashboard_swot.py into dashboard_tabs/ in the tab split.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_XSEC_DIR = os.path.join(_REPO_ROOT, "DEM_Transects", "outputs")
# The transect-map overlay (field centerlines, distance bands, transects) IS committed under data/,
# so the DEM Map View can draw it even on Streamlit Cloud. Rebuilt by DEM_Transects/map_transects.py.
_XSEC_DATA_DIR = os.path.join(_REPO_ROOT, "DEM_Transects", "data")


@st.cache_data(ttl=86400, show_spinner=False)
def load_transect_overlay():
    """The transect-map geometry as a GeoJSON dict (or None): field centerlines, distance-from-anchor
    bands, trimmed transects, channel crossings, anchor. Rendered as toggle layers in the DEM Map View."""
    import json
    try:
        with open(os.path.join(_XSEC_DATA_DIR, "transect_map_overlay.geojson")) as f:
            return json.load(f)
    except Exception:
        return None


@st.cache_data(ttl=86400, show_spinner=False)
def load_xsec_B():
    """Approach B — iso-distance-from-anchor arc transects (Kanektok vs Uyak).

    Returns (channels, profiles) or (None, None). profiles: full arc cross-sections
    (R_km, arc_m, elevation_m). channels: one row per radius —

      geometry     R_km, kan_arc_m, uyak_arc_m, fp_ref_m, fp_zone_n/width_m, geoid_m, n_valid, n_tot
      DEM water    kan_wse_m, uyak_wse_m, diff_uyak_minus_kan
      SWOT water   swot_{kan,uyak}_wse_{med,p10,p90}_m, swot_kan_wse_survey_m,
                   swot_diff_uyak_minus_kan  <- the PASS-PAIRED difference; prefer this over the
                   DEM one, which carries a differential-stage artifact from the multi-date mosaic
      superelev    {kan,uyak}_superelev_m (primary, at SWOT median stage), _{med,p10,p90}_m (band),
                   _dem_m (all-DEM variant)
      β geometry   kan_depth_m, kan_bed_m (stage-matched), kan_bed_dem_m, kan_crest_m, kan_HAR_m,
                   kan_HM_m, kan_beta, kan_freeboard_over_depth (the bankfull check)
      migration QC kan/uyak_snap_offset_m, kan/uyak_snap_clipped  (2026 field line vs 2010–2021 DEM)

    Reads the committed `data/` copies first (present on the hosted app) and falls back to the
    scratch `outputs/` copies from a local `build_arc_B.py` run.
    """
    for base in (_XSEC_DATA_DIR, _XSEC_DIR):
        try:
            channels = pd.read_parquet(os.path.join(base, "arcB_channels.parquet"))
            profiles = pd.read_parquet(os.path.join(base, "arcB_profiles.parquet"))
            return channels, profiles
        except Exception:
            continue
    return None, None


def add_transect_overlay(m, overlay):
    """Draw the DEM-transect geometry on a folium map as toggleable FeatureGroups: the field
    centerlines, the distance-from-anchor bands (radar grid), the trimmed transects + channel
    crossings, and the anchor. `overlay` is the GeoJSON dict from load_transect_overlay()."""
    feats = overlay.get("features", [])

    def of_kind(k):
        return [f for f in feats if f["properties"].get("kind") == k]

    def latlon(coords):  # GeoJSON [lon,lat] -> folium (lat,lon)
        return [(y, x) for x, y in coords]

    KAN, UYAK, BAND = COLOR_MAP["Kanektok_River"], COLOR_MAP["Uyak_Creek"], "#17becf"

    fg_cl = folium.FeatureGroup(name="Field centerlines (ADCP/GPS)", show=True)
    for f in of_kind("centerline"):
        is_kan = f["properties"]["reach"] == "Kanektok_River"
        folium.PolyLine(latlon(f["geometry"]["coordinates"]), color=KAN if is_kan else UYAK,
                        weight=3, opacity=0.95,
                        tooltip=f"{'Kanektok' if is_kan else 'Uyak'} centerline (field)").add_to(fg_cl)
    fg_cl.add_to(m)

    # Distance-from-anchor bands: dense thin "radar" arcs, labelled every 5 km. Off by default.
    fg_band = folium.FeatureGroup(name="Distance-from-anchor bands (km)", show=False)
    for f in of_kind("band"):
        p, coords = f["properties"], latlon(f["geometry"]["coordinates"])
        major = p.get("major")
        folium.PolyLine(coords, color=BAND, weight=1.8 if major else 0.8,
                        opacity=0.85 if major else 0.35,
                        tooltip=f"{p['r_km']:.0f} km from anchor" if major else None).add_to(fg_band)
        if major:
            folium.map.Marker(coords[-1], icon=folium.DivIcon(
                html=f'<div style="font-size:11px;color:#0e7c7b;font-weight:bold;'
                     f'text-shadow:0 0 2px #fff">{p["r_km"]:.0f} km</div>')).add_to(fg_band)
    fg_band.add_to(m)

    fg_tr = folium.FeatureGroup(name="Transects (trimmed to reach)", show=True)
    for f in of_kind("transect"):
        p = f["properties"]
        folium.PolyLine(latlon(f["geometry"]["coordinates"]), color="#6a51a3", weight=2,
                        opacity=0.85, dash_array="6,6",
                        tooltip=f"Transect at {p['r_km']:.0f} km").add_to(fg_tr)
    for f in of_kind("crossing"):
        p = f["properties"]
        is_kan = p["reach"] == "Kanektok_River"
        lon, lat = f["geometry"]["coordinates"]
        folium.CircleMarker((lat, lon), radius=4, color=KAN if is_kan else UYAK, fill=True,
                            fill_color=KAN if is_kan else UYAK, fill_opacity=1.0,
                            tooltip=f"{'Kanektok' if is_kan else 'Uyak'} crossing @ {p['r_km']:.0f} km"
                            ).add_to(fg_tr)
    fg_tr.add_to(m)

    for f in of_kind("anchor"):
        lon, lat = f["geometry"]["coordinates"]
        folium.Marker((lat, lon), tooltip="Anchor (distance origin)",
                      icon=folium.Icon(color="red", icon="star")).add_to(m)



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


