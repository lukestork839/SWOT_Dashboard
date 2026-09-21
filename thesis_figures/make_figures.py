#!/usr/bin/env python3
"""Thesis figure builder.

Generates publication-ready static figures for the Kanektok avulsion-risk thesis,
reusing the validated analysis in `core.py` and the shared styling in `config.py`.

Each figure has a `build_figN(...)` function returning a matplotlib Figure. The CLI
renders one, several, or all figures to `thesis_figures/output/` as PDF + PNG.

Usage
-----
    python -m thesis_figures.make_figures --list
    python -m thesis_figures.make_figures 5          # build Figure 5
    python -m thesis_figures.make_figures 5 6 7      # build several
    python -m thesis_figures.make_figures --all
    python -m thesis_figures.make_figures --smoke    # verify data + core, no plots

All figures (1-8) have in-module builders. Fig 2 (the pipeline flowchart) is a
matplotlib-drawn diagram rather than a data plot, but is generated here too so it
stays consistent with the thesis typography and is regenerable.
"""

from __future__ import annotations

import argparse
import sys

import matplotlib
matplotlib.use("Agg")  # headless render
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
from matplotlib.legend_handler import HandlerTuple
import numpy as np
import pandas as pd

from . import config, core

#: Output sub-folder for this series. The SWOT thesis and the DEM writeup are
#: separate documents with independent numbering, so their renders are kept apart
#: (see make_dem_figures.SERIES).
SERIES = "SWOT_Figures"


# ---------------------------------------------------------------------------
# SHARED PLOT HELPERS (thesis conventions used across figures)
# ---------------------------------------------------------------------------
def reverse_distance_axis(ax):
    """Coast on the left (~70 km), confluence on the right (0 km) -- matches every
    distance-vs-x plot in the dashboard. Call after data is plotted (autoscale set)."""
    lo, hi = ax.get_xlim()
    ax.set_xlim(max(lo, hi), min(lo, hi))


def style_distance_axis(ax, xmax, orientation_labels: bool = True):
    """Apply the shared downriver x-axis convention: reversed (coast/mouth on the
    left ~xmax, confluence 0 km on the right), standard label, and optional
    below-axis flow-orientation cues. Used by every distance-profile figure."""
    ax.set_xlabel("Distance Downriver from Anchor (km)")
    ax.set_xlim(xmax + 1.0, -1.0)
    if orientation_labels:
        ax.annotate("Bering Sea\n(mouth)", xy=(0.0, -0.11), xycoords="axes fraction",
                    fontsize=8, style="italic", color="#666666", ha="left", va="top")
        ax.annotate("Anchor point\n(0 km)", xy=(1.0, -0.11), xycoords="axes fraction",
                    fontsize=8, style="italic", color="#666666", ha="right", va="top")


def add_bifurcation_line(ax, vertical: bool = True):
    """Dashed marker for the bifurcation point (2.493 km from the anchor)."""
    line = ax.axvline if vertical else ax.axhline
    line(config.BIFURCATION_DIST_KM, ls="--", lw=0.9, color=config.BASELINE_COLOR, zorder=1)
    # Label near the top of the axis. Extend leftward (into the plot) so it never
    # clips the right edge -- the bifurcation sits at 2.493 km, close to the 0-km side.
    if vertical:
        ax.annotate("Bifurcation", xy=(config.BIFURCATION_DIST_KM, 1.0),
                    xycoords=("data", "axes fraction"), xytext=(-3, -3),
                    textcoords="offset points", fontsize=8, color=config.BASELINE_COLOR,
                    ha="right", va="top")


class NotImplementedFigure(RuntimeError):
    """Raised by a stubbed figure builder that has not been designed yet."""


def _stub(n: int, title: str, source: str) -> None:
    raise NotImplementedFigure(
        f"Figure {n} ({title}) is not implemented yet.\n"
        f"  Source: {source}\n"
        f"  We will design and build it together, one figure at a time."
    )


# ---------------------------------------------------------------------------
# FIGURE BUILDERS  (implemented one at a time as specs are finalised)
# ---------------------------------------------------------------------------
def _mercator_scalebar(ax, km, center_lat, loc=(0.38, 0.06), color="white",
                       stroke="black", fontsize=11, stroke_lw=1.3,
                       fontweight="bold"):
    """Draw a ground-accurate scale bar on a Web-Mercator (EPSG:3857) axis.

    Web Mercator distances are inflated by 1/cos(lat), so a bar representing
    `km` ground kilometres spans `km*1000/cos(center_lat)` map units. Drawn as a
    single filled bar (white fill + thin black edge, so it reads on dark imagery and
    has no disconnected end ticks) with a lightly haloed bold label centred
    above it. `loc` is the bar's lower-left corner in axes fraction.

    `stroke` is the label's outline colour and must contrast with `color`; on a pale
    basemap (e.g. hypsometric topography) pass color="black", stroke="white", or the
    label is drawn black-on-black and disappears into a blob.

    Label legibility is a halo-to-glyph ratio problem, not a size problem alone. The
    halo is stroked on the glyph outline, so half its width falls *inside* the letter;
    once `stroke_lw` approaches a fifth of `fontsize` it closes the counters of a
    serif "km" and the label reads as a smudge, worst over mid-tone imagery. The
    defaults keep that ratio near 1:8 and carry the weight in the glyph (bold) rather
    than in the outline, which is what survives projection.
    """
    import matplotlib.patheffects as pe
    from matplotlib.patches import Rectangle
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    L = km * 1000.0 / np.cos(np.radians(center_lat))   # map units for `km` on ground
    bx = x0 + loc[0] * (x1 - x0)
    by = y0 + loc[1] * (y1 - y0)
    h = 0.022 * (y1 - y0)
    ax.add_patch(Rectangle((bx, by), L, h, facecolor=color, edgecolor="black",
                           linewidth=1.0, zorder=9))
    ax.text(bx + L / 2, by + h * 1.5, f"{km:g} km", ha="center", va="bottom",
            fontsize=fontsize, color=color, fontweight=fontweight,
            path_effects=[pe.withStroke(linewidth=stroke_lw, foreground=stroke)],
            zorder=9)


def _north_arrow(ax, loc=(0.055, 0.80), color="white", icon_path=None, zoom=0.13,
                 target_px=150, stroke="black"):
    """North arrow (Web Mercator is north-up, so no rotation needed).

    Uses the Nalaquq village map icon (`icon_path`; the graphic already carries the
    "N" + arrowhead) when available, else falls back to a simple drawn arrow so the
    module still renders on machines without the asset. The icon's thin double-line
    design aliases badly if matplotlib downsamples the full 569 px source to a tiny
    on-figure size, so we pre-resize to `target_px` with a high-quality Lanczos filter
    (PIL) first, then embed. `loc` is the icon's bottom-centre in axes fraction.
    """
    import os
    import matplotlib.patheffects as pe
    if icon_path and os.path.exists(icon_path):
        from matplotlib.offsetbox import OffsetImage, AnnotationBbox
        from PIL import Image
        src = Image.open(icon_path).convert("RGBA")
        h = target_px
        w = round(src.width * target_px / src.height)
        img = np.asarray(src.resize((w, h), Image.LANCZOS), dtype=float) / 255.0
        oi = OffsetImage(img, zoom=zoom, interpolation="lanczos")
        ab = AnnotationBbox(oi, loc, xycoords="axes fraction", frameon=False,
                            box_alignment=(0.5, 0.0), zorder=9)
        ax.add_artist(ab)
        return
    fx = [pe.withStroke(linewidth=3, foreground=stroke)]
    ax.annotate("", xy=(loc[0], loc[1] + 0.10), xytext=(loc[0], loc[1]),
                xycoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", color=color, lw=2.2,
                                path_effects=fx))
    ax.annotate("N", xy=(loc[0], loc[1] + 0.115), xycoords="axes fraction",
                ha="center", va="bottom", fontsize=10, fontweight="bold",
                color=color, path_effects=fx)


def _locator_inset(ax, tf, lon, lat, loc="lower right", width="26%", height="36%",
                   webm=3857, view=((-172, 51), (-129, 71))):
    """Alaska locator inset marking the study area as a POINT, not an extent box.

    A locator box is conventionally read as "the exact area of the main map", so it
    has to be drawn at true scale or not at all. Here it cannot be: the main map covers
    37 x 13 km, which at Alaska scale is roughly one percent of the view width -- a
    speck. An earlier version enforced a minimum on-screen box size so it stayed
    visible, which drew a 132 x 168 km rectangle: 13x too tall and 46x too large by
    area, misrepresenting the study footprint as most of the lower Kuskokwim delta.

    A point marker makes no false claim about extent, so that is what is drawn: a dark
    dot with a white ring, sized for legibility rather than for scale. `lon`/`lat` are
    the study-area centre; `view` is the (SW, NE) lon/lat corner pair of the inset.
    """
    from mpl_toolkits.axes_grid1.inset_locator import inset_axes
    import contextily as cx
    axins = inset_axes(ax, width=width, height=height, loc=loc, borderpad=0.5)
    (x0, y0), (x1, y1) = [tf.transform(lo, la) for lo, la in view]
    axins.set_xlim(x0, x1); axins.set_ylim(y0, y1)
    cx.add_basemap(axins, crs=webm, source=cx.providers.Esri.NatGeoWorldMap,
                   zoom=4, attribution=False, zorder=0)
    mx, my = tf.transform(lon, lat)
    axins.scatter([mx], [my], marker="o", s=30, color="black", edgecolor="white",
                  linewidths=1.2, zorder=5)
    axins.set_xticks([]); axins.set_yticks([])
    for s in axins.spines.values():
        s.set(visible=True, edgecolor="0.3", linewidth=0.8)
    return axins


