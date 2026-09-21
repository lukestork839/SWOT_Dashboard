#!/usr/bin/env python3
"""Presentation figure builder.

Figures made for the defense/presentation deck rather than a numbered thesis
series. They reuse the thesis styling (`config.apply_style`) so slides and
document read as one body of work. Renders go to `output/Presentation/`.

P1 — Superelevation comparison: the avulsion-ready perched channel drawn with
Gearon et al. (2024) notation (H_AR, H_M, beta) next to the Kanektok's measured
median cross-section geometry, both at the same true vertical scale.

P7 — Raw satellite imagery of the bifurcation: the two channels with no
overlays at all, so the Uyak's narrowness relative to the Kanektok reads
directly off the image rather than off an analysis corridor. `points=True`
renders the same frame with the SWOT node cloud on top; the two are built to be
shown side by side.

P8 — The same scene at Fig 10's exact extent, with and without the degree
ticks: the A/B partner for flipping against Fig 10 in a deck.

Usage
-----
    python -m thesis_figures.make_presentation_figures
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import config

SERIES = "Presentation"

# --- Measured median geometry (thesis_canonical_values.md section 1.7; 64 arcs).
# The individual medians are taken over slightly different arc populations, so
# A + B approximates H_M rather than summing exactly; the drawing hangs the bed
# one ADCP depth below the water line (Gearon depth rule 3, as in the analysis).
H_AR_KAN = 0.14      # m, near-channel crest above the floodplain reference (median)
H_M_KAN = 2.86       # m, crest -> bed (median)
FREEBOARD_KAN = -1.50  # m, median water surface below the floodplain reference
DEPTH_ADCP = 1.30    # m, per-arc median measured thalweg depth
BETA_KAN = 0.06
BED_KAN = FREEBOARD_KAN - DEPTH_ADCP   # -2.80 m

# --- Schematic perched channel, beta ~ 1: bed aggraded to floodplain grade
# (Gearon 2024 main text; Mohrig 2000 "practical maximum"). Drawn with the SAME
# channel depth H_M as the Kanektok so the only difference between the panels is
# where that channel sits relative to the plain.
H_M_PERCH = H_M_KAN
BED_PERCH = 0.0                       # bed at floodplain grade
CREST_PERCH = BED_PERCH + H_M_PERCH   # +2.86 m
WSE_PERCH = BED_PERCH + DEPTH_ADCP    # water rides +1.30 m above the plain

TERRAIN_FILL = "#E4D5B5"
TERRAIN_EDGE = "#8A7355"
WATER_FILL = "#A6CBE3"
WATER_EDGE = "#33658A"
REF_COLOR = "#557A3C"      # floodplain reference line
ANNOT = "#B3402A"          # measurement brackets (reads against tan + blue)

X_MAX = 600.0              # m, schematic across-floodplain window
CH_L, CH_R = 262.0, 338.0  # channel banks (~76 m wide, order of the real channel)


def _smooth(x, y, sigma_pts=6):
    """Light gaussian smoothing so control-point terrain reads as ground."""
    k = np.exp(-0.5 * (np.arange(-3 * sigma_pts, 3 * sigma_pts + 1) / sigma_pts) ** 2)
    k /= k.sum()
    ypad = np.pad(y, 3 * sigma_pts, mode="edge")
    return x, np.convolve(ypad, k, mode="valid")


def _terrain(control, x0=0.0, x1=X_MAX, n=1200):
    """Dense terrain polyline from (x, z) control points."""
    cx, cz = zip(*control)
    x = np.linspace(x0, x1, n)
    return _smooth(x, np.interp(x, cx, cz))


def _fill_water(ax, x, z, level, x0, x1):
    """Fill the channel with water up to `level` between x0..x1. The surface
    line spans only the wetted extent (where the terrain sits below `level`),
    so sloped banks are not overdrawn."""
    m = (x >= x0) & (x <= x1)
    ax.fill_between(x[m], z[m], level, where=z[m] <= level,
                    color=WATER_FILL, edgecolor="none", zorder=2)
    wet = x[m & (z <= level)]
    ax.plot([wet.min(), wet.max()], [level, level],
            color=WATER_EDGE, lw=1.6, zorder=3)


def _vbracket(ax, x, z0, z1, label, dx_text=14, ha="left", fs=9, lw=1.4):
    """Vertical measurement bracket with serif label to the side."""
    ax.annotate("", xy=(x, z0), xytext=(x, z1),
                arrowprops=dict(arrowstyle="<->", color=ANNOT, lw=lw,
                                shrinkA=0, shrinkB=0), zorder=6)
    for zz in (z0, z1):
        ax.plot([x - 6, x + 6], [zz, zz], color=ANNOT, lw=lw, zorder=6)
    ax.text(x + dx_text if ha == "left" else x - dx_text, (z0 + z1) / 2, label,
            ha=ha, va="center", fontsize=fs, color=ANNOT)


# Terrain control points shared between the annotated (P1/P2) and plain (P3)
# variants, so the drawn ground can never drift apart between versions.
TERRAIN_PERCHED = [
    (0, 0.0), (55, 0.06), (105, 0.40), (150, 1.20), (190, 2.30),
    (218, CREST_PERCH), (245, CREST_PERCH),
    (268, BED_PERCH), (300, BED_PERCH), (332, BED_PERCH),
    (355, CREST_PERCH), (382, CREST_PERCH),
    (415, 2.25), (455, 1.10), (505, 0.35), (555, 0.06), (X_MAX, 0.0),
]
TERRAIN_KAN_MEDIAN = [
    (0, -0.06), (100, 0.04), (160, -0.08), (205, 0.02),
    (228, H_AR_KAN), (245, 0.0), (262, -1.85),
    (280, BED_KAN), (300, BED_KAN), (320, BED_KAN),
    (338, -1.85), (355, 0.0), (372, H_AR_KAN),
    (398, 0.0), (450, -0.07), (525, 0.03), (X_MAX, -0.04),
]


def _panel_schematic(ax_a, annotated=True):
    """Panel (a): superelevated channel, beta ~ 1 (shared by P1, P2 and P3).

    With annotated=False, only the ground, water, and floodplain line are
    drawn -- for the plain visual-comparison variant (P3)."""
    xa, za = _terrain(TERRAIN_PERCHED)
    ax_a.fill_between(xa, za, -3.6, color=TERRAIN_FILL, edgecolor="none", zorder=1)
    ax_a.plot(xa, za, color=TERRAIN_EDGE, lw=1.4, zorder=4)
    _fill_water(ax_a, xa, za, WSE_PERCH, 245, 355)

    ax_a.axhline(0, color=REF_COLOR, lw=1.2, ls=(0, (5, 3)), zorder=5)
    ax_a.text(8, 0.10, "floodplain", color=REF_COLOR, fontsize=9, va="bottom")
    if not annotated:
        return

    # Gearon notation: H_AR crest->floodplain, H_M crest->bed, beta = ratio.
    # H_AR sits outside the ridge, hung from a dashed crest-level guide.
    ax_a.plot([382, 545], [CREST_PERCH, CREST_PERCH], color=ANNOT, lw=0.8,
              ls=(0, (3, 3)), zorder=5)
    _vbracket(ax_a, 538, 0.0, CREST_PERCH, "$H_{AR}$", dx_text=10)
    _vbracket(ax_a, 300, BED_PERCH, CREST_PERCH, "", dx_text=0)
    ax_a.text(300, 2.02, "$H_M$", ha="center", va="center", fontsize=10,
              color=ANNOT, zorder=7,
              bbox=dict(facecolor="#FFFFFF", edgecolor="none", pad=1.5))
    ax_a.annotate("water above\nthe floodplain",
                  xy=(252, WSE_PERCH + 0.04), xytext=(20, 2.25), fontsize=9,
                  color=WATER_EDGE, ha="left", va="center",
                  arrowprops=dict(arrowstyle="-", color=WATER_EDGE, lw=0.9))
    ax_a.text(300, -0.42, "bed aggraded to floodplain grade",
              ha="center", va="top", fontsize=9, color=TERRAIN_EDGE, zorder=6)
    ax_a.text(0.03, 0.05,
              r"$\beta = H_{AR}/H_M \approx 1$",
              transform=ax_a.transAxes, fontsize=11, color=ANNOT,
              ha="left", va="bottom")

    ax_a.set_title("(a) Superelevated channel — avulsion setup\n"
                   "(schematic, after Gearon et al., 2024)", fontsize=10)


def figure_p1():
    config.apply_style()
    fig, axes = plt.subplots(
        1, 2, figsize=(config.FIG_WIDTH_FULL, 3.4), sharey=True,
        gridspec_kw=dict(wspace=0.06))
    ax_a, ax_b = axes
    _panel_schematic(ax_a)

    # ---------------- Panel (b): measured Kanektok medians -------------------
    xb, zb = _terrain(TERRAIN_KAN_MEDIAN)
    ax_b.fill_between(xb, zb, -3.6, color=TERRAIN_FILL, edgecolor="none", zorder=1)
    ax_b.plot(xb, zb, color=TERRAIN_EDGE, lw=1.4, zorder=4)
    _fill_water(ax_b, xb, zb, FREEBOARD_KAN, 240, 360)

    ax_b.axhline(0, color=REF_COLOR, lw=1.2, ls=(0, (5, 3)), zorder=5)
    ax_b.text(8, 0.10, "floodplain reference", color=REF_COLOR, fontsize=9,
              va="bottom")

    # The "ridge": +0.14 m, barely clear of the line width.
    ax_b.annotate(r"$H_{AR}$ = +0.14 m",
                  xy=(372, H_AR_KAN), xytext=(400, 1.05), fontsize=9,
                  color=ANNOT, ha="left", va="center",
                  arrowprops=dict(arrowstyle="-", color=ANNOT, lw=0.9))
    _vbracket(ax_b, 205, BED_KAN, H_AR_KAN, "", dx_text=0)
    ax_b.text(205, -1.33, "$H_M$\n2.86 m", ha="center", va="center",
              fontsize=9, color=ANNOT, zorder=7,
              bbox=dict(facecolor=TERRAIN_FILL, edgecolor="none", pad=1.5))
    _vbracket(ax_b, 435, FREEBOARD_KAN, 0.0, "water\n$-$1.50 m", dx_text=10)
    ax_b.annotate("bed = water $-$ 1.30 m\n(ADCP depth)",
                  xy=(326, -2.76), xytext=(485, -2.35), fontsize=9,
                  color=TERRAIN_EDGE, ha="center", va="center", zorder=6,
                  arrowprops=dict(arrowstyle="-", color=TERRAIN_EDGE, lw=0.8))
    ax_b.text(0.03, 0.03,
              r"$\beta = 0.14/2.86 = 0.06$",
              transform=ax_b.transAxes, fontsize=11, color=ANNOT,
              ha="left", va="bottom")

    ax_b.set_title("(b) Kanektok River — measured\n"
                   "(median geometry, 64 DEM arcs)", fontsize=10)

    _shared_cosmetics(fig, axes)
    return config.savefig(fig, "P1_superelevation_comparison", subdir=SERIES)


# --- Highest-beta arc (P2 panel b): the R = 25.0 km arc, the beta maximum of
# the 63 depth-valid arcs (thesis_canonical_values.md ridge-claim audit; values
# recomputed from the tracked arcB_channels.parquet). A real ridge exists here
# (H_AR +2.34 m), but the water surface still sits below the floodplain.
H_AR_MAX = 2.34      # m, crest above the floodplain reference
H_M_MAX = 4.72       # m, crest -> bed
BETA_MAX = 0.495
WSE_MAX = -1.06      # m, median water surface below the floodplain reference
BED_MAX = H_AR_MAX - H_M_MAX   # -2.38 m: bed hung one H_M below the crest


def figure_p2():
    config.apply_style()
    fig, axes = plt.subplots(
        1, 2, figsize=(config.FIG_WIDTH_FULL, 3.4), sharey=True,
        gridspec_kw=dict(wspace=0.06))
    ax_a, ax_b = axes
    _panel_schematic(ax_a)

    # ---------------- Panel (b): highest-beta arc ----------------------------
    # High ground flanks BOTH sides (as the real arc transects show): a tall
    # bank right at the channel (the DSM crest pick) and a second ridge set
    # back behind a low bench on the other side.
    xb, zb = _terrain([
        (0, -0.02), (80, 0.04), (130, 0.40), (165, 1.60), (192, 2.25),
        (205, H_AR_MAX), (228, H_AR_MAX),
        (240, 1.0), (252, -0.6), (262, -1.9),
        (275, BED_MAX), (300, BED_MAX), (325, BED_MAX),
        (340, -1.9), (352, -0.4), (365, 0.12), (430, 0.10),
        (465, 0.70), (495, 1.95), (515, 2.15), (535, 2.15),
        (560, 1.20), (582, 0.30), (X_MAX, 0.12),
    ])
    ax_b.fill_between(xb, zb, -3.6, color=TERRAIN_FILL, edgecolor="none", zorder=1)
    ax_b.plot(xb, zb, color=TERRAIN_EDGE, lw=1.4, zorder=4)
    _fill_water(ax_b, xb, zb, WSE_MAX, 240, 360)

    ax_b.axhline(0, color=REF_COLOR, lw=1.2, ls=(0, (5, 3)), zorder=5)
    ax_b.text(398, 0.16, "floodplain\nreference", color=REF_COLOR,
              fontsize=8.5, ha="center", va="bottom", zorder=6)

    # A real ridge this time: H_AR gets a true bracket off a crest guide.
    ax_b.plot([45, 205], [H_AR_MAX, H_AR_MAX], color=ANNOT, lw=0.8,
              ls=(0, (3, 3)), zorder=5)
    ax_b.plot([228, 308], [H_AR_MAX, H_AR_MAX], color=ANNOT, lw=0.8,
              ls=(0, (3, 3)), zorder=5)
    ax_b.text(122, 2.52, "$H_{AR}$ = +2.34 m\n(DSM crest pick)", ha="center",
              va="bottom", fontsize=9, color=ANNOT, zorder=7)
    _vbracket(ax_b, 52, 0.0, H_AR_MAX, "", dx_text=0)
    _vbracket(ax_b, 300, BED_MAX, H_AR_MAX, "", dx_text=0)
    ax_b.text(300, 1.55, "$H_M$\n4.72 m", ha="center", va="center",
              fontsize=9, color=ANNOT, zorder=7,
              bbox=dict(facecolor="#FFFFFF", edgecolor="none", pad=1.5))
    _vbracket(ax_b, 405, WSE_MAX, 0.0, "water\n$-$1.06 m", dx_text=10)
    ax_b.annotate("water still below\nthe floodplain",
                  xy=(268, WSE_MAX - 0.22), xytext=(148, -2.45), fontsize=9,
                  color=WATER_EDGE, ha="center", va="center", zorder=6,
                  arrowprops=dict(arrowstyle="-", color=WATER_EDGE, lw=0.9))
    ax_b.text(500, 2.35, "second ridge,\nset back", ha="center", va="bottom",
              fontsize=8.5, color=TERRAIN_EDGE, zorder=6)
    ax_b.text(0.03, 0.03,
              r"$\beta = 2.34/4.72 = 0.495$",
              transform=ax_b.transAxes, fontsize=11, color=ANNOT,
              ha="left", va="bottom")
    ax_b.text(0.97, 0.03, "the highest $\\beta$ of the 63 arcs —\nno arc reaches 0.5",
              transform=ax_b.transAxes, fontsize=9, color=TERRAIN_EDGE,
              ha="right", va="bottom", zorder=6)

    ax_b.set_title("(b) Kanektok River — highest-$\\beta$ arc\n"
                   "(single arc, 25.0 km from the anchor)", fontsize=10)

    _shared_cosmetics(fig, axes)
    return config.savefig(fig, "P2_superelevation_maxbeta", subdir=SERIES)


def figure_p3():
    """P3 -- the plain visual comparison: no notation, no numbers, just where
    the water sits relative to the floodplain in each configuration."""
    config.apply_style()
    fig, axes = plt.subplots(
        1, 2, figsize=(config.FIG_WIDTH_FULL, 3.4), sharey=True,
        gridspec_kw=dict(wspace=0.06))
    ax_a, ax_b = axes

    _panel_schematic(ax_a, annotated=False)
    ax_a.annotate("water above\nthe floodplain",
                  xy=(252, WSE_PERCH + 0.04), xytext=(20, 2.25), fontsize=10,
                  color=WATER_EDGE, ha="left", va="center",
                  arrowprops=dict(arrowstyle="-", color=WATER_EDGE, lw=0.9))
    ax_a.set_title("(a) A superelevated river —\nready to spill toward a new course",
                   fontsize=10)

    xb, zb = _terrain(TERRAIN_KAN_MEDIAN)
    ax_b.fill_between(xb, zb, -3.6, color=TERRAIN_FILL, edgecolor="none", zorder=1)
    ax_b.plot(xb, zb, color=TERRAIN_EDGE, lw=1.4, zorder=4)
    _fill_water(ax_b, xb, zb, FREEBOARD_KAN, 240, 360)
    ax_b.axhline(0, color=REF_COLOR, lw=1.2, ls=(0, (5, 3)), zorder=5)
    ax_b.text(8, 0.10, "floodplain", color=REF_COLOR, fontsize=9, va="bottom")
    ax_b.annotate("water below\nthe floodplain",
                  xy=(300, FREEBOARD_KAN + 0.02), xytext=(455, 1.35), fontsize=10,
                  color=WATER_EDGE, ha="center", va="center",
                  arrowprops=dict(arrowstyle="-", color=WATER_EDGE, lw=0.9))
    ax_b.set_title("(b) The Kanektok River —\nset down into its own floodplain",
                   fontsize=10)

    _shared_cosmetics(fig, axes, ylabel="Height vs the floodplain (m)")
    return config.savefig(fig, "P3_superelevation_visual", subdir=SERIES)


# --- P4: both channels on one shared floodplain (professor-requested view).
# Uyak water/floodplain numbers from the same 63-arc analysis as the Kanektok
# medians (thesis_canonical_values.md section 1.7); Uyak depth from the mouth
# reach (31-33 km), the only reach the boat survey covered on both rivers.
FREEBOARD_UYAK = -0.49    # m, median water surface below the floodplain reference
DEPTH_UYAK_MOUTH = 1.08   # m, boat ADCP, mouth reach only
BED_UYAK = FREEBOARD_UYAK - DEPTH_UYAK_MOUTH   # -1.57 m

X4_MAX = 700.0
BRK_L, BRK_R = 333.0, 367.0   # axis-break band: ~2.6 km of corridor omitted

TERRAIN_P4_KAN = [            # left block, 0..BRK_L (Kanektok, ~50 m channel)
    (0, -0.05), (40, 0.03), (80, -0.06), (110, 0.02),
    (128, H_AR_KAN), (142, 0.0), (152, -1.9),
    (165, BED_KAN), (190, BED_KAN), (215, BED_KAN),
    (228, -1.9), (238, 0.0), (250, H_AR_KAN),
    (268, 0.0), (300, -0.05), (BRK_L, 0.0),
]
TERRAIN_P4_UYAK = [           # right block, BRK_R..X4_MAX (Uyak, ~30 m channel)
    (BRK_R, -0.02), (400, 0.06), (440, -0.04), (480, 0.05), (500, 0.10),
    (512, 0.0), (520, -0.8),
    (528, BED_UYAK), (540, BED_UYAK), (552, BED_UYAK),
    (560, -0.8), (568, 0.0), (580, 0.10),
    (600, 0.02), (640, -0.05), (670, 0.04), (X4_MAX, 0.0),
]


def _draw_two_channel_base(ax):
    """Both channels on the shared floodplain (base drawing for P4 and P5):
    terrain, water, floodplain line, axis break (with its ~2.6 km label),
    channel names."""
    # Left block: the Kanektok, measured medians.
    xk, zk = _terrain(TERRAIN_P4_KAN, 0.0, BRK_L, 670)
    ax.fill_between(xk, zk, -3.6, color=TERRAIN_FILL, edgecolor="none", zorder=1)
    ax.plot(xk, zk, color=TERRAIN_EDGE, lw=1.4, zorder=4)
    _fill_water(ax, xk, zk, FREEBOARD_KAN, 140, 240)

    # Right block: the Uyak, nearly at grade. The submerged bed is dashed --
    # its depth comes from the mouth reach only.
    xu, zu = _terrain(TERRAIN_P4_UYAK, BRK_R, X4_MAX, 670)
    ax.fill_between(xu, zu, -3.6, color=TERRAIN_FILL, edgecolor="none", zorder=1)
    ch = (xu >= 512) & (xu <= 568)
    ax.plot(xu[~ch & (xu < 540)], zu[~ch & (xu < 540)],
            color=TERRAIN_EDGE, lw=1.4, zorder=4)
    ax.plot(xu[~ch & (xu > 540)], zu[~ch & (xu > 540)],
            color=TERRAIN_EDGE, lw=1.4, zorder=4)
    ax.plot(xu[ch], zu[ch], color=TERRAIN_EDGE, lw=1.4, ls=(0, (3, 2)), zorder=4)
    _fill_water(ax, xu, zu, FREEBOARD_UYAK, 508, 572)

    # Floodplain reference, continuous across the break: one shared plain.
    ax.axhline(0, color=REF_COLOR, lw=1.2, ls=(0, (5, 3)), zorder=5)
    ax.text(8, 0.12, "floodplain", color=REF_COLOR, fontsize=9, va="bottom")

    # Axis break: white band + wavy edges, ~2.6 km of corridor omitted.
    ax.axvspan(BRK_L, BRK_R, color="#FFFFFF", zorder=3, lw=0)
    zz = np.linspace(-3.6, 0.45, 200)
    for xb in (BRK_L, BRK_R):
        ax.plot(xb + 5.0 * np.sin(zz * 5.5), zz, color=TERRAIN_EDGE, lw=1.1,
                zorder=4, solid_capstyle="round")
    ax.text((BRK_L + BRK_R) / 2, -1.75, "$\\approx$ 2.6 km", rotation=90,
            ha="center", va="center", fontsize=8, color=TERRAIN_EDGE, zorder=6)

    # Channel names.
    ax.text(190, 0.62, "Kanektok River", ha="center", va="bottom", fontsize=10)
    ax.text(540, 0.62, "Uyak Creek", ha="center", va="bottom", fontsize=10)


def figure_p4():
    """P4 -- Kanektok vs Uyak on the one floodplain they share: a composite
    arc transect at matched radius, the inter-channel corridor collapsed to an
    axis break. Both waters below the plain; the Kanektok ~1 m lower."""
    config.apply_style()
    fig, ax = plt.subplots(figsize=(config.FIG_WIDTH_FULL, 3.4))
    _draw_two_channel_base(ax)

    # Water levels vs the plain.
    _vbracket(ax, 95, FREEBOARD_KAN, 0.0, "water\n$-$1.50 m", dx_text=-10,
              ha="right")
    _vbracket(ax, 620, FREEBOARD_UYAK, 0.0, "", dx_text=0)
    ax.annotate("water $-$0.49 m —\nnearly at grade",
                xy=(626, FREEBOARD_UYAK / 2), xytext=(612, 1.15), fontsize=9,
                color=ANNOT, ha="center", va="bottom", zorder=7,
                arrowprops=dict(arrowstyle="-", color=ANNOT, lw=0.8))
    ax.text(540, BED_UYAK - 0.28, "(depth measured\nnear the mouth)",
            ha="center", va="top", fontsize=8, color=TERRAIN_EDGE, zorder=6)
    ax.annotate("bed = water $-$ 1.30 m\n(ADCP depth)",
                xy=(172, BED_KAN - 0.02), xytext=(112, -3.02), fontsize=8,
                color=TERRAIN_EDGE, ha="center", va="center", zorder=6,
                arrowprops=dict(arrowstyle="-", color=TERRAIN_EDGE, lw=0.8))

    # The punchline: carry the Kanektok's water level across the plain -- the
    # Uyak's water rides ~1 m above it.
    ax.plot([243, BRK_L], [FREEBOARD_KAN, FREEBOARD_KAN], color=WATER_EDGE,
            lw=0.9, ls=(0, (1.5, 2.5)), zorder=5)
    ax.plot([BRK_R, 470], [FREEBOARD_KAN, FREEBOARD_KAN], color=WATER_EDGE,
            lw=0.9, ls=(0, (1.5, 2.5)), zorder=5)
    ax.plot([440, 505], [FREEBOARD_UYAK, FREEBOARD_UYAK], color=WATER_EDGE,
            lw=0.9, ls=(0, (1.5, 2.5)), zorder=5)
    _vbracket(ax, 452, FREEBOARD_KAN, FREEBOARD_UYAK, "", dx_text=0)
    ax.text(440, -1.0, "the Kanektok runs\n$\\approx$ 1 m lower",
            ha="right", va="center", fontsize=9, color=ANNOT, zorder=7)

    ax.set_title("One floodplain, two channels — both below grade,"
                 " the Kanektok $\\approx$ 1 m lower\n"
                 "(measured medians at matched distance from the anchor,"
                 " 63 DEM arcs)", fontsize=10)

    _shared_cosmetics(
        fig, [ax], ylabel="Height vs the floodplain (m)",
        note="one arc across the floodplain — horizontal compressed and the "
             "corridor between the channels omitted; true slopes are far gentler",
        x_max=X4_MAX)
    return config.savefig(fig, "P4_two_channel_transect", subdir=SERIES)


def figure_p5():
    """P5 -- the two-channel transect with no numbers (companion to P3): just
    where each river's water sits relative to the floodplain they share."""
    config.apply_style()
    fig, ax = plt.subplots(figsize=(config.FIG_WIDTH_FULL, 3.4))
    _draw_two_channel_base(ax)

    ax.annotate("water well below\nthe floodplain",
                xy=(150, FREEBOARD_KAN + 0.04), xytext=(75, -2.55), fontsize=10,
                color=WATER_EDGE, ha="center", va="center", zorder=6,
                arrowprops=dict(arrowstyle="-", color=WATER_EDGE, lw=0.9))
    ax.annotate("water just below\nthe floodplain",
                xy=(566, FREEBOARD_UYAK - 0.06), xytext=(645, -1.55),
                fontsize=10, color=WATER_EDGE, ha="center", va="center",
                zorder=6, arrowprops=dict(arrowstyle="-", color=WATER_EDGE,
                                          lw=0.9))

    # The comparison, in words: dotted level guides meeting at a bracket.
    ax.plot([243, BRK_L], [FREEBOARD_KAN, FREEBOARD_KAN], color=WATER_EDGE,
            lw=0.9, ls=(0, (1.5, 2.5)), zorder=5)
    ax.plot([BRK_R, 470], [FREEBOARD_KAN, FREEBOARD_KAN], color=WATER_EDGE,
            lw=0.9, ls=(0, (1.5, 2.5)), zorder=5)
    ax.plot([440, 505], [FREEBOARD_UYAK, FREEBOARD_UYAK], color=WATER_EDGE,
            lw=0.9, ls=(0, (1.5, 2.5)), zorder=5)
    _vbracket(ax, 452, FREEBOARD_KAN, FREEBOARD_UYAK, "", dx_text=0)
    ax.text(452, -2.0, "the Kanektok\nruns lower",
            ha="center", va="center", fontsize=10, color=ANNOT, zorder=7)

    ax.set_title("One floodplain, two channels — and the Kanektok is the low road",
                 fontsize=10)

    _shared_cosmetics(
        fig, [ax], ylabel="Height vs the floodplain (m)",
        note="one arc across the floodplain — horizontal compressed and the "
             "corridor between the channels omitted; true slopes are far gentler",
        x_max=X4_MAX)
    return config.savefig(fig, "P5_two_channel_visual", subdir=SERIES)


