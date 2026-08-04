"""
River centerline derivation for the DEM_Transects pipeline.

The centerline is a *pluggable input*: transect generation only needs a shapely
LineString in a projected (metric) CRS. This module provides two ways to get one:

  1. load_centerline(path)        — read a centerline someone else produced
                                     (e.g. a coworker's hand-drawn line, or RivGraph
                                     output) from any OGR-readable file.
  2. polygon_to_centerline(poly)  — derive a TEMPORARY centerline from a river-corridor
                                     polygon by medial-axis skeletonization. Good enough
                                     to exercise the transect machinery until the real
                                     centerline arrives; swap it out by feeding
                                     load_centerline() instead.

All outputs are returned in the supplied projected CRS so downstream distances are in
metres.
"""

from __future__ import annotations

import math

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely.geometry import LineString
from skimage.morphology import skeletonize


def load_centerline(path: str, target_crs) -> gpd.GeoDataFrame:
    """Load a centerline from a file and reproject to `target_crs`.

    Returns a GeoDataFrame of LineString(s). Use this once the coworker's polygons /
    centerline arrive — the rest of the pipeline is identical.
    """
    gdf = gpd.read_file(path)
    line_types = {"LineString", "MultiLineString"}
    if not set(gdf.geom_type).issubset(line_types):
        raise ValueError(f"{path} must contain (Multi)LineString geometry, got "
                         f"{sorted(set(gdf.geom_type))}")
    return gdf.to_crs(target_crs)


def points_to_centerline(lon, lat, dist_km, target_crs, bin_km: float = 0.2,
                         min_pts: int = 20, smooth_window: int = 5,
                         simplify_tolerance: float = 40.0) -> LineString:
    """Derive a channel centerline from a cloud of in-channel points (e.g. SWOT water
    pixels), using distance-from-anchor to order them.

    Points are binned by `dist_km`; the median (lon, lat) of each well-populated bin is
    the channel centre at that distance. Ordering bins by distance yields a path that
    follows the water, which (for these rivers, flowing monotonically away from the
    anchor) is a far better temporary channel centerline than the corridor medial axis.

    Args:
        lon, lat, dist_km: 1-D arrays of equal length (degrees, degrees, km).
        target_crs: projected CRS for the output line (metres).
        bin_km: distance-bin width; 0.2 km matches the default transect spacing.
        min_pts: drop bins with fewer points than this (suppresses noisy tails).
        smooth_window: rolling-median window (in bins) applied to the ordered centre
            coordinates to reduce jitter; set 1 to disable.
        simplify_tolerance: Douglas-Peucker tolerance (m) on the final line.

    Returns:
        shapely LineString in `target_crs`.
    """
    df = pd.DataFrame({"lon": np.asarray(lon), "lat": np.asarray(lat),
                       "dist_km": np.asarray(dist_km)})
    df["bin"] = np.round(df["dist_km"] / bin_km) * bin_km
    grp = df.groupby("bin").agg(lon=("lon", "median"), lat=("lat", "median"),
                                n=("lon", "size")).reset_index()
    grp = grp[grp["n"] >= min_pts].sort_values("bin")
    if len(grp) < 2:
        raise ValueError("Too few populated distance bins to form a centerline; "
                         "lower min_pts or bin_km.")
    if smooth_window > 1:
        grp["lon"] = grp["lon"].rolling(smooth_window, center=True, min_periods=1).median()
        grp["lat"] = grp["lat"].rolling(smooth_window, center=True, min_periods=1).median()

    pts = gpd.GeoSeries(gpd.points_from_xy(grp["lon"], grp["lat"]),
                        crs=4326).to_crs(target_crs)
    line = LineString([(p.x, p.y) for p in pts])
    return line.simplify(simplify_tolerance)


def polygon_to_centerline(poly, pixel_size: float = 20.0,
                          simplify_tolerance: float = 40.0) -> LineString:
    """Derive a temporary centerline from a corridor polygon via skeletonization.

    Rasterizes the polygon to a binary mask, computes its morphological skeleton
    (medial axis), then extracts the longest path through the skeleton graph (its
    "diameter") so side-spurs are discarded and we keep the main stem.

    Args:
        poly: shapely Polygon in a PROJECTED CRS (metres). pixel_size and
              simplify_tolerance are interpreted in those units.
        pixel_size: rasterization cell size in metres. Smaller = finer skeleton but
              slower; 20 m is plenty for a ~km-wide corridor.
        simplify_tolerance: Douglas-Peucker tolerance (m) to smooth the pixel-stepped
              path into a clean line.

    Returns:
        shapely LineString in the same CRS as `poly`.
    """
    minx, miny, maxx, maxy = poly.bounds
    width = max(1, int(math.ceil((maxx - minx) / pixel_size)))
    height = max(1, int(math.ceil((maxy - miny) / pixel_size)))
    transform = from_origin(minx, maxy, pixel_size, pixel_size)

    mask = rasterize([(poly, 1)], out_shape=(height, width), transform=transform,
                     fill=0, dtype="uint8").astype(bool)
    skel = skeletonize(mask)

    coords = set(map(tuple, np.argwhere(skel)))  # {(row, col)}
    if len(coords) < 2:
        raise ValueError("Skeleton too small to form a centerline; reduce pixel_size.")

    # Build an 8-connected graph over skeleton pixels (diagonal weight = sqrt(2)).
    g = nx.Graph()
    for (r, c) in coords:
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nb = (r + dr, c + dc)
                if nb in coords:
                    g.add_edge((r, c), nb, weight=math.hypot(dr, dc))

    # Longest geodesic path (tree diameter) via double Dijkstra on the largest component.
    comp = max(nx.connected_components(g), key=len)
    h = g.subgraph(comp)
    start = next(iter(h))
    far_a = max(nx.single_source_dijkstra_path_length(h, start).items(),
                key=lambda kv: kv[1])[0]
    lengths, paths = nx.single_source_dijkstra(h, far_a)
    far_b = max(lengths.items(), key=lambda kv: kv[1])[0]
    path = paths[far_b]  # ordered list of (row, col) cell indices

    # Cell indices -> projected coordinates at cell centres.
    rows = np.array([r for r, _ in path])
    cols = np.array([c for _, c in path])
    xs = minx + (cols + 0.5) * pixel_size
    ys = maxy - (rows + 0.5) * pixel_size
    line = LineString(np.column_stack([xs, ys]))
    return line.simplify(simplify_tolerance)