def build_fig0(zoom: int = 11):
    """Fig 0 -- Regional setting: Kuskokwim Bay, Quinhagak, and the two distributaries.

    The wide "where are we" map the committee asked the thesis to open with. It is
    deliberately geographic rather than analytic: no polygons, no node clouds, no arc
    frame -- those belong to the detailed study-area figures that follow. Content is
    limited to what a first-time reader needs to orient: Kuskokwim Bay and the coast,
    the village of Quinhagak (Kuinerraq), the Kanektok mainstem arriving out of the
    Ahklun Mountains, the bifurcation, and the two distributaries (field-surveyed
    centerlines, thesis palette). Rivers are labelled directly on the map instead of
    in a legend so the figure reads at a glance.

    Frame is ~90 x 60 km centred on the lower Kanektok: wide enough that the bay,
    the village, and the mountain front are all *in* the picture (the reviewer
    complaint about Fig 1 was that none of them are), small enough that the two
    distributaries are still distinct lines rather than a smudge. Basemap tiles are
    fetched at build time (needs network).
    """
    import os
    import contextily as cx
    import matplotlib.patheffects as pe
    from pyproj import Transformer

    WEBM = 3857
    tf = Transformer.from_crs(4326, WEBM, always_xy=True)

    # View window (lon/lat corners), chosen so Quinhagak sits lower-left with open
    # bay water west of it, the reach crosses the middle, and the frame's east end
    # reaches the Ahklun Mountains front where the Kanektok leaves its canyon.
    VIEW_W, VIEW_E = -162.30, -160.75
    VIEW_S, VIEW_N = 59.52, 60.06
    x0, y0 = tf.transform(VIEW_W, VIEW_S)
    x1, y1 = tf.transform(VIEW_E, VIEW_N)

    # Quinhagak (Kuinerraq) village site, north bank of the Kanektok mouth (GNIS).
    QUIN_LON, QUIN_LAT = -161.9106, 59.7494

    fig, ax = plt.subplots(
        figsize=(config.FIG_WIDTH_FULL,
                 config.FIG_WIDTH_FULL * (y1 - y0) / (x1 - x0) + 0.3))
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect("equal")
    cx.add_basemap(ax, crs=WEBM, source=cx.providers.Esri.WorldImagery,
                   zoom=zoom, attribution=False, zorder=0)

    # Field-surveyed distributary centerlines (same files the DEM arc analysis snaps
    # to), drawn with a dark halo so they read over both water and tundra.
    # Uyak Creek is drawn at half the Kanektok's line width: a cartographic cue
    # to the size contrast between mainstem and secondary distributary, which is
    # otherwise invisible at this scale. The halo scales with the line so the
    # thinner blue does not disappear inside its own outline.
    import geopandas as gpd
    cl_dir = os.path.join(config.REPO_ROOT, "DEM_Transects", "data")
    for reach, fname, lw in [
            ("Kanektok_River", "kanektok_centerline_official.gpkg", 1.9),
            ("Uyak_Creek", "uyak_centerline_official.gpkg", 0.95)]:
        g = gpd.read_file(os.path.join(cl_dir, fname)).to_crs(WEBM)
        geom = g.geometry.iloc[0]
        line = (max(geom.geoms, key=lambda s: s.length)
                if geom.geom_type == "MultiLineString" else geom)
        lx, ly = line.xy
        ax.plot(lx, ly, color=config.river_color(reach), lw=lw, zorder=5,
                solid_capstyle="round",
                path_effects=[pe.withStroke(linewidth=lw + 1.3,
                                            foreground="black", alpha=0.6)])

    # On-map feature labels. White with a dark stroke reads on imagery everywhere;
    # water/terrain names italic (cartographic convention), settlement name upright.
    def label(lon, lat, text, size=9, style="italic", ha="center", va="center",
              rotation=0):
        mx, my = tf.transform(lon, lat)
        ax.text(mx, my, text, fontsize=size, fontstyle=style, color="white",
                ha=ha, va=va, rotation=rotation, rotation_mode="anchor", zorder=7,
                path_effects=[pe.withStroke(linewidth=2.2, foreground="black")])

    # Bay label rides the open water NORTH of the furniture corner (scale bar +
    # north arrow own the lower left); mountains label sits just clear of the
    # locator inset's top edge, over the range front it names.
    label(-162.17, 59.88, "Kuskokwim\nBay", size=11)
    label(-161.02, 59.745, "Ahklun Mountains", size=10)
    label(-161.62, 59.765, "Kanektok River", rotation=8)
    # Anchored from the text's BOTTOM edge and lifted clear of the channel: the
    # Uyak crest reaches 59.8253 N at this longitude, so a centred label at
    # 59.825 straddled its own river.
    label(-161.70, 59.8290, "Uyak Creek", rotation=8, va="bottom")

    # Quinhagak: village marker + name (Yup'ik name per the community's usage).
    qx, qy = tf.transform(QUIN_LON, QUIN_LAT)
    ax.scatter([qx], [qy], marker="s", s=42, color="white", edgecolor="black",
               linewidths=1.0, zorder=8)
    label(QUIN_LON + 0.015, QUIN_LAT - 0.012, "Quinhagak (Kuinerraq)",
          size=9, style="normal", ha="left", va="top")

    # Bifurcation: the single most important point on the map -- star + direct label.
    bx, by = tf.transform(config.BIFURCATION_LON, config.BIFURCATION_LAT)
    ax.scatter([bx], [by], marker="*", s=150, color="white", edgecolor="black",
               linewidths=1.0, zorder=8)
    label(config.BIFURCATION_LON + 0.012, config.BIFURCATION_LAT + 0.016,
          "bifurcation", size=8.5, style="normal", ha="left", va="bottom")

    # Degree ticks on the frame (axis units are Web-Mercator metres).
    lon_ticks = [-162.2, -161.8, -161.4, -161.0]
    lat_ticks = [59.6, 59.8, 60.0]
    ax.set_xticks([tf.transform(lo, lat_ticks[0])[0] for lo in lon_ticks])
    ax.set_xticklabels([f"{abs(lo):.1f}°W" for lo in lon_ticks])
    ax.set_yticks([tf.transform(lon_ticks[0], la)[1] for la in lat_ticks])
    ax.set_yticklabels([f"{la:.1f}°N" for la in lat_ticks])
    ax.grid(False)
    ax.tick_params(direction="out")

    # Furniture over the open bay water (lower left): scale bar with the north arrow
    # above it. Alaska locator lower right, study area marked as a point (see
    # _locator_inset for why a point and not an extent box).
    _mercator_scalebar(ax, km=20, center_lat=59.79, loc=(0.045, 0.055))
    _north_arrow(ax, loc=(0.062, 0.115), zoom=0.20,
                 icon_path=config.NORTH_ICON_PATH)
    _locator_inset(ax, tf, (VIEW_W + VIEW_E) / 2, (VIEW_S + VIEW_N) / 2,
                   width="24%", height="30%")
    return fig


