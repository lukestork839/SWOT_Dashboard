import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from scipy import stats
import numpy as np
import os
import glob

# --- CONFIGURATION ---
PAGE_TITLE = "SWOT River Dynamics: Kanektok & Uyak"
DATA_DIR = "batch_outputs"
FILE_NAME = "master_all_data"

# FIXED COLORS
COLOR_MAP = {
    "Kanektok_River": "firebrick",  # Deep Red
    "Uyak_Creek": "dodgerblue"      # Bright Blue
}

st.set_page_config(page_title=PAGE_TITLE, layout="wide", page_icon="🌊")

# --- DATA LOADING ---
@st.cache_data
def load_data():
    """
    Loads data by stitching split Parquet files (for GitHub compatibility),
    falling back to a single file if running locally.
    """
    df = None
    
    # 1. Look for Split Files (Preferred for GitHub)
    split_pattern = os.path.join(DATA_DIR, "master_all_data_part_*.parquet")
    split_files = glob.glob(split_pattern)
    
    if split_files:
        split_files.sort()
        df_list = [pd.read_parquet(f) for f in split_files]
        df = pd.concat(df_list, ignore_index=True)
    
    # 2. Fallback to Single Parquet
    elif os.path.exists(os.path.join(DATA_DIR, f"{FILE_NAME}.parquet")):
        df = pd.read_parquet(os.path.join(DATA_DIR, f"{FILE_NAME}.parquet"))
        
    # 3. Fallback to CSV
    elif os.path.exists(os.path.join(DATA_DIR, f"{FILE_NAME}.csv")):
        df = pd.read_csv(os.path.join(DATA_DIR, f"{FILE_NAME}.csv"))
    
    if df is not None:
        df['Pass_Date'] = pd.to_datetime(df['Pass_Date'])
        if 'dist_km' in df.columns:
            df = df.sort_values(by=['Pass_Date', 'dist_km'])
        return df
        
    return None

def main():
    # --- SIDEBAR ---
    st.sidebar.title("🌊 Analysis Controls")
    
    df = load_data()
    
    if df is None:
        st.error(f"❌ Data not found in `{DATA_DIR}/`. Please check your file setup.")
        st.stop()

    # 1. River Selector
    if 'Reach_Name' in df.columns:
        all_reaches = df['Reach_Name'].unique()
        selected_reaches = st.sidebar.multiselect("Select Rivers:", all_reaches, default=all_reaches)
    else:
        st.error("Column 'Reach_Name' missing.")
        st.stop()
    
    # 2. Date Slider
    min_date = df['Pass_Date'].min().date()
    max_date = df['Pass_Date'].max().date()
    
    if min_date == max_date:
        start_date, end_date = min_date, max_date
        st.sidebar.info(f"📅 Data available for: {min_date}")
    else:
        start_date, end_date = st.sidebar.slider(
            "Time Frame:",
            min_value=min_date,
            max_value=max_date,
            value=(min_date, max_date)
        )

    # 3. Filter Data
    mask = (
        (df['Reach_Name'].isin(selected_reaches)) &
        (df['Pass_Date'].dt.date >= start_date) &
        (df['Pass_Date'].dt.date <= end_date)
    )
    filtered_df = df[mask]

    # --- MAIN PAGE ---
    st.title(PAGE_TITLE)
    
    # Top Row: Basic Counts
    col1, col2 = st.columns(2)
    col1.metric("Passes Analyzed", filtered_df['Pass_Date'].nunique())
    col2.metric("Total Data Points", len(filtered_df))
    
    if filtered_df.empty:
        st.warning("⚠️ No data matches your selection.")
        st.stop()

    # --- SUMMARY STATS TABLE (RESTORED) ---
    st.subheader("Summary Stats (Averages for Selected Time Period)")
    
    if 'slope_calc' in filtered_df.columns:
        # Group by River Name and calculate averages
        summary_stats = filtered_df.groupby("Reach_Name")[["wse", "slope_calc"]].mean().reset_index()
        
        # Rename columns for clarity (optional)
        summary_stats = summary_stats.rename(columns={
            "wse": "Avg WSE (m)",
            "slope_calc": "Avg Slope (cm/km)"
        })
        
        # Display as a clean table (use_container_width makes it span the page)
        st.dataframe(
            summary_stats.style.format({"Avg WSE (m)": "{:.2f}", "Avg Slope (cm/km)": "{:.2f}"}),
            use_container_width=True,
            hide_index=True 
        )
    else:
        st.warning("Column 'slope_calc' missing, cannot calculate summary stats.")

    # --- TABS ---
    tab1, tab2, tab3 = st.tabs(["📈 Gradient Profile", "🗺️ Map View", "📄 Raw Data"])

    # --- TAB 1: INTERACTIVE GRAPH ---
    with tab1:
        st.subheader(f"River Profile ({start_date} to {end_date})")
        
        # 1. Base Scatter Plot (Fixed Colors)
        fig = px.scatter(
            filtered_df, 
            x="dist_km", 
            y="wse", 
            color="Reach_Name", 
            color_discrete_map=COLOR_MAP, 
            opacity=0.3, 
            hover_data=["Pass_Date", "height_uncertainty"],
            labels={"wse": "WSE (m)", "dist_km": "Distance Upstream (km)"}
        )

        # 2. Add Trendlines & Slopes
        for reach in selected_reaches:
            reach_data = filtered_df[filtered_df['Reach_Name'] == reach]
            if len(reach_data) < 5: continue
            
            # Linear Regression
            slope, intercept, r, _, _ = stats.linregress(reach_data['dist_km'], reach_data['wse'])
            slope_cm = slope * 100
            
            # Generate Line Points
            x_range = np.linspace(reach_data['dist_km'].min(), reach_data['dist_km'].max(), 100)
            y_range = intercept + slope * x_range
            
            # Add Line Trace
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
        
        fig_map = px.scatter_mapbox(
            filtered_df,
            lat="latitude",
            lon="longitude",
            color="Reach_Name",
            color_discrete_map=COLOR_MAP, 
            size_max=10,
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
        st.dataframe(filtered_df, use_container_width=True)
        
        csv = filtered_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "⬇️ Download Data as CSV",
            csv,
            "swot_filtered_data.csv",
            "text/csv",
            key='download-csv'
        )

if __name__ == "__main__":
    main()
