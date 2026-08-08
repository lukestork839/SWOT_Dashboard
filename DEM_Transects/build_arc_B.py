"""
Approach B — radial "iso-distance-from-anchor" arc transects.

Each transect is the ARC of points at a constant straight-line distance (radius) from the
shared divergence anchor — so every point on it is the same "downstream" distance the SWOT
dashboard uses. An arc at radius R is a single cross-valley cut spanning
Kanektok -> floodplain -> Uyak, letting the two rivers be compared side-by-side at a matched
downstream position (the fan/delta radial-distance-from-apex convention; see research notes).

Each channel is located by SNAPPING to the actual DEM low: both channels use a field-surveyed
centerline as the prior (Uyak from a hunter's boat GPS, Kanektok from a boat ADCP thalweg run),
accurate to the real channel (~20-50 m), so a TIGHT search window suffices. Within that window
(clipped at the midpoint between the two channels) the thalweg is the centroid of the deepest
terrain, and the water surface is a void-robust low percentile in a tight window on it. A
floodplain reference (median of the corridor between the channels) then gives each channel's
superelevation = water surface - corridor, the actual avulsion criterion.

Precedent/caveat (Merwade et al. 2006): straight-line radius = along-channel flow distance
ONLY where the channel runs straight from the anchor. The validity panel below quantifies each
river's bearing drift with radius so we know which reach the arc frame is trustworthy over.

SWOT does three jobs here that the DEM cannot do alone (all via data/swot_arc_reference.parquet,
built by swot_arc_reference.py — see that script for the reasoning):
  - sets the vertical datum per radius (EGM2008 runs 13.77 m at the anchor to 13.27 m at the coast;
    a constant offset cancels within an arc but tilts any DEM-vs-SWOT comparison),
  - supplies the stage DISTRIBUTION, so superelevation is quoted at a declared stage with a band
    instead of at whatever stage the multi-date DEM mosaic happened to catch,
  - supplies a same-stage channel bed (SWOT overflew during the 2026 boat-ADCP survey) and the
    pass-paired Uyak−Kanektok difference, which is the only version of that comparison with the
    differential-stage artifact removed.

Deliverables — figures to DEM_Transects/outputs/ (scratch), the two dashboard parquets to data/ (tracked/hosted):
  - arcB_sections.png     example arc cross-sections, Kanektok-centered (x=0) toward the Uyak, with
                          the Gearon β anatomy (bed ▼, crest ▲, H_M / H_AR measure bars, β label)
  - arcB_sidebyside.png   Kanektok vs Uyak elevation vs radius + SWOT stage bands + both differences
  - arcB_beta.png         Kanektok Gearon β = H_AR/H_M vs radius + depth/H_M/H_AR
  - arcB_validity.png     bearing-vs-radius per river (sinuosity from the anchor)
  - data/arcB_channels.parquet  per-radius channel elevations, superelevation (SWOT-staged, with
                          band), Kanektok depth/bed/β, SWOT reference columns, and migration QC
  - data/arcB_profiles.parquet  full elevation-vs-arc cross-sections (float32/zstd) — drives the tab

Run:  python3 DEM_Transects/swot_arc_reference.py   # first — builds the SWOT reference
      python3 DEM_Transects/build_arc_B.py
"""

from __future__ import annotations

import os

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RASTER = os.path.join(ROOT, "batch_outputs", "arcticdem_rivers_2m.tif")
# SWOT channel centerlines — no longer a prior here (both channels use the field centerlines
# below); kept only for the comparison overlay drawn by map_transects.py.
CENTERLINE = os.path.join(HERE, "outputs", "swot_centerlines.gpkg")
# Official field-surveyed centerlines — both accurate to the real channel, so both drive TIGHT snap
# windows. Uyak: a hunter's boat-GPS tracks (build_uyak_centerline.py). Kanektok: a boat ADCP
# thalweg run (build_kanektok_centerline.py). Each is the field draft after any hand-editing.
UYAK_CL = os.path.join(HERE, "data", "uyak_centerline_official.gpkg")
KAN_CL = os.path.join(HERE, "data", "kanektok_centerline_official.gpkg")
OUT = os.path.join(HERE, "outputs")
# The two parquets that DRIVE the dashboard Cross-Sections tab are published to data/ (tracked, not
# outputs/) so the tab works on the hosted app, not just local runs. Figures stay scratch in OUT.
DATA = os.path.join(HERE, "data")

