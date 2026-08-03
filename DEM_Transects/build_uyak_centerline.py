"""
Build a hand-truthed Uyak Creek centerline from field GPS.

The SWOT Uyak centerline is too smooth — it cuts straight chords across meanders and
sits ~500 m off the real channel, which biased the Approach-B channel prior. Here we
replace it with a centerline derived from **boat GPS tracks** a hunter ran down the Uyak
(onX exports) plus a hand sketch that fills the one gap between the two boat runs:

  onx-markups-2025-04-21.gpx     2024 run, radius  2.6 - 14.5 km  (near reach)
  Sketches.geojson               hand sketch,     14.6 - 16.3 km  (gap filler)
  onx-markups-2025-04-21 2.gpx   2023 run, radius 16.2 - 37.8 km  (far reach; has a doubleback)

Method: the boat track *is* the centerline — a boat can only run where the channel is deep
enough, so every trackpoint already sits on the channel thread. So we simply CONCATENATE the
three sources in along-channel order (each in its native point order, oriented to run
anchor-outward), with only a light rolling-mean to shed GPS jitter / within-channel weave.
Meanders are preserved in full — no radial binning, which would collapse any meander running
tangentially to an arc. The one edit is truncating the 2023 track's far-end doubleback.

Output: outputs/uyak_centerline_draft.gpkg / .geojson (Reach_Name='Uyak_Creek', EPSG:4326) plus
outputs/uyak_centerline_check.html to eyeball against imagery. This is the DRAFT — the OFFICIAL
centerline is data/uyak_centerline_official.gpkg, which is this draft after hand-editing (far-end
branch choice etc.). build_arc_B.py reads the official file; re-running this script only refreshes
the draft, never the official one.

Run:  python3 DEM_Transects/build_uyak_centerline.py
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "outputs")
DL = "/home/luke/Downloads"

ANCHOR = (59.82463509, -161.33397834)   # lat, lon — shared radial origin (SWOT/DEM dist_km)
R_EARTH = 6371.0088
GPX_NS = "{http://www.topografix.com/GPX/1/1}"

# Light rolling-mean over consecutive trackpoints (~7 m spacing) purely to shed GPS jitter and
# the boat's within-channel weave. Small enough (~5 pts ≈ 30 m) that river meanders are untouched.
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


def gpx_track(path):
    """All trackpoints (lat, lon) from a GPX file, in file order."""
    root = ET.parse(path).getroot()
    pts = [(float(p.get("lat")), float(p.get("lon")))
           for p in root.iter(f"{GPX_NS}trkpt")]
    return np.array(pts)


def geojson_line(path):
    """Vertices (lat, lon) of the (first) LineString in a GeoJSON."""
    g = gpd.read_file(path)
    coords = []
    for geom in g.geometry:
        lines = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
        for ln in lines:
            coords.extend([(y, x) for x, y in ln.coords])
    return np.array(coords)


def _orient_outward(arr):
    """Orient a (lat,lon) point array so it runs from its low-radius end to its high-radius end."""
    d, _ = dist_bear(arr[:, 0], arr[:, 1])
    return arr[::-1] if d[0] > d[-1] else arr


def load_sources():
    """Concatenate the three sources into one along-channel-ordered (lat, lon, src) frame.

    Each source is already an along-channel point sequence (boat trackpoints in time order, or
    the sketch's vertices); the three tile end-to-end by radius (near 2024 -> sketch gap -> far
    2023), so we just orient each anchor-outward and lay them end to end — no binning.

    The 2023 far track has a doubleback at its far end: the boat ran up one branch to a
    turnaround (~37.8 km, its max radius), then backtracked and took another branch to continue.
    Only the clean outbound limb is a valid centerline, so we truncate the 2023 track at its
    max-radius point and drop the rest (the backtrack + second branch). That divergence sits
    mostly beyond the 35 km arc limit; the residual 33-35 km stub is left for hand-editing.
    """
    g2024 = gpx_track(os.path.join(DL, "onx-markups-2025-04-21.gpx"))
    g2023 = gpx_track(os.path.join(DL, "onx-markups-2025-04-21 2.gpx"))
    d23, _ = dist_bear(g2023[:, 0], g2023[:, 1])
    g2023 = g2023[: int(np.argmax(d23)) + 1]        # keep outbound limb only
    sk = geojson_line(os.path.join(DL, "Sketches.geojson"))
    frames = [
        pd.DataFrame(dict(zip(("lat", "lon"), _orient_outward(g2024).T), src="gpx_2024_near")),
        pd.DataFrame(dict(zip(("lat", "lon"), _orient_outward(sk).T), src="sketch_gap")),
        pd.DataFrame(dict(zip(("lat", "lon"), _orient_outward(g2023).T), src="gpx_2023_far")),
    ]
    return pd.concat(frames, ignore_index=True)


def build_centerline(pts: pd.DataFrame):
    """Use the along-channel-ordered trackpoints directly, with only a light GPS-jitter smooth.

    No radial binning: the boat track already sits on the channel thread, and binning by
    distance-from-anchor would collapse any meander running tangentially to an arc. We keep
    every point in order and apply a short rolling-mean (SMOOTH_PTS) to remove GPS scatter and
    the within-channel weave, leaving the meanders intact.
    """
    out = pts.copy().reset_index(drop=True)
    for c in ("lat", "lon"):
        out[c] = out[c].rolling(SMOOTH_PTS, center=True, min_periods=1).mean()
    out["radius_km"], _ = dist_bear(out["lat"], out["lon"])
    return out


def main():
    pts = load_sources()
    agg = build_centerline(pts)
    line = LineString(np.column_stack([agg["lon"], agg["lat"]]))

    gdf = gpd.GeoDataFrame({"Reach_Name": ["Uyak_Creek"]}, geometry=[line], crs=4326)
    gpkg = os.path.join(OUT, "uyak_centerline_draft.gpkg")       # DRAFT (not the official file)
    gdf.to_file(gpkg, driver="GPKG")
    # Editable copy for hand-touchup of the far end (open in QGIS/geojson.io, adjust, re-save).
    geojson = os.path.join(OUT, "uyak_centerline_draft.geojson")
    gdf.to_file(geojson, driver="GeoJSON")

    # --- verification map: raw tracks (by source) + derived centerline ---
    lat0, lon0 = agg["lat"].mean(), agg["lon"].mean()
    m = folium.Map(location=[lat0, lon0], zoom_start=11, tiles=None, control_scale=True)
    folium.TileLayer("Esri.WorldImagery", name="Satellite", attr="Esri").add_to(m)
    src_col = {"gpx_2024_near": "#ffd000", "sketch_gap": "#00e5ff", "gpx_2023_far": "#ff5cf0"}
    for src, col in src_col.items():
        fg = folium.FeatureGroup(name=f"raw: {src}", show=True)
        sub = pts[pts["src"] == src]
        folium.PolyLine([(r.lat, r.lon) for r in sub.itertuples()],
                        color=col, weight=1.5, opacity=0.6).add_to(fg)
        fg.add_to(m)
    fg_c = folium.FeatureGroup(name="centerline (boat-based)", show=True)
    folium.PolyLine([(r.lat, r.lon) for r in agg.itertuples()],
                    color="#00ff37", weight=3.0, opacity=0.95,
                    tooltip="Uyak centerline (boat GPS, meanders preserved)").add_to(fg_c)
    fg_c.add_to(m)
    folium.Marker(list(ANCHOR), tooltip="Anchor",
                  icon=folium.Icon(color="red", icon="star")).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    html = os.path.join(OUT, "uyak_centerline_check.html")
    m.save(html)

    print(f"{len(pts)} trackpoints -> {len(agg)}-vertex centerline "
          f"(radius {agg['radius_km'].min():.1f}-{agg['radius_km'].max():.1f} km, meanders preserved)")
    print(f"wrote {gpkg}")
    print(f"wrote {geojson}")
    print(f"wrote {html}")


if __name__ == "__main__":
    main()
