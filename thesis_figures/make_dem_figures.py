#!/usr/bin/env python3
"""DEM writeup figure builder.

Companion to `make_figures.py`. That module renders the SWOT thesis figure series;
this one renders the DEM writeup's own, independently numbered series. The two
documents are separate, so their renders go to separate folders under
`thesis_figures/output/` (`SWOT_Figures/` and `DEM_Figures/`) and a "Figure 1" in
one never collides with the "Figure 1" in the other.

Styling, palette, and the reversed-distance axis convention are imported from
`config.py` / `make_figures.py` so both series look like one thesis.

Usage
-----
    python -m thesis_figures.make_dem_figures --list
    python -m thesis_figures.make_dem_figures 1                 # all D1 variants
    python -m thesis_figures.make_dem_figures 1 --variant C     # one variant
"""

from __future__ import annotations

import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
import numpy as np

from . import config
from .make_figures import _locator_inset, _mercator_scalebar, _north_arrow

SERIES = "DEM_Figures"

# --- Geometry of the arc sampling frame (kept in lockstep with DEM_Transects/build_arc_B.py).
# If those constants change, the figure is wrong, so they are named here explicitly
# rather than silently defaulted.
R_EARTH_KM = 6371.0088
BEAR_MIN, BEAR_MAX = 248.0, 294.0     # bearing sector covering both rivers + margin
ARC_R_MIN, ARC_R_MAX, ARC_R_STEP = 3.0, 34.5, 0.5
GEOID_M = 13.46                       # EGM2008 at the anchor; ellipsoidal -> orthometric

DEM_10M = os.path.join(config.REPO_ROOT, "batch_outputs", "arcticdem_rivers.tif")
ARC_CHANNELS = os.path.join(config.REPO_ROOT, "DEM_Transects", "data", "arcB_channels.parquet")
# Nalaquq (Quinhagak) village map icon, used as the north arrow. The white variant
# reads over dark satellite imagery; the colour variant over pale topography.
NORTH_ICON_LIGHT_BG = os.path.join(config.ASSETS_DIR, "nalaquq_north_color.png")
CENTERLINES = {
    "Kanektok_River": os.path.join(config.REPO_ROOT, "DEM_Transects", "data",
                                   "kanektok_centerline_official.gpkg"),
    "Uyak_Creek": os.path.join(config.REPO_ROOT, "DEM_Transects", "data",
                               "uyak_centerline_official.gpkg"),
}

WEBM = 3857

# Hypsometric ramp for the shaded-relief basemap. Plain "terrain" starts in deep
# blue, which over a near-sea-level coastal plain reads as open water and implies the
# whole floodplain is inundated -- so the blue-water end of the ramp is truncated
# away and the scale runs green -> straw -> brown -> white over land only.
HYPSO = LinearSegmentedColormap.from_list(
    "hypso_land", plt.get_cmap("terrain")(np.linspace(0.25, 1.0, 256)))


# ---------------------------------------------------------------------------
# GEOMETRY HELPERS
# ---------------------------------------------------------------------------
def _dest(lat_deg, lon_deg, dist_km, bearing_deg):
    """Forward spherical geodesic -- identical formulation to build_arc_B.dest()."""
    la1, lo1 = np.radians(lat_deg), np.radians(lon_deg)
    br, dr = np.radians(np.asarray(bearing_deg, float)), np.asarray(dist_km, float) / R_EARTH_KM
    la2 = np.arcsin(np.sin(la1) * np.cos(dr) + np.cos(la1) * np.sin(dr) * np.cos(br))
    lo2 = lo1 + np.arctan2(np.sin(br) * np.sin(dr) * np.cos(la1),
                           np.cos(dr) - np.sin(la1) * np.sin(la2))
    return np.degrees(la2), np.degrees(lo2)


def _arc_latlon(radius_km, n=200):
    """Iso-distance arc at `radius_km` from the anchor, across the bearing sector."""
    br = np.linspace(BEAR_MIN, BEAR_MAX, n)
    return _dest(config.ANCHOR_LAT, config.ANCHOR_LON, radius_km, br)