ANCHOR = (59.82463509, -161.33397834)   # lat, lon — same anchor SWOT/DEM dist_km uses
R_EARTH = 6371.0088
# Per-arc SWOT reference (geoid, stage distribution, pass-paired difference, survey-stage WSE),
# built by swot_arc_reference.py. See that script for why each column exists.
SWOT_REF = os.path.join(HERE, "data", "swot_arc_reference.parquet")
# EGM2008 fallback if the SWOT reference is missing — the old constant. It is accurate to ~0.3 m
# anywhere on the reach and cancels exactly in within-arc differences (β, superelevation,
# Uyak−Kanektok), but it puts a ~0.5 m tilt into DEM-vs-SWOT comparisons, so prefer the artifact.
GEOID_FALLBACK = 13.46
BEAR_MIN, BEAR_MAX = 248.0, 294.0        # bearing sector covering both rivers + margin
ARC_STEP_M = 2.0                         # along-arc sample spacing = native 2 m DEM resolution
                                         # (10 m skipped 4/5 of pixels, blurring floodplain/bank/ridge detail)
MEAS_WIN_M = 50.0                        # WSE measurement half-window on the thalweg (channels are narrow,
                                         # ~30-50 m; at 2 m sampling this window genuinely resolves the water,
                                         # ~15-25 samples, so P2 is a real percentile of the channel not a lone min)
CH_WIN_M = 250.0                         # channel+bank exclusion half-window for the floodplain corridor
# Search half-width to locate each real DEM channel. Both channels now use an accurate field
# centerline (boat GPS Uyak, boat ADCP Kanektok), so both get the same TIGHT window: it snaps to
# the DEM low (correcting residual GPS / DEM-date channel shift) with no room to wander onto nearby
# ponds/sloughs. Symmetric windows also remove the last method asymmetry between the two rivers.
SNAP_WIN_KAN_M = 75.0
SNAP_WIN_UYAK_M = 75.0
# One percentile does both jobs: P2 is the deepest sliver of terrain = the (narrow) channel water.
# The WSE value is insensitive to this choice to <0.25 m (< the DEM's ~0.5 m accuracy); P2 keeps the
# pick firmly on the water while the moderate MEAS_WIN_M keeps it a hair above the min (void-robust).
LOCATE_PCTL = 2.0                        # deepest-percentile whose centroid marks the channel thalweg
WSE_PCTL = 2.0                           # low percentile within MEAS_WIN_M = channel water surface
FP_MIN_WIDTH_M = 100.0                   # min inter-channel corridor width for a floodplain reference
FP_MIN_PTS = 5                           # min valid samples in the corridor for a floodplain reference
# --- Gearon β = H_AR / H_M (avulsion superelevation number; Gearon et al. 2024) ---
# β = (ridge crest − floodplain) / (ridge crest − channel bed); threshold β≈1 = bed aggraded to the
# floodplain (perched, avulsion-prone). The channel BED comes from the boat-ADCP thalweg depth
# (bed = DEM water surface − depth) — ArcticDEM images the water surface, so without a measured
# depth H_M would be only the freeboard crest−WSE and β biased high. Kanektok only for now (the
# Uyak has ADCP depth near its mouth only; its β / depth model is deferred).
KAN_DEPTH = os.path.join(HERE, "data", "kanektok_thalweg_depth.parquet")
DEPTH_WIN_KM = 0.25                      # radius half-window for binning ADCP thalweg depth to an arc
# Half-window each side of the thalweg to find the bank crest. Set by CHANNEL GEOMETRY, not tuned:
# Gearon works "within roughly three channel widths" of the channel, and the Kanektok is ~50 m wide,
# so ~150 m. The earlier 350 m was ~7 channel widths and reached regional high ground rather than a
# bank — the P98 there kept climbing with the window instead of settling on a levee (offset from the
# thalweg tracked the window: 57 m at ±75, 193 m at ±350), the signature of no local maximum.
# Independent check, from the bankfull idea: a bank the river actually fills should have freeboard
# A = (crest − water surface) comparable to the channel depth B (ADCP median 1.30 m). Measured A/B by
# window: 0.66 @60 m, 1.02 @100 m, 1.27 @150 m, 1.72 @250 m, 1.87 @350 m, 1.96 @500 m. At 350 m the
# "bank" stood 1.9× the channel depth above the water — unfillable, and Gearon's anomalous rule-3
# regime. At 150 m it is bankfull-consistent. See AVULSION_ANALYSIS.md §4.
CREST_WIN_M = 150.0
CREST_PCTL = 98.0                        # robust bank-high percentile; crest = LOWER of the two banks
_to3413 = Transformer.from_crs(4326, 3413, always_xy=True)


def dest(lat_deg, lon_deg, dist_km, bearing_deg):
    """Forward spherical geodesic: point at dist_km/bearing from (lat,lon)."""
    la1, lo1 = np.radians(lat_deg), np.radians(lon_deg)
    br, dr = np.radians(bearing_deg), np.asarray(dist_km) / R_EARTH
    la2 = np.arcsin(np.sin(la1) * np.cos(dr) + np.cos(la1) * np.sin(dr) * np.cos(br))
    lo2 = lo1 + np.arctan2(np.sin(br) * np.sin(dr) * np.cos(la1),
                           np.cos(dr) - np.sin(la1) * np.sin(la2))
    return np.degrees(la2), np.degrees(lo2)


