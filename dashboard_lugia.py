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
MAX_PLOT_POINTS = 25000  # Safety Cap: Max points to plot (Prevents OOM Crash)

# FIXED COLORS
COLOR_MAP = {
    "Kanektok_River": "firebrick",  # Deep Red
    "Uyak_Creek": "dodgerblue"      # Bright Blue
}

st.set_page_config(page_title=PAGE_TITLE, layout="wide", page_icon="🌊")

@st.cache_resource
def get_database_connection():
    """
    Establishes a connection to DuckDB and creates a virtual view of the parquet files.
    """
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

    # --- SIDEBAR CONTROLS (WRAPPED IN FORM) ---
    st.sidebar.title("🌊 Analysis Controls")
    
    # 1. Get Metadata (Lightweight)
    try:
        date_range = con.execute("SELECT MIN(Pass_Date), MAX(Pass_Date) FROM river_data").fetchone()
        min_date, max_date = date_range[0], date_range[1]
        available_reaches = con.execute("SELECT DISTINCT Reach_Name FROM river_data").fetchdf()['Reach_Name'].tolist()
    except:
        st.error("Could not read metadata. Check data files.")
        st.stop()
        
    # --- THE FORM ---
    # This prevents the app from crashing while you drag the slider!
    with st.sidebar.form("analysis_form"):
        st.write("### 1. Select Time & Rivers")
        
        # Date Slider
        start_date, end_date = st.slider(
            "Time Frame:",
            min_value=min_date.date(),
            max_value=max_date.date(),
            value=(min_date.date(), max_date.date())
        )

        # River Selector
        selected_reaches = st.multiselect(
            "Select Rivers:", 
            available_reaches, 
            default=available_reaches
        )

        # Submit Button
        submitted = st.form_submit_button("🔄 Update Analysis")

    # Default to loading data on first run
    if not submitted and "data_loaded" not in st.session_state:
        st.session_state.data_loaded = True

    if not selected_reaches:
        st.warning("Please select at least one river.")
        st.stop()

    # 3. FILTER DATA (Lazy Load)
    rivers_sql = "'" + "','".join(selected_reaches) + "'"
    
    # Query for Stats (Uses ALL data for accuracy)
    query_full = f"""
        SELECT * FROM river_data 
        WHERE Reach_Name IN ({rivers_sql})
        AND Pass_Date >= '{start_date}'
        AND Pass_Date <= '{end_date}'
    """
    
    # Check count
    count = con.execute(f"SELECT COUNT(*) FROM ({query_full})").fetchone()[0]
    
    if count == 0:
        st.warning("⚠️ No data matches your selection.")
        st.stop()

    # --- MEMORY PROTECTION ---
    if count > MAX_PLOT_POINTS:
        # Load random sample for Visualization
        query_viz = f"{query_full} USING SAMPLE {MAX_PLOT_POINTS} ROWS"
        viz_df = con.execute(query_viz).fetchdf()
        
        if submitted: # Only show warning if user just clicked
            st.toast(f"ℹ️ Downsampling: Showing {MAX_PLOT_POINTS} of {count} points.", icon="📉")
    else:
        viz_df = con.execute(query_full).fetchdf()

    # Load Full Data for Stats (Memory safe in DuckDB)
    stats_query = f"""
        SELECT Reach_Name, 
               AVG(wse) as avg_wse, 
               AVG(slope_calc) as avg_slope 
        FROM ({query_full}) 
        GROUP BY Reach_Name
    """
    stats_df = con.execute(stats_query).fetchdf()

    # --- MAIN PAGE ---
    st.title(PAGE_TITLE)
    
    # KPIs
    col1, col2 = st.columns(2)
    col1.metric("Passes Analyzed", viz_df['Pass_Date'].nunique())
    col2.metric("Total Data Points", count) 

    # --- SUMMARY STATS TABLE ---
    st.subheader("Summary Stats (Averages for Selected Time Period)")
    
    display_stats = stats_df.rename(columns={
        "avg_wse": "Avg WSE (m)",
        "avg_slope": "Avg Slope (cm/km)"
    })
    
    st.dataframe(
        display_stats.style.format({"Avg WSE (m)": "{:.2f}", "Avg Slope (cm/km)": "{:.2f}"}),
        use_container_width=True,
        hide_index=True 
    )

    # --- TABS ---
    tab1, tab2, tab3 = st.tabs(["📈 Gradient Profile", "🗺️ Map View", "📄 Raw Data"])

    # --- TAB 1: INTERACTIVE GRAPH ---
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
            labels={"wse": "WSE (m)", "dist_km": "Distance Upstream (km)"}
        )

        for reach in selected_reaches:
            reach_data = viz_df[viz_df['Reach_Name'] == reach]
            if len(reach_data) < 5: continue
            
            slope, intercept, r, _, _ = stats.linregress(reach_data['dist_km'], reach_data['wse'])
            slope_cm = slope * 100
            
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

        fig.update_layout(height=600, template="plotly_white")
        st.plotly_chart(fig, use_container_width=True)

    # --- TAB 2: MAP VIEW ---
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

    # --- TAB 3: DATA TABLE ---
    with tab3:
        st.subheader("Data Inspector")
        st.dataframe(viz_df.head(1000), use_container_width=True)
        st.caption(f"Showing first 1000 rows of {count}.")
        
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