def _longest(geom):
    return max(geom.geoms, key=lambda s: s.length) if geom.geom_type == "MultiLineString" else geom


def _load_centerlines(crs=WEBM):
    """Field-surveyed centerlines (Kanektok ADCP thalweg run, Uyak boat GPS track),
    reprojected to the map CRS. These are the same lines the arc analysis snaps to."""
    import geopandas as gpd
    out = {}
    for reach, path in CENTERLINES.items():
        g = gpd.read_file(path).to_crs(crs)
        out[reach] = _longest(g.geometry.iloc[0])
    return out


# ---------------------------------------------------------------------------
# TOPOGRAPHIC BASEMAP (the DEM itself, rendered as hillshade + hypsometric tint)
# ---------------------------------------------------------------------------
def _hillshade_rgb(xlim, ylim, vert_exag=25.0, azdeg=315.0, altdeg=42.0,
                   cmap=HYPSO, clip=(0.5, 95.0)):
    """Render the 10 m ArcticDEM strip as a shaded-relief image in Web Mercator.

    Returns (rgb, extent, vmin, vmax, norm). The DEM is reprojected 4326 -> 3857 on
    the fly (bilinear) so it shares the axis CRS with the satellite variants and the
    existing scale-bar / locator helpers. Elevations are converted from the
    ArcticDEM ellipsoidal datum to orthometric by subtracting the EGM2008 geoid, so
    the colour bar reads in the same vertical datum as every DEM profile figure.

    Shading uses matplotlib's LightSource in "soft light" blend, which keeps the
    hypsometric colour readable in the flat coastal plain instead of crushing it to
    grey the way a plain multiply blend does. `vert_exag` is display-only.
    """
    import rasterio
    from rasterio.warp import calculate_default_transform, reproject, Resampling
    from matplotlib.colors import LightSource, Normalize

    with rasterio.open(DEM_10M) as src:
        dst_tf, w_, h_ = calculate_default_transform(
            src.crs, f"EPSG:{WEBM}", src.width, src.height, *src.bounds)
        dst_w, dst_h = int(w_ or 0), int(h_ or 0)
        dst = np.full((dst_h, dst_w), np.nan, dtype="float32")
        reproject(source=rasterio.band(src, 1), destination=dst,
                  src_transform=src.transform, src_crs=src.crs,
                  dst_transform=dst_tf, dst_crs=f"EPSG:{WEBM}",
                  src_nodata=src.nodata, dst_nodata=np.nan,
                  resampling=Resampling.bilinear)

    dst[dst <= -1000] = np.nan
    dst = dst - GEOID_M

    # Crop to the plotted window (+1 px margin) so the colour stretch is set by what
    # the reader actually sees, not by terrain off the edge of the figure.
    west, north = dst_tf.c, dst_tf.f
    px, py = dst_tf.a, -dst_tf.e
    c0 = max(0, int((xlim[0] - west) / px) - 1)
    c1 = min(dst_w, int((xlim[1] - west) / px) + 2)
    r0 = max(0, int((north - ylim[1]) / py) - 1)
    r1 = min(dst_h, int((north - ylim[0]) / py) + 2)
    z = dst[r0:r1, c0:c1]
    extent = (west + c0 * px, west + c1 * px, north - r1 * py, north - r0 * py)

    vmin, vmax = np.nanpercentile(z, clip)
    norm = Normalize(vmin=vmin, vmax=vmax)
    ls = LightSource(azdeg=azdeg, altdeg=altdeg)
    # LightSource cannot handle NaN; shade a filled copy and re-mask afterwards.
    filled = np.where(np.isfinite(z), z, vmin)
    cm = cmap if hasattr(cmap, "__call__") else plt.get_cmap(cmap)
    rgb = ls.shade(filled, cmap=cm, norm=norm, blend_mode="soft",
                   vert_exag=vert_exag, dx=px, dy=py)
    rgb = np.dstack([rgb[..., :3], np.where(np.isfinite(z), 1.0, 0.0)])
    return rgb, extent, vmin, vmax, norm