def build_fig1(zoom: int = 12, n_points: int = 90000, pad_frac: float = 0.06):
    """Fig 1 -- Study Area & Spatial Normalization Map (Methodology 4.1).

    Satellite (Esri World Imagery) study-area map of the Kanektok River and Uyak
    Creek near Quinhagak, Alaska, built entirely in matplotlib so it is uniform with
    the other figures (serif type, exact firebrick/dodgerblue palette, 300 DPI vector)
    rather than a Folium screenshot. Overlays, per river: the analysis polygon
    (`river_poly.zip`, mid-low opacity fill + coloured edge) and a downsampled cloud
    of SWOT nodes at low alpha, so denser (better-sampled) reaches read darker.
    Markers: the anchor / distance origin (0 km), the channel bifurcation (~2.5 km
    downriver of the anchor), and the 15 km virtual-gauge stage-reference points used
    in Fig 3. Cartographic furniture: lat/lon edge labels, a ground-accurate scale
    bar, a north arrow, and an Alaska locator inset. Basemap tiles are fetched at
    build time (needs network).
    """
    import geopandas as gpd
    import contextily as cx
    from pyproj import Transformer
    from mpl_toolkits.axes_grid1.inset_locator import inset_axes

    WEBM = 3857
    tf = Transformer.from_crs(4326, WEBM, always_xy=True)

    # Polygon -> map CRS. The shapefile's Name field is "Kanektok"/"Uyak"; map those
    # to the canonical reach keys so colours/labels match every other figure.
    polys = gpd.read_file("zip://river_poly.zip").to_crs(WEBM)
    name_to_reach = {"Kanektok": "Kanektok_River", "Uyak": "Uyak_Creek"}
    polys["reach"] = polys["Name"].map(name_to_reach)

    # Study extent from the polygons. Symmetric side/bottom padding, but extra room
    # up top (north) so the legend sits in open tundra ABOVE the channels instead of
    # overlapping them.
    minx, miny, maxx, maxy = polys.total_bounds
    spanx, spany = maxx - minx, maxy - miny
    dx = spanx * pad_frac
    xlim = (minx - dx, maxx + dx)
    ylim = (miny - spany * pad_frac, maxy + spany * 0.42)

    # SWOT nodes, downsampled per river (seeded) so low-alpha overplot shows density
    # without rendering millions of points. Coordinates transformed 4326 -> 3857.
    con = core.connect()
    pts = core.load_swot(con, reaches=list(config.COLOR_MAP), open_water_only=True)
    rng = np.random.default_rng(42)

    fig, ax = plt.subplots(figsize=(config.FIG_WIDTH_FULL, config.FIG_WIDTH_FULL / 2.6))
    ax.set_xlim(*xlim); ax.set_ylim(*ylim)
    ax.set_aspect("equal")

    plot_order = sorted(config.COLOR_MAP, key=lambda r: r == "Uyak_Creek")
    for reach in plot_order:
        color = config.river_color(reach)
        # Analysis polygon: mid-low fill + coloured edge.
        sub = polys[polys["reach"] == reach]
        # Very light fill just delineates the analysis extent; the SWOT node cloud
        # (below) carries the colour, so denser sampling reads as a darker channel.
        sub.plot(ax=ax, facecolor=color, edgecolor="none", alpha=0.05, zorder=3)
        sub.boundary.plot(ax=ax, edgecolor=color, linewidth=1.3, zorder=3)
        # SWOT node cloud (downsampled), low alpha => density shows through.
        d = pts[pts["Reach_Name"] == reach]
        if len(d) > n_points:
            d = d.iloc[rng.choice(len(d), n_points, replace=False)]
        px, py = tf.transform(d["longitude"].to_numpy(), d["latitude"].to_numpy())
        ax.scatter(px, py, s=1.8, color=color, alpha=0.09, edgecolor="none",
                   rasterized=True, zorder=4)

    # Reference markers (transform lon/lat -> map CRS). Shapes chosen to read on dark
    # imagery: white circle = anchor, yellow star = bifurcation, white triangles =
    # the two 15 km stage-reference points (one per river; see Fig 3).
    def _mk(lon, lat, **kw):
        mx, my = tf.transform(lon, lat)
        ax.scatter([mx], [my], zorder=6,
                   linewidths=1.1, edgecolor="black", **kw)

    _mk(config.ANCHOR_LON, config.ANCHOR_LAT, marker="o", s=45, color="white")
    _mk(config.BIFURCATION_LON, config.BIFURCATION_LAT, marker="*", s=130, color="white")
    for lon, lat in [(-161.59942627, 59.80504608), (-161.60218811, 59.82960510)]:
        _mk(lon, lat, marker="v", s=32, color="white")

    # Satellite basemap underneath everything (zorder 0). Attribution in the caption.
    cx.add_basemap(ax, crs=WEBM, source=cx.providers.Esri.WorldImagery,
                   zoom=zoom, attribution=False, zorder=0)

    # --- lat/lon edge labels (axis is in metres; convert nice degree ticks) --------
    lon_ticks = [-161.9, -161.7, -161.5, -161.3]
    lat_ticks = [59.75, 59.80, 59.85]
    ax.set_xticks([tf.transform(lo, lat_ticks[0])[0] for lo in lon_ticks])
    ax.set_xticklabels([f"{abs(lo):.1f}°W" for lo in lon_ticks])
    ax.set_yticks([tf.transform(lon_ticks[0], la)[1] for la in lat_ticks])
    ax.set_yticklabels([f"{la:.2f}°N" for la in lat_ticks])
    ax.grid(False)
    ax.tick_params(direction="out")

    # --- cartographic furniture ----------------------------------------------------
    _mercator_scalebar(ax, km=5, center_lat=59.80, loc=(0.38, 0.06))
    # North arrow in the lower-left corner (kept clear of channels and legend),
    # same Nalaquq icon treatment as Fig 0 so the exported render is self-contained.
    _north_arrow(ax, loc=(0.062, 0.075), zoom=0.20,
                 icon_path=config.NORTH_ICON_PATH)

    # --- legend (white box, legible over imagery) ----------------------------------
    handles = [
        Patch(facecolor=config.river_color("Kanektok_River"), alpha=0.30,
              edgecolor=config.river_color("Kanektok_River"), linewidth=1.3),
        Patch(facecolor=config.river_color("Uyak_Creek"), alpha=0.30,
              edgecolor=config.river_color("Uyak_Creek"), linewidth=1.3),
        Line2D([], [], marker="o", ls="none", mfc="white", mec="black", ms=6),
        Line2D([], [], marker="*", ls="none", mfc="white", mec="black", ms=10),
        Line2D([], [], marker="v", ls="none", mfc="white", mec="black", ms=6),
    ]
    labels = ["Kanektok River", "Uyak Creek", "Anchor (0 km)",
              "Bifurcation", "15 km stage reference"]
    ax.legend(handles, labels, loc="upper left", frameon=True, facecolor="white",
              framealpha=0.92, edgecolor="0.4", fontsize=7, borderpad=0.4,
              labelspacing=0.35, handletextpad=0.5)

    # --- Alaska locator inset (lower right, over open tundra) -----------------------
    # NOTE: placed lower-right, NOT upper-right -- the reach's eastern end (anchor +
    # bifurcation) sits top-right, and an inset there would hide the key channel split.
    # The study area is marked with a point, not an extent box; see _locator_inset().
    # Point = centre of the analysis extent, not the anchor: the anchor sits at the
    # reach's eastern end, ~18 km off centre.
    w, s, e, n = polys.to_crs(4326).total_bounds
    _locator_inset(ax, tf, (w + e) / 2, (s + n) / 2)

    return fig