def dist_bear(lat, lon):
    """Distance (km) and bearing (deg) of points from the anchor."""
    la1, lo1 = np.radians(ANCHOR[0]), np.radians(ANCHOR[1])
    la2, lo2 = np.radians(np.asarray(lat)), np.radians(np.asarray(lon))
    dla, dlo = la2 - la1, lo2 - lo1
    a = np.sin(dla / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin(dlo / 2) ** 2
    d = 2 * R_EARTH * np.arcsin(np.sqrt(a))
    br = np.degrees(np.arctan2(np.sin(dlo) * np.cos(la2),
                               np.cos(la1) * np.sin(la2) - np.sin(la1) * np.cos(la2) * np.cos(dlo))) % 360
    return d, br


def hand_centerline_dbr(path):
    """Per-vertex (radius_km, bearing) for a field-surveyed centerline — every vertex kept.

    Used for both rivers' field centerlines (boat GPS Uyak, boat ADCP thalweg Kanektok). Does NOT
    resample to a fixed count or assume radius is monotonic: the dense trackpoints carry the true
    meanders, and the prior lookup below (nearest_bearing) picks the nearest crossing per arc rather
    than interpolating across meander limbs (which would smear a meander that recrosses an arc).
    """
    g = gpd.read_file(path).to_crs(4326).geometry.iloc[0]
    g = max(g.geoms, key=lambda s: s.length) if g.geom_type == "MultiLineString" else g
    lon, lat = np.asarray(g.xy[0]), np.asarray(g.xy[1])
    d, br = dist_bear(lat, lon)
    return d, br


def nearest_bearing(d_arr, br_arr, R, max_gap_km=0.25):
    """Bearing of the centerline vertex whose radius is closest to R (nan if none within max_gap).

    Picks an actual channel crossing at radius R instead of averaging limbs, so a meander that
    swings tangentially to the arc (crossing R more than once) still yields an on-channel prior.
    """
    i = int(np.argmin(np.abs(d_arr - R)))
    return float(br_arr[i]) if abs(d_arr[i] - R) <= max_gap_km else np.nan


def ridge_crest(center, arc_m, z, win=CREST_WIN_M, pctl=CREST_PCTL):
    """Alluvial-ridge crest beside a channel = the LOWER of the two bank highs (Gearon's H_AR ref).

    Takes a robust high (`pctl`) of the terrain on each side of the thalweg within `win`, and returns
    the lower of the two — the limiting bank a flood must overtop to leave the channel toward the
    floodplain. NaN if either flank has too few samples.
    """
    if not np.isfinite(center):
        return np.nan
    inner = (arc_m >= center) & (arc_m <= center + win) & np.isfinite(z)
    outer = (arc_m <= center) & (arc_m >= center - win) & np.isfinite(z)
    if inner.sum() < 3 or outer.sum() < 3:
        return np.nan
    return float(min(np.percentile(z[inner], pctl), np.percentile(z[outer], pctl)))


def sample_arc(src, R, bearings, geoid):
    """Sample the DEM along the arc at radius R over `bearings`, returned as orthometric (EGM2008) m.

    `geoid` is the EGM2008 height AT THIS RADIUS, not a constant: it runs ~13.77 m at the anchor to
    ~13.27 m at the coast. Within one arc the geoid is effectively constant, so this choice does not
    touch any within-arc difference (β, H_AR, H_M, superelevation, Uyak−Kanektok all cancel it) — it
    matters because it puts the DEM on the same vertical datum as SWOT, which is what lets the two be
    compared without a spurious ~0.5 m along-reach tilt.
    """
    lat, lon = dest(ANCHOR[0], ANCHOR[1], R, bearings)
    x, y = _to3413.transform(lon, lat)
    z = np.array([v[0] for v in src.sample(np.column_stack([x, y]))], float)
    z[(z == src.nodata) | (z == 0)] = np.nan
    return z - geoid


def main():
    kd, kb = hand_centerline_dbr(KAN_CL)    # field ADCP-thalweg prior (accurate) for the Kanektok
    ud, ub = hand_centerline_dbr(UYAK_CL)   # field boat-GPS prior (accurate) for the Uyak
    radii = np.arange(3.0, 35.0, 0.5)

    # ADCP thalweg depth (Day-03), binned to each arc for the Gearon β bed / H_M term.
    dep_df = pd.read_parquet(KAN_DEPTH)
    dep_r, dep_v = dep_df["radius_km"].to_numpy(), dep_df["depth_m"].to_numpy()

    def kan_depth_at(R):
        m = np.abs(dep_r - R) <= DEPTH_WIN_KM
        return float(np.median(dep_v[m])) if m.sum() >= 3 else np.nan

    # SWOT per-arc reference: geoid, stage distribution, pass-paired difference, survey-stage WSE.
    try:
        swot = pd.read_parquet(SWOT_REF).set_index("R_km")
    except Exception:
        swot = None
        print(f"WARNING: {os.path.relpath(SWOT_REF, ROOT)} not found — falling back to a constant "
              f"{GEOID_FALLBACK} m geoid, and the SWOT stage/bed columns will be empty. "
              f"Run: python3 DEM_Transects/swot_arc_reference.py")

    def swot_at(R, col, default=np.nan):
        if swot is None or col not in swot.columns:
            return default
        try:
            v = float(swot.loc[R, col])
        except KeyError:
            return default
        return v if np.isfinite(v) else default

    rows = []
    profiles = []
    example_R = [8, 16, 24, 32]
    examples = {}
    with rasterio.open(RASTER) as src:
        for R in radii:
            n = int(np.radians(BEAR_MAX - BEAR_MIN) * R * 1000 / ARC_STEP_M)
            bearings = np.linspace(BEAR_MIN, BEAR_MAX, max(n, 50))
            arc_m = np.radians(bearings - BEAR_MIN) * R * 1000.0   # along-arc distance (m)
            geoid_R = swot_at(R, "geoid_m", GEOID_FALLBACK)
            z = sample_arc(src, R, bearings, geoid_R)
            profiles.append(pd.DataFrame({"R_km": R, "arc_m": arc_m, "elevation_m": z}))

            kbr = nearest_bearing(kd, kb, R)   # nearest crossing on each meandering field centerline
            ubr = nearest_bearing(ud, ub, R)

            def arc_pos(cbr):  # centerline prior: bearing -> along-arc distance (m)
                return np.radians(cbr - BEAR_MIN) * R * 1000.0 if np.isfinite(cbr) else np.nan

            def snap_wse(cm_prior, mid, win):
                # Locate the channel by SNAPPING to the actual DEM low. The centerline is only a
                # prior (both field lines are accurate to ~20-50 m, but the DEM date may differ from
                # the survey), so `win` is a tight, uniform search half-width. Two steps:
                #   (1) LOCATE: over a wide search window (±win, clipped at the midpoint between the
                #       two channels so the Kanektok/Uyak picks can't cross-contaminate), the channel
                #       thalweg = centroid of the deepest LOCATE_PCTL of the terrain.
                #   (2) MEASURE: water surface = WSE_PCTL within ±MEAS_WIN_M of that thalweg (tight, so
                #       the narrow channel's water isn't diluted by floodplain/bars in the value).
                # ArcticDEM images the surface, not the true bed, so the value is a water surface.
                if not np.isfinite(cm_prior):
                    return np.nan, np.nan
                lo, hi = cm_prior - win, cm_prior + win
                if np.isfinite(mid):
                    if cm_prior <= mid:
                        hi = min(hi, mid)
                    else:
                        lo = max(lo, mid)
                search = (arc_m >= lo) & (arc_m <= hi) & np.isfinite(z)
                if search.sum() < FP_MIN_PTS:
                    return cm_prior, np.nan
                thr = np.percentile(z[search], LOCATE_PCTL)
                center = float(np.median(arc_m[search & (z <= thr)]))   # thalweg position
                meas = (np.abs(arc_m - center) <= MEAS_WIN_M) & np.isfinite(z)
                if not meas.any():
                    return center, np.nan
                return center, float(np.percentile(z[meas], WSE_PCTL))

            def floodplain_ref(a, b):
                # Reference = median terrain of the corridor strictly BETWEEN the two channels,
                # excluding each channel's ±CH_WIN_M notch. This is the floodplain a Kanektok->
                # Uyak avulsion would drain across, so each channel's water surface minus this
                # is a direct "is the channel perched above the avulsion pathway?" measure.
                if not (np.isfinite(a) and np.isfinite(b)):
                    return np.nan, 0, np.nan
                lo, hi = sorted([a, b])
                width = (hi - CH_WIN_M) - (lo + CH_WIN_M)
                zone = (arc_m > lo + CH_WIN_M) & (arc_m < hi - CH_WIN_M) & np.isfinite(z)
                if zone.sum() < FP_MIN_PTS or width < FP_MIN_WIDTH_M:
                    return np.nan, int(zone.sum()), width
                return float(np.median(z[zone])), int(zone.sum()), width

            cm_k, cm_u = arc_pos(kbr), arc_pos(ubr)
            mid = 0.5 * (cm_k + cm_u) if (np.isfinite(cm_k) and np.isfinite(cm_u)) else np.nan
            kcm, kz = snap_wse(cm_k, mid, SNAP_WIN_KAN_M)
            ucm, uz = snap_wse(cm_u, mid, SNAP_WIN_UYAK_M)
            fp, fp_n, fp_w = floodplain_ref(kcm, ucm)

            # --- Channel bed, stage-matched where possible -------------------------------------
            # bed = water surface − measured depth is only a true bed if BOTH are at the same stage.
            # The ArcticDEM v4.1 mosaic is a 2010–2021 multi-date blend, but the ADCP depths are from
            # 2026-05-28..06-03, and SWOT overflew ON 2026-05-28 and 05-30. So the survey-stage SWOT
            # water surface gives a same-stage bed; the DEM-only bed (kept alongside for comparison)
            # mixes stages and sits ~0.2–0.3 m too low, which inflates H_M and depresses β.
            kdep = kan_depth_at(R)
            kwse_surv = swot_at(R, "swot_kan_wse_survey_m")
            kbed_dem = kz - kdep if (np.isfinite(kz) and np.isfinite(kdep)) else np.nan
            kbed = (kwse_surv - kdep) if (np.isfinite(kwse_surv) and np.isfinite(kdep)) else kbed_dem

            # Gearon β: crest = lower bank high beside the thalweg; H_AR = crest − floodplain,
            # H_M = crest − bed, β = H_AR/H_M. All three are TOPOGRAPHIC surfaces — the water
            # surface is not a term in β, it only serves to locate the bed under the depth sounding.
            kcrest = ridge_crest(kcm, arc_m, z)
            kHAR = kcrest - fp if (np.isfinite(kcrest) and np.isfinite(fp)) else np.nan
            kHM = kcrest - kbed if (np.isfinite(kcrest) and np.isfinite(kbed)) else np.nan
            kbeta = kHAR / kHM if (np.isfinite(kHAR) and np.isfinite(kHM) and kHM > 0) else np.nan
            # Freeboard over channel depth — the bankfull consistency check that set CREST_WIN_M.
            # A/B near 1 means the river can actually fill to this bank; A/B ≫ 1 means the "crest"
            # is regional high ground, not a bank (Gearon's anomalous rule-3 regime).
            kAB = ((kcrest - kz) / kdep
                   if (np.isfinite(kcrest) and np.isfinite(kz) and np.isfinite(kdep) and kdep > 0)
                   else np.nan)

            # --- Migration QC -------------------------------------------------------------------
            # The boat centerlines are 2026; the DEM is 2010–2021. Record how far each pick had to
            # move from its field prior, and flag picks that ran into the search wall (where the DEM
            # channel may lie further out still and the pick is therefore only a lower bound).
            k_off = kcm - cm_k if (np.isfinite(kcm) and np.isfinite(cm_k)) else np.nan
            u_off = ucm - cm_u if (np.isfinite(ucm) and np.isfinite(cm_u)) else np.nan

            rows.append({"R_km": R, "kan_wse_m": kz, "uyak_wse_m": uz,
                         "kan_arc_m": kcm, "uyak_arc_m": ucm,
                         "fp_ref_m": fp, "fp_zone_n": fp_n, "fp_zone_width_m": fp_w,
                         "kan_depth_m": kdep, "kan_bed_m": kbed, "kan_bed_dem_m": kbed_dem,
                         "kan_crest_m": kcrest, "kan_HAR_m": kHAR, "kan_HM_m": kHM,
                         "kan_beta": kbeta, "kan_freeboard_over_depth": kAB,
                         "geoid_m": geoid_R,
                         "kan_snap_offset_m": k_off, "uyak_snap_offset_m": u_off,
                         "kan_snap_clipped": bool(np.isfinite(k_off)
                                                  and abs(k_off) >= SNAP_WIN_KAN_M - ARC_STEP_M),
                         "uyak_snap_clipped": bool(np.isfinite(u_off)
                                                   and abs(u_off) >= SNAP_WIN_UYAK_M - ARC_STEP_M),
                         "swot_kan_wse_med_m": swot_at(R, "swot_kan_wse_med_m"),
                         "swot_kan_wse_p10_m": swot_at(R, "swot_kan_wse_p10_m"),
                         "swot_kan_wse_p90_m": swot_at(R, "swot_kan_wse_p90_m"),
                         "swot_uyak_wse_med_m": swot_at(R, "swot_uyak_wse_med_m"),
                         "swot_uyak_wse_p10_m": swot_at(R, "swot_uyak_wse_p10_m"),
                         "swot_uyak_wse_p90_m": swot_at(R, "swot_uyak_wse_p90_m"),
                         "swot_kan_wse_survey_m": kwse_surv,
                         "swot_diff_uyak_minus_kan": swot_at(R, "diff_pass_paired_m"),
                         "n_valid": int(np.isfinite(z).sum()), "n_tot": len(z)})
            if int(round(R)) in example_R and int(round(R)) not in examples:
                examples[int(round(R))] = (arc_m.copy(), z.copy(), kcm, ucm, fp, kbed, kcrest)

    ch = pd.DataFrame(rows)
    # DEM-derived difference. Kept for continuity, but it is NOT the number to quote: the mosaic is a
    # multi-date blend that caught the Kanektok near the 29th percentile of observed stages and the
    # Uyak near the 76th, so ~0.34 m of this is a differential-stage artifact. Use
    # `swot_diff_uyak_minus_kan` (both rivers in the SAME overpass, so stage cancels) instead.
    ch["diff_uyak_minus_kan"] = ch["uyak_wse_m"] - ch["kan_wse_m"]

    # Superelevation of each channel's water surface above the inter-channel floodplain corridor.
    # Positive => channel water sits ABOVE the corridor floor (perched, avulsion-prone);
    # negative => channel is incised below the surrounding floodplain (the safe, usual case).
    #
    # This is inherently STAGE-DEPENDENT — "is the channel perched?" has a different answer at low
    # and high water — so the headline pair below is quoted at the SWOT median stage and carried with
    # a p10–p90 band, rather than at whatever single stage the DEM blend happened to capture. The
    # `_dem_` columns are the all-DEM version: less defensible in absolute stage terms, but immune to
    # any DEM-vs-SWOT vertical bias because both terms come off the same raster.
    ch["kan_superelev_dem_m"] = ch["kan_wse_m"] - ch["fp_ref_m"]
    ch["uyak_superelev_dem_m"] = ch["uyak_wse_m"] - ch["fp_ref_m"]
    for tag in ("kan", "uyak"):
        for stat in ("med", "p10", "p90"):
            ch[f"{tag}_superelev_{stat}_m"] = ch[f"swot_{tag}_wse_{stat}_m"] - ch["fp_ref_m"]
    # Primary superelevation = SWOT median stage, falling back to the DEM where SWOT is thin.
    ch["kan_superelev_m"] = ch["kan_superelev_med_m"].fillna(ch["kan_superelev_dem_m"])
    ch["uyak_superelev_m"] = ch["uyak_superelev_med_m"].fillna(ch["uyak_superelev_dem_m"])
    ch.to_parquet(os.path.join(DATA, "arcB_channels.parquet"), index=False)

    # Full arc profiles (elevation vs along-arc distance) for interactive dashboard rendering.
    # float32 + zstd keeps the committed, hosted artifact small (~2 MB) at sub-mm/sub-cm precision.
    prof = pd.concat(profiles, ignore_index=True)
    for c in ("R_km", "arc_m", "elevation_m"):
        prof[c] = prof[c].astype("float32")
    prof.to_parquet(os.path.join(DATA, "arcB_profiles.parquet"), index=False, compression="zstd")
    print(f"wrote data/arcB_profiles.parquet ({len(prof)} pts, {ch['R_km'].nunique()} arcs)")
    valid = ch.dropna(subset=["kan_wse_m", "uyak_wse_m"])
    print(f"{len(ch)} arcs | median arc data coverage "
          f"{(ch['n_valid']/ch['n_tot']).median()*100:.0f}%")

    print("\n--- water surface: DEM vs SWOT ---")
    for tag, name in (("kan", "Kanektok"), ("uyak", "Uyak")):
        res = (ch[f"{tag}_wse_m"] - ch[f"swot_{tag}_wse_med_m"]).dropna()
        if len(res):
            print(f"  {name:9s} DEM − SWOT(median stage): median {res.median():+.2f} m "
                  f"over {len(res)} arcs")
    sd = ch.dropna(subset=["swot_diff_uyak_minus_kan"])
    print(f"  Uyak − Kanektok, PASS-PAIRED SWOT (stage cancels): "
          f"median {sd['swot_diff_uyak_minus_kan'].median():+.2f} m on {len(sd)} arcs")
    print(f"  Uyak − Kanektok, DEM only (carries a differential-stage artifact): "
          f"median {valid['diff_uyak_minus_kan'].median():+.2f} m")

    fpv = ch.dropna(subset=["fp_ref_m"])
    print("\n--- superelevation above the inter-channel corridor (+ = perched) ---")
    print(f"  floodplain reference on {len(fpv)}/{len(ch)} arcs "
          f"(corridor width median {fpv['fp_zone_width_m'].median():.0f} m)")
    for tag, name in (("kan", "Kanektok"), ("uyak", "Uyak")):
        s = fpv.dropna(subset=[f"{tag}_superelev_med_m"])
        if len(s):
            print(f"  {name:9s} median stage {s[f'{tag}_superelev_med_m'].median():+.2f} m "
                  f"(p10 {s[f'{tag}_superelev_p10_m'].median():+.2f}, "
                  f"p90 {s[f'{tag}_superelev_p90_m'].median():+.2f}); "
                  f"perched at median stage on {(s[f'{tag}_superelev_med_m']>0).mean()*100:.0f}% of arcs")

    bv = ch.dropna(subset=["kan_beta"])
    print(f"\n--- Kanektok Gearon β = H_AR/H_M (crest window ±{CREST_WIN_M:.0f} m) ---")
    print(f"  β median {bv['kan_beta'].median():.2f} on {len(bv)} arcs "
          f"(β ≤ 0 — i.e. NO ridge above the floodplain — on "
          f"{(bv['kan_beta']<=0).mean()*100:.0f}% of them)")
    print(f"  H_AR (crest−floodplain) median {bv['kan_HAR_m'].median():+.2f} m, "
          f"H_M (crest−bed) median {bv['kan_HM_m'].median():.2f} m "
          f"(ADCP depth median {bv['kan_depth_m'].median():.2f} m)")
    print(f"  bankfull check: freeboard/depth median {bv['kan_freeboard_over_depth'].median():.2f} "
          f"(≈1 = a bank the river can fill; ≫1 = the crest is not a bank)")
    bed_shift = (ch["kan_bed_m"] - ch["kan_bed_dem_m"]).dropna()
    if len(bed_shift):
        print(f"  stage-matched bed sits {bed_shift.median():+.2f} m vs the DEM-only bed "
              f"(SWOT at the ADCP survey stage vs the 2010–2021 mosaic stage)")

    print("\n--- migration QC: field centerline (2026) vs DEM channel (2010–2021 mosaic) ---")
    for tag, name, win in (("kan", "Kanektok", SNAP_WIN_KAN_M), ("uyak", "Uyak", SNAP_WIN_UYAK_M)):
        o = ch[f"{tag}_snap_offset_m"].abs().dropna()
        clip = ch[f"{tag}_snap_clipped"].mean() * 100
        print(f"  {name:9s} |offset| median {o.median():.0f} m, p90 {o.quantile(.9):.0f} m "
              f"(search wall ±{win:.0f} m); AT THE WALL on {clip:.0f}% of arcs")
    print("  (the WSE value is insensitive to this — the pick moves, the water elevation does not — "
          "but the channel POSITION, and hence the crest window anchored on it, is uncertain)")

    _sections_fig(examples)
    _sidebyside_fig(ch)
    _beta_fig(ch)
    _validity_fig(kd, kb, ud, ub)


def _sections_fig(examples):
    """Arc cross-sections re-centered on the Kanektok (x=0, increasing toward the Uyak), trimmed a
    little past the Uyak, with the Kanektok bed ▼ and ridge crest ▲ marked (β/H_M/H_AR values live
    in the parquet + dashboard metrics, not on the plot)."""
    PAD_KM = 0.75    # context to show past each channel; the outward sweep beyond is off-system
    fig, axes = plt.subplots(len(examples), 1, figsize=(13, 3 * len(examples)))
    for ax, R in zip(np.atleast_1d(axes), sorted(examples)):
        arc_m, z, kcm, ucm, fp, kbed, kcrest = examples[R]
        # Re-center: x = 0 is the Kanektok, x grows toward the Uyak (sign robust to geometry).
        sgn = np.sign(ucm - kcm) if (np.isfinite(kcm) and np.isfinite(ucm)) else 1.0
        sgn = sgn if sgn != 0 else 1.0
        origin = kcm if np.isfinite(kcm) else 0.0
        xr = (arc_m - origin) * sgn / 1000.0
        xk = 0.0 if np.isfinite(kcm) else np.nan
        xu = (ucm - origin) * sgn / 1000.0 if np.isfinite(ucm) else np.nan
        left = (xk if np.isfinite(xk) else np.nanmin(xr)) - PAD_KM
        right = (xu if np.isfinite(xu) else np.nanmax(xr)) + PAD_KM
        win = (xr >= left) & (xr <= right)
        ax.plot(xr[win], z[win], lw=0.7, color="0.3")
        if np.isfinite(xk):
            ax.axvline(xk, color="#08519c", lw=1.5, label="Kanektok")
        if np.isfinite(xu):
            ax.axvline(xu, color="#d94801", lw=1.5, label="Uyak")
        if np.isfinite(fp) and np.isfinite(xk) and np.isfinite(xu):
            lo, hi = sorted([xk, xu])
            ax.axvspan(lo + CH_WIN_M / 1000, hi - CH_WIN_M / 1000, color="#a1d99b", alpha=0.25)
            ax.axhline(fp, color="#31a354", lw=1.2, ls="--", label="floodplain ref")
        if np.isfinite(xk) and np.isfinite(kbed):
            ax.plot(xk, kbed, marker="v", color="#08519c", ms=8, label="Kanektok bed (ADCP)")
        if np.isfinite(xk) and np.isfinite(kcrest):
            ax.plot(xk, kcrest, marker="^", color="#08519c", ms=8, label="Kanektok ridge crest")
        ax.set_xlim(left, right)
        ax.set_title(f"Arc transect at radius {R} km from anchor "
                     f"(Kanektok -> floodplain -> Uyak)", fontsize=10)
        ax.set_xlabel("distance from Kanektok toward Uyak (km)")
        ax.set_ylabel("elevation (m)")
        ax.legend(fontsize=8)
    fig.suptitle("Approach B — Kanektok-centered arc cross-sections (bed ▼ / crest ▲)", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    fig.savefig(os.path.join(OUT, "arcB_sections.png"), dpi=130)
    plt.close(fig)
    print("wrote arcB_sections.png")


def _sidebyside_fig(ch):
    """Long profiles with the SWOT stage bands overlaid, and the two versions of the inter-river
    difference side by side — DEM (stage-contaminated) vs pass-paired SWOT (stage cancels)."""
    fig, ax = plt.subplots(1, 2, figsize=(14, 5))
    for tag, col, name in (("kan", "#08519c", "Kanektok"), ("uyak", "#d94801", "Uyak")):
        p10, p90 = ch[f"swot_{tag}_wse_p10_m"], ch[f"swot_{tag}_wse_p90_m"]
        if p10.notna().any():
            ax[0].fill_between(ch["R_km"], p10, p90, color=col, alpha=0.18,
                               label=f"{name} SWOT stage p10–p90")
        ax[0].plot(ch["R_km"], ch[f"{tag}_wse_m"], color=col, lw=1.3, label=f"{name} DEM water surface")
    ax[0].plot(ch["R_km"], ch["kan_bed_m"], color="#08519c", lw=1.1, ls=":",
               label="Kanektok bed (survey-stage WSE − ADCP depth)")
    ax[0].plot(ch["R_km"], ch["fp_ref_m"], color="#31a354", lw=1.0, ls="--", label="floodplain ref")
    ax[0].set(xlabel="Distance from anchor (km, ≈ downstream)",
              ylabel="Elevation (m, EGM2008)",
              title="Side-by-side channel long profile (matched radius)")
    ax[0].legend(fontsize=7)
    ax[1].axhline(0, color="k", lw=0.7)
    ax[1].plot(ch["R_km"], ch["diff_uyak_minus_kan"], color="#bcbddc", lw=1.2,
               label="DEM only (carries a differential-stage artifact)")
    ax[1].plot(ch["R_km"], ch["swot_diff_uyak_minus_kan"], color="#6a51a3", lw=1.6,
               label="SWOT, pass-paired (stage cancels)")
    ax[1].set(xlabel="Distance from anchor (km)", ylabel="Uyak − Kanektok water surface (m)",
              title="Elevation difference (Uyak higher if > 0)")
    ax[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "arcB_sidebyside.png"), dpi=130)
    plt.close(fig)
    print("wrote arcB_sidebyside.png")


def _beta_fig(ch):
    """Kanektok Gearon β = H_AR/H_M vs radius, plus the heights that feed it.

    β ≈ 0 is the headline here, and it means something specific: H_AR ≈ 0, i.e. there is no alluvial
    ridge standing above the floodplain to measure. We plot β = 0 as the reference line rather than
    β = 1, because β = 1 is not the operative threshold — Gearon's criterion is βγ ≥ Λ, and this
    analysis deliberately does not evaluate the gradient term γ.
    """
    fig, ax = plt.subplots(1, 2, figsize=(14, 5))
    bv = ch.dropna(subset=["kan_beta"])
    ax[0].axhline(0.0, color="#cb181d", lw=1.3, ls="--", label="β = 0 (no ridge above floodplain)")
    ax[0].plot(bv["R_km"], bv["kan_beta"], color="#08519c", lw=1.4, marker="o", ms=3,
               label="Kanektok β")
    ax[0].fill_between(bv["R_km"], 0, bv["kan_beta"], color="#08519c", alpha=0.12)
    lo, hi = float(bv["kan_beta"].min()), float(bv["kan_beta"].max())
    pad = max(0.1, 0.1 * (hi - lo))
    ax[0].set(xlabel="Distance from anchor (km, ≈ downstream)",
              ylabel="β = H_AR / H_M", ylim=(lo - pad, hi + pad),
              title=f"Kanektok β (median {bv['kan_beta'].median():.2f}) — H_AR ≈ 0, "
                    f"so there is no ridge to superelevate")
    ax[0].legend(fontsize=9)
    ax[1].plot(ch["R_km"], ch["kan_depth_m"], color="#6baed6", lw=1.3, label="ADCP thalweg depth")
    ax[1].plot(ch["R_km"], ch["kan_HM_m"], color="#08306b", lw=1.3, label="H_M (crest − bed)")
    ax[1].plot(ch["R_km"], ch["kan_HAR_m"], color="#31a354", lw=1.3, label="H_AR (crest − floodplain)")
    ax[1].axhline(0, color="k", lw=0.6)
    ax[1].set(xlabel="Distance from anchor (km)", ylabel="Height (m)",
              title=f"β ingredients (crest window ±{CREST_WIN_M:.0f} m): depth, H_M, ridge height H_AR")
    ax[1].legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "arcB_beta.png"), dpi=130)
    plt.close(fig)
    print("wrote arcB_beta.png")


def _validity_fig(kd, kb, ud, ub):
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(kd, kb, color="#08519c", lw=1.3, label="Kanektok")
    ax.plot(ud, ub, color="#d94801", lw=1.3, label="Uyak")
    ax.set(xlabel="Distance from anchor (km)", ylabel="Bearing from anchor (deg)",
           title="Channel bearing vs radius — flat = runs straight from anchor (arc-perpendicular-to-flow valid)")
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "arcB_validity.png"), dpi=130)
    plt.close(fig)
    print("wrote arcB_validity.png")


if __name__ == "__main__":
    main()