# ---------------------------------------------------------------------------
# SHARED MAP FURNITURE
# ---------------------------------------------------------------------------
def _draw_arcs(ax, tf, every=4, color="white", lw=0.5, alpha=0.55,
               label_at=(5, 10, 20, 30), label_color="white", halo="black",
               spokes=True):
    """Overlay the iso-distance arc frame: one polyline per sampled radius.

    The arcs ARE the sampling geometry -- every channel, crest, and floodplain value
    in the DEM writeup is measured along one of these. Drawing every 4th (2 km
    spacing) keeps the fan legible; the caption states the true 0.5 km step.

    `halo` is the contrasting outline colour for the arc lines and radius labels;
    it must be the OPPOSITE of `color`/`label_color` (white-on-dark imagery,
    black-on-pale topography), otherwise the labels vanish into their own stroke.
    """
    radii = np.arange(ARC_R_MIN, ARC_R_MAX + 1e-9, ARC_R_STEP)
    stroke = [pe.withStroke(linewidth=lw + 1.1, foreground=halo, alpha=0.45)]
    x0, x1 = sorted(ax.get_xlim())
    y0, y1 = sorted(ax.get_ylim())
    for R in radii[::every]:
        la, lo = _arc_latlon(R)
        x, y = tf.transform(lo, la)
        ax.plot(x, y, color=color, lw=lw, alpha=alpha, zorder=4,
                solid_capstyle="butt", path_effects=stroke)
    if spokes:
        for br in (BEAR_MIN, BEAR_MAX):
            la, lo = _dest(config.ANCHOR_LAT, config.ANCHOR_LON,
                           np.array([0.0, ARC_R_MAX]), br)
            x, y = tf.transform(lo, la)
            ax.plot(x, y, color=color, lw=0.5, alpha=alpha * 0.75, ls=(0, (4, 3)),
                    zorder=4, path_effects=stroke)
    # Radius labels ride the arc's LOWEST point that is still inside the plotted
    # window. Two constraints drive that choice: anchoring to a fixed bearing (the
    # obvious approach) throws the long-radius labels clean off the map, because the
    # sector's northern limb exits the frame well before 30 km; and the southern edge
    # is the only band of the map left free by the top-left legend.
    dy = 0.014 * (y1 - y0)
    for R in label_at:
        la, lo = _arc_latlon(R, n=400)
        x, y = tf.transform(lo, la)
        x, y = np.asarray(x), np.asarray(y)
        inside = (x >= x0) & (x <= x1) & (y >= y0) & (y <= y1)
        if not inside.any():
            continue
        i = np.flatnonzero(inside)[np.argmin(y[inside])]
        low = y[i] < y0 + 0.06 * (y1 - y0)      # label would be clipped by the frame
        ax.text(x[i], y[i] + dy if low else y[i] - dy, f"{R:g} km", fontsize=6.5,
                color=label_color, ha="center", va="bottom" if low else "top",
                zorder=7, path_effects=[pe.withStroke(linewidth=2.0, foreground=halo)])


def _draw_centerlines(ax, lines, lw=1.7, zorder=5, halo="black"):
    fx = [pe.withStroke(linewidth=lw + 1.6, foreground=halo, alpha=0.55)] if halo else None
    for reach, line in lines.items():
        x, y = line.xy
        ax.plot(x, y, color=config.river_color(reach), lw=lw, zorder=zorder,
                solid_capstyle="round", path_effects=fx)