# --- P6: the bifurcation virtual gauge (data figure, not a schematic).
# Reads the per-pass results of bifurcation_gauge.py: local gradient over the
# fixed radial 3.5-7.5 km window vs stage at each river's virtual gauge, sited
# 1 km along-channel past the split.
GAUGE_PARQUET = "temporal_results/bifurcation_gauge_per_pass.parquet"
GAUGE_SUMMARY = "temporal_results/bifurcation_gauge_results.json"


def figure_p6():
    """P6 -- the bifurcation virtual gauge.

    (a) each river's local gradient against its gauge stage; (b) the two water
    surfaces below the split, which leave the bifurcation together and separate
    downstream as the steeper channel outruns the other.
    """
    import json

    config.apply_style()
    per = pd.read_parquet(GAUGE_PARQUET)
    with open(GAUGE_SUMMARY) as f:
        summ = json.load(f)
    g = per[per["gated"]]
    div = pd.DataFrame(summ["stage_divergence"])

    fig, (ax, ax2) = plt.subplots(
        1, 2, figsize=(config.FIG_WIDTH_FULL + 0.9, 3.3),
        gridspec_kw={"width_ratios": [1.75, 1]}, constrained_layout=True)

    for reach in ["Kanektok_River", "Uyak_Creek"]:
        d = g[g["reach"] == reach]
        c = config.river_color(reach)
        ax.plot(np.asarray(d["stage_m"], dtype=float),
                np.asarray(d["slope_cm_km"], dtype=float),
                linestyle="none", marker="o", ms=4.5, color=c, alpha=0.55,
                label=config.river_label(reach), zorder=3)
        ax.axhline(float(np.median(np.asarray(d["slope_cm_km"], dtype=float))),
                   color=c, ls=":", lw=1.2, alpha=0.8, zorder=2)
    ax.set_ylabel("Hydraulic Gradient (cm/km)")
    ax.set_xlabel("Stage at the virtual gauge (m)")
    ax.legend(loc="center left")
    ax.set_title("(a)  Gradient vs stage", fontsize=10, loc="left")

    # (b) the two water surfaces separating below the split.
    for reach, wse, q1, q3 in [
            ("Kanektok_River", "kanektok_wse_m", "kanektok_q1_m", "kanektok_q3_m"),
            ("Uyak_Creek", "uyak_wse_m", "uyak_q1_m", "uyak_q3_m")]:
        c = config.river_color(reach)
        ax2.fill_between(div["s_km"], div[q1], div[q3], color=c, alpha=0.15, lw=0)
        ax2.plot(div["s_km"], div[wse], color=c, lw=1.6, marker="o", ms=3.2,
                 label=config.river_label(reach), zorder=3)
    # Label the gap at both ends: they leave the split together, and by 3 km
    # the steeper Kanektok has dropped half a metre below the Uyak.
    span = div["s_km"].iloc[-1] - div["s_km"].iloc[0]
    ax2.set_xlim(div["s_km"].iloc[0] - 0.22 * span, div["s_km"].iloc[-1] + 0.22 * span)
    for row, side in ((div.iloc[0], "left"), (div.iloc[-1], "right")):
        mid = (row.kanektok_wse_m + row.uyak_wse_m) / 2
        if abs(row.gap_median_m) > 0.15:      # an arrow only where it can be seen
            ax2.annotate("", xy=(row.s_km, row.kanektok_wse_m),
                         xytext=(row.s_km, row.uyak_wse_m),
                         arrowprops=dict(arrowstyle="<->", lw=0.8, color="0.25"))
        ax2.annotate(f"{abs(row.gap_median_m):.2f} m", xy=(row.s_km, mid),
                     xytext=(7 if side == "left" else -7, 0),
                     textcoords="offset points", fontsize=7.5, color="0.25",
                     va="center", ha="left" if side == "left" else "right")
    ax2.set_xlabel("Along-channel distance past the split (km)", fontsize=9)
    ax2.set_ylabel("Water-surface elevation (m)")
    ax2.set_title("(b)  The surfaces separate", fontsize=10, loc="left")

    return config.savefig(fig, "P6_bifurcation_gauge", subdir=SERIES)


