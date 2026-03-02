#!/usr/bin/env python3
"""
SWOT Calibration Diagnostic Tool

Compares field GPS measurements with SWOT satellite data to verify calibration.
Extracts raw SWOT values and shows step-by-step corrections.

Usage:
    python calibration_diagnostic.py
"""

import earthaccess
import xarray as xr
import pandas as pd
import geopandas as gpd
import numpy as np
from datetime import datetime
import os

# ============================================================================
# CONFIGURATION
# ============================================================================

# Field calibration data
FIELD_CALIBRATION = {
    'Nov_11_2025': {
        'date': '2025-11-11',
        'time': '21:35',
        'lat': 59.757431,
        'lon': -161.880117,
        'antenna_elevation': 17.294,  # From Emlid shapefile
        'staff_height': 1.900,  # From readme
        'wse_measured': 15.394  # antenna_elevation - staff_height
    },
    'Nov_13_2025': {
        'date': '2025-11-13',
        'time': '06:15',
        'lat': 59.757448,
        'lon': -161.880128,
        'antenna_elevation': 13.629,
        'staff_height': 1.900,
        'wse_measured': 11.729
    }
}

# SWOT data configuration
SWOT_COLLECTIONS = {
    'provisional': 'SWOT_L2_HR_PIXC_D',
    'validated': 'SWOT_L2_HR_PIXC_2.0'
}