def _draw_markers(ax, tf, snapped=None):
    """Anchor (distance origin), bifurcation, and optionally the DEM-located channel
    positions the arc analysis actually measured at."""
    def mk(lon, lat, **kw):
        mx, my = tf.transform(lon, lat)
        ax.scatter([mx], [my], zorder=8, linewidths=1.0, edgecolor="black", **kw)

    if snapped is not None:
        for reach, (lat, lon) in snapped.items():
            x, y = tf.transform(lon, lat)
            ax.scatter(x, y, s=5.5, marker="o", color=config.river_color(reach),
                       edgecolor="white", linewidths=0.35, zorder=7)
    mk(config.ANCHOR_LON, config.ANCHOR_LAT, marker="o", s=46, color="white")
    mk(config.BIFURCATION_LON, config.BIFURCATION_LAT, marker="*", s=140, color="white")


def _snapped_channel_latlon():
    """Where the DEM located each thalweg, per arc -- read back from the arc analysis
    output and converted from (radius, along-arc distance) to lat/lon so it can be
    plotted on the map. Shows the reader that the arc frame tracks the real channels."""
    import pandas as pd
    if not os.path.exists(ARC_CHANNELS):
        return None
    c = pd.read_parquet(ARC_CHANNELS)
    out = {}
    for reach, col in [("Kanektok_River", "kan_arc_m"), ("Uyak_Creek", "uyak_arc_m")]:
        d = c[["R_km", col]].dropna()
        br = BEAR_MIN + np.degrees(d[col].to_numpy() / (d["R_km"].to_numpy() * 1000.0))
        out[reach] = _dest(config.ANCHOR_LAT, config.ANCHOR_LON, d["R_km"].to_numpy(), br)
    return out


def _degree_ticks(ax, tf, lon_ticks=(-161.9, -161.7, -161.5, -161.3),
                  lat_ticks=(59.75, 59.80, 59.85), labels=True):
    ax.set_xticks([tf.transform(lo, lat_ticks[0])[0] for lo in lon_ticks])
    ax.set_yticks([tf.transform(lon_ticks[0], la)[1] for la in lat_ticks])
    if labels:
        ax.set_xticklabels([f"{abs(lo):.1f}°W" for lo in lon_ticks])
        ax.set_yticklabels([f"{la:.2f}°N" for la in lat_ticks])
    else:
        ax.set_xticklabels([]); ax.set_yticklabels([])
    ax.grid(False)
    ax.tick_params(direction="out", labelsize=7)


def _dem_centre_lonlat():
    """Centre of the plotted window in lon/lat, for the locator inset's point marker.

    Deliberately the centre of the mapped extent rather than the anchor: the anchor
    sits at the reach's eastern end, ~18 km off centre.
    """
    import rasterio
    with rasterio.open(DEM_10M) as src:
        w, s, e, n = src.bounds        # already EPSG:4326
    return (w + e) / 2, (s + n) / 2


def _dem_extent(pad_frac=0.01):
    """Plot window = the 10 m DEM footprint (its own bounding box, which is the
    corridor-polygon bounding box) reprojected to Web Mercator.

    Every variant uses this window, including the satellite-only ones, so that the
    topographic and imagery treatments are pixel-aligned and directly comparable --
    and so the shaded relief fills its axes instead of floating in a white margin.
    """
    import rasterio
    from rasterio.warp import transform_bounds
    with rasterio.open(DEM_10M) as src:
        w, s, e, n = transform_bounds(src.crs, f"EPSG:{WEBM}", *src.bounds)
    dx, dy = (e - w) * pad_frac, (n - s) * pad_frac
    return (w - dx, e + dx), (s - dy, n + dy)


#: Axes margins (figure fractions) used by the map figures. Fixed rather than left to
#: a layout engine, because `_map_layout` has to solve for the figure height that makes
#: an equal-aspect axes exactly fill its slot, and that needs the margins up front.
MAP_MARGINS = dict(left=0.078, right=0.995, top=0.995, bottom=0.052)


