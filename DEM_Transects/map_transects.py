"""
Placement sanity-check map.

Overlays, on a satellite basemap, the exact geometry the Approach-B analysis uses:
  - the official field centerlines that drive the channel picks: boat-GPS Uyak + boat-ADCP Kanektok,
  - the SWOT channel centerlines (now only a comparison overlay, no longer a prior),
  - the Approach-B iso-distance-from-anchor transects, each TRIMMED to the Kanektok->Uyak reach
    (+0.75 km past each channel — the same span the cross-section figure shows) and dotted where it
    crosses each field centerline, so the map transect and the plotted section line up,
  - the distance-from-anchor bands: concentric arcs ("radar pulses") every 1 km (labelled every
    5 km) marking the same distance the dashboard slider scrubs, so you can read a slider position
    straight off the map,
  - the shared anchor and the bifurcation point.

Everything is rebuilt by importing build_arc_B, so the map shows precisely what the analysis
actually sampled — no separate copy to drift.

Run:  python3 DEM_Transects/map_transects.py   ->  outputs/transect_map.html
"""

from __future__ import annotations

import json
import os

import folium
import geopandas as gpd
import numpy as np
from folium.plugins import MeasureControl
from shapely.geometry import LineString

import build_arc_B as B

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "outputs")
DATA = os.path.join(HERE, "data")
CENTERLINE = B.CENTERLINE
# Lightweight overlay the dashboard's DEM Map View renders as toggle layers. Committed (data/), and
# read with plain json there so the dashboard needs no geopandas — same geometry as this map, one
# source of truth, rebuilt whenever this script runs.
OVERLAY = os.path.join(DATA, "transect_map_overlay.geojson")

# Match the dashboard COLOR_MAP (Kanektok firebrick, Uyak dodgerblue).
KAN, UYAK = "#b22222", "#1e90ff"
BIFURCATION = (59.828886, -161.377778)
PAD_KM = 0.75    # context past each channel — matches the cross-section trim in build_arc_B.py


def approach_B_arcs(radii, kd, kb, ud, ub) -> list:
    """Approach-B transects, each TRIMMED to the Kanektok->Uyak reach it actually samples.

    For each radius the two field centerlines are crossed at bearings `kbr` (Kanektok) and `ubr`
    (Uyak); the transect is drawn only between them, plus PAD_KM past each channel (converted to a
    bearing span, degrees(pad/R)). Returns (R, arc LineString, Kanektok crossing, Uyak crossing);
    radii where either centerline has no crossing within tolerance are skipped.
    """
    arcs = []
    for R in radii:
        kbr = B.nearest_bearing(kd, kb, R)
        ubr = B.nearest_bearing(ud, ub, R)
        if not (np.isfinite(kbr) and np.isfinite(ubr)):
            continue
        pad_deg = np.degrees(PAD_KM / R)
        b0, b1 = sorted([kbr, ubr])
        bearings = np.linspace(b0 - pad_deg, b1 + pad_deg, 240)
        lat, lon = B.dest(B.ANCHOR[0], B.ANCHOR[1], R, bearings)
        klat, klon = B.dest(B.ANCHOR[0], B.ANCHOR[1], R, kbr)
        ulat, ulon = B.dest(B.ANCHOR[0], B.ANCHOR[1], R, ubr)
        arcs.append((R, LineString(np.column_stack([lon, lat])),
                     (float(klat), float(klon)), (float(ulat), float(ulon))))
    return arcs


def distance_bands(radii) -> list:
    """Concentric iso-distance-from-anchor arcs ('radar pulses') over the analysis bearing sector.

    Full-sector arcs (unlike the trimmed transects): they are the distance reference the dashboard
    slider scrubs, so each ring == one slider position in km from the anchor.
    """
    bands = []
    bearings = np.linspace(B.BEAR_MIN, B.BEAR_MAX, 96)   # smooth enough for a reference arc
    for R in radii:
        lat, lon = B.dest(B.ANCHOR[0], B.ANCHOR[1], R, bearings)
        bands.append((R, LineString(np.column_stack([lon, lat]))))
    return bands


