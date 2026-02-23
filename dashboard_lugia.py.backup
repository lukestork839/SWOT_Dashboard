import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from scipy import stats
from scipy.ndimage import gaussian_filter1d
import numpy as np
import duckdb
import os
import folium
from folium import plugins
from folium.plugins import MeasureControl
from streamlit_folium import st_folium
import matplotlib.colors as mcolors
import matplotlib.cm as cm

# Try importing LinearColormap from different locations depending on version
try:
    from branca.colormap import LinearColormap
except ImportError:
    try:
        from folium.colormap import LinearColormap
    except ImportError:
        # Fallback: create a dummy class if not available
        LinearColormap = None

# --- CONFIGURATION ---
PAGE_TITLE = "SWOT River Dynamics: Kanektok & Uyak"
DATA_DIR = "batch_outputs"
MAX_PLOT_POINTS = 25000  # Safety Cap for browser rendering

# FIXED COLORS
COLOR_MAP = {
    "Kanektok_River": "firebrick",
    "Uyak_Creek": "dodgerblue"
}

st.set_page_config(page_title=PAGE_TITLE, layout="wide", page_icon="🌊")

@st.cache_resource
def get_database_connection():
    con = duckdb.connect(database=':memory:')
    parquet_pattern = os.path.join(DATA_DIR, "master_all_data_part_*.parquet")
    
    try:
        con.execute(f"CREATE OR REPLACE VIEW river_data AS SELECT * FROM read_parquet('{parquet_pattern}')")
        return con
    except Exception as e:
        st.error(f"❌ Could not connect to data: {e}")
        return None