def build_fig2():
    """Fig 2 -- SWOT ingestion & processing pipeline (Methodology 4.2).

    Flowchart of the custom Python pipeline (SWOT_Pull.py), drawn in matplotlib (no
    external diagramming tool) so it shares the thesis typography and is regenerable.
    It plots no data, so it is unaffected by data refreshes. Flow, top to bottom:
      source (NASA PIXC) -> per-pass processing [ingest & open pixel_cloud, spatial
      subset to the two channel polygons, geophysical WSE correction, Haversine
      distance mapping, and the four ordered quality-control gates] -> daily-CSV
      provenance checkpoint -> master aggregation with the documented known-bad-pass
      exclusion -> the two data products (master parquet + per-pass reference
      gradient) that feed the dashboard, the temporal analysis, and the thesis
      figures. Category colours encode pipeline STAGE (not river), deliberately
      distinct from the firebrick/dodgerblue river palette used elsewhere.
    """
    from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

    # Stage palette: soft fills + darker edges. Kept clearly apart from the
    # firebrick/dodgerblue river palette -- here colour means pipeline stage.
    C_SRC = ("#D9E1F2", "#2F5597")    # source
    C_STEP = ("#FFFFFF", "#333333")   # per-pass processing step
    C_QC = ("#FCE4D6", "#C55A11")     # quality-control gate
    C_CHK = ("#FFF2CC", "#BF9000")    # daily-CSV checkpoint (provenance)
    C_AGG = ("#E7E6F5", "#5B4FA0")    # aggregation
    C_PROD = ("#E2EFDA", "#548235")   # data product
    C_DOWN = ("#EDEDED", "#595959")   # downstream consumer
    C_CONT = "#F7F8FA"                # per-pass container fill
    C_QCONT = "#FBEEE6"               # QC sub-container fill
    ARROW = "#555555"
    REFARROW = "#7A9A5B"              # reference-gradient data-flow arrows

    fig, ax = plt.subplots(figsize=(config.FIG_WIDTH_FULL, 9.6))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    def box(cx, cy, w, h, text, fc, ec, *, fs=6.9, weight="normal",
            tc="#111111", z=3):
        ax.add_patch(FancyBboxPatch(
            (cx - w / 2, cy - h / 2), w, h,
            boxstyle="round,pad=0,rounding_size=0.7",
            linewidth=1.1, edgecolor=ec, facecolor=fc, zorder=z))
        ax.text(cx, cy, text, ha="center", va="center", fontsize=fs,
                color=tc, weight=weight, zorder=z + 1, linespacing=1.35)
        return {"top": (cx, cy + h / 2), "bot": (cx, cy - h / 2),
                "lft": (cx - w / 2, cy), "rgt": (cx + w / 2, cy)}

    def arrow(p0, p1, rad=0.0, color=ARROW, lw=1.3):
        ax.add_patch(FancyArrowPatch(
            p0, p1, arrowstyle="-|>", mutation_scale=13, lw=lw, color=color,
            connectionstyle=f"arc3,rad={rad}", shrinkA=2, shrinkB=2, zorder=2.5))

    # --- containers (behind everything) ---------------------------------------
    ax.add_patch(FancyBboxPatch((2, 42), 96, 49.5,
                 boxstyle="round,pad=0,rounding_size=1.0", linewidth=1.0,
                 edgecolor="#C4CAD3", facecolor=C_CONT, zorder=0.5))
    ax.text(4, 89.6, "Per-pass processing",
            ha="left", va="center", fontsize=8.5, weight="bold", color="#5A6373",
            zorder=1.0)
    ax.add_patch(FancyBboxPatch((6, 43.5), 88, 13.5,
                 boxstyle="round,pad=0,rounding_size=0.8", linewidth=1.0,
                 edgecolor=C_QC[1], facecolor=C_QCONT, zorder=1.2))
    ax.text(8, 55.5, "Quality-control filters",
            ha="left", va="center", fontsize=7.6, style="italic",
            color=C_QC[1], zorder=1.6)

    # --- nodes ----------------------------------------------------------------
    # Boxes carry short titles only; the mechanics live in the Methods text.
    src = box(50, 96, 54, 5.4, "SWOT satellite data",
              *C_SRC, fs=10, weight="bold", tc="#20375E")

    ingest = box(50, 86, 50, 5.4, "Data ingest", *C_STEP, fs=9.5, weight="bold")
    subset = box(50, 78.3, 50, 5.4, "Spatial subset", *C_STEP, fs=9.5, weight="bold")
    wse = box(50, 70.6, 50, 5.4, "Elevation correction", *C_STEP, fs=9.5, weight="bold")
    dist = box(50, 62.9, 50, 5.4, "Distance mapping", *C_STEP, fs=9.5, weight="bold")

    qc_y, qc_w, qc_h = 49.0, 19.0, 6.0
    qc_cx = [17.0, 39.0, 61.0, 83.0]
    qc = [
        box(qc_cx[0], qc_y, qc_w, qc_h, "Cross-track\nfilter", *C_QC, fs=8.5, weight="bold"),
        box(qc_cx[1], qc_y, qc_w, qc_h, "Calibration\nfilter", *C_QC, fs=8.5, weight="bold"),
        box(qc_cx[2], qc_y, qc_w, qc_h, "Classification\nfilter", *C_QC, fs=8.5, weight="bold"),
        box(qc_cx[3], qc_y, qc_w, qc_h, "Outlier\nfilter", *C_QC, fs=8.5, weight="bold"),
    ]

    chk = box(50, 37, 54, 5.4, "Daily checkpoint", *C_CHK, fs=9.5, weight="bold")

    agg = box(50, 27.8, 54, 5.4, "Aggregation", *C_AGG, fs=9.5, weight="bold", tc="#2E2760")

    prod_m = box(27, 18.3, 40, 5.4, "Master dataset",
                 *C_PROD, fs=9.5, weight="bold", tc="#33501F")
    prod_r = box(73, 18.3, 40, 5.4, "Reference gradient",
                 *C_PROD, fs=9.5, weight="bold", tc="#33501F")

    d_temporal = box(18, 5.6, 28, 5.4, "Temporal analysis", *C_DOWN, fs=8.6, weight="bold")
    d_dash = box(50, 5.6, 28, 5.4, "Interactive dashboard", *C_DOWN, fs=8.6, weight="bold")
    d_figs = box(82, 5.6, 28, 5.4, "Thesis figures", *C_DOWN, fs=8.6, weight="bold")

    # --- arrows ---------------------------------------------------------------
    arrow(src["bot"], ingest["top"])
    arrow(ingest["bot"], subset["top"])
    arrow(subset["bot"], wse["top"])
    arrow(wse["bot"], dist["top"])
    arrow(dist["bot"], (50, 57.0))                     # into the QC container
    for a, b in zip(qc[:-1], qc[1:]):
        arrow(a["rgt"], b["lft"])                      # filter order, left → right
    arrow((50, 43.5), chk["top"])                      # QC container out → checkpoint
    arrow(chk["bot"], agg["top"])
    arrow(agg["bot"], prod_m["top"], rad=0.12)
    arrow(agg["bot"], prod_r["top"], rad=-0.12)
    # master feeds all three consumers; reference gradient feeds dashboard + figures
    arrow(prod_m["bot"], d_temporal["top"], rad=0.10)
    arrow(prod_m["bot"], d_dash["top"], rad=0.0)
    arrow(prod_m["bot"], d_figs["top"], rad=-0.16)
    arrow(prod_r["bot"], d_dash["top"], rad=0.16, color=REFARROW)
    arrow(prod_r["bot"], d_figs["top"], rad=-0.10, color=REFARROW)

    return fig