def _map_layout(fig, xlim, ylim, rows=1, hspace=0.03):
    """Resize `fig` so equal-aspect map axes fill their slots, then apply the margins.

    An equal-aspect axes cannot be stretched to its subplot slot -- it shrinks to the
    data aspect and centres itself, leaving dead white bands above and below (and, in
    the two-panel case, a wide gap between the panels). Neither `tight_layout` nor
    `constrained_layout` fixes that; they resize the *slot*, not the figure, so the
    band just moves. The fix is to solve for the figure height that makes the slot
    match the map's aspect exactly:

        axes_w = W * (right - left)                    # inches
        axes_h = axes_w * (dy / dx)                    # inches, equal aspect
        fig_h  = (rows + (rows - 1) * hspace) * axes_h / (top - bottom)
    """
    m = MAP_MARGINS
    W = fig.get_size_inches()[0]
    axes_h = W * (m["right"] - m["left"]) * (ylim[1] - ylim[0]) / (xlim[1] - xlim[0])
    fig.set_size_inches(
        W, (rows + (rows - 1) * hspace) * axes_h / (m["top"] - m["bottom"]))
    fig.subplots_adjust(hspace=hspace, **m)


def _load_polys():
    import geopandas as gpd
    polys = gpd.read_file("zip://" + os.path.join(config.REPO_ROOT, "river_poly.zip")).to_crs(WEBM)
    polys["reach"] = polys["Name"].map({"Kanektok": "Kanektok_River", "Uyak": "Uyak_Creek"})
    return polys