def figure_p7(zoom: int = 15, pad_frac: float = 0.0, points: bool = False):
    """P7 -- the two channels as raw satellite imagery, with or without the data.

    An unannotated companion to Fig 10, framed on the bifurcation so both
    channels are in view at once: the Kanektok leaves the split as a broad,
    bright, multi-thread braid, the Uyak as a single dark thread an order of
    magnitude narrower. Fig 10 covers the same ground but carries the analysis
    furniture -- polygons, node clouds, gauges -- and at that density the Uyak's
    coloured mask reads just as wide as the Kanektok's, which is an artifact of
    the corridor being drawn around a braid plain rather than a channel. This
    figure strips all of it back so the channels speak for themselves; the size
    contrast is the whole point, so it is deliberately left free of overlays
    that would beg the question.

    Framed tighter than Fig 10 (~3 km wide rather than ~8) because the Uyak is
    only a few image pixels across: at Fig 10's extent it is not resolvable.

    Two caveats belong with any width claim read off this figure. The Esri
    mosaic carries an acquisition seam that runs diagonally across the scene --
    the northern half, which is the Uyak's floodplain, is from a paler and
    drier-looking pass than the southern half -- so some of the apparent
    contrast in tone is the imagery, not the rivers. And a single scene is a
    single unknown stage; the width contrast it shows is one snapshot, not a
    stage-averaged measurement. The quantitative comparison lives in the gauge
    and gradient figures, not here.

    `points` draws the SWOT node cloud over the same scene at the house alpha,
    producing the second half of a side-by-side pair: identical extent, figure
    size, zoom and furniture, so the only thing that changes between the two is
    the data. The pair is the cleanest way to show what the corridor masks cost.
    Read left to right, the Uyak's cloud is revealed to be as broad as the
    Kanektok's even though the imagery beneath it is a single thread a few
    pixels wide -- the artifact P7's caption describes in words, made visible --
    and the straight diagonal seam where the two clouds meet is the boundary
    between the analysis polygons, not anything in the river.

    Dots are larger here than in Figs 1 and 10 (s=4.5 vs 1.8/2.6) for the same
    reason Fig 10's are larger than Fig 1's: each SWOT pixel covers far more
    screen area at this zoom, and at the smaller size the sampling lattice
    itself shows through as texture and reads as noise. The alpha is unchanged
    from every other node cloud in the thesis, so density still means density.

    Basemap tiles are fetched at build time (needs network).
    """
    import contextily as cx
    from pyproj import Transformer

    from .make_figures import _mercator_scalebar, _north_arrow

    config.apply_style()
    WEBM = 3857
    tf = Transformer.from_crs(4326, WEBM, always_xy=True)

    # Window centred on the bifurcation (-161.3778, 59.8289): far enough west to
    # carry a few km of each channel below the split, tight enough that the Uyak
    # thread is more than one pixel wide.
    x0, y0 = tf.transform(-161.410, 59.816)
    x1, y1 = tf.transform(-161.355, 59.840)
    dx, dy = (x1 - x0) * pad_frac, (y1 - y0) * pad_frac

    fig, ax = plt.subplots(
        figsize=(config.FIG_WIDTH_FULL,
                 config.FIG_WIDTH_FULL * ((y1 - y0) + 2 * dy) / ((x1 - x0) + 2 * dx)))
    ax.set_xlim(x0 - dx, x1 + dx)
    ax.set_ylim(y0 - dy, y1 + dy)
    ax.set_aspect("equal")
    cx.add_basemap(ax, crs=WEBM, source=cx.providers.Esri.WorldImagery,
                   zoom=zoom, attribution=False, zorder=0)

    if points:
        from . import core

        # Every node in frame, not a sample: the whole claim is how much ground
        # the cloud covers, so thinning it would understate the figure's point.
        con = core.connect()
        pts = core.load_swot(con, reaches=list(config.COLOR_MAP),
                             open_water_only=True)
        # Clip generously past the axis limits -- points just outside still paint
        # partially inside, and cropping at the limits leaves a visible hard edge.
        pts = pts[pts["longitude"].between(-161.42, -161.345)
                  & pts["latitude"].between(59.810, 59.846)]
        # Uyak last, as everywhere else, so the narrower river is never buried.
        for reach in sorted(config.COLOR_MAP, key=lambda r: r == "Uyak_Creek"):
            d = pts[pts["Reach_Name"] == reach]
            px, py = tf.transform(d["longitude"].to_numpy(),
                                  d["latitude"].to_numpy())
            ax.scatter(px, py, s=4.5, color=config.river_color(reach),
                       alpha=0.09, edgecolor="none",   # house node-cloud alpha (Figs 1, 10)
                       rasterized=True, zorder=4)
        # Deliberately no legend. The panel is meant to be shown beside the
        # overlay-free one, where the imagery is the subject and a keyed box in
        # the corner both covers it and pulls the eye off it; the two colours get
        # named on the slide or in the talk instead.

    # Full-bleed: no ticks, no frame, no graticule -- just the imagery.
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Furniture only. A 1 km bar on a ~3 km frame; both sit over the darker
    # southern floodplain, where white reads cleanly.
    #
    # Label set well above the 11pt house default. Scale-bar legibility is a
    # *displayed* size problem, and this is the largest render in the set (6.5 in
    # wide and nearly square, against Fig 1's 6.5 x 2.2), so it is scaled down
    # hardest to fit a slide -- and this pair is meant to be shown two-up, which
    # halves it again. At the default the label lands roughly half the on-screen
    # size of Fig 1's. 20pt restores parity for a two-up slide; the halo is
    # raised with it to hold the ~1:8.5 stroke-to-glyph ratio that keeps the
    # counters of "km" open.
    _mercator_scalebar(ax, km=1, center_lat=59.828, loc=(0.06, 0.06),
                       fontsize=20, stroke_lw=2.4)
    _north_arrow(ax, loc=(0.93, 0.10), zoom=0.20,
                 icon_path=config.NORTH_ICON_PATH)

    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    name = "P7_channel_imagery_swot" if points else "P7_channel_imagery"
    return config.savefig(fig, name, subdir=SERIES)