SEARCH_RADIUS_KM = 0.5  # Search within 500m of calibration point
TEMP_DIR = 'temp_calibration_data'

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate great circle distance in km"""
    R = 6371  # Earth radius in km
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
    c = 2 * np.arcsin(np.sqrt(a))
    return R * c

def normalize_longitude(lon):
    """Normalize longitude to -180 to 180 range"""
    return np.where(lon > 180, lon - 360, lon)

# ============================================================================
# MAIN DIAGNOSTIC FUNCTIONS
# ============================================================================

def download_swot_granule(target_date, cal_lat, cal_lon, output_dir):
    """
    Download SWOT granule for a specific date and location

    Args:
        target_date: Date string 'YYYY-MM-DD'
        cal_lat: Calibration latitude
        cal_lon: Calibration longitude
        output_dir: Directory to save downloaded files

    Returns:
        Path to downloaded NetCDF file, or None if not found
    """
    print(f"\n{'='*70}")
    print(f"DOWNLOADING SWOT DATA FOR {target_date}")
    print(f"{'='*70}")
    print(f"  Location: {cal_lat:.6f}°N, {cal_lon:.6f}°W")

    # Authenticate
    earthaccess.login()

    # Create bounding box around calibration point (±1 degree)
    bbox = (cal_lon - 1, cal_lat - 1, cal_lon + 1, cal_lat + 1)

    # Search for granules
    results = earthaccess.search_data(
        short_name=SWOT_COLLECTIONS['validated'],
        temporal=(target_date, target_date),
        bounding_box=bbox
    )

    if not results:
        print(f"  No validated data found, trying provisional...")
        results = earthaccess.search_data(
            short_name=SWOT_COLLECTIONS['provisional'],
            temporal=(target_date, target_date),
            bounding_box=bbox
        )

    if not results:
        print(f"  ✗ No SWOT data found for {target_date}")
        return None

    print(f"  ✓ Found {len(results)} granule(s)")

    # Download first granule
    os.makedirs(output_dir, exist_ok=True)
    downloaded = earthaccess.download(results[0], output_dir)

    if downloaded:
        print(f"  ✓ Downloaded: {downloaded[0]}")
        return downloaded[0]
    else:
        print(f"  ✗ Download failed")
        return None

def extract_calibration_data(netcdf_path, cal_lat, cal_lon, search_radius_km):
    """
    Extract SWOT data near calibration point from NetCDF file

    Args:
        netcdf_path: Path to SWOT NetCDF file
        cal_lat: Calibration point latitude
        cal_lon: Calibration point longitude
        search_radius_km: Search radius in kilometers

    Returns:
        DataFrame with SWOT measurements near calibration point
    """
    print(f"\n{'='*70}")
    print(f"EXTRACTING DATA FROM NETCDF")
    print(f"{'='*70}")
    print(f"  Calibration point: {cal_lat:.6f}°N, {cal_lon:.6f}°W")
    print(f"  Search radius: {search_radius_km} km")

    # Open NetCDF file
    with xr.open_dataset(netcdf_path, group='pixel_cloud') as ds:
        # Extract relevant variables
        lat = ds['latitude'].values
        lon = normalize_longitude(ds['longitude'].values)

        # Calculate distance from calibration point
        dist = haversine_distance(cal_lat, cal_lon, lat, lon)

        # Filter to points within search radius
        mask = dist <= search_radius_km

        if not np.any(mask):
            print(f"  ✗ No points found within {search_radius_km} km")
            return None

        print(f"  ✓ Found {np.sum(mask)} points within search radius")

        # Extract data for nearby points
        data = {
            'latitude': lat[mask],
            'longitude': lon[mask],
            'distance_km': dist[mask],
            'height_raw': ds['height'].values[mask],
            'geoid': ds['geoid'].values[mask],
            'solid_earth_tide': ds['solid_earth_tide'].values[mask],
            'pole_tide': ds['pole_tide'].values[mask],
            'load_tide_fes': ds['load_tide_fes'].values[mask],
            'classification': ds['classification'].values[mask],
            'height_uncert': ds['height_uncert'].values[mask]
        }

        df = pd.DataFrame(data)

        # Calculate WSE (same formula as SWOT_Pull.py)
        df['wse'] = (df['height_raw'] - df['geoid'] -
                     df['solid_earth_tide'] - df['pole_tide'] - df['load_tide_fes'])

        # Sort by distance
        df = df.sort_values('distance_km')

        return df

def generate_calibration_report(swot_df, field_data, output_file):
    """
    Generate comprehensive calibration comparison report

    Args:
        swot_df: DataFrame with SWOT measurements
        field_data: Dictionary with field calibration data
        output_file: Path to save report
    """

    report_lines = []

    report_lines.append("="*70)
    report_lines.append("SWOT CALIBRATION DIAGNOSTIC REPORT")
    report_lines.append("="*70)
    report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("")

    # Field measurement info
    report_lines.append("FIELD MEASUREMENT:")
    report_lines.append("-"*70)
    report_lines.append(f"Date/Time: {field_data['date']} {field_data['time']}")
    report_lines.append(f"Location: {field_data['lat']:.6f}°N, {field_data['lon']:.6f}°W")
    report_lines.append(f"Antenna Elevation (from GPS): {field_data['antenna_elevation']:.3f} m")
    report_lines.append(f"Staff Height (above water): {field_data['staff_height']:.3f} m")
    report_lines.append(f"→ Water Surface Elevation: {field_data['wse_measured']:.3f} m")
    report_lines.append("")

    if swot_df is None or len(swot_df) == 0:
        report_lines.append("✗ No SWOT data available for comparison")
        with open(output_file, 'w') as f:
            f.write('\n'.join(report_lines))
        return

    # SWOT closest point analysis
    closest = swot_df.iloc[0]

    report_lines.append("SWOT SATELLITE MEASUREMENT (Closest Point):")
    report_lines.append("-"*70)
    report_lines.append(f"Distance from calibration point: {closest['distance_km']*1000:.1f} m")
    report_lines.append(f"Location: {closest['latitude']:.6f}°N, {closest['longitude']:.6f}°W")
    report_lines.append(f"Classification: {closest['classification']:.0f}")
    report_lines.append(f"Height Uncertainty: ±{closest['height_uncert']:.3f} m")
    report_lines.append("")
    report_lines.append("Raw Values and Corrections:")
    report_lines.append(f"  Height (ellipsoidal):    {closest['height_raw']:.3f} m")
    report_lines.append(f"  - Geoid (EGM2008):       {closest['geoid']:.3f} m")
    report_lines.append(f"  - Solid Earth Tide:      {closest['solid_earth_tide']:.3f} m")
    report_lines.append(f"  - Pole Tide:             {closest['pole_tide']:.3f} m")
    report_lines.append(f"  - Load Tide (FES2014):   {closest['load_tide_fes']:.3f} m")
    report_lines.append(f"  {'─'*40}")
    report_lines.append(f"  → Water Surface Elevation: {closest['wse']:.3f} m")
    report_lines.append("")

    # Statistics for all nearby points
    report_lines.append(f"SWOT STATISTICS (all {len(swot_df)} points within {SEARCH_RADIUS_KM} km):")
    report_lines.append("-"*70)
    report_lines.append(f"Mean WSE:   {swot_df['wse'].mean():.3f} m (±{swot_df['wse'].std():.3f} m)")
    report_lines.append(f"Median WSE: {swot_df['wse'].median():.3f} m")
    report_lines.append(f"Range:      {swot_df['wse'].min():.3f} to {swot_df['wse'].max():.3f} m")
    report_lines.append(f"Mean Geoid: {swot_df['geoid'].mean():.3f} m")
    report_lines.append("")

    # Comparison
    diff_closest = field_data['wse_measured'] - closest['wse']
    diff_mean = field_data['wse_measured'] - swot_df['wse'].mean()

    report_lines.append("COMPARISON:")
    report_lines.append("="*70)
    report_lines.append(f"Field GPS WSE:           {field_data['wse_measured']:.3f} m")
    report_lines.append(f"SWOT WSE (closest):      {closest['wse']:.3f} m")
    report_lines.append(f"SWOT WSE (mean nearby):  {swot_df['wse'].mean():.3f} m")
    report_lines.append("")
    report_lines.append(f"DIFFERENCE (Field - SWOT closest): {diff_closest:+.3f} m")
    report_lines.append(f"DIFFERENCE (Field - SWOT mean):    {diff_mean:+.3f} m")
    report_lines.append("")

    # Interpretation
    report_lines.append("INTERPRETATION:")
    report_lines.append("-"*70)

    if abs(diff_closest) < 0.5:
        report_lines.append("✓ GOOD AGREEMENT: Difference < 0.5 m")
        report_lines.append("  Likely due to tidal variation and measurement uncertainty")
    elif abs(diff_closest) < 2.0:
        report_lines.append("△ MODERATE DIFFERENCE: 0.5-2.0 m")
        report_lines.append("  Possible causes: Tidal variation, timing difference, location offset")
    elif abs(diff_closest) > 8.0:
        report_lines.append("✗ LARGE DISCREPANCY: > 8 m")
        report_lines.append("  HYPOTHESIS: Field GPS 'Elevation' is likely ELLIPSOIDAL height")
        report_lines.append("  (not orthometric as labeled)")
        report_lines.append("")
        report_lines.append("  CORRECTED ANALYSIS:")
        geoid_avg = swot_df['geoid'].mean()
        corrected_wse = field_data['antenna_elevation'] - geoid_avg - field_data['staff_height']
        corrected_diff = corrected_wse - closest['wse']
        report_lines.append(f"    If field GPS is ellipsoidal height:")
        report_lines.append(f"      Antenna height (ellipsoidal): {field_data['antenna_elevation']:.3f} m")
        report_lines.append(f"      - SWOT Geoid:                 {geoid_avg:.3f} m")
        report_lines.append(f"      - Staff height:               {field_data['staff_height']:.3f} m")
        report_lines.append(f"      → Corrected WSE:              {corrected_wse:.3f} m")
        report_lines.append(f"      → New difference:             {corrected_diff:+.3f} m")
        if abs(corrected_diff) < 1.0:
            report_lines.append(f"      ✓ MUCH BETTER AGREEMENT!")
    else:
        report_lines.append("△ NOTICEABLE DIFFERENCE")
        report_lines.append("  Further investigation recommended")

    report_lines.append("")
    report_lines.append("="*70)

    # Write report
    report_text = '\n'.join(report_lines)
    with open(output_file, 'w') as f:
        f.write(report_text)

    print(report_text)
    print(f"\n✓ Report saved to: {output_file}")

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main calibration diagnostic workflow"""

    print("\n" + "="*70)
    print("SWOT CALIBRATION DIAGNOSTIC TOOL")
    print("="*70)

    # Select calibration event to analyze
    print("\nAvailable calibration events:")
    for i, (name, data) in enumerate(FIELD_CALIBRATION.items(), 1):
        print(f"  {i}. {name}: {data['date']} at {data['time']}")

    choice = input("\nSelect event to analyze (1 or 2): ").strip()

    if choice == '1':
        event_name = 'Nov_11_2025'
        swot_date = '2025-11-12'  # Closest SWOT pass
    elif choice == '2':
        event_name = 'Nov_13_2025'
        swot_date = '2025-11-13'  # Same day
    else:
        print("Invalid choice")
        return

    field_data = FIELD_CALIBRATION[event_name]

    print(f"\nAnalyzing: {event_name}")
    print(f"Field measurement: {field_data['date']} {field_data['time']}")
    print(f"SWOT pass date: {swot_date}")

    # Download SWOT granule
    netcdf_path = download_swot_granule(
        swot_date,
        field_data['lat'],
        field_data['lon'],
        TEMP_DIR
    )

    if netcdf_path is None:
        print("\n✗ Could not download SWOT data. Exiting.")
        return

    # Extract calibration data
    swot_df = extract_calibration_data(
        netcdf_path,
        field_data['lat'],
        field_data['lon'],
        SEARCH_RADIUS_KM
    )

    # Generate report
    report_file = f"batch_outputs/calibration_report_{event_name}.txt"
    generate_calibration_report(swot_df, field_data, report_file)

    # Save detailed SWOT data to CSV
    if swot_df is not None:
        csv_file = f"batch_outputs/swot_calibration_data_{event_name}.csv"
        swot_df.to_csv(csv_file, index=False)
        print(f"✓ Detailed SWOT data saved to: {csv_file}")

if __name__ == "__main__":
    main()