# ---------------------------------------------------------------------------
# DEM FIGURE 1 -- Study area, field centerlines, and the arc sampling frame
# ---------------------------------------------------------------------------
def build_dem_fig1(variant: str = "D", zoom: int = 12):
    """DEM Fig 1 -- study area, field centerlines, and the arc sampling frame.

    Four candidate treatments of the same content, so the version can be chosen by eye:

      A  Satellite only. Imagery + field centerlines + arc frame. Minimal; closest to
         the SWOT thesis Figure 1 visual language.
      B  A, plus the two 10 m corridor polygons. Makes the point that the polygon
         analysis integrates a ~1.4-1.7 km wide valley swath, not a channel.
      C  Topographic. The 10 m ArcticDEM itself as hillshade + hypsometric tint with
         an elevation colour bar, so the basemap IS the dataset the writeup measures.
      D  Two panels: (a) satellite context with corridor polygons and the Alaska
         locator, (b) shaded-relief topography with the arc frame and the DEM-located
         thalweg positions. Does both jobs at the cost of vertical space.
    """
    import contextily as cx
    from pyproj import Transformer

    variant = variant.upper()
    if variant not in "ABCD" or len(variant) != 1:
        raise ValueError(f"variant must be one of A, B, C, D (got {variant!r})")

    tf = Transformer.from_crs(4326, WEBM, always_xy=True)
    polys = _load_polys()
    lines = _load_centerlines()
    snapped = _snapped_channel_latlon()
    xlim, ylim = _dem_extent()

    def corridor(ax):
        for reach in ("Kanektok_River", "Uyak_Creek"):
            sub = polys[polys["reach"] == reach]
            color = config.river_color(reach)
            sub.plot(ax=ax, facecolor=color, edgecolor="none", alpha=0.13, zorder=2)
            sub.boundary.plot(ax=ax, edgecolor=color, linewidth=0.9, alpha=0.9, zorder=3)

    def satellite(ax):
        cx.add_basemap(ax, crs=WEBM, source=cx.providers.Esri.WorldImagery,
                       zoom=zoom, attribution=False, zorder=0)

    def topo(ax):
        """Shaded relief + an INSET colour bar.

        The colour bar is drawn inside the map rather than alongside it: an attached
        colour bar steals width from its own axes only, which in the two-panel variant
        would leave the topographic panel narrower than the imagery panel and destroy
        the pixel alignment that makes the two comparable.
        """
        from mpl_toolkits.axes_grid1.inset_locator import inset_axes
        rgb, extent, vmin, vmax, norm = _hillshade_rgb(xlim, ylim)
        ax.imshow(rgb, extent=extent, origin="upper", interpolation="bilinear",
                  zorder=0, aspect="equal")
        cax = inset_axes(ax, width="1.6%", height="52%", loc="lower right",
                         borderpad=1.1)
        sm = plt.cm.ScalarMappable(norm=norm, cmap=HYPSO)
        cb = ax.figure.colorbar(sm, cax=cax, orientation="vertical")
        cb.set_label("Elevation (m)", fontsize=6.5, labelpad=2)
        cb.ax.tick_params(labelsize=6, length=2, pad=1.5)
        cb.ax.yaxis.set_label_position("left")
        cb.ax.yaxis.set_ticks_position("left")
        cb.outline.set_linewidth(0.5)
        for t in cb.ax.get_yticklabels() + [cb.ax.yaxis.label]:
            t.set_path_effects([pe.withStroke(linewidth=1.8, foreground="white")])
        return cb

    legbox = dict(frameon=True, facecolor="white", framealpha=0.90, edgecolor="0.4",
                  fontsize=6.5, borderpad=0.35, labelspacing=0.30, handletextpad=0.5,
                  handlelength=1.6, borderaxespad=0.35)

    def legend(ax, show_corridor, show_snapped, loc="upper left"):
        h = [Line2D([], [], color=config.river_color("Kanektok_River"), lw=1.8),
             Line2D([], [], color=config.river_color("Uyak_Creek"), lw=1.8)]
        lb = ["Kanektok centerline", "Uyak centerline"]
        if show_corridor:
            h += [Patch(facecolor="0.55", alpha=0.35, edgecolor="0.25", linewidth=0.9)]
            lb += ["Corridor polygon"]
        h += [Line2D([], [], color="0.25", lw=0.8)]
        lb += ["Iso-distance arcs"]
        if show_snapped:
            h += [Line2D([], [], marker="o", ls="none", mfc="0.35", mec="white",
                         mew=0.4, ms=4)]
            lb += ["DEM thalweg"]
        h += [Line2D([], [], marker="o", ls="none", mfc="white", mec="black", ms=6),
              Line2D([], [], marker="*", ls="none", mfc="white", mec="black", ms=10)]
        lb += ["Anchor (0 km)", "Bifurcation"]
        ax.legend(h, lb, loc=loc, **legbox)

    # ---------------- single-panel variants ----------------
    if variant in ("A", "B", "C"):
        fig, ax = plt.subplots(figsize=(config.FIG_WIDTH_FULL, 3.0))
        ax.set_xlim(*xlim); ax.set_ylim(*ylim); ax.set_aspect("equal")

        if variant == "C":
            topo(ax)
            # Pale topography: dark ink with a white halo. The inverse (the imagery
            # convention) puts a black stroke around black text and erases it.
            arc_col, halo, bar_col = "0.12", "white", "black"
        else:
            satellite(ax)
            arc_col, halo, bar_col = "white", "black", "white"
        if variant == "B":
            corridor(ax)

        _draw_arcs(ax, tf, color=arc_col, label_color=arc_col, halo=halo,
                   lw=0.5 if variant != "C" else 0.45,
                   alpha=0.6 if variant != "C" else 0.8)
        _draw_centerlines(ax, lines, halo=halo)
        _draw_markers(ax, tf)
        _degree_ticks(ax, tf)
        # Scale bar sits ABOVE the bottom edge: the radius labels occupy that edge, and
        # at y=0.05 the bar's caption lands on top of the "20 km" tick.
        _mercator_scalebar(ax, km=5, center_lat=59.80, loc=(0.40, 0.22),
                           color=bar_col, stroke=halo)
        # The village icon is white line-art: it reads on dark imagery but vanishes
        # into pale topography, so variant C falls back to the drawn arrow instead.
        _north_arrow(ax, loc=(0.030, 0.06), color=bar_col, zoom=0.20, stroke=halo,
                     icon_path=None if variant == "C" else config.NORTH_ICON_PATH)
        legend(ax, show_corridor=(variant == "B"), show_snapped=False)
        if variant != "C":
            _locator_inset(ax, tf, *_dem_centre_lonlat())
        _map_layout(fig, xlim, ylim)
        return fig

    # ---------------- two-panel variant D ----------------
    fig, axes = plt.subplots(2, 1, figsize=(config.FIG_WIDTH_FULL, 6.0),
                             sharex=True, sharey=True)
    axa, axb = axes
    for ax in axes:
        ax.set_xlim(*xlim); ax.set_ylim(*ylim); ax.set_aspect("equal")

    # (a) satellite context + corridor polygons + locator
    satellite(axa)
    corridor(axa)
    _draw_centerlines(axa, lines)
    _draw_markers(axa, tf)
    _degree_ticks(axa, tf)
    _mercator_scalebar(axa, km=5, center_lat=59.80, loc=(0.40, 0.22))
    _north_arrow(axa, loc=(0.030, 0.06), zoom=0.20, icon_path=config.NORTH_ICON_PATH)
    legend(axa, show_corridor=True, show_snapped=False)
    _locator_inset(axa, tf, *_dem_centre_lonlat())

    # (b) shaded-relief topography + arc frame + DEM-located thalweg
    topo(axb)
    _draw_arcs(axb, tf, color="0.12", label_color="0.12", halo="white", lw=0.45,
               alpha=0.8)
    _draw_centerlines(axb, lines, lw=1.2, halo="white")
    _draw_markers(axb, tf, snapped=snapped)
    _degree_ticks(axb, tf)
    h = [Line2D([], [], color="0.25", lw=0.8),
         Line2D([], [], marker="o", ls="none", mfc="0.35", mec="white", mew=0.4, ms=4)]
    axb.legend(h, [f"Iso-distance arcs ({ARC_R_STEP:g} km step)", "DEM-located thalweg"],
               loc="upper left", **legbox)

    # Panel tags sit top-RIGHT: the legends occupy top-left in both panels, and the
    # only feature near the right edge (the anchor) is at mid-height.
    for ax, tag in zip(axes, "ab"):
        ax.annotate(f"({tag})", xy=(0.988, 0.955), xycoords="axes fraction",
                    fontsize=10, fontweight="bold", color="white", ha="right", va="top",
                    path_effects=[pe.withStroke(linewidth=2.6, foreground="black")],
                    zorder=10)
    _map_layout(fig, xlim, ylim, rows=2)
    return fig


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
BUILDERS = {1: build_dem_fig1}
VARIANTS = {1: ("A", "B", "C", "D")}


