"""
Perpendicular transect generation and DEM sampling for the DEM_Transects pipeline.

Given a centerline (projected CRS), this builds cross-section transects perpendicular to
the channel at a fixed along-channel spacing, then samples a DEM raster along each one to
produce tidy cross-section profiles — the programmatic equivalent of the prior ArcGIS
workflow (GeneratePointsAlongLines + AddSurfaceInformation), and the input Gearon's
analysis picks ridge/floodplain elevations from.

Gearon et al. (2025, GRL) used ~200 m node spacing perpendicular to flow on FABDEM; we
default to the same but on the 2 m ArcticDEM.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import Transformer
from shapely.geometry import LineString, Point


def generate_transects(centerline: LineString, crs, spacing: float = 200.0,
                       half_width: float = 1500.0,
                       tangent_delta: float = 5.0) -> gpd.GeoDataFrame:
    """Build perpendicular transects at fixed along-channel spacing.

    Args:
        centerline: LineString in a projected CRS (metres).
        crs: the CRS of `centerline` (e.g. EPSG:32604).
        spacing: along-channel distance between transects (m).
        half_width: transect half-length each side of the centerline (m); full transect
            length is 2*half_width. Make it wide enough to cross the floodplain and reach
            the valley sides.
        tangent_delta: along-line offset (m) used to estimate the local flow direction.

    Returns:
        GeoDataFrame with columns [transect_id, station_m, cx, cy, geometry], where
        station_m is along-channel distance from the centerline start and (cx, cy) is the
        channel-crossing point.
    """
    length = centerline.length
    stations = np.arange(0.0, length + 1e-9, spacing)
    records = []
    for tid, s in enumerate(stations):
        center = centerline.interpolate(s)
        # Local tangent via a small symmetric finite difference along the line.
        p0 = centerline.interpolate(max(0.0, s - tangent_delta))
        p1 = centerline.interpolate(min(length, s + tangent_delta))
        dx, dy = p1.x - p0.x, p1.y - p0.y
        norm = np.hypot(dx, dy)
        if norm == 0:
            continue
        # Unit normal (perpendicular to tangent).
        ux, uy = -dy / norm, dx / norm
        a = (center.x - ux * half_width, center.y - uy * half_width)
        b = (center.x + ux * half_width, center.y + uy * half_width)
        records.append({
            "transect_id": tid,
            "station_m": float(s),
            "cx": center.x, "cy": center.y,
            "geometry": LineString([a, b]),
        })
    return gpd.GeoDataFrame(records, crs=crs)


def sample_dem_along_transects(transects: gpd.GeoDataFrame, raster_path: str,
                               step: float = 10.0, geoid_offset: float = 13.46,
                               nodata_to_nan: bool = True,
                               fill_values: "tuple" = (0.0,)) -> "tuple":
    """Sample a DEM raster at fixed intervals along each transect.

    The transect geometry is in a projected CRS; the raster may be in any CRS (the 2 m
    ArcticDEM is EPSG:3413). Sample points are reprojected to the raster CRS for value
    lookup, so the returned `lon`/`lat` columns are raster-CRS coordinates, not degrees —
    callers that need geographic coordinates must reproject them.

    `cross_dist_m` is signed distance from the channel-crossing centre (negative on one
    bank, positive on the other), which is what cross-section / ridge picking operates on.

    elevation_m = raster_value - geoid_offset, converting ArcticDEM ellipsoidal heights to
    approximate orthometric (EGM2008) heights matching SWOT. The offset is constant here;
    ridge height and slopes are datum-invariant, only absolute WSE comparisons depend on it.

    Returns:
        (DataFrame, n_nodata) where DataFrame has one row per sample point with columns
        [transect_id, station_m, cross_dist_m, elevation_m, lon, lat, raster_value].
    """
    import pandas as pd

    with rasterio.open(raster_path) as src:
        raster_crs = src.crs
        nodata = src.nodata
        to_raster = Transformer.from_crs(transects.crs, raster_crs, always_xy=True)

        frames = []
        for row in transects.itertuples():
            line: LineString = row.geometry
            n = max(2, int(round(line.length / step)) + 1)
            along = np.linspace(0.0, line.length, n)
            pts = [line.interpolate(d) for d in along]
            xs = np.array([p.x for p in pts])
            ys = np.array([p.y for p in pts])
            lon, lat = to_raster.transform(xs, ys)
            vals = np.array([v[0] for v in src.sample(np.column_stack([lon, lat]))],
                            dtype="float64")
            frames.append(pd.DataFrame({
                "transect_id": row.transect_id,
                "station_m": row.station_m,
                "cross_dist_m": along - line.length / 2.0,
                "raster_value": vals,
                "lon": lon, "lat": lat,
            }))

    df = pd.concat(frames, ignore_index=True)
    if nodata is not None and nodata_to_nan:
        df.loc[df["raster_value"] == nodata, "raster_value"] = np.nan
    # This raster carries no nodata flag; GEE exports 0-fill outside DEM coverage, and
    # real ArcticDEM ellipsoidal heights here are >12 m, so 0 is unambiguously fill.
    for fv in fill_values:
        df.loc[df["raster_value"] == fv, "raster_value"] = np.nan
    n_nodata = int(df["raster_value"].isna().sum())
    df["elevation_m"] = df["raster_value"] - geoid_offset
    return df, n_nodata