def _fig3_time_series(m, typhoon, col, ylabel, legend_loc, legend_ncol=2):
    """One standalone time-series figure of the temporal-stability record."""
    order = sorted(config.COLOR_MAP, key=lambda r: r == "Uyak_Creek")
    fig, ax = plt.subplots(figsize=(config.FIG_WIDTH_FULL, 3.1),
                           constrained_layout=True)
    # winter (Dec-Mar) shading -- no gated open-water data there.
    for y0 in (2023, 2024, 2025):
        ax.axvspan(pd.Timestamp(f"{y0}-12-01"), pd.Timestamp(f"{y0+1}-03-31"),
                   color="lightsteelblue", alpha=0.25, lw=0, zorder=0)
    ax.axvline(pd.Timestamp(typhoon), color="black", ls="--", lw=1.2, zorder=1)
    ax.annotate("Typhoon Halong", xy=(pd.Timestamp(typhoon), 1.0),
                xycoords=("data", "axes fraction"), xytext=(3, -3),
                textcoords="offset points", fontsize=8, color="black",
                ha="left", va="top")
    for reach in order:
        d = m[m["reach"] == reach].sort_values("date")
        ax.plot(d["date"].to_numpy(), d[col].to_numpy(), linestyle="none",
                marker="o", ms=4, color=config.river_color(reach), alpha=0.75,
                label=config.river_label(reach), zorder=3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_xlim(m["date"].min() - pd.Timedelta(days=40),
                m["date"].max() + pd.Timedelta(days=40))
    ax.set_xlabel("Date")
    ax.set_ylabel(ylabel)
    ax.legend(loc=legend_loc, ncol=legend_ncol)
    return fig


def build_fig3():
    """Fig 3a/3b/3c -- Temporal Stability & Stage-Invariance (Results 5.1).

    Three standalone figures (thesis Figures 16-18) from the one-time temporal
    analysis (temporal_results/), split so each can sit beside the text that
    discusses it:
      3a: WSE at the fixed 15 km reference (stage proxy) vs date,
      3b: robust per-pass hydraulic gradient vs date,
    both with winter (Dec-Mar, no open-water data) shaded and Typhoon Halong
    landfall marked; and
      3c: gradient vs stage, demonstrating stage-invariance (flat bands justify
    pooling passes across seasons/years).
    QC-excluded passes (config.EXCLUDED_PASSES) are dropped.
    Source: temporal_metrics_per_pass.parquet + temporal_analysis_results.json.
    """
    m = core.load_temporal_metrics()
    results = core.load_temporal_results()
    typhoon = results["method"]["typhoon_date"]
    order = sorted(config.COLOR_MAP, key=lambda r: r == "Uyak_Creek")

    # Legend spots chosen around the data: 3a top-centre (clear sky between the
    # 2023 outliers at left and the typhoon label at right), 3b centre-right
    # (the 197-210 cm/km band is empty away from the early-2023 outliers).
    fig_a = _fig3_time_series(m, typhoon, "wse_ref_m", "WSE at 15 km (m)",
                              "upper center")
    fig_b = _fig3_time_series(m, typhoon, "slope_cm_km",
                              "Hydraulic Gradient (cm/km)", "center right",
                              legend_ncol=1)

    # 3c: stage-invariance -- gradient vs stage, with per-river median lines.
    fig_c, ax_c = plt.subplots(figsize=(config.FIG_WIDTH_FULL, 3.4),
                               constrained_layout=True)
    for reach in order:
        d = m[m["reach"] == reach]
        color = config.river_color(reach)
        ax_c.plot(d["wse_ref_m"].to_numpy(), d["slope_cm_km"].to_numpy(),
                  linestyle="none", marker="o", ms=5, color=color, alpha=0.55,
                  label=config.river_label(reach), zorder=3)
        ax_c.axhline(float(d["slope_cm_km"].median()), color=color, ls=":",
                     lw=1.2, alpha=0.8, zorder=2)
    ax_c.set_xlabel("Water Surface Elevation at 15 km (m)  —  stage proxy")
    ax_c.set_ylabel("Hydraulic Gradient (cm/km)")
    ax_c.legend(loc="upper right", ncol=1)

    return [("a", fig_a), ("b", fig_b), ("c", fig_c)]


def build_fig4():
    """Fig 4 -- Reference Hydraulic Gradient Distribution (Results 5.2).

    Distribution of per-pass robust (Theil-Sen) reach gradients over the gated,
    full-coverage open-water passes. Each dot is one pass; a bold median line and a
    shaded IQR band summarise each river (the dashboard's representation -- a box
    plot collapses because Kanektok's IQR is ~1 cm/km). The y-axis is zoomed to the
    informative range so the tight Kanektok cluster and the small median offset are
    legible; a note reports any high-gradient passes beyond the axis.
    Source: reference_gradient_per_pass.parquet.
    """
    ref = core.load_reference_gradient()
    ow = ref[(ref["open_water"]) & (ref["gated"])].copy()
    ow["abs"] = ow["theilsen_cm_km"].abs()

    order = sorted(config.COLOR_MAP, key=lambda r: r == "Uyak_Creek")
    rng = np.random.default_rng(42)   # reproducible jitter

    fig, ax = plt.subplots(figsize=(config.FIG_WIDTH_HALF * 1.7, config.FIG_HEIGHT_DEFAULT))
    ax.grid(True, axis="y"); ax.grid(False, axis="x")   # categorical x: no vertical grid

    q25s, q75s = [], []
    for xi, reach in enumerate(order):
        vals = ow[ow["Reach_Name"] == reach]["abs"].to_numpy()
        if len(vals) == 0:
            continue
        color = config.river_color(reach)
        q25, med, q75 = np.percentile(vals, [25, 50, 75])
        q25s.append(q25); q75s.append(q75)
        # IQR band, median line, jittered passes.
        ax.fill_between([xi - 0.30, xi + 0.30], [q25, q25], [q75, q75],
                        color=color, alpha=0.20, linewidth=0, zorder=2)
        ax.plot([xi - 0.36, xi + 0.36], [med, med], color=color, lw=3, zorder=5)
        ax.scatter(xi + rng.uniform(-0.16, 0.16, len(vals)), vals, s=14,
                   color=color, alpha=0.5, edgecolor="none", zorder=3)
        # Median value labels on the OUTER side of each column (Kanektok left,
        # Uyak right), in the widened side margins so nothing clips.
        if xi == 0:                      # left column -> left margin
            lx, lha = xi - 0.42, "right"
        else:                            # right column -> right margin
            lx, lha = xi + 0.42, "left"
        ax.annotate(f"median\n{med:.1f} cm/km", xy=(lx, med),
                    fontsize=8.5, color=color, fontweight="bold",
                    ha=lha, va="center")

    # Zoom y to the clusters; report any passes beyond the axis.
    ymin = min(q25s) - 5.0
    ymax = max(q75s) + 6.0
    ax.set_ylim(ymin, ymax)
    off = int(((ow["abs"] > ymax) | (ow["abs"] < ymin)).sum())
    if off:
        hi = ow["abs"].max()
        ax.annotate(f"{off} pass(es) beyond axis (up to {hi:.0f} cm/km)",
                    xy=(0.5, 0.985), xycoords="axes fraction", fontsize=7.5,
                    style="italic", color="#666666", ha="center", va="top")

    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([config.river_label(r) for r in order])
    ax.set_xlim(-0.95, len(order) - 0.05)   # wide side margins for the outer labels
    ax.set_ylabel("Reference Hydraulic Gradient (cm/km)")

    # Neutral legend explaining the encoding (rivers are identified by the x-axis).
    handles = [Line2D([], [], color="0.35", lw=3),
               Patch(facecolor="0.5", alpha=0.30, linewidth=0),
               Line2D([], [], color="0.4", marker="o", ls="none", ms=5, alpha=0.6)]
    ax.legend(handles, ["Median", "IQR (25–75%)", "One gated pass"],
              loc="upper right", fontsize=8)
    fig.tight_layout()
    return fig


def build_fig5(node_km: float = 0.5, band=(5, 95), band_alpha: float = 0.30,
               show_points: bool = False):
    """Fig 5 -- Absolute Spatial Gradient Profile (Results 5.3).

    CONTEXT figure: median WSE profile per river with a shaded percentile band
    showing the spread across all open-water passes (123: Kanektok 123, Uyak 115). This is the canonical
    line+ribbon treatment for dense, heavily-overlapping distributions (Wilke,
    Fundamentals of Data Visualization, ch. 18) and the SWOT convention of
    aggregating repeat passes by median. It shows the concave-up longitudinal shape
    and the near-coincidence of the two rivers -- the fine (~1-2 m) sub-elevation
    signal is only resolvable in the difference/detrended figures (Figs 6, 7), so it
    is deliberately NOT forced onto this 68 m absolute axis. No linear cm/km slope is
    drawn (the characteristic gradient is the Theil-Sen value in Fig 4).

    Args:
        node_km:     distance-bin width for the median/percentile profile.
        band:        (lo, hi) percentiles for the shaded spread band; None to omit.
        show_points: overlay an ultra-faint raw-return cloud (off by default).
    """
    con = core.connect()
    df = core.load_swot(con, reaches=list(config.COLOR_MAP), open_water_only=True)

    fig, ax = plt.subplots(figsize=(config.FIG_WIDTH_FULL, config.FIG_HEIGHT_DEFAULT))

    # Kanektok first, Uyak layered on top (matches dashboard draw order).
    plot_order = sorted(config.COLOR_MAP, key=lambda r: r == "Uyak_Creek")

    # Optional ultra-faint raw cloud (kept off: the band already conveys spread).
    if show_points:
        for reach in plot_order:
            d = df[df["Reach_Name"] == reach]
            if len(d) == 0:
                continue
            ax.plot(d["dist_km"].to_numpy(), d["wse"].to_numpy(),
                    linestyle="none", marker="o", markersize=1.2,
                    markerfacecolor=config.river_color(reach), markeredgecolor="none",
                    alpha=0.06, rasterized=True, zorder=2)

    # Percentile band + median profile line per river. Build composite legend
    # handles (colored band patch + line) so the legend shows each river's OWN
    # band colour, not a generic grey swatch.
    legend_handles, legend_labels = [], []
    for reach in plot_order:
        d = df[df["Reach_Name"] == reach]
        if len(d) == 0:
            continue
        color = config.river_color(reach)
        # core.round_half_away: same tie convention as the SQL binning paths
        # (pandas .round is banker's and disagreed on exact-boundary points).
        node = core.round_half_away(d["dist_km"].to_numpy() / node_km) * node_km
        grp = d.assign(node=node).groupby("node")["wse"]
        med = grp.median().sort_index()
        if band is not None:
            q_lo = grp.quantile(band[0] / 100.0).sort_index()
            q_hi = grp.quantile(band[1] / 100.0).sort_index()
            ax.fill_between(med.index.to_numpy(), q_lo.to_numpy(), q_hi.to_numpy(),
                            color=color, alpha=band_alpha, linewidth=0, zorder=3)
        ax.plot(med.index.to_numpy(), med.to_numpy(),
                color=color, lw=2.2, alpha=1.0, solid_capstyle="round", zorder=4)
        band_patch = Patch(facecolor=color, alpha=band_alpha, linewidth=0)
        median_line = Line2D([], [], color=color, lw=2.2)
        # Order (line, band) to match the legend title "Median line & ... band".
        legend_handles.append((median_line, band_patch) if band is not None else median_line)
        legend_labels.append(config.river_label(reach))

    add_bifurcation_line(ax)

    # Datum (EGM2008 orthometric) is stated in the caption, not the axis, so the
    # rotated label fits the 4-in axis height without clipping.
    ax.set_ylabel("Water Surface Elevation (m)")
    style_distance_axis(ax, float(df["dist_km"].max()))
    # Clip y to the bulk so a few faint filtered strays don't waste vertical space.
    ylo, yhi = np.nanpercentile(df["wse"].to_numpy(), [0.5, 99.9])
    pad = 0.04 * (yhi - ylo)
    ax.set_ylim(ylo - pad, yhi + pad)

    # Legend: each river = its coloured band + median line (composite handle). The
    # band's meaning (percentile range) is stated in the legend title and caption.
    title = f"Median line & {band[0]}–{band[1]}% band" if band is not None else None
    ax.legend(legend_handles, legend_labels, loc="upper left", title=title,
              handler_map={tuple: HandlerTuple(ndivide=None)})
    fig.tight_layout()
    return fig


def build_fig6(bin_km: float = 0.1, band=(25, 75)):
    """Fig 6 -- Localized Elevation Difference (Results 5.3).

    Per-pass Kanektok-minus-Uyak WSE difference in `bin_km` bins (see
    core.elevation_difference): median across passes as a bold line, a shaded
    consistency band (across-pass IQR), and sign shading between the line and the
    zero-line (red = Kanektok higher/superelevated; blue = Uyak higher/sub-elevated,
    matching the river palette). The prominent dashed zero-line marks equal
    water-surface elevation between the two channels. Max-deficit annotation is
    computed live from the data (auto-updates when the polygon-cleaned data lands).
    Source: Elevation Difference tab (per-pass median instead of pooled AVG).
    """
    con = core.connect()
    d = core.elevation_difference(con, open_water_only=True, bin_km=bin_km, band=band)
    x = d["dist_bin"].to_numpy()
    y = d["diff"].to_numpy()
    k_color = config.river_color("Kanektok_River")
    u_color = config.river_color("Uyak_Creek")

    fig, ax = plt.subplots(figsize=(config.FIG_WIDTH_FULL, config.FIG_HEIGHT_DEFAULT))

    sign_alpha = 0.32       # sign-fill opacity (raised for clarity)
    band_alpha = 0.42       # consistency-band opacity
    band_gray = "0.45"      # consistency-band grey

    # Sign shading between the difference line and zero: red where Kanektok is
    # higher (>0), blue where Uyak is higher (<0). interpolate=True closes the
    # wedges cleanly at zero crossings.
    ax.fill_between(x, y, 0, where=(y >= 0), interpolate=True,
                    color=k_color, alpha=sign_alpha, linewidth=0, zorder=2)
    ax.fill_between(x, y, 0, where=(y <= 0), interpolate=True,
                    color=u_color, alpha=sign_alpha, linewidth=0, zorder=2)

    # Across-pass consistency band (IQR) hugging the median line.
    if band is not None and "lo" in d:
        ax.fill_between(x, d["lo"].to_numpy(), d["hi"].to_numpy(),
                        color=band_gray, alpha=band_alpha, linewidth=0, zorder=3)

    # Median difference line + prominent zero-line.
    ax.plot(x, y, color="black", lw=1.8, zorder=5)
    ax.axhline(0, color="black", ls="--", lw=1.4, zorder=4)
    ax.annotate("Equal elevation", xy=(0.015, 0.0), xycoords=("axes fraction", "data"),
                xytext=(0, 3), textcoords="offset points", fontsize=8,
                color="#444444", ha="left", va="bottom")

    add_bifurcation_line(ax)

    # Dynamic annotation of the maximum sub-elevation (deepest deficit).
    imin = int(np.argmin(y))
    ax.annotate(f"Max sub-elevation: {y[imin]:.2f} m",
                xy=(x[imin], y[imin]), xytext=(x[imin] - 6, y[imin] - 0.15),
                textcoords="data", fontsize=8.5, color=u_color, fontweight="bold",
                ha="center", va="top",
                arrowprops=dict(arrowstyle="->", color=u_color, lw=1.0))

    ax.set_ylabel("Elevation Difference (m)\n[Kanektok − Uyak]")
    style_distance_axis(ax, float(x.max()))
    # Expand y-limits -- extra room at the BOTTOM so the frameless legend sits in a
    # clear margin below the data instead of overlapping it.
    y_lo = float(min(y.min(), d["lo"].min() if "lo" in d else y.min()))
    y_hi = float(max(y.max(), d["hi"].max() if "hi" in d else y.max(), 0.05))
    ax.set_ylim(y_lo - 0.85, y_hi + 0.30)

    # Legend: sign fills + consistency band. Frameless -- it sits in the expanded
    # bottom margin (see y-limits above), so nothing shows through it.
    handles = [Patch(facecolor=k_color, alpha=sign_alpha, linewidth=0),
               Patch(facecolor=u_color, alpha=sign_alpha, linewidth=0)]
    labels = ["Kanektok higher", "Uyak higher (sub-elevation)"]
    if band is not None and "lo" in d:
        handles.append(Patch(facecolor=band_gray, alpha=band_alpha, linewidth=0))
        labels.append(f"{band[0]}–{band[1]}% across passes")
    ax.legend(handles, labels, loc="lower left", ncol=1, frameon=False)
    fig.tight_layout()
    return fig


def build_fig7(node_km: float = 0.5, band=(25, 75)):
    """Fig 7 -- Detrended Relative Elevation Profile (Results 5.4).

    Removes the large-scale downstream trend by subtracting a SINGLE 2nd-order
    polynomial fit to BOTH rivers pooled (the shared regional gradient), so the
    flattened zero-line is that common baseline and each river's residual shows its
    structural offset from it. Per river: residual-domain MAD flag (Modified Z>3.5,
    matching the dashboard Detrended tab) removes localised contamination, then a
    median residual line + IQR band. Faint dashed horizontal markers at each river's
    overall median residual lock in the ~1 m gap (Uyak above, Kanektok below).
    Source: Detrended Profile tab.
    """
    con = core.connect()
    df = core.load_swot(con, reaches=list(config.COLOR_MAP), open_water_only=True).copy()

    # Common regional baseline: one 2nd-order polynomial over BOTH rivers pooled.
    base, _, _ = core.calculate_detrending(
        df["dist_km"].tolist(), df["wse"].tolist(), "Polynomial (2nd order)")
    df["resid"] = df["wse"].to_numpy() - base

    fig, ax = plt.subplots(figsize=(config.FIG_WIDTH_FULL, config.FIG_HEIGHT_DEFAULT))
    plot_order = sorted(config.COLOR_MAP, key=lambda r: r == "Uyak_Creek")

    legend_handles, legend_labels = [], []
    span_lo, span_hi = [], []          # track band extent for y-limits
    median_markers = []                 # (color, value, label) for the gap lines
    for reach in plot_order:
        d = df[df["Reach_Name"] == reach]
        if len(d) == 0:
            continue
        color = config.river_color(reach)
        resid = d["resid"].to_numpy()
        keep = ~core.flag_residual_outliers(resid)   # per-river Modified Z>3.5
        dd = d.loc[keep]
        node = core.round_half_away(dd["dist_km"].to_numpy() / node_km) * node_km
        grp = dd.assign(node=node).groupby("node")["resid"]
        med = grp.median().sort_index()
        q_lo = grp.quantile(band[0] / 100.0).sort_index()
        q_hi = grp.quantile(band[1] / 100.0).sort_index()
        ax.fill_between(med.index.to_numpy(), q_lo.to_numpy(), q_hi.to_numpy(),
                        color=color, alpha=0.28, linewidth=0, zorder=3)
        ax.plot(med.index.to_numpy(), med.to_numpy(), color=color, lw=2.2,
                solid_capstyle="round", zorder=5)
        span_lo.append(q_lo.min()); span_hi.append(q_hi.max())
        med_val = float(np.median(dd["resid"]))
        median_markers.append((color, med_val))
        # Median value folded into the legend label (avoids floating in-plot text
        # that the data lines would cover).
        legend_handles.append((Line2D([], [], color=color, lw=2.2),
                               Patch(facecolor=color, alpha=0.28, linewidth=0)))
        legend_labels.append(f"{config.river_label(reach)}  (median {med_val:+.2f} m)")

    # Bold baseline (the polynomial, now flat at zero) + dashed reach-median markers.
    ax.axhline(0, color="black", lw=1.8, zorder=4)
    for color, val in median_markers:
        ax.axhline(val, color=color, ls="--", lw=1.1, alpha=0.7, zorder=2)

    add_bifurcation_line(ax)

    ax.set_ylabel("Detrended WSE Residual (m)")
    style_distance_axis(ax, float(df["dist_km"].max()))
    lo, hi = min(span_lo), max(span_hi)
    pad = 0.25 * (hi - lo)
    ax.set_ylim(lo - pad, hi + pad)

    # Legend carries all the annotation: river median lines + bands (with values)
    # and the polynomial baseline. Placed upper-left, in the clear corner.
    legend_handles.append(Line2D([], [], color="black", lw=1.8))
    legend_labels.append("Polynomial baseline (0 m)")
    title = f"Median line & {band[0]}–{band[1]}% band"
    leg = ax.legend(legend_handles, legend_labels, loc="upper left", title=title,
                    handler_map={tuple: HandlerTuple(ndivide=None)}, fontsize=9)
    leg._legend_box.align = "left"   # left-align the title with the entries
    fig.tight_layout()
    return fig


def build_fig8(smooth_km: float = 2.0):
    """Fig 8 -- Interval Slope Profile (Results 5.3 / Discussion).

    Local hydraulic gradient along each river: 100 m median-WSE bins, `smooth_km`
    Gaussian smoothing, numerical derivative (core.calculate_slope_profile). Plotted
    as absolute slope (cm/km, positive) so it reads as steepness and is comparable to
    the reference gradients. Both profiles decay smoothly downstream (steep near the
    anchor, gentle near the mouth) with no abrupt knickpoints, and the two rivers
    track each other closely (interweaving) rather than one sitting persistently
    higher -- supporting the claim that localised gradients do not spike dangerously.
    Source: Slope Profile tab.
    """
    con = core.connect()
    df = core.load_swot(con, reaches=list(config.COLOR_MAP), open_water_only=True)

    fig, ax = plt.subplots(figsize=(config.FIG_WIDTH_FULL, config.FIG_HEIGHT_DEFAULT))
    plot_order = sorted(config.COLOR_MAP, key=lambda r: r == "Uyak_Creek")

    all_slopes = []
    for reach in plot_order:
        d = df[df["Reach_Name"] == reach]
        if len(d) == 0:
            continue
        x_eval, slope_cm_km, _ = core.calculate_slope_profile(
            d["dist_km"].tolist(), d["wse"].tolist(), smooth_km=smooth_km)
        slope = np.abs(slope_cm_km)   # steepness magnitude (raw derivative is negative)
        all_slopes.append(slope)
        ax.plot(x_eval, slope, color=config.river_color(reach), lw=2.2,
                solid_capstyle="round", label=config.river_label(reach), zorder=4)

    add_bifurcation_line(ax)

    ax.set_ylabel("Interval Slope (cm/km)")
    style_distance_axis(ax, float(df["dist_km"].max()))
    amin = min(s.min() for s in all_slopes)
    amax = max(s.max() for s in all_slopes)
    ax.set_ylim(max(0.0, amin - 20), amax + 20)

    ax.legend(loc="upper left")
    fig.tight_layout()
    return fig


def build_fig9(res_km: float = 0.5, method: str = "theilsen",
               xmax: float = 34.0, zoom_km: float = 8.0, band=(25, 75)):
    """Fig 9 -- Fine-Scale (Backwater-Scale) Slope Profile (Results 5.3 / Discussion).

    The reach-average gradients differ by only ~3.6 cm/km, which hides where the
    hydraulic contrast actually lives. This figure computes the slope WITHIN each
    pass (stage constant) at ~`res_km` resolution, then aggregates the median across
    passes with a 25-75% pass-to-pass band (core.finescale_slope_profile, robust
    Theil-Sen) -- resolving the ~0.5 km structure that Fig 8's 2 km Gaussian
    (~4.7 km FWHM) smooths away. Two panels: (a) the full reach, (b) a zoom on the
    bifurcation. Dashed horizontal lines mark each river's reach-average reference
    gradient; near the bifurcation the local slope towers well above it, and Kanektok
    sits clearly above Uyak. Source: Fine-Scale Slope tab.
    """
    con = core.connect()
    data = core.finescale_slope_profile(
        con, reaches=tuple(config.COLOR_MAP), res_km=res_km, method=method, xmax=xmax)

    # Reach-average reference gradient (canonical, gated open-water Theil-Sen median).
    ref = core.load_reference_gradient()
    ow = ref[(ref["open_water"]) & (ref["gated"])]
    ref_grad = {r: ow[ow["Reach_Name"] == r]["theilsen_cm_km"].abs().median()
                for r in config.COLOR_MAP}

    plot_order = sorted(config.COLOR_MAP, key=lambda r: r == "Uyak_Creek")

    fig, (ax_full, ax_zoom) = plt.subplots(
        2, 1, figsize=(config.FIG_WIDTH_FULL, config.FIG_HEIGHT_DEFAULT * 1.7))

    def _draw(ax, xlim_hi):
        ymax = 0.0
        for reach in plot_order:
            r = data.get(reach)
            if not r:
                continue
            g, med, lo, hi = r["grid"], r["med"], r["lo"], r["hi"]
            m = g <= xlim_hi
            col = config.river_color(reach)
            ax.fill_between(g[m], lo[m], hi[m], color=col, alpha=0.15,
                            linewidth=0, zorder=2)
            ax.plot(g[m], med[m], color=col, lw=2.0, solid_capstyle="round",
                    label=config.river_label(reach), zorder=4)
            finite = med[m][np.isfinite(med[m])]
            if finite.size:
                ymax = max(ymax, float(np.nanmax(hi[m])))
            # reach-average reference gradient (dashed)
            rg = ref_grad.get(reach)
            if rg is not None and np.isfinite(rg):
                ax.axhline(rg, color=col, ls=(0, (5, 3)), lw=1.0, alpha=0.9, zorder=3)
        add_bifurcation_line(ax)
        ax.set_ylabel("Interval Slope (cm/km)")
        ax.set_xlim(xlim_hi + 1.0, -1.0)     # reversed: anchor (0) on the right
        ax.set_ylim(0.0, ymax + 25)
        return ymax

    # (a) Full reach
    _draw(ax_full, xmax)
    ax_full.legend(loc="upper left")
    # The two reach-average reference gradients (~195 / ~192) nearly coincide, so a
    # single note in clear low-slope space beats two overlapping per-line labels.
    rgk, rgu = ref_grad.get("Kanektok_River"), ref_grad.get("Uyak_Creek")
    ax_full.annotate(
        f"dashed = reach-average reference gradient (Kanektok {rgk:.0f}, Uyak {rgu:.0f} cm/km)",
        xy=(0.5, 0.04), xycoords="axes fraction", fontsize=7, style="italic",
        color="#555555", ha="center", va="bottom")
    ax_full.set_title("(a) Full reach", fontsize=10, loc="left", color="#333333")

    # (b) Bifurcation zoom
    _draw(ax_zoom, zoom_km)
    ax_zoom.set_title(f"(b) Bifurcation zoom (0–{zoom_km:.0f} km)",
                      fontsize=10, loc="left", color="#333333")
    ax_zoom.set_xlabel("Distance Downriver from Anchor (km)")
    ax_zoom.annotate("Anchor point (0 km)", xy=(1.0, -0.14), xycoords="axes fraction",
                     fontsize=8, style="italic", color="#666666", ha="right", va="top")

    # Near-bifurcation contrast annotation (the headline of the re-analysis).
    def _near(reach):
        r = data.get(reach)
        if not r:
            return np.nan
        nb = (r["grid"] >= 1.0) & (r["grid"] <= 5.0)
        return float(np.nanmedian(r["med"][nb])) if nb.any() else np.nan
    k, u = _near("Kanektok_River"), _near("Uyak_Creek")
    if np.isfinite(k) and np.isfinite(u):
        ax_zoom.annotate(
            f"1–5 km median slope:\nKanektok {k:.0f}, Uyak {u:.0f} cm/km "
            f"(+{k - u:.0f})",
            xy=(0.03, 0.95), xycoords="axes fraction", fontsize=8,
            ha="left", va="top", color="#333333",
            bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="#CCCCCC", lw=0.8))

    fig.tight_layout()
    return fig


