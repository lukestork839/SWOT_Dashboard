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
def _mercator_scalebar(ax, km, center_lat, loc=(0.38, 0.06), color="white"):
    """Draw a ground-accurate scale bar on a Web-Mercator (EPSG:3857) axis.

    Web Mercator distances are inflated by 1/cos(lat), so a bar representing
    `km` ground kilometres spans `km*1000/cos(center_lat)` map units. Drawn as a
    single filled bar (white fill + thin black edge, so it reads on dark imagery and
    has no disconnected end ticks) with a light-stroked, normal-weight label centred
    above it. `loc` is the bar's lower-left corner in axes fraction.
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
            fontsize=8, color=color, fontweight="normal",
            path_effects=[pe.withStroke(linewidth=1.8, foreground="black")], zorder=9)


def _north_arrow(ax, loc=(0.055, 0.80), color="white", icon_path=None, zoom=0.13,
                 target_px=150):
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
    stroke = [pe.withStroke(linewidth=3, foreground="black")]
    ax.annotate("", xy=(loc[0], loc[1] + 0.10), xytext=(loc[0], loc[1]),
                xycoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", color=color, lw=2.2,
                                path_effects=stroke))
    ax.annotate("N", xy=(loc[0], loc[1] + 0.115), xycoords="axes fraction",
                ha="center", va="bottom", fontsize=10, fontweight="bold",
                color=color, path_effects=stroke)


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
    # North arrow is added in post from the Nalaquq village vector logo (stays crisp
    # at small size, unlike a rasterised icon); the lower-left corner is left clear
    # for it. See _north_arrow() / config.NORTH_ICON_PATH if a drawn arrow is wanted.

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
    axins = inset_axes(ax, width="26%", height="36%", loc="lower right", borderpad=0.5)
    ak = [(-172, 51), (-129, 71)]   # (lon,lat) SW / NE corners of the Alaska view
    (ax0, ay0), (ax1, ay1) = [tf.transform(lo, la) for lo, la in ak]
    axins.set_xlim(ax0, ax1); axins.set_ylim(ay0, ay1)
    cx.add_basemap(axins, crs=WEBM, source=cx.providers.Esri.NatGeoWorldMap,
                   zoom=4, attribution=False, zorder=0)
    # Red box marking the map's extent within Alaska. The true study footprint is a
    # speck at state scale, so enforce a minimum on-screen size (centred on the study
    # centroid) so the locator box stays visible; it represents "the area shown here".
    from matplotlib.patches import Rectangle as _Rect
    bx0, bx1 = xlim; by0, by1 = ylim
    cxc, cyc = (bx0 + bx1) / 2, (by0 + by1) / 2
    min_w = 0.055 * (ax1 - ax0); min_h = 0.07 * (ay1 - ay0)
    bw = max(bx1 - bx0, min_w); bh = max(by1 - by0, min_h)
    axins.add_patch(_Rect((cxc - bw / 2, cyc - bh / 2), bw, bh,
                          facecolor=(1, 1, 1, 0.55), edgecolor="white",
                          linewidth=1.2, zorder=5))
    axins.set_xticks([]); axins.set_yticks([])
    for s in axins.spines.values():
        s.set(visible=True, edgecolor="0.3", linewidth=0.8)

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


def build_fig3():
    """Fig 3 -- Temporal Stability & Stage-Invariance (Results 5.1).

    Three panels from the one-time temporal analysis (temporal_results/):
      (a) WSE at 15 km (stage proxy) vs date,
      (b) robust hydraulic gradient vs date,
    both with winter (Dec-Mar, no open-water data) shaded and Typhoon Halong
    landfall marked -- showing seasonal, interannual, and pre/post-typhoon
    stability on one time axis; and
      (c) gradient vs stage, demonstrating stage-invariance (flat bands justify
    pooling passes across seasons/years). The typhoon comparison is INTERIM (see
    caption). QC-excluded passes (config.EXCLUDED_PASSES) are dropped.
    Source: temporal_metrics_per_pass.parquet + temporal_analysis_results.json.
    """
    m = core.load_temporal_metrics()
    results = core.load_temporal_results()
    typhoon = results["method"]["typhoon_date"]
    order = sorted(config.COLOR_MAP, key=lambda r: r == "Uyak_Creek")

    fig, (ax_a, ax_b, ax_c) = plt.subplots(
        3, 1, figsize=(config.FIG_WIDTH_FULL, 8.2), constrained_layout=True)

    def _events(ax):
        # winter (Dec-Mar) shading -- no gated open-water data there.
        for y0 in (2023, 2024, 2025):
            ax.axvspan(pd.Timestamp(f"{y0}-12-01"), pd.Timestamp(f"{y0+1}-03-31"),
                       color="lightsteelblue", alpha=0.25, lw=0, zorder=0)
        ax.axvline(pd.Timestamp(typhoon), color="black", ls="--", lw=1.2, zorder=1)

    # (a) WSE at 15 km vs date, (b) gradient vs date.
    for ax, col in ((ax_a, "wse_ref_m"), (ax_b, "slope_cm_km")):
        _events(ax)
        for reach in order:
            d = m[m["reach"] == reach].sort_values("date")
            ax.plot(d["date"].to_numpy(), d[col].to_numpy(), linestyle="none",
                    marker="o", ms=4, color=config.river_color(reach), alpha=0.75,
                    label=config.river_label(reach), zorder=3)
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.set_xlim(m["date"].min() - pd.Timedelta(days=40),
                    m["date"].max() + pd.Timedelta(days=40))
    ax_a.tick_params(labelbottom=False)   # (b) carries the shared date axis
    # typhoon label on the top panel
    ax_a.annotate("Typhoon Halong", xy=(pd.Timestamp(typhoon), 1.0),
                  xycoords=("data", "axes fraction"), xytext=(3, -3),
                  textcoords="offset points", fontsize=8, color="black",
                  ha="left", va="top")
    ax_a.set_ylabel("WSE at 15 km (m)")
    ax_b.set_ylabel("Hydraulic Gradient\n(cm/km)")
    ax_b.set_xlabel("Date")
    ax_a.legend(loc="lower left", ncol=2)

    # (c) stage-invariance: gradient vs stage, with per-river median lines.
    for reach in order:
        d = m[m["reach"] == reach]
        color = config.river_color(reach)
        ax_c.plot(d["wse_ref_m"].to_numpy(), d["slope_cm_km"].to_numpy(),
                  linestyle="none", marker="o", ms=5, color=color, alpha=0.55,
                  label=config.river_label(reach), zorder=3)
        ax_c.axhline(float(d["slope_cm_km"].median()), color=color, ls=":",
                     lw=1.2, alpha=0.8, zorder=2)
    ax_c.set_xlabel("Water Surface Elevation at 15 km (m)  —  stage proxy")
    ax_c.set_ylabel("Hydraulic Gradient\n(cm/km)")
    ax_c.legend(loc="upper right", ncol=1)

    # Panel labels.
    for ax, lab in ((ax_a, "(a)"), (ax_b, "(b)"), (ax_c, "(c)")):
        ax.annotate(lab, xy=(0.0, 1.0), xycoords="axes fraction", xytext=(2, -2),
                    textcoords="offset points", fontsize=11, fontweight="bold",
                    ha="left", va="top")
    return fig


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
        grp = d.assign(node=(d["dist_km"] / node_km).round() * node_km).groupby("node")["wse"]
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
        grp = dd.assign(node=(dd["dist_km"] / node_km).round() * node_km).groupby("node")["resid"]
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


# Registry: figure number -> (builder, short title).
FIGURES = {
    1: (build_fig1, "Study Area & Spatial Normalization Map"),
    2: (build_fig2, "Custom Python Pipeline Flowchart"),
    3: (build_fig3, "Temporal Stability & Stage-Invariance"),
    4: (build_fig4, "Reference Hydraulic Gradient Distribution"),
    5: (build_fig5, "Absolute Spatial Gradient Profile"),
    6: (build_fig6, "Localized Elevation Difference"),
    7: (build_fig7, "Detrended Relative Elevation Profile"),
    8: (build_fig8, "Interval Slope Profile"),
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
            paths = config.savefig(fig, f"figure_{n:02d}")
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
