"""Shared scientific constants and data locations for the SWOT project.

Single source of truth for every value that must agree across the researcher
dashboard, the village dashboard, and the thesis figures. Presentation-only
settings (page titles, plot point caps, figure typography) stay with their
consumer; anything that would change a NUMBER lives here.
"""

from __future__ import annotations

import os
import sys

# --- PATHS -------------------------------------------------------------------
# Repo root = parent of this file's directory (swot_core/).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(REPO_ROOT, "batch_outputs")
# Full local archive (thesis + local dev) vs the deployment subset behind the
# stable release URL (Streamlit Cloud).
FULL_DATA_PATH = os.path.join(DATA_DIR, "master_all_data.parquet")
DEPLOY_DATA_PATH = os.path.join(REPO_ROOT, "dashboard_data.parquet")
REF_GRADIENT_PATH = os.path.join(DATA_DIR, "reference_gradient_per_pass.parquet")
DEM_PATH = os.path.join(DATA_DIR, "dem_river_elevations.parquet")
TEMPORAL_DIR = os.path.join(REPO_ROOT, "temporal_results")

# Stable release-asset URLs (the file behind each URL is swapped at deploy time;
# the URL itself never changes — see docs/development_notes.md deploy recipe).
REMOTE_PARQUET_URL = "https://github.com/lukestork839/SWOT_Dashboard/releases/download/v2.0-data/dashboard_data.parquet"
REMOTE_DEM_URL = "https://github.com/lukestork839/SWOT_Dashboard/releases/download/v2.0-data/dem_river_elevations.parquet"
REMOTE_REFGRAD_URL = "https://github.com/lukestork839/SWOT_Dashboard/releases/download/v2.0-data/reference_gradient_per_pass.parquet"

# --- STUDY AREA ----------------------------------------------------------------
# 0 km = the ANCHOR POINT, the common origin all dist_km values are measured
# from (radially, Haversine). It sits ~2.5 km UPRIVER of the bifurcation — it
# is NOT a confluence and NOT the bifurcation itself.
ANCHOR_LAT = 59.82463509
ANCHOR_LON = -161.33397834
# Where Kanektok River and Uyak Creek diverge (59°49'43.99"N, 161°22'40.00"W)
BIFURCATION_LAT = 59.828886
BIFURCATION_LON = -161.377778
BIFURCATION_DIST_KM = 2.493  # Haversine distance from anchor point

REACH_NAMES = ("Kanektok_River", "Uyak_Creek")

# Series colours shared by both dashboards and the thesis figures (CSS named
# colours; thesis matplotlib resolves the same names — pixel-identical).
COLOR_MAP = {
    "Kanektok_River": "firebrick",
    "Uyak_Creek": "dodgerblue",
}

# --- ANALYSIS CONSTANTS --------------------------------------------------------
# Open-water months (Apr–Nov): ice season (Dec–Mar) inflates WSE by 0.5–2+ m and
# is excluded from every analysis view. (Ingestion applies the stricter May–Oct
# hard line via qc_registry.ICE_SAFE_MONTHS when building master products.)
OPEN_WATER_MONTHS = (4, 5, 6, 7, 8, 9, 10, 11)

# Residual-domain Modified Z-Score flag threshold (Iglewicz & Hoaglin 1993).
# Same estimator as the ingestion MAD filter; applied by consumers to residuals
# from a cross-pass baseline so whole-pass contamination is also isolatable.
RESIDUAL_MAD_THRESHOLD = 3.5

# --- QC REGISTRY RE-EXPORT -------------------------------------------------------
# qc_registry.py stays at the repo root because the ingestion pipeline
# (SWOT_Pull.py) imports it there; re-export rather than move so there is
# still exactly one registry object.
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from qc_registry import KNOWN_BAD_PASSES, ICE_SAFE_MONTHS  # noqa: E402,F401

# Consumer-side QC exclusion list (defense-in-depth against a stale master
# parquet; ingestion already drops these upstream). Alias kept for readability.
EXCLUDED_PASSES = KNOWN_BAD_PASSES
