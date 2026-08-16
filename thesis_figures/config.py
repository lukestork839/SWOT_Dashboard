"""Publication styling and shared constants for thesis figures.

This module centralises everything that must stay *consistent across every figure*
in the thesis: fonts, sizes, colours, output paths, physical dimensions and DPI.
Import `apply_style()` at the top of any figure builder before plotting.

Design intent
-------------
Thesis figures are static, print-first artefacts, so the conventions differ from
the interactive dashboard:
  * full data (no browser-performance downsampling),
  * fixed physical width matched to the thesis text block,
  * embedded vector output (PDF) plus a high-DPI raster (PNG),
  * consistent typography and no interactive-only decoration (emoji, hover, etc.).

The *science* (detrending, Theil-Sen gradient, binning, slope) is NOT redefined
here -- it lives in `core.py`, ported verbatim from the validated dashboard so the
figures are provably identical to the analysis.
"""

from __future__ import annotations

import os

import matplotlib as mpl

# --- PATHS -----------------------------------------------------------------
# Shared locations come from swot_core.config (single source of truth for every
# consumer). The thesis default data source = the FULL local archive, NOT the
# deployment subset — figures must match the thesis text.
# Bootstrap: make the repo root importable FIRST (swot_core lives there), so this
# module also works when imported from outside the repo root.
import sys as _sys
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _repo_root not in _sys.path:
    _sys.path.insert(0, _repo_root)

from swot_core.config import (  # noqa: E402
    REPO_ROOT, FULL_DATA_PATH, DEPLOY_DATA_PATH,
    REF_GRADIENT_PATH, DEM_PATH, TEMPORAL_DIR,
)
DATA_PATH = FULL_DATA_PATH

# Where rendered figures are written.
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

# Assets bundled with the figure module (kept in-repo for reproducibility).
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
# Nalaquq (Quinhagak) village map icon, used as the Fig 1 north arrow -- the icon
# already includes the "N" + arrowhead. White variant reads over dark imagery.
NORTH_ICON_PATH = os.path.join(ASSETS_DIR, "nalaquq_north_white.png")

# --- STUDY-AREA CONSTANTS, QC LIST, COLOURS (shared via swot_core.config) ---
# Study geometry, the residual-MAD threshold, the QC exclusion registry
# (defense-in-depth re-application of qc_registry at load time), and the series
# colours are all single-sourced from swot_core.config so the figures, both
# dashboards, and (for QC) the ingestion pipeline can never disagree. The
# colours are CSS named colours, which matplotlib also resolves —
# pixel-identical to the live dashboard, no hex drift.
from swot_core.config import (  # noqa: E402
    ANCHOR_LAT, ANCHOR_LON,
    BIFURCATION_LAT, BIFURCATION_LON, BIFURCATION_DIST_KM,
    RESIDUAL_MAD_THRESHOLD, EXCLUDED_PASSES, COLOR_MAP,
)
DIFF_COLOR = "darkgreen"    # Kanektok-minus-Uyak difference series (matches dashboard)
BASELINE_COLOR = "#333333"  # trend / zero / baseline reference lines (near-black)
OUTLIER_COLOR = "#999999"   # flagged residual-domain outliers

# Dense-scatter opacity (Rule 1.6): low alpha reveals density instead of a blob.
SCATTER_ALPHA = 0.15


def river_label(reach: str) -> str:
    """Human-readable river name for axis labels and legends."""
    return reach.replace("_", " ")


def river_color(reach: str) -> str:
    return COLOR_MAP.get(reach, "black")


# --- PHYSICAL DIMENSIONS ---------------------------------------------------
# Figures are rendered at their FINAL printed width (letter page, 1-in margins =>
# 6.5-in text block) so text renders true-size with NO document scaling. Change
# FIG_WIDTH_FULL here to rescale every figure at once.
FIG_WIDTH_FULL = 6.5     # inches, full text width
FIG_WIDTH_HALF = 3.25    # inches, half width (side-by-side panels)
FIG_HEIGHT_DEFAULT = 4.0  # ~1.6 landscape ratio at full width

# Raster export resolution. 300 dpi is the thesis/print standard.
DPI = 300

# Output formats written for every figure (vector first for LaTeX/Word embedding).
FORMATS = ("pdf", "png")


def apply_style() -> None:
    """Apply the thesis-wide matplotlib rcParams. Call once before plotting.

    Conservative, journal-style defaults: serif-free clean type, hairline spines,
    inward ticks, restrained grid. Tweak here to restyle *every* figure at once.
    """
    mpl.rcParams.update({
        # Typography: SERIF to match the thesis body text (Times New Roman). TNR is
        # proprietary and usually absent on Linux, so we prefer it but fall back to
        # Liberation Serif -- metrically IDENTICAL to Times New Roman (drop-in clone),
        # then Nimbus Roman (also a Times clone). Rendered output is indistinguishable
        # from Times New Roman. Math uses STIX (Times-like) so symbols match.
        # (true-size at 6.5-in width: labels ~12pt, ticks/legend ~10pt)
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Liberation Serif", "Nimbus Roman", "DejaVu Serif"],
        "mathtext.fontset": "stix",
        "font.size": 11,
        "axes.titlesize": 12,
        "axes.labelsize": 12,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
        "figure.titlesize": 12,
        # Backgrounds: pure white everywhere (Rule 1.1)
        "figure.facecolor": "#FFFFFF",
        "axes.facecolor": "#FFFFFF",
        "savefig.facecolor": "#FFFFFF",
        # Lines & markers
        "lines.linewidth": 1.6,
        "lines.markersize": 3,
        # Axes / spines: drop top+right, keep bottom+left crisp near-black (Rule 1.2)
        "axes.linewidth": 1.0,
        "axes.edgecolor": "#000000",
        "axes.spines.top": False,
        "axes.spines.right": False,
        # Gridlines: faint light-grey dashed, major only (Rule 1.3)
        "axes.grid": True,
        "axes.grid.which": "major",
        "grid.linestyle": "--",
        "grid.linewidth": 0.5,
        "grid.alpha": 1.0,
        "grid.color": "#E0E0E0",
        # Ticks
        "xtick.direction": "out",
        "ytick.direction": "out",
        "xtick.major.width": 1.0,
        "ytick.major.width": 1.0,
        # Legend
        "legend.frameon": False,
        # Output
        "figure.dpi": 110,          # on-screen preview
        "savefig.dpi": DPI,         # file export (300)
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
        "pdf.fonttype": 42,         # embed TrueType (editable text in vector output)
        "ps.fonttype": 42,
    })


def savefig(fig, name: str, formats=FORMATS, subdir: str | None = None):
    """Save `fig` to OUTPUT_DIR as `name` in each requested format.

    `subdir` selects a series folder under OUTPUT_DIR. The SWOT and DEM writeups are
    separate documents with independent figure numbering, so their renders are kept
    apart ("SWOT_Figures" / "DEM_Figures") to stop a Figure 1 in one series from
    overwriting the Figure 1 in the other.

    Returns the list of written paths. Creates the target directory if needed.
    """
    out = OUTPUT_DIR if subdir is None else os.path.join(OUTPUT_DIR, subdir)
    os.makedirs(out, exist_ok=True)
    paths = []
    for fmt in formats:
        path = os.path.join(out, f"{name}.{fmt}")
        fig.savefig(path, format=fmt)
        paths.append(path)
    return paths