def build_fig10(zoom: int = 13, n_points: int = 120000, pad_frac: float = 0.07):
    """Fig 10 -- Bifurcation & Virtual-Gauge Detail Map.

    Zoomed companion to Fig 1, covering the anchor-to-~8 km reach where the
    bifurcation-gauge analysis lives (bifurcation_gauge.py). Same construction
    as Fig 1 -- analysis polygons plus the SWOT node clouds at the usual low
    alpha over Esri World Imagery -- with markers for the anchor (0 km), the
    bifurcation (~2.5 km), and the two virtual gauges, each sited 1 km
    ALONG-CHANNEL past the split on its river's official centerline (the
    channels are ~740 m apart there). The centerlines are drawn so the siting
    reads directly off the map. Gauge positions are read from the analysis
    summary, never hardcoded, so map and numbers cannot drift apart. Basemap
    tiles are fetched at build time (needs network).
    """
    import json
    import geopandas as gpd
    import contextily as cx
    from pyproj import Transformer
    from matplotlib import patheffects as pe

    WEBM = 3857
    tf = Transformer.from_crs(4326, WEBM, always_xy=True)

    polys = gpd.read_file("zip://river_poly.zip").to_crs(WEBM)
    name_to_reach = {"Kanektok": "Kanektok_River", "Uyak": "Uyak_Creek"}
    polys["reach"] = polys["Name"].map(name_to_reach)

    # Extent: bounding box of the SWOT pixels within 8 km of the anchor
    # (lon -161.476..-161.339, lat 59.803..59.843, from the master archive),
    # padded, with extra room up top so the legend sits over tundra (Fig 1).
    x0, y0 = tf.transform(-161.476, 59.803)
    x1, y1 = tf.transform(-161.339, 59.843)
    dx = (x1 - x0) * pad_frac
    xlim = (x0 - dx, x1 + dx)
    ylim = (y0 - (y1 - y0) * 0.10, y1 + (y1 - y0) * 0.34)

    con = core.connect()
    pts = core.load_swot(con, reaches=list(config.COLOR_MAP), open_water_only=True)
    pts = pts[pts["dist_km"] <= 8.5]
    rng = np.random.default_rng(42)

    fig, ax = plt.subplots(figsize=(config.FIG_WIDTH_FULL, config.FIG_WIDTH_FULL / 1.4))
    ax.set_xlim(*xlim); ax.set_ylim(*ylim)
    ax.set_aspect("equal")

    plot_order = sorted(config.COLOR_MAP, key=lambda r: r == "Uyak_Creek")
    for reach in plot_order:
        color = config.river_color(reach)
        sub = polys[polys["reach"] == reach]
        sub.plot(ax=ax, facecolor=color, edgecolor="none", alpha=0.05, zorder=3)
        sub.boundary.plot(ax=ax, edgecolor=color, linewidth=1.3, zorder=3)
        d = pts[pts["Reach_Name"] == reach]
        if len(d) > n_points:
            d = d.iloc[rng.choice(len(d), n_points, replace=False)]
        px, py = tf.transform(d["longitude"].to_numpy(), d["latitude"].to_numpy())
        # Same low alpha as Fig 1; slightly larger dots because each pixel
        # covers ~5x more screen area at this zoom.
        ax.scatter(px, py, s=2.6, color=color, alpha=0.09, edgecolor="none",
                   rasterized=True, zorder=4)

    def _mk(lon, lat, **kw):
        mx, my = tf.transform(lon, lat)
        ax.scatter([mx], [my], zorder=6,
                   linewidths=1.1, edgecolor="black", **kw)

    # Official channel centerlines -- the ruler the gauges are sited along.
    for reach, path in [("Kanektok_River",
                         "DEM_Transects/data/kanektok_centerline_official.gpkg"),
                        ("Uyak_Creek",
                         "DEM_Transects/data/uyak_centerline_official.gpkg")]:
        cl = gpd.read_file(path).to_crs(WEBM)
        cl.plot(ax=ax, color=config.river_color(reach), linewidth=1.0, zorder=5,
                path_effects=[pe.Stroke(linewidth=2.2, foreground="white",
                                        alpha=0.75), pe.Normal()])

    _mk(config.ANCHOR_LON, config.ANCHOR_LAT, marker="o", s=55, color="white")
    _mk(config.BIFURCATION_LON, config.BIFURCATION_LAT, marker="*", s=170,
        color="white")
    # Bifurcation virtual gauges (bifurcation_gauge.py): one per river, sited
    # 1 km along-channel past the split on that river's centerline. Read from
    # the analysis summary so the map always shows the gauges actually used.
    with open(f"{config.TEMPORAL_DIR}/bifurcation_gauge_results.json") as f:
        gsum = json.load(f)
    gmeta = gsum["gauges"][f"{gsum['primary_s_km']:.2f}"]
    for reach, p in gmeta["points"].items():
        _mk(p["lon"], p["lat"], marker="D", s=42, color="white")
    gauge_s_km, gauge_sep_m = gmeta["s_km"], gmeta["separation_m"]

    cx.add_basemap(ax, crs=WEBM, source=cx.providers.Esri.WorldImagery,
                   zoom=zoom, attribution=False, zorder=0)

    # --- lat/lon edge labels --------------------------------------------------------
    lon_ticks = [-161.46, -161.42, -161.38, -161.34]
    lat_ticks = [59.81, 59.82, 59.83, 59.84]
    ax.set_xticks([tf.transform(lo, lat_ticks[0])[0] for lo in lon_ticks])
    ax.set_xticklabels([f"{abs(lo):.2f}°W" for lo in lon_ticks])
    ax.set_yticks([tf.transform(lon_ticks[0], la)[1] for la in lat_ticks])
    ax.set_yticklabels([f"{la:.2f}°N" for la in lat_ticks])
    ax.grid(False)
    ax.tick_params(direction="out")

    # --- cartographic furniture ----------------------------------------------------
    _mercator_scalebar(ax, km=2, center_lat=59.82, loc=(0.42, 0.06))
    # North arrow lower-RIGHT here: the lower-left corner is river at this zoom.
    _north_arrow(ax, loc=(0.91, 0.115), zoom=0.20,
                 icon_path=config.NORTH_ICON_PATH)

    handles = [
        Patch(facecolor=config.river_color("Kanektok_River"), alpha=0.30,
              edgecolor=config.river_color("Kanektok_River"), linewidth=1.3),
        Patch(facecolor=config.river_color("Uyak_Creek"), alpha=0.30,
              edgecolor=config.river_color("Uyak_Creek"), linewidth=1.3),
        Line2D([], [], marker="o", ls="none", mfc="white", mec="black", ms=6),
        Line2D([], [], marker="*", ls="none", mfc="white", mec="black", ms=10),
        Line2D([], [], marker="D", ls="none", mfc="white", mec="black", ms=5),
    ]
    labels = ["Kanektok River", "Uyak Creek", "Anchor (0 km)",
              "Bifurcation",
              f"Virtual gauge ({gauge_s_km:g} km along-channel past the split)"]
    ax.legend(handles, labels, loc="upper left", frameon=True, facecolor="white",
              framealpha=0.92, edgecolor="0.4", fontsize=7, borderpad=0.4,
              labelspacing=0.35, handletextpad=0.5)

    return fig