def main(argv=None):
    p = argparse.ArgumentParser(description="Build DEM writeup figures.")
    p.add_argument("figures", nargs="*", type=int, help="figure numbers (e.g. 1)")
    p.add_argument("--variant", help="single variant to build (e.g. C)")
    p.add_argument("--list", action="store_true", help="list available figures")
    a = p.parse_args(argv)

    if a.list or not a.figures:
        print("DEM writeup figures (output/DEM_Figures/):")
        for n, fn in BUILDERS.items():
            head = (fn.__doc__ or "").strip().splitlines()[0]
            v = "".join(VARIANTS.get(n, ()))
            print(f"  {n}: {head}" + (f"   [variants: {', '.join(v)}]" if v else ""))
        return 0

    config.apply_style()
    for n in a.figures:
        if n not in BUILDERS:
            print(f"  ! no builder for DEM figure {n}", file=sys.stderr)
            continue
        vs = [a.variant] if a.variant else list(VARIANTS.get(n, (None,)))
        for v in vs:
            fig = BUILDERS[n]() if v is None else BUILDERS[n](variant=v)
            name = f"dem_fig{n:02d}" + (f"_{v}" if v else "")
            paths = config.savefig(fig, name, subdir=SERIES)
            plt.close(fig)
            print("  wrote " + ", ".join(os.path.relpath(q, config.REPO_ROOT) for q in paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