def export_overlay(kan_hand, uyak_hand, bands_minor, bands_major, arcsB, path):
    """Write the transect geometry as a GeoJSON FeatureCollection for the dashboard to render.

    Each feature carries a `kind` (centerline / band / transect / crossing / anchor) plus the props
    the dashboard styles by, so it can group them into toggle layers with no geopandas dependency.
    Coordinates are GeoJSON order [lon, lat] throughout.
    """
    feats = []

    def line(coords_xy, props):  # round to 6 dp (~0.1 m) to keep the committed file small
        feats.append({"type": "Feature", "properties": props, "geometry": {
            "type": "LineString", "coordinates": [[round(float(x), 6), round(float(y), 6)]
                                                   for x, y in coords_xy]}})

    def point(lon, lat, props):
        feats.append({"type": "Feature", "properties": props, "geometry": {
            "type": "Point", "coordinates": [round(float(lon), 6), round(float(lat), 6)]}})

    for _, r in kan_hand.iterrows():
        line(r.geometry.coords, {"kind": "centerline", "reach": "Kanektok_River"})
    for _, r in uyak_hand.iterrows():
        line(r.geometry.coords, {"kind": "centerline", "reach": "Uyak_Creek"})
    for R, geom in bands_minor:
        line(geom.coords, {"kind": "band", "r_km": float(R), "major": False})
    for R, geom in bands_major:
        line(geom.coords, {"kind": "band", "r_km": float(R), "major": True})
    for R, geom, kpt, upt in arcsB:
        line(geom.coords, {"kind": "transect", "r_km": float(R)})
        point(kpt[1], kpt[0], {"kind": "crossing", "reach": "Kanektok_River", "r_km": float(R)})
        point(upt[1], upt[0], {"kind": "crossing", "reach": "Uyak_Creek", "r_km": float(R)})
    point(B.ANCHOR[1], B.ANCHOR[0], {"kind": "anchor"})

    with open(path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f)
    return len(feats)


def main():
    centerlines = gpd.read_file(CENTERLINE).to_crs(4326)
    kd, kb = B.hand_centerline_dbr(B.KAN_CL)
    ud, ub = B.hand_centerline_dbr(B.UYAK_CL)
    arcsB = approach_B_arcs(np.arange(4.0, 33.0, 4.0), kd, kb, ud, ub)
    bands_minor = distance_bands(np.arange(2.0, 34.01, 1.0))
    bands_major = distance_bands(np.arange(5.0, 34.01, 5.0))

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

    # --- Distance-from-anchor bands ("radar pulses"): the slider's distance grid ---
    fg_band = folium.FeatureGroup(name="Distance-from-anchor bands (km)", show=True)
    for _, geom in bands_minor:
        coords = [(y, x) for x, y in geom.coords]
        folium.PolyLine(coords, color="#17becf", weight=0.8, opacity=0.35).add_to(fg_band)
    for R, geom in bands_major:
        coords = [(y, x) for x, y in geom.coords]
        folium.PolyLine(coords, color="#17becf", weight=1.8, opacity=0.85,
                        tooltip=f"{R:.0f} km from anchor").add_to(fg_band)
        folium.map.Marker(
            coords[-1],
            icon=folium.DivIcon(html=f'<div style="font-size:11px;color:#0e7c7b;'
                                     f'font-weight:bold;text-shadow:0 0 2px #fff">{R:.0f} km</div>')
        ).add_to(fg_band)
    fg_band.add_to(m)

    # --- Approach-B transects (trimmed to the Kanektok->Uyak reach) + channel crossings ---
    fg_arc = folium.FeatureGroup(name="B transects (trimmed to reach)", show=True)
    for R, geom, kpt, upt in arcsB:
        coords = [(y, x) for x, y in geom.coords]
        folium.PolyLine(coords, color="#6a51a3", weight=2, opacity=0.85, dash_array="6,6",
                        tooltip=f"Transect at {R:.0f} km from anchor "
                                f"(Kanektok -> floodplain -> Uyak, +{PAD_KM:g} km each end)"
                        ).add_to(fg_arc)
        folium.CircleMarker(kpt, radius=4, color=KAN, fill=True, fill_color=KAN, fill_opacity=1.0,
                            tooltip=f"Kanektok crossing @ {R:.0f} km").add_to(fg_arc)
        folium.CircleMarker(upt, radius=4, color=UYAK, fill=True, fill_color=UYAK, fill_opacity=1.0,
                            tooltip=f"Uyak crossing @ {R:.0f} km").add_to(fg_arc)
        folium.map.Marker(
            coords[0],
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
    n_feat = export_overlay(kan_hand, uyak_hand, bands_minor, bands_major, arcsB, OVERLAY)
    print(f"{len(arcsB)} trimmed transects, {len(bands_minor)} distance bands "
          f"({len(bands_major)} labelled), {len(centerlines)} SWOT centerlines + field lines")
    print(f"wrote {out}")
    print(f"wrote {OVERLAY} ({n_feat} features)")


if __name__ == "__main__":
    main()