# Registry: figure number -> (builder, short title).
FIGURES = {
    0: (build_fig0, "Regional Setting Overview Map"),
    1: (build_fig1, "Study Area & Spatial Normalization Map"),
    2: (build_fig2, "Custom Python Pipeline Flowchart"),
    3: (build_fig3, "Temporal Stability & Stage-Invariance"),
    4: (build_fig4, "Reference Hydraulic Gradient Distribution"),
    5: (build_fig5, "Absolute Spatial Gradient Profile"),
    6: (build_fig6, "Localized Elevation Difference"),
    7: (build_fig7, "Detrended Relative Elevation Profile"),
    8: (build_fig8, "Interval Slope Profile"),
    9: (build_fig9, "Fine-Scale Slope Profile"),
    10: (build_fig10, "Bifurcation & Virtual-Gauge Detail Map"),
}
EXTERNAL = {}  # all figures now have in-module builders


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _list():
    print("Thesis figures:")
    for n in sorted({*FIGURES, *EXTERNAL}):
        if n in FIGURES:
            _, title = FIGURES[n]
            print(f"  Figure {n}: {title}")
        else:
            print(f"  Figure {n}: {EXTERNAL[n]}")


def _smoke():
    """Verify the data layer and ported computations run headless (no plotting)."""
    config.apply_style()
    con = core.connect()
    df = core.load_swot(con, reaches=list(config.COLOR_MAP), open_water_only=True)
    print(f"[smoke] SWOT rows (open-water): {len(df):,}")
    print(f"[smoke] rivers: {sorted(df['Reach_Name'].unique())}")
    ref = core.load_reference_gradient()
    ow = ref[(ref["open_water"]) & (ref["gated"])]
    for reach in config.COLOR_MAP:
        d = ow[ow["Reach_Name"] == reach]
        if len(d):
            med = d["theilsen_cm_km"].abs().median()
            print(f"[smoke] {config.river_label(reach)}: {len(d)} gated passes, "
                  f"Theil-Sen median {med:.1f} cm/km")
    ediff = core.elevation_difference(con)
    print(f"[smoke] elevation-difference bins: {len(ediff)}, "
          f"min diff {ediff['diff'].min():.3f} m, "
          f"mean {ediff['diff'].mean():.3f} m, "
          f"median passes/bin {int(ediff['n_passes'].median())}")
    # Exercise the ported slope/detrend math on Kanektok.
    k = df[df["Reach_Name"] == "Kanektok_River"]
    _, slope, _ = core.calculate_slope_profile(k["dist_km"].tolist(), k["wse"].tolist())
    base, _, name = core.calculate_detrending(k["dist_km"].tolist(), k["wse"].tolist(),
                                              "Polynomial (2nd order)")
    print(f"[smoke] slope profile pts: {len(slope)}; detrend baseline '{name}' ok")
    print("[smoke] OK -- data + core computations verified.")