def main():
    con = get_database_connection()
    if not con:
        st.error("❌ Failed to initialize database connection.")
        st.stop()

    st.sidebar.title("🌊 Analysis Controls")

    # 1. Get Metadata
    try:
        date_range = con.execute("SELECT MIN(Pass_Date), MAX(Pass_Date) FROM river_data").fetchone()
        if date_range is None or date_range[0] is None:
            st.error("❌ No data found in parquet files. Please run Lugia.py first to generate data.")
            st.stop()

        min_date = pd.to_datetime(date_range[0])
        max_date = pd.to_datetime(date_range[1])
        available_reaches = con.execute("SELECT DISTINCT Reach_Name FROM river_data").fetchdf()['Reach_Name'].tolist()
    except Exception as e:
        st.error(f"❌ Could not read metadata: {e}")
        st.info("💡 This usually means the parquet files are missing or corrupted. Try running `python Lugia.py` to regenerate the data.")
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

        selected_reaches = st.multiselect(
            "Select Rivers:",
            available_reaches,
            default=available_reaches
        )

        st.write("### 2. Detrending Method")
        detrend_method = st.selectbox(
            "Baseline Trend:",
            options=[
                "Polynomial (2nd order)",
                "Polynomial (3rd order)",
                "Linear",
                "LOESS (Local Regression)"
            ],
            index=0,
            help="Method to calculate baseline elevation trend for detrended analysis"
        )

        # Method descriptions
        with st.expander("ℹ️ About Baseline Trend Methods"):
            st.markdown("""
            **Polynomial (2nd order)** - *Recommended for most cases*
            - Fits a smooth curved baseline (parabola)
            - Best for: Rivers with gentle, consistent curvature
            - Good balance of smoothness and flexibility

            **Polynomial (3rd order)** - *More flexible*
            - Fits a more complex curve with one inflection point
            - Best for: Rivers with varying curvature (steep→gentle→steep)
            - Can capture more detail but may overfit noise

            **Linear** - *Simplest*
            - Fits a straight line baseline
            - Best for: Rivers with approximately constant gradient
            - May miss important curvature in the profile

            **LOESS (Local Regression)** - *Adaptive*
            - Smoothly adapts to local variations in the data
            - Best for: Complex profiles with varying characteristics
            - Most flexible but can be sensitive to data density

            💡 **Tip**: Start with Polynomial (2nd order). If rivers show significant
            elevation differences near the edges but not in the middle (or vice versa),
            try a more flexible method.
            """)


        st.write("### 3. Map Display Options")
        map_color_by = st.selectbox(
            "Color Points By:",
            options=[
                "River Name",
                "WSE (Water Surface Elevation)",
                "Classification",
                "Detrended Residual (m)",
                "Interval Slope (cm/km)"
            ],
            index=0,
            help="Choose what metric to visualize on the map"
        )

        basemap_style = st.selectbox(
            "Basemap Style:",
            options=[
                "OpenStreetMap",
                "Terrain (Stamen)",
                "Satellite (ESRI)",
                "Watercolor (Stamen)",
                "CartoDB Positron (Light)",
                "CartoDB Dark Matter"
            ],
            index=0
        )

        point_opacity = st.slider(
            "Point Opacity:",
            min_value=0.1,
            max_value=1.0,
            value=0.7,
            step=0.1,
            help="Adjust transparency of map points (lower = more transparent, easier to see basemap)"
        )

        submitted = st.form_submit_button("🔄 Update Analysis")

    if not submitted and "data_loaded" not in st.session_state:
        st.session_state.data_loaded = True

    if not selected_reaches:
        st.warning("Please select at least one river.")
        st.stop()

    # 3. FILTER DATA
    rivers_sql = "'" + "','".join(selected_reaches) + "'"
    
    # Base conditions
    where_clause = f"""
        WHERE Reach_Name IN ({rivers_sql})
        AND Pass_Date >= '{start_date}'
        AND Pass_Date <= '{end_date}'
    """
    
    # Check total count first
    try:
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

    # --- MAIN PAGE ---
    st.title(PAGE_TITLE)
    
    col1, col2 = st.columns(2)
    col1.metric("Passes Analyzed", viz_df['Pass_Date'].nunique())
    col2.metric("Total Data Points", count) 

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
        use_container_width=True,
        hide_index=True
    )

    # --- CALCULATE ADVANCED METRICS FOR MAP VISUALIZATION ---
    # These are used for map coloring options

    # 1. Calculate Detrended Residuals (using fixed methods, not broken np.polyfit)
    x_all = viz_df['dist_km'].values
    y_all = viz_df['wse'].values

    # Use selected detrending method (same fixed methods as Detrended Profile tab)
    if detrend_method == "Linear":
        # Use scipy.stats.linregress (np.polyfit has numerical issues)
        slope, intercept, _, _, _ = stats.linregress(x_all, y_all)
        baseline_pred = slope * x_all + intercept
    elif detrend_method == "Polynomial (2nd order)":
        # Use numpy.polynomial.Polynomial.fit (more stable than polyfit)
        poly = np.polynomial.Polynomial.fit(x_all, y_all, 2)
        baseline_pred = poly(x_all)
    elif detrend_method == "Polynomial (3rd order)":
        # Use numpy.polynomial.Polynomial.fit (more stable than polyfit)
        poly = np.polynomial.Polynomial.fit(x_all, y_all, 3)
        baseline_pred = poly(x_all)
    else:  # LOESS
        # Simple LOESS approximation using Gaussian smoothing
        sorted_idx = np.argsort(x_all)
        x_sorted = x_all[sorted_idx]
        y_sorted = y_all[sorted_idx]
        sigma = len(x_all) * 0.15 / 3
        y_smooth = gaussian_filter1d(y_sorted, sigma=sigma, mode='nearest')
        baseline_pred = np.zeros_like(y_all)
        baseline_pred[sorted_idx] = y_smooth

    viz_df['detrended_residual'] = y_all - baseline_pred

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

    # --- TABS ---
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📈 Gradient Profile", "🔀 Elevation Difference", "🎯 Detrended Profile", "📐 Interval Slopes", "🗺️ Map View", "📄 Raw Data"])

    with tab1:
        st.subheader(f"River Profile ({start_date} to {end_date})")
        
        fig = px.scatter(
            viz_df, 
            x="dist_km", 
            y="wse", 
            color="Reach_Name", 
            color_discrete_map=COLOR_MAP, 
            opacity=0.3, 
            hover_data=["Pass_Date", "height_uncertainty"],
            labels={
                "wse": "Water Surface Elevation (m)", 
                "dist_km": "Distance from Confluence Anchor (km)"
            }
        )

        # Trendlines
        for reach in selected_reaches:
            reach_data = viz_df[viz_df['Reach_Name'] == reach]
            if len(reach_data) < 5: continue
            
            slope, intercept, r, _, _ = stats.linregress(reach_data['dist_km'], reach_data['wse'])
            slope_cm = abs(slope * 100) # Use Absolute value for display "Steepness"
            
            x_range = np.linspace(reach_data['dist_km'].min(), reach_data['dist_km'].max(), 100)
            y_range = intercept + slope * x_range
            
            line_color = COLOR_MAP.get(reach, "black")
            
            fig.add_trace(go.Scatter(
                x=x_range, 
                y=y_range, 
                mode='lines',
                name=f"{reach} Trend: {slope_cm:.1f} cm/km",
                line=dict(color=line_color, width=4, dash='dash')
            ))

        # 🔄 REVERSE THE X-AXIS HERE
        fig.update_xaxes(autorange="reversed")

        fig.update_layout(height=600, template="plotly_white")
        st.plotly_chart(fig, use_container_width=True)

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
        - "Interval Slopes" shows how steepness varies along the river
        """)

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
                        xaxis_title="Distance from Confluence Anchor (km)",
                        yaxis_title="Elevation Difference (m)",
                        height=600,
                        template="plotly_white",
                        hovermode='x unified'
                    )

                    # Reverse x-axis to match other plots (Coast on left, Confluence on right)
                    fig_diff.update_xaxes(autorange="reversed")

                    st.plotly_chart(fig_diff, use_container_width=True)

                    # Add interpretation guide
                    st.info("""
                    **How to Read This Graph:**
                    - **Positive values** (above zero): Kanektok River has higher water surface elevation
                    - **Negative values** (below zero): Uyak Creek has higher water surface elevation
                    - **Zero line**: Rivers have equal elevation
                    - Data is binned every 100 meters and averaged for clarity
                    """)

                    # Show summary statistics
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Average Difference", f"{diff_df['elevation_diff'].mean():.3f} m")
                    col2.metric("Max Difference", f"{diff_df['elevation_diff'].max():.3f} m")
                    col3.metric("Number of Bins", len(diff_df))

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
            # Get full dataset for both rivers (for accurate baseline)
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
                # Prepare data for baseline fitting (combine both rivers)
                x_all = baseline_df['dist_km'].values
                y_all = baseline_df['wse'].values

                # Fit baseline based on selected method
                if detrend_method == "Linear":
                    # Use scipy.stats.linregress (np.polyfit has numerical issues with large datasets)
                    slope_manual, intercept_manual, r_value, p_value, std_err = stats.linregress(x_all, y_all)
                    baseline_pred = slope_manual * x_all + intercept_manual
                    coeffs = [slope_manual, intercept_manual]
                    method_name = "Linear Fit"
                elif detrend_method == "Polynomial (2nd order)":
                    # Use numpy.polynomial.Polynomial.fit (more numerically stable than polyfit)
                    poly = np.polynomial.Polynomial.fit(x_all, y_all, 2)
                    baseline_pred = poly(x_all)
                    coeffs = poly.coef
                    method_name = "2nd Order Polynomial"
                elif detrend_method == "Polynomial (3rd order)":
                    # Use numpy.polynomial.Polynomial.fit (more numerically stable than polyfit)
                    poly = np.polynomial.Polynomial.fit(x_all, y_all, 3)
                    baseline_pred = poly(x_all)
                    coeffs = poly.coef
                    method_name = "3rd Order Polynomial"
                else:  # LOESS
                    baseline_pred = loess_smooth(x_all, y_all, frac=0.15)
                    method_name = "LOESS (Local Regression)"

                # Calculate residuals
                baseline_df['residual'] = y_all - baseline_pred
                baseline_df['baseline'] = baseline_pred

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

                    fig_detrend.add_trace(go.Scatter(
                        x=reach_data['dist_km'],
                        y=reach_data['residual'],
                        mode='markers',
                        name=reach,
                        marker=dict(color=line_color, size=3, opacity=0.4),
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
                    xaxis_title="Distance from Confluence Anchor (km)",
                    yaxis_title=f"Residual Elevation (m) - Detrended using {method_name}",
                    height=600,
                    template="plotly_white",
                    hovermode='closest',
                    showlegend=True
                )

                # Reverse x-axis to match other plots
                fig_detrend.update_xaxes(autorange="reversed")

                st.plotly_chart(fig_detrend, use_container_width=True)

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
                        use_container_width=True,
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
                        xaxis_title="Distance from Confluence Anchor (km)",
                        yaxis_title="Water Surface Elevation (m)",
                        height=500,
                        template="plotly_white",
                        title=f"Original Data with {method_name} Baseline"
                    )

                    fig_baseline.update_xaxes(autorange="reversed")
                    st.plotly_chart(fig_baseline, use_container_width=True)

        except Exception as e:
            st.error(f"Error calculating detrended profile: {e}")
            import traceback
            st.code(traceback.format_exc())

    with tab4:
        st.subheader(f"Interval Slopes: 100m Segments ({start_date} to {end_date})")

        # Query to calculate slopes for 100m intervals per river
        slope_query = f"""
            WITH binned_data AS (
                SELECT
                    ROUND(dist_km / 0.1) * 0.1 AS dist_bin,
                    Reach_Name,
                    AVG(wse) AS avg_wse,
                    COUNT(*) AS point_count
                FROM river_data
                {where_clause}
                GROUP BY dist_bin, Reach_Name
                HAVING COUNT(*) >= 3  -- Require at least 3 points per bin for reliable average
            ),
            slopes AS (
                SELECT
                    dist_bin,
                    Reach_Name,
                    avg_wse,
                    point_count,
                    LAG(avg_wse) OVER (PARTITION BY Reach_Name ORDER BY dist_bin) as prev_wse,
                    LAG(dist_bin) OVER (PARTITION BY Reach_Name ORDER BY dist_bin) as prev_dist,
                    (dist_bin - LAG(dist_bin) OVER (PARTITION BY Reach_Name ORDER BY dist_bin)) as dist_gap,
                    CASE
                        WHEN LAG(dist_bin) OVER (PARTITION BY Reach_Name ORDER BY dist_bin) IS NOT NULL
                        THEN ((avg_wse - LAG(avg_wse) OVER (PARTITION BY Reach_Name ORDER BY dist_bin)) /
                              (dist_bin - LAG(dist_bin) OVER (PARTITION BY Reach_Name ORDER BY dist_bin))) * 100
                        ELSE NULL
                    END as interval_slope_cm_km
                FROM binned_data
            )
            SELECT
                dist_bin,
                Reach_Name,
                avg_wse,
                point_count,
                interval_slope_cm_km,
                dist_gap
            FROM slopes
            WHERE interval_slope_cm_km IS NOT NULL
              AND dist_gap <= 0.15  -- Only include consecutive bins (max 150m gap allows for slight irregularities)
              AND ABS(interval_slope_cm_km) <= 1000  -- Filter out unrealistic extreme slopes
            ORDER BY Reach_Name, dist_bin
        """

        try:
            slope_df = con.execute(slope_query).fetchdf()

            if len(slope_df) == 0:
                st.warning("No interval slope data available for the selected filters.")
            else:
                # Create the interval slopes plot
                fig_slopes = go.Figure()

                for reach in selected_reaches:
                    reach_data = slope_df[slope_df['Reach_Name'] == reach]
                    if len(reach_data) == 0:
                        continue

                    line_color = COLOR_MAP.get(reach, "black")

                    fig_slopes.add_trace(go.Scatter(
                        x=reach_data['dist_bin'],
                        y=reach_data['interval_slope_cm_km'].abs(),  # Absolute value for "steepness"
                        mode='lines+markers',
                        name=reach,
                        line=dict(color=line_color, width=2),
                        marker=dict(size=4),
                        customdata=reach_data[['point_count', 'dist_gap']],
                        hovertemplate='<b>' + reach + '</b><br>' +
                                      'Distance: %{x:.2f} km<br>' +
                                      'Slope: %{y:.2f} cm/km<br>' +
                                      'Points in bin: %{customdata[0]}<br>' +
                                      'Gap to prev: %{customdata[1]:.2f} km<br>' +
                                      '<extra></extra>'
                    ))

                # Update layout
                fig_slopes.update_layout(
                    xaxis_title="Distance from Confluence Anchor (km)",
                    yaxis_title="Interval Slope (cm/km) - Absolute Value",
                    height=600,
                    template="plotly_white",
                    hovermode='x unified',
                    showlegend=True
                )

                # Reverse x-axis to match other plots
                fig_slopes.update_xaxes(autorange="reversed")

                st.plotly_chart(fig_slopes, use_container_width=True)

                # Add interpretation guide
                st.info("""
                **How to Read This Graph:**
                - Each point represents the **average slope** over a ~100-meter river segment
                - **Higher values** = Steeper gradient (rapid elevation change)
                - **Lower values** = Gentler gradient (gradual elevation change)
                - Values are absolute (steepness) for easier comparison
                - Helps identify specific reaches with different hydraulic characteristics

                **Quality Filters Applied:**
                - Bins require ≥3 data points for reliable averaging
                - Only consecutive bins shown (≤150m gap)
                - Extreme outliers removed (>1000 cm/km filtered out)
                """)

                # Show summary statistics per river
                st.subheader("Interval Slope Statistics")

                stats_data = []
                for reach in selected_reaches:
                    reach_data = slope_df[slope_df['Reach_Name'] == reach]
                    if len(reach_data) > 0:
                        stats_data.append({
                            "River": reach,
                            "Average Slope (cm/km)": reach_data['interval_slope_cm_km'].abs().mean(),
                            "Max Slope (cm/km)": reach_data['interval_slope_cm_km'].abs().max(),
                            "Min Slope (cm/km)": reach_data['interval_slope_cm_km'].abs().min(),
                            "Std Dev (cm/km)": reach_data['interval_slope_cm_km'].abs().std(),
                            "Number of Intervals": len(reach_data),
                            "Avg Points/Bin": reach_data['point_count'].mean()
                        })

                if stats_data:
                    stats_summary = pd.DataFrame(stats_data)
                    st.dataframe(
                        stats_summary.style.format({
                            "Average Slope (cm/km)": "{:.2f}",
                            "Max Slope (cm/km)": "{:.2f}",
                            "Min Slope (cm/km)": "{:.2f}",
                            "Std Dev (cm/km)": "{:.2f}"
                        }),
                        use_container_width=True,
                        hide_index=True
                    )

        except Exception as e:
            st.error(f"Error calculating interval slopes: {e}")

    with tab5:
        st.subheader("Satellite Data Point Locations")

        # Sample data if too large (for performance)
        if len(viz_df) > 10000:
            map_df = viz_df.sample(10000)
            st.info(f"📍 Showing 10,000 sampled points (out of {len(viz_df):,}) for map performance.")
        else:
            map_df = viz_df

        # Calculate map center
        center_lat = map_df['latitude'].mean()
        center_lon = map_df['longitude'].mean()

        # Map basemap style to Folium tiles
        basemap_tiles = {
            "OpenStreetMap": "OpenStreetMap",
            "Terrain (Stamen)": "Stamen Terrain",
            "Satellite (ESRI)": "Esri WorldImagery",
            "Watercolor (Stamen)": "Stamen Watercolor",
            "CartoDB Positron (Light)": "CartoDB positron",
            "CartoDB Dark Matter": "CartoDB dark_matter"
        }

        selected_tiles = basemap_tiles.get(basemap_style, "OpenStreetMap")

        # Create Folium map
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=10,
            tiles=selected_tiles,
            control_scale=True
        )

        # Add measuring tool (Distance & Area)
        plugins.MeasureControl(
            position='topleft',
            primary_length_unit='kilometers',
            secondary_length_unit='meters',
            primary_area_unit='sqkilometers',
            secondary_area_unit='acres'
        ).add_to(m)

        # Configure coloring based on user selection
        if map_color_by == "River Name":
            # Discrete colors by river
            color_mapping = {
                "Kanektok_River": "firebrick",
                "Uyak_Creek": "dodgerblue"
            }

            for reach_name, color in color_mapping.items():
                reach_data = map_df[map_df['Reach_Name'] == reach_name]
                feature_group = folium.FeatureGroup(name=reach_name)

                for _, row in reach_data.iterrows():
                    folium.CircleMarker(
                        location=[row['latitude'], row['longitude']],
                        radius=3,
                        color=color,
                        fill=True,
                        fillColor=color,
                        fillOpacity=point_opacity,
                        popup=folium.Popup(
                            f"<b>{reach_name}</b><br>"
                            f"WSE: {row['wse']:.2f} m<br>"
                            f"Date: {row['Pass_Date']}<br>"
                            f"Class: {row['classification']}",
                            max_width=200
                        )
                    ).add_to(feature_group)

                feature_group.add_to(m)

        elif map_color_by == "WSE (Water Surface Elevation)":
            # Continuous colors by WSE using viridis colormap
            wse_min = map_df['wse'].min()
            wse_max = map_df['wse'].max()

            # Create colormap
            colormap = cm.get_cmap('viridis')
            norm = mcolors.Normalize(vmin=wse_min, vmax=wse_max)

            feature_group = folium.FeatureGroup(name="WSE Elevation")

            for _, row in map_df.iterrows():
                wse_val = row['wse']
                rgba = colormap(norm(wse_val))
                hex_color = mcolors.rgb2hex(rgba[:3])

                folium.CircleMarker(
                    location=[row['latitude'], row['longitude']],
                    radius=3,
                    color=hex_color,
                    fill=True,
                    fillColor=hex_color,
                    fillOpacity=point_opacity,
                    popup=folium.Popup(
                        f"<b>{row['Reach_Name']}</b><br>"
                        f"WSE: {wse_val:.2f} m<br>"
                        f"Date: {row['Pass_Date']}<br>"
                        f"Class: {row['classification']}",
                        max_width=200
                    )
                ).add_to(feature_group)

            feature_group.add_to(m)

            # Add colorbar legend (if available)
            if LinearColormap is not None:
                colormap_legend = LinearColormap(
                    colors=['#440154', '#31688e', '#35b779', '#fde724'],  # viridis colors
                    vmin=wse_min,
                    vmax=wse_max,
                    caption='Water Surface Elevation (m)'
                )
                colormap_legend.add_to(m)

        elif map_color_by == "Classification":
            # Discrete colors by classification
            class_colors = {
                3: "#FFA500",  # Orange
                4: "#00CED1",  # Turquoise
                5: "#90EE90",  # Light green
                6: "#FFB6C1",  # Light pink
                7: "#DDA0DD"   # Plum
            }

            for class_val, color in class_colors.items():
                class_data = map_df[map_df['classification'] == class_val]
                if len(class_data) == 0:
                    continue

                feature_group = folium.FeatureGroup(name=f"Class {class_val}")

                for _, row in class_data.iterrows():
                    folium.CircleMarker(
                        location=[row['latitude'], row['longitude']],
                        radius=3,
                        color=color,
                        fill=True,
                        fillColor=color,
                        fillOpacity=point_opacity,
                        popup=folium.Popup(
                            f"<b>{row['Reach_Name']}</b><br>"
                            f"WSE: {row['wse']:.2f} m<br>"
                            f"Date: {row['Pass_Date']}<br>"
                            f"Classification: {class_val}",
                            max_width=200
                        )
                    ).add_to(feature_group)

                feature_group.add_to(m)

        elif map_color_by == "Detrended Residual (m)":
            # Continuous colors by detrended residual using diverging colormap (RdBu)
            res_min = map_df['detrended_residual'].min()
            res_max = map_df['detrended_residual'].max()
            res_abs_max = max(abs(res_min), abs(res_max))

            # Create diverging colormap (red-white-blue)
            colormap = cm.get_cmap('RdBu_r')  # Reversed: red=positive, blue=negative
            norm = mcolors.Normalize(vmin=-res_abs_max, vmax=res_abs_max)

            feature_group = folium.FeatureGroup(name="Detrended Residual")

            for _, row in map_df.iterrows():
                res_val = row['detrended_residual']
                rgba = colormap(norm(res_val))
                hex_color = mcolors.rgb2hex(rgba[:3])

                folium.CircleMarker(
                    location=[row['latitude'], row['longitude']],
                    radius=3,
                    color=hex_color,
                    fill=True,
                    fillColor=hex_color,
                    fillOpacity=point_opacity,
                    weight=0,  # No border for cleaner look
                    popup=folium.Popup(
                        f"<b>{row['Reach_Name']}</b><br>"
                        f"Residual: {res_val:+.3f} m<br>"
                        f"WSE: {row['wse']:.2f} m<br>"
                        f"Date: {row['Pass_Date']}",
                        max_width=200
                    )
                ).add_to(feature_group)

            feature_group.add_to(m)

            # Add colorbar legend (if available)
            if LinearColormap is not None:
                colormap_legend = LinearColormap(
                    colors=['#2166ac', '#4393c3', '#92c5de', '#d1e5f0',
                            '#f7f7f7', '#fddbc7', '#f4a582', '#d6604d', '#b2182b'],  # RdBu colors
                    vmin=-res_abs_max,
                    vmax=res_abs_max,
                    caption='Residual (m)'  # Shortened to prevent cut-off
                )
                colormap_legend.add_to(m)

        elif map_color_by == "Interval Slope (cm/km)":
            # Continuous colors by interval slope using sequential colormap (YlOrRd)
            slope_min = map_df['interval_slope'].abs().min()
            slope_max = map_df['interval_slope'].abs().max()

            # Create sequential colormap (yellow to red)
            colormap = cm.get_cmap('YlOrRd')
            norm = mcolors.Normalize(vmin=slope_min, vmax=slope_max)

            feature_group = folium.FeatureGroup(name="Interval Slope")

            for _, row in map_df.iterrows():
                slope_val = abs(row['interval_slope'])  # Use absolute value
                rgba = colormap(norm(slope_val))
                hex_color = mcolors.rgb2hex(rgba[:3])

                folium.CircleMarker(
                    location=[row['latitude'], row['longitude']],
                    radius=3,
                    color=hex_color,
                    fill=True,
                    fillColor=hex_color,
                    fillOpacity=point_opacity,
                    popup=folium.Popup(
                        f"<b>{row['Reach_Name']}</b><br>"
                        f"Interval Slope: {slope_val:.2f} cm/km<br>"
                        f"WSE: {row['wse']:.2f} m<br>"
                        f"Date: {row['Pass_Date']}",
                        max_width=200
                    )
                ).add_to(feature_group)

            feature_group.add_to(m)

            # Add colorbar legend (if available)
            if LinearColormap is not None:
                colormap_legend = LinearColormap(
                    colors=['#ffffb2', '#fecc5c', '#fd8d3c', '#f03b20', '#bd0026'],  # YlOrRd colors
                    vmin=slope_min,
                    vmax=slope_max,
                    caption='Interval Slope Magnitude (cm/km)'
                )
                colormap_legend.add_to(m)

        # Add layer control (toggle layers on/off)
        folium.LayerControl().add_to(m)

        # Display map in Streamlit
        # Use key and returned_objects to prevent unwanted reruns
        st_folium(
            m,
            width=1400,
            height=600,
            key="river_map",
            returned_objects=[]  # Don't return any objects to prevent reruns
        )

        # Add interpretation guide based on color mode
        if map_color_by == "Detrended Residual (m)":
            st.info(f"""
            **Color Interpretation - Detrended Residual (using {detrend_method}):**
            - **Red**: Points ABOVE the baseline trend (higher than expected elevation)
            - **Blue**: Points BELOW the baseline trend (lower than expected elevation)
            - **White**: Points exactly on the baseline

            **What this shows:**
            - Spatial patterns of elevation deviations from the overall river profile
            - Areas where water is consistently higher/lower than the fitted curve
            - Red clusters = steeper than average reaches
            - Blue clusters = gentler than average reaches

            💡 Try different baseline methods in the sidebar to see how patterns change!
            """)
        elif map_color_by == "Interval Slope (cm/km)":
            st.info("""
            **Color Interpretation - Interval Slope:**
            - **Yellow**: Gentle slopes (low gradient)
            - **Orange**: Moderate slopes
            - **Red**: Steep slopes (high gradient)

            **What this shows:**
            - Segment-by-segment steepness (100m intervals)
            - Spatial distribution of hydraulic gradients
            - Red areas = higher energy, faster flow potential
            - Yellow areas = lower energy, slower flow

            💡 Compare both rivers to see which has consistently steeper reaches!
            """)

    with tab6:
        st.subheader("Data Inspector")
        st.dataframe(viz_df.head(1000), use_container_width=True)
        st.caption(f"Showing first 1000 rows of visualization sample.")
        
        csv = viz_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "⬇️ Download Sample Data as CSV",
            csv,
            "swot_sample_data.csv",
            "text/csv",
            key='download-csv'
        )

if __name__ == "__main__":
    main()
