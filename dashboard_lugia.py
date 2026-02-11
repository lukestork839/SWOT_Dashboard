import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from scipy import stats
import numpy as np
import duckdb
import os

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
    if not con: st.stop()

    st.sidebar.title("🌊 Analysis Controls")
    
    # 1. Get Metadata
    try:
        date_range = con.execute("SELECT MIN(Pass_Date), MAX(Pass_Date) FROM river_data").fetchone()
        min_date = pd.to_datetime(date_range[0])
        max_date = pd.to_datetime(date_range[1])
        available_reaches = con.execute("SELECT DISTINCT Reach_Name FROM river_data").fetchdf()['Reach_Name'].tolist()
    except Exception as e:
        st.error(f"Could not read metadata: {e}")
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

    # --- TABS ---
    tab1, tab2, tab3 = st.tabs(["📈 Gradient Profile", "🗺️ Map View", "📄 Raw Data"])

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

    with tab2:
        st.subheader("Satellite Data Point Locations")
        
        if len(viz_df) > 10000:
            map_df = viz_df.sample(10000)
        else:
            map_df = viz_df

        fig_map = px.scatter_mapbox(
            map_df,
            lat="latitude",
            lon="longitude",
            color="Reach_Name",
            color_discrete_map=COLOR_MAP, 
            size_max=8,
            zoom=8,
            hover_data=["wse", "Pass_Date"]
        )
        fig_map.update_layout(
            mapbox_style="carto-positron", 
            height=600,
            margin={"r":0,"t":0,"l":0,"b":0}
        )
        st.plotly_chart(fig_map, use_container_width=True)

    with tab3:
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