def main(argv=None):
    p = argparse.ArgumentParser(description="Build thesis figures.")
    p.add_argument("figures", nargs="*", type=int, help="figure numbers to build")
    p.add_argument("--all", action="store_true", help="build every implemented figure")
    p.add_argument("--list", action="store_true", help="list figures and exit")
    p.add_argument("--smoke", action="store_true", help="verify data+core, no plotting")
    p.add_argument("--data", metavar="PARQUET",
                   help="override the SWOT data source (default: config.DATA_PATH = "
                        "full archive). Use to A/B old vs new-polygon data.")
    p.add_argument("--ref-gradient", metavar="PARQUET",
                   help="override the reference-gradient artifact path (Fig 4).")
    args = p.parse_args(argv)

    # Data-source overrides apply to every downstream figure/smoke call.
    if args.data:
        config.DATA_PATH = args.data
        print(f"[data] SWOT source overridden -> {args.data}")
    if args.ref_gradient:
        config.REF_GRADIENT_PATH = args.ref_gradient
        print(f"[data] reference-gradient source overridden -> {args.ref_gradient}")

    if args.list:
        _list()
        return 0
    if args.smoke:
        _smoke()
        return 0

    if args.all:
        targets = sorted(FIGURES)
    elif args.figures:
        targets = args.figures
    else:
        p.print_help()
        return 1

    config.apply_style()
    built, skipped = [], []
    for n in targets:
        if n in EXTERNAL:
            print(f"Figure {n}: external ({EXTERNAL[n]}) -- skipping.")
            continue
        if n not in FIGURES:
            print(f"Figure {n}: unknown -- skipping.")
            continue
        builder, title = FIGURES[n]
        try:
            fig = builder()
            # A builder may return a single Figure or a list of (suffix, Figure)
            # pairs for figures exported as separate standalone files (Fig 3).
            if isinstance(fig, list):
                paths = []
                for suffix, f in fig:
                    paths += config.savefig(f, f"figure_{n:02d}{suffix}",
                                            subdir=SERIES)
                    plt.close(f)
            else:
                paths = config.savefig(fig, f"figure_{n:02d}", subdir=SERIES)
                plt.close(fig)
            built.append(n)
            print(f"Figure {n} ({title}) -> {', '.join(paths)}")
        except NotImplementedFigure as e:
            skipped.append(n)
            print(f"Figure {n}: {e}")

    if built:
        print(f"\nBuilt: {built}")
    if skipped:
        print(f"Pending (not yet designed): {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