def figure_p8(zoom: int = 13, pad_frac: float = 0.07, bare: bool = False):
    """P8 -- Fig 10's frame with the analysis stripped off, for A/B flipping.

    Identical extent, figure size, zoom and furniture placement to Fig 10, with
    everything derived from data removed: no polygons, no node clouds, no
    centerlines, no anchor/bifurcation/gauge markers, no legend. Flipped back
    and forth against Fig 10 in a deck, the two register exactly, so the only
    thing that changes between slides is the analysis overlay itself.

    That the Uyak is barely legible here is the point, not a defect. At this
    extent its channel is roughly one image pixel wide, while Fig 10 draws it as
    a corridor as broad as the Kanektok's -- because the corridor is fitted
    around the braid plain the SWOT pixels come from, not around the channel.
    The flip makes the gap between what the analysis polygon depicts and what is
    actually in the water visible in one gesture. P7 is the close-up that shows
    the Uyak's thread resolved; this is the wide pair that shows why the
    close-up was needed.

    `bare` drops the degree ticks for a full-bleed slide. It is off by default:
    the ticks are what guarantee the saved image crops to the same box as Fig
    10's, and a bare render shifts the map slightly under the tight bounding
    box, which shows up as a jump when the slides are flipped.

    Basemap tiles are fetched at build time (needs network).
    """
    import contextily as cx
    from pyproj import Transformer

    from .make_figures import _mercator_scalebar, _north_arrow

    config.apply_style()
    WEBM = 3857
    tf = Transformer.from_crs(4326, WEBM, always_xy=True)

    # Extent copied from build_fig10 verbatim -- including the asymmetric top
    # headroom, which exists there to park the legend. It is empty tundra here,
    # but it has to stay or the frames do not register.
    x0, y0 = tf.transform(-161.476, 59.803)
    x1, y1 = tf.transform(-161.339, 59.843)
    dx = (x1 - x0) * pad_frac
    xlim = (x0 - dx, x1 + dx)
    ylim = (y0 - (y1 - y0) * 0.10, y1 + (y1 - y0) * 0.34)

    fig, ax = plt.subplots(figsize=(config.FIG_WIDTH_FULL,
                                    config.FIG_WIDTH_FULL / 1.4))
    ax.set_xlim(*xlim); ax.set_ylim(*ylim)
    ax.set_aspect("equal")
    cx.add_basemap(ax, crs=WEBM, source=cx.providers.Esri.WorldImagery,
                   zoom=zoom, attribution=False, zorder=0)

    if bare:
        ax.set_xticks([]); ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
    else:
        # Same graticule as Fig 10, so the two slides crop identically.
        lon_ticks = [-161.46, -161.42, -161.38, -161.34]
        lat_ticks = [59.81, 59.82, 59.83, 59.84]
        ax.set_xticks([tf.transform(lo, lat_ticks[0])[0] for lo in lon_ticks])
        ax.set_xticklabels([f"{abs(lo):.2f}°W" for lo in lon_ticks])
        ax.set_yticks([tf.transform(lon_ticks[0], la)[1] for la in lat_ticks])
        ax.set_yticklabels([f"{la:.2f}°N" for la in lat_ticks])
        ax.tick_params(direction="out")
    ax.grid(False)

    # Furniture in Fig 10's exact positions so it does not move on the flip.
    _mercator_scalebar(ax, km=2, center_lat=59.82, loc=(0.42, 0.06))
    _north_arrow(ax, loc=(0.91, 0.115), zoom=0.20,
                 icon_path=config.NORTH_ICON_PATH)

    name = "P8_fig10_extent_bare" if bare else "P8_fig10_extent"
    return config.savefig(fig, name, subdir=SERIES)


def _shared_cosmetics(fig, axes, ylabel="Elevation vs floodplain reference (m)",
                      note="across the floodplain — horizontal compressed; "
                           "true slopes are far gentler",
                      x_max=X_MAX):
    for ax in axes:
        ax.set_xlim(0, x_max)
        ax.set_ylim(-3.6, 3.6)
        ax.set_xticks([])
        ax.grid(False)
        ax.spines["bottom"].set_visible(False)
    axes[0].set_ylabel(ylabel)
    fig.text(0.54, 0.015, note,
             ha="center", va="bottom", fontsize=9, style="italic")
    fig.subplots_adjust(left=0.09, right=0.985, top=0.86, bottom=0.09)


if __name__ == "__main__":
    for p in (figure_p1() + figure_p2() + figure_p3() + figure_p4()
              + figure_p5() + figure_p6()
              + figure_p7() + figure_p7(points=True)
              + figure_p8() + figure_p8(bare=True)):
        print(p)
