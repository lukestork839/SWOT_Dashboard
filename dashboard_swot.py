"""Researcher dashboard entrypoint (Streamlit Cloud app: swotdashboard.streamlit.app).

The filename is load-bearing: the deployed app's main-file path points here.
All tab content lives in dashboard_tabs/ (shared with the village app); all
science lives in swot_core. This file only owns the page frame: welcome page,
pass selection, the per-selection data preamble, and tab dispatch.
"""
import numpy as np
import streamlit as st

from dashboard_tabs import (
    dem, detrended_profile, elevation_difference, fine_scale, gradient_profile,
    hydraulic_gradient, map_view, raw_data, slope_profile, temporal,
)
from dashboard_tabs.common import (
    PAGE_TITLE, MAX_PLOT_POINTS, TabContext,
    calculate_detrending, calculate_slope_profile,
    get_data_version, get_database_connection, load_metadata,
    load_dem_profile, load_dem_points,
    render_pass_checklist, _select_passes,
    # Re-exported so tools/regression_gate.py (which imports this module
    # headless) keeps a single stable surface across the split:
    load_detrend_frame, compute_finescale_pass_matrix,
    load_reference_gradient, load_refgrad_decomposition,
    flag_residual_outliers,
    _fine_aggregate, _fine_window_coverage, _fine_window_slope,
    FINE_RES_KM, FINE_XMAX_KM, FINE_WINDOW_KM,
)

# Names this module only re-exports (see the import comment above): without
# this, linters flag them as unused imports.
__all__ = [
    "load_detrend_frame", "compute_finescale_pass_matrix",
    "load_reference_gradient", "load_refgrad_decomposition",
    "flag_residual_outliers",
    "_fine_aggregate", "_fine_window_coverage", "_fine_window_slope",
    "FINE_RES_KM", "FINE_XMAX_KM", "FINE_WINDOW_KM",
]

st.set_page_config(page_title=PAGE_TITLE, layout="wide", page_icon="🌊")


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
            # (confirmed_pass_dates is cleared with them, and Streamlit may have
            # garbage-collected the pass_{date} widget keys, so the checkboxes can
            # re-seed to defaults rather than reflect the last choice.)
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

    # Warn if any selected passes are in ice season. Lives OUTSIDE the
    # data-reload branch below so it persists on every rerun instead of
    # flashing once and vanishing on the next interaction.
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
        # FILTER DATA (reach names SQL-escaped; they double as cache keys, and
        # current names contain no quotes so the escaped string is byte-identical)
        rivers_sql = "'" + "','".join(r.replace("'", "''") for r in selected_reaches) + "'"
        dates_sql = ",".join(f"CAST('{d}' AS DATE)" for d in selected_pass_dates)

        # Base conditions (explicit CAST needed for DuckDB httpfs DATE filtering)
        where_clause = f"""
            WHERE Reach_Name IN ({rivers_sql})
            AND CAST(Pass_Date AS DATE) IN ({dates_sql})
        """

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
                       MEDIAN(wse) AS bin_wse
                FROM river_data {where_clause}
                GROUP BY Reach_Name, ROUND(dist_km)
            )
            SELECT Reach_Name,
                   AVG(bin_wse) AS avg_wse
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
        # 1. Calculate Detrended Residuals against the CANONICAL baseline: the
        # same load_detrend_frame fit the Detrended Profile tab uses (fitted on
        # the full selection frame), evaluated at this plot sample's distances.
        # Previously the map refit its own 2nd-order polynomial on viz_df — a
        # different sample of the same selection — so the two "identical" fits
        # disagreed by up to ~9 cm and the map's colors didn't match the tab's
        # residuals. Both calls below are st.cache_data hits (the Detrended tab
        # makes the identical calls), so this adds no work.
        # polyval expects the polynomial methods' ascending real-domain coeffs;
        # detrend_method is hardcoded to "Polynomial (2nd order)" above (the
        # Linear method returns [slope, intercept], which would need reversal).
        bdf, _bmethod, _btotal = load_detrend_frame(con, where_clause, detrend_method)
        if _bmethod is not None:
            _, coeffs, _ = calculate_detrending(
                bdf['dist_km'].tolist(), bdf['wse'].tolist(), detrend_method)
            baseline_pred = np.polynomial.polynomial.polyval(
                viz_df['dist_km'].to_numpy(dtype=float), coeffs)
            viz_df['detrended_residual'] = viz_df['wse'].values - baseline_pred
        else:
            # Degenerate selection (< 3 points): no 2nd-order fit exists.
            viz_df['detrended_residual'] = np.nan

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
            "🔀 Elevation Difference", "📐 Slope Profile", "🔬 Fine-Scale Slope", "📄 Raw Data",
            "⏳ Temporal Results",
        ]
        swot_tabs = st.tabs(swot_tab_names)
        tab1, tab_grad, tab3, tab5, tab2, tab4, tab_fine, tab6, tab_temporal = swot_tabs


    # --- TAB DISPATCH ---
    # Everything a tab needs is passed explicitly; render order matches the
    # original monolith exactly (session-state side effects are order-sensitive).
    ctx = TabContext(
        con=con,
        viz_df=viz_df,
        selected_reaches=selected_reaches,
        detrend_method=detrend_method,
        where_clause=where_clause,
        plotly_template=plotly_template,
        dem_profile=dem_profile,
        dem_points=dem_points,
    )

    with tab1:
        gradient_profile.render(ctx)

    with tab_grad:
        hydraulic_gradient.render(ctx)

    with main_dem:
        dem.render(ctx)

    with tab2:
        elevation_difference.render(ctx)

    with tab3:
        detrended_profile.render(ctx)

    with tab4:
        slope_profile.render(ctx)

    with tab_fine:
        fine_scale.render(ctx)

    with tab5:
        map_view.render(ctx)

    with tab6:
        raw_data.render(ctx)

    with tab_temporal:
        temporal.render(ctx)

    # --- SUMMARY STATS & DATA INFO (inside SWOT tab) ---
    with main_swot:
        st.divider()
        st.subheader("Summary Statistics")

        col1, col2, col3 = st.columns(3)
        # Count from the SELECTION, not the sampled viz_df — systematic sampling
        # can drop every point of a small pass and silently undercount here.
        col1.metric("Passes Analyzed", len(selected_pass_dates))
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
    data_version = get_data_version()
    st.session_state["data_version"] = data_version
    con = get_database_connection(data_version)
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
