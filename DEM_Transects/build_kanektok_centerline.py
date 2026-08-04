"""
Build a field-truthed Kanektok River centerline from boat ADCP survey tracks.

The SWOT Kanektok centerline is the current Approach-B channel prior, but it is smooth —
it cuts straight chords across meanders (median ~56 m, up to ~200 m off the real thalweg),
which is why the Kanektok snap window has to stay wide (±1200 m). Here we replace it with a
centerline derived from a **boat ADCP survey** our coworkers ran down the Kanektok in
late May–early Jun 2026 (RiverSurveyor / velocity_depth exports).

Source: `ADCP Data/Kanektok_Day_03/Shapefiles/*_velocity_depth_01_ASC.shp`. Day 03 is the one
day that is a single continuous **longitudinal thalweg run** — the boat ran the deep thread
from ~1.9 km to ~34.4 km radius, one transect tiling into the next (each advancing 0.5–1.3 km
downstream). The other days (02, 05, 06) are discrete bank-to-bank *discharge* crossings — great
for cross-section depth (Gearon beta, later) but wrong for a centerline, so they are excluded here.

Method — identical in spirit to build_uyak_centerline.py: the boat track *is* the thalweg (a boat
runs where the channel is deep), so we keep the longitudinal transects in along-channel order and
apply only a light rolling-mean to shed GPS jitter / within-channel weave. Meanders are preserved
in full — no radial binning (which would collapse meanders running tangential to an arc).
We isolate the longitudinal run by keeping only transects whose radius span exceeds
LONGITUDINAL_MIN_SPAN_KM (the stationary discharge crossings span <0.1 km and are dropped).

Output: outputs/kanektok_centerline_draft.gpkg / .geojson (Reach_Name='Kanektok_River', EPSG:4326)
plus outputs/kanektok_centerline_check.html to eyeball against imagery. This is the DRAFT — the
OFFICIAL centerline is data/kanektok_centerline_official.gpkg, which is this draft after any
hand-editing. build_arc_B.py reads the official file; re-running this script only refreshes the
draft, never the official one.

Run:  python3 DEM_Transects/build_kanektok_centerline.py
"""

from __future__ import annotations

import glob
import os

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "outputs")
DATA = os.path.join(HERE, "data")
ADCP_DIR = "/home/luke/Downloads/ADCP Data"
DAY03_SHP = os.path.join(ADCP_DIR, "Kanektok_Day_03", "Shapefiles",
                         "*_velocity_depth_01_ASC.shp")

ANCHOR = (59.82463509, -161.33397834)   # lat, lon — shared radial origin (SWOT/DEM dist_km)
R_EARTH = 6371.0088

# A transect is part of the continuous longitudinal run if its points sweep more than this much
# radius; the stationary bank-to-bank discharge crossings sweep <0.1 km and are excluded.
LONGITUDINAL_MIN_SPAN_KM = 0.3

# Light rolling-mean over consecutive pings (~2.7 m spacing) purely to shed GPS jitter and the
# boat's within-channel weave. Small enough (~5 pts ≈ 14 m) that river meanders are untouched.
SMOOTH_PTS = 5


