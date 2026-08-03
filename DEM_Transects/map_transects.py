"""
Placement sanity-check map.

Overlays, on a satellite basemap, the exact geometry the Approach-B analysis uses:
  - the official field centerlines that drive the channel picks: boat-GPS Uyak + boat-ADCP Kanektok,
  - the SWOT channel centerlines (now only a comparison overlay, no longer a prior),
  - the Approach-B iso-distance-from-anchor arcs,
  - the shared anchor and the bifurcation point.

Everything is rebuilt by importing build_arc_B, so the map shows precisely what the analysis
actually sampled — no separate copy to drift.

Run:  python3 DEM_Transects/map_transects.py   ->  outputs/transect_map.html
"""

from __future__ import annotations

import os

import folium
import geopandas as gpd
import numpy as np
from folium.plugins import MeasureControl
from shapely.geometry import LineString

import build_arc_B as B

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "outputs")
CENTERLINE = B.CENTERLINE

# Match the dashboard COLOR_MAP (Kanektok firebrick, Uyak dodgerblue).
KAN, UYAK = "#b22222", "#1e90ff"
BIFURCATION = (59.828886, -161.377778)


def approach_B_arcs(radii) -> list:
    """Rebuild the Approach-B arcs (constant distance-from-anchor) as WGS84 LineStrings."""
    arcs = []
    for R in radii:
        bearings = np.linspace(B.BEAR_MIN, B.BEAR_MAX, 240)
        lat, lon = B.dest(B.ANCHOR[0], B.ANCHOR[1], R, bearings)
        arcs.append((R, LineString(np.column_stack([lon, lat]))))
    return arcs


def main():
    centerlines = gpd.read_file(CENTERLINE).to_crs(4326)
    arcsB = approach_B_arcs(np.arange(4.0, 33.0, 4.0))

    # Map centred on the centerlines' bounding box.
    minx, miny, maxx, maxy = centerlines.total_bounds
    m = folium.Map(location=[(miny + maxy) / 2, (minx + maxx) / 2], zoom_start=11,
                   tiles=None, control_scale=True)
    folium.TileLayer("Esri.WorldImagery", name="Satellite (ESRI)", attr="Esri").add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
    MeasureControl(position="topleft", primary_length_unit="kilometers").add_to(m)

    # --- SWOT centerlines (comparison overlay only; both picks now use field centerlines) ---
    fg_cl = folium.FeatureGroup(name="SWOT centerlines (reference)", show=True)
    for _, r in centerlines.iterrows():
        color = KAN if r["Reach_Name"] == "Kanektok_River" else UYAK
        coords = [(y, x) for x, y in r.geometry.coords]
        folium.PolyLine(coords, color=color, weight=3, opacity=0.9, dash_array="8,6",
                        tooltip=f"SWOT {r['Reach_Name'].replace('_', ' ')}").add_to(fg_cl)
    fg_cl.add_to(m)

    # --- Official field centerlines that actually drive the Approach-B channel picks ---
    fg_uyak = folium.FeatureGroup(name="Uyak centerline (field GPS)", show=True)
    uyak_hand = gpd.read_file(B.UYAK_CL).to_crs(4326)
    for _, r in uyak_hand.iterrows():
        coords = [(y, x) for x, y in r.geometry.coords]
        folium.PolyLine(coords, color=UYAK, weight=3, opacity=0.95,
                        tooltip="Uyak centerline (field boat GPS)").add_to(fg_uyak)
    fg_uyak.add_to(m)

    fg_kan = folium.FeatureGroup(name="Kanektok centerline (field ADCP)", show=True)
    kan_hand = gpd.read_file(B.KAN_CL).to_crs(4326)
    for _, r in kan_hand.iterrows():
        coords = [(y, x) for x, y in r.geometry.coords]
        folium.PolyLine(coords, color=KAN, weight=3, opacity=0.95,
                        tooltip="Kanektok centerline (field boat ADCP thalweg)").add_to(fg_kan)
    fg_kan.add_to(m)

    # --- Approach-B arcs ---
    fg_arc = folium.FeatureGroup(name="B iso-distance arcs", show=True)
    for R, geom in arcsB:
        coords = [(y, x) for x, y in geom.coords]
        folium.PolyLine(coords, color="#6a51a3", weight=2, opacity=0.85, dash_array="6,6",
                        tooltip=f"Arc {R:.0f} km from anchor").add_to(fg_arc)
        folium.map.Marker(
            coords[len(coords) // 2],
            icon=folium.DivIcon(html=f'<div style="font-size:11px;color:#6a51a3;'
                                     f'font-weight:bold">{R:.0f} km</div>')).add_to(fg_arc)
    fg_arc.add_to(m)

    # --- Anchor & bifurcation ---
    folium.Marker(list(B.ANCHOR), tooltip="Anchor (distance origin)",
                  icon=folium.Icon(color="red", icon="star")).add_to(m)
    folium.Marker(list(BIFURCATION), tooltip="Bifurcation point",
                  icon=folium.Icon(color="green", icon="info-sign")).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    m.fit_bounds([[miny, minx], [maxy, maxx]])

    out = os.path.join(OUT, "transect_map.html")
    m.save(out)
    print(f"{len(arcsB)} B arcs, {len(centerlines)} SWOT centerlines + field Uyak & Kanektok lines")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
