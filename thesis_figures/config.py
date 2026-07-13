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
# Repo root = parent of this file's directory (thesis_figures/).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Default data source = the FULL local archive (2023-2026), NOT the deployment
# subset. The thesis methodology cites "121 open-water overpasses", which is the
# full archive; dashboard_data.parquet holds only ~60. Figures must match the text.
FULL_DATA_PATH = os.path.join(REPO_ROOT, "batch_outputs", "master_all_data.parquet")
DEPLOY_DATA_PATH = os.path.join(REPO_ROOT, "dashboard_data.parquet")  # deployment subset
DATA_PATH = FULL_DATA_PATH
REF_GRADIENT_PATH = os.path.join(REPO_ROOT, "batch_outputs", "reference_gradient_per_pass.parquet")
DEM_PATH = os.path.join(REPO_ROOT, "batch_outputs", "dem_river_elevations.parquet")
TEMPORAL_DIR = os.path.join(REPO_ROOT, "temporal_results")

# Where rendered figures are written.
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

# Assets bundled with the figure module (kept in-repo for reproducibility).
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
# Nalaquq (Quinhagak) village map icon, used as the Fig 1 north arrow -- the icon
# already includes the "N" + arrowhead. White variant reads over dark imagery.
NORTH_ICON_PATH = os.path.join(ASSETS_DIR, "nalaquq_north_white.png")

# --- STUDY-AREA CONSTANTS (kept in sync with dashboard_swot.py) ------------
ANCHOR_LAT = 59.82463509
ANCHOR_LON = -161.33397834
BIFURCATION_LAT = 59.828886
BIFURCATION_LON = -161.377778
BIFURCATION_DIST_KM = 2.493

# Residual-domain outlier flag for the Detrended Profile (matches dashboard).
RESIDUAL_MAD_THRESHOLD = 3.5  # Modified Z-score (Iglewicz & Hoaglin 1993)

# --- QC: FLAGGED / EXCLUDED PASSES -----------------------------------------
# Documented registry of satellite passes excluded from ALL figures as a single
# source of truth (core applies it to every data path). This is a QC flag list,
# NOT a raw-data edit -- the parquet is left intact and inspectable; the pass is
# only filtered at load/analysis time, preserving provenance and reproducibility.
# Each entry: 'YYYY-MM-DD': 'reason (evidence)'.
EXCLUDED_PASSES = {
    "2025-04-17": (
        "Spring-breakup ice contamination: reach gradient anomalously steep on BOTH "
        "channels simultaneously (Uyak 236, Kanektok 224 cm/km vs medians 192/196) -- "
        "a synchronous basin-wide spike is an ice-event signature, not a real gradient. "
        "Robust medians are unaffected; excluded so it cannot bias means/bands/extremes."
    ),
}

# --- COLOURS ---------------------------------------------------------------
# Match the live dashboard EXACTLY: the dashboard's COLOR_MAP uses the CSS named
# colours "firebrick" / "dodgerblue", so we reuse the same names (pixel-identical,
# no hex drift) => Fig 1's dashboard screenshot agrees with Figs 5-8. Red/blue is
# colourblind-safe enough (blue is unaffected by red-green deficiency).
#   Kanektok = firebrick (#B22222), Uyak = dodgerblue (#1E90FF)
COLOR_MAP = {
    "Kanektok_River": "firebrick",
    "Uyak_Creek": "dodgerblue",
}
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


def savefig(fig, name: str, formats=FORMATS):
    """Save `fig` to OUTPUT_DIR as `name` in each requested format.

    Returns the list of written paths. Creates OUTPUT_DIR if needed.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    paths = []
    for fmt in formats:
        path = os.path.join(OUTPUT_DIR, f"{name}.{fmt}")
        fig.savefig(path, format=fmt)
        paths.append(path)
    return paths