def dist_bear(lat, lon):
    """Great-circle distance (km) and bearing (deg) from the anchor."""
    la1, lo1 = np.radians(ANCHOR[0]), np.radians(ANCHOR[1])
    la2, lo2 = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    dla, dlo = la2 - la1, lo2 - lo1
    a = np.sin(dla / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin(dlo / 2) ** 2
    d = 2 * R_EARTH * np.arcsin(np.sqrt(a))
    br = np.degrees(np.arctan2(np.sin(dlo) * np.cos(la2),
                               np.cos(la1) * np.sin(la2) - np.sin(la1) * np.cos(la2) * np.cos(dlo))) % 360
    return d, br


def load_backbone() -> pd.DataFrame:
    """Concatenate Day-03's longitudinal transects into one along-channel (lat, lon, depth) frame.

    Each velocity_depth shapefile is one transect, its pings already in time order. We keep only
    the transects that sweep a real distance downstream (the longitudinal run), order them by their
    low-radius end, and lay them head-to-tail — the boat ran monotonically downstream, so this
    reproduces the thalweg from ~1.9 km to ~34.4 km radius.
    """
    segs = []
    for f in sorted(glob.glob(DAY03_SHP)):
        g = gpd.read_file(f).sort_values(["HOUR", "MINUTE", "SECOND"]).reset_index(drop=True)
        d, _ = dist_bear(g["LAT"].values, g["LON"].values)
        if d.max() - d.min() > LONGITUDINAL_MIN_SPAN_KM:
            segs.append((float(d.min()), g))
    segs.sort(key=lambda t: t[0])
    frames = [pd.DataFrame({"lat": g["LAT"].values, "lon": g["LON"].values,
                            "depth_m": g["DEPTH"].values}) for _, g in segs]
    out = pd.concat(frames, ignore_index=True)
    return out


def build_centerline(pts: pd.DataFrame) -> pd.DataFrame:
    """Along-channel-ordered thalweg pings with only a light GPS-jitter smooth (meanders intact)."""
    out = pts.copy().reset_index(drop=True)
    for c in ("lat", "lon"):
        out[c] = out[c].rolling(SMOOTH_PTS, center=True, min_periods=1).mean()
    out["radius_km"], _ = dist_bear(out["lat"], out["lon"])
    return out


def main():
    pts = load_backbone()
    agg = build_centerline(pts)
    line = LineString(np.column_stack([agg["lon"], agg["lat"]]))

    gdf = gpd.GeoDataFrame({"Reach_Name": ["Kanektok_River"]}, geometry=[line], crs=4326)
    gpkg = os.path.join(OUT, "kanektok_centerline_draft.gpkg")       # DRAFT (not the official file)
    gdf.to_file(gpkg, driver="GPKG")
    geojson = os.path.join(OUT, "kanektok_centerline_draft.geojson")
    gdf.to_file(geojson, driver="GeoJSON")

    # Committed depth artifact: the raw Day-03 thalweg pings (radius + measured River Depth) that
    # build_arc_B joins to each arc for the bed elevation / Gearon H_M term. Written to data/ so the
    # arc analysis reproduces without the large external ADCP folder. Radius is from the raw ping
    # position (independent of any hand-editing of the centerline geometry above).
    depth = pts.dropna(subset=["depth_m"]).copy()
    depth = depth[depth["depth_m"] > 0]
    depth["radius_km"], _ = dist_bear(depth["lat"], depth["lon"])
    depth_pq = os.path.join(DATA, "kanektok_thalweg_depth.parquet")
    depth[["lat", "lon", "depth_m", "radius_km"]].to_parquet(depth_pq, index=False)

    # --- verification map: raw thalweg pings (depth-coloured) + derived CL + SWOT prior ---
    lat0, lon0 = agg["lat"].mean(), agg["lon"].mean()
    m = folium.Map(location=[lat0, lon0], zoom_start=11, tiles=None, control_scale=True)
    folium.TileLayer("Esri.WorldImagery", name="Satellite", attr="Esri").add_to(m)

    fg_raw = folium.FeatureGroup(name="ADCP pings (depth)", show=True)
    dmax = float(np.nanpercentile(pts["depth_m"], 98)) or 1.0
    for r in pts.itertuples():
        if np.isnan(r.depth_m):
            continue
        frac = min(max(r.depth_m / dmax, 0.0), 1.0)
        col = f"#{int(255*(1-frac)):02x}{int(120+80*frac):02x}{int(60+180*frac):02x}"
        folium.CircleMarker((r.lat, r.lon), radius=1.5, color=col, fill=True,
                            fill_opacity=0.7, weight=0,
                            tooltip=f"{r.depth_m:.2f} m").add_to(fg_raw)
    fg_raw.add_to(m)

    swot_path = os.path.join(OUT, "swot_centerlines.gpkg")
    if os.path.exists(swot_path):
        swot = gpd.read_file(swot_path).to_crs(4326)
        kan = swot[swot["Reach_Name"] == "Kanektok_River"]
        if len(kan):
            fg_s = folium.FeatureGroup(name="SWOT Kanektok CL (old prior)", show=True)
            folium.PolyLine([(y, x) for x, y in kan.geometry.iloc[0].coords],
                            color="#ff00ff", weight=2, opacity=0.8,
                            dash_array="6,6", tooltip="SWOT centerline").add_to(fg_s)
            fg_s.add_to(m)

    fg_c = folium.FeatureGroup(name="centerline (ADCP thalweg)", show=True)
    folium.PolyLine([(r.lat, r.lon) for r in agg.itertuples()],
                    color="#00ff37", weight=3.0, opacity=0.95,
                    tooltip="Kanektok centerline (ADCP thalweg, meanders preserved)").add_to(fg_c)
    fg_c.add_to(m)
    folium.Marker(list(ANCHOR), tooltip="Anchor",
                  icon=folium.Icon(color="red", icon="star")).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    html = os.path.join(OUT, "kanektok_centerline_check.html")
    m.save(html)

    print(f"{len(pts)} thalweg pings -> {len(agg)}-vertex centerline "
          f"(radius {agg['radius_km'].min():.1f}-{agg['radius_km'].max():.1f} km, meanders preserved)")
    print(f"wrote {gpkg}")
    print(f"wrote {geojson}")
    print(f"wrote {depth_pq} ({len(depth)} depth pings, median {depth['depth_m'].median():.2f} m)")
    print(f"wrote {html}")


if __name__ == "__main__":
    main()
