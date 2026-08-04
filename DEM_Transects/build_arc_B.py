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

Deliverables — figures to DEM_Transects/outputs/ (scratch), the two dashboard parquets to data/ (tracked/hosted):
  - arcB_sections.png     example arc cross-sections, Kanektok-centered (x=0) toward the Uyak, with
                          the Gearon β anatomy (bed ▼, crest ▲, H_M / H_AR measure bars, β label)
  - arcB_sidebyside.png   Kanektok vs Uyak channel elevation vs radius + difference + Kanektok bed
  - arcB_beta.png         Kanektok Gearon β = H_AR/H_M vs radius (avulsion threshold β=1) + depth/H_M/H_AR
  - arcB_validity.png     bearing-vs-radius per river (sinuosity from the anchor)
  - data/arcB_channels.parquet  per-radius channel elevations, superelevation, and Kanektok depth/bed/β
  - data/arcB_profiles.parquet  full elevation-vs-arc cross-sections (float32/zstd) — drives the tab

Run:  python3 DEM_Transects/build_arc_B.py
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
GEOID = 13.46
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
CREST_WIN_M = 350.0                      # half-window each side of the thalweg to find the bank crest
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


def sample_arc(src, R, bearings):
    """Sample the DEM (orthometric m) along the arc at radius R over `bearings`."""
    lat, lon = dest(ANCHOR[0], ANCHOR[1], R, bearings)
    x, y = _to3413.transform(lon, lat)
    z = np.array([v[0] for v in src.sample(np.column_stack([x, y]))], float)
    z[(z == src.nodata) | (z == 0)] = np.nan
    return z - GEOID


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

    rows = []
    profiles = []
    example_R = [8, 16, 24, 32]
    examples = {}
    with rasterio.open(RASTER) as src:
        for R in radii:
            n = int(np.radians(BEAR_MAX - BEAR_MIN) * R * 1000 / ARC_STEP_M)
            bearings = np.linspace(BEAR_MIN, BEAR_MAX, max(n, 50))
            arc_m = np.radians(bearings - BEAR_MIN) * R * 1000.0   # along-arc distance (m)
            z = sample_arc(src, R, bearings)
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

            # Gearon β for the Kanektok: bed = water surface − measured ADCP depth; crest = lower
            # bank high beside the thalweg; H_AR = crest − floodplain, H_M = crest − bed, β = H_AR/H_M.
            kdep = kan_depth_at(R)
            kbed = kz - kdep if (np.isfinite(kz) and np.isfinite(kdep)) else np.nan
            kcrest = ridge_crest(kcm, arc_m, z)
            kHAR = kcrest - fp if (np.isfinite(kcrest) and np.isfinite(fp)) else np.nan
            kHM = kcrest - kbed if (np.isfinite(kcrest) and np.isfinite(kbed)) else np.nan
            kbeta = kHAR / kHM if (np.isfinite(kHAR) and np.isfinite(kHM) and kHM > 0) else np.nan

            rows.append({"R_km": R, "kan_wse_m": kz, "uyak_wse_m": uz,
                         "kan_arc_m": kcm, "uyak_arc_m": ucm,
                         "fp_ref_m": fp, "fp_zone_n": fp_n, "fp_zone_width_m": fp_w,
                         "kan_depth_m": kdep, "kan_bed_m": kbed, "kan_crest_m": kcrest,
                         "kan_HAR_m": kHAR, "kan_HM_m": kHM, "kan_beta": kbeta,
                         "n_valid": int(np.isfinite(z).sum()), "n_tot": len(z)})
            if int(round(R)) in example_R and int(round(R)) not in examples:
                examples[int(round(R))] = (arc_m.copy(), z.copy(), kcm, ucm, fp, kbed, kcrest)

    ch = pd.DataFrame(rows)
    ch["diff_uyak_minus_kan"] = ch["uyak_wse_m"] - ch["kan_wse_m"]
    # Superelevation of each channel's water surface above the inter-channel floodplain corridor.
    # Positive => channel water sits ABOVE the corridor floor (perched, avulsion-prone);
    # negative => channel is incised below the surrounding floodplain (the safe, usual case).
    ch["kan_superelev_m"] = ch["kan_wse_m"] - ch["fp_ref_m"]
    ch["uyak_superelev_m"] = ch["uyak_wse_m"] - ch["fp_ref_m"]
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
    print(f"Uyak - Kanektok channel water surface (P{WSE_PCTL:.0f}): "
          f"median {valid['diff_uyak_minus_kan'].median():+.2f} m "
          f"(Uyak higher if +), Uyak higher on {(valid['diff_uyak_minus_kan']>0).mean()*100:.0f}% of arcs")
    fpv = ch.dropna(subset=["fp_ref_m"])
    print(f"floodplain reference available on {len(fpv)}/{len(ch)} arcs "
          f"(corridor width median {fpv['fp_zone_width_m'].median():.0f} m)")
    print(f"superelevation above corridor (+ = perched): "
          f"Kanektok median {fpv['kan_superelev_m'].median():+.2f} m, "
          f"Uyak median {fpv['uyak_superelev_m'].median():+.2f} m")
    bv = ch.dropna(subset=["kan_beta"])
    print(f"Kanektok Gearon β = H_AR/H_M (avulsion threshold β≈1): median {bv['kan_beta'].median():.2f} "
          f"on {len(bv)} arcs, β<1 (not avulsion-prone) on {(bv['kan_beta']<1).mean()*100:.0f}%")
    print(f"  H_AR (crest−floodplain) median {bv['kan_HAR_m'].median():+.2f} m, "
          f"H_M (crest−bed, measured) median {bv['kan_HM_m'].median():.2f} m "
          f"(ADCP depth median {bv['kan_depth_m'].median():.2f} m)")

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
    fig, ax = plt.subplots(1, 2, figsize=(14, 5))
    ax[0].plot(ch["R_km"], ch["kan_wse_m"], color="#08519c", lw=1.3, label="Kanektok water surface")
    ax[0].plot(ch["R_km"], ch["kan_bed_m"], color="#08519c", lw=1.1, ls=":",
               label="Kanektok bed (WSE − ADCP depth)")
    ax[0].plot(ch["R_km"], ch["uyak_wse_m"], color="#d94801", lw=1.3, label="Uyak water surface")
    ax[0].plot(ch["R_km"], ch["fp_ref_m"], color="#31a354", lw=1.0, ls="--", label="floodplain ref")
    ax[0].set(xlabel="Distance from anchor (km, ≈ downstream)",
              ylabel="Elevation (m)",
              title="Side-by-side channel long profile (matched radius)")
    ax[0].legend(fontsize=8)
    ax[1].axhline(0, color="k", lw=0.7)
    ax[1].plot(ch["R_km"], ch["diff_uyak_minus_kan"], color="#6a51a3", lw=1.2)
    ax[1].set(xlabel="Distance from anchor (km)", ylabel="Uyak − Kanektok water surface (m)",
              title="Elevation difference (Uyak higher if > 0)")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "arcB_sidebyside.png"), dpi=130)
    plt.close(fig)
    print("wrote arcB_sidebyside.png")


def _beta_fig(ch):
    """Kanektok Gearon β = H_AR/H_M vs radius (threshold β=1), plus the depth/bed that feed it."""
    fig, ax = plt.subplots(1, 2, figsize=(14, 5))
    bv = ch.dropna(subset=["kan_beta"])
    ax[0].axhline(1.0, color="#cb181d", lw=1.3, ls="--", label="avulsion threshold β = 1")
    ax[0].plot(bv["R_km"], bv["kan_beta"], color="#08519c", lw=1.4, marker="o", ms=3,
               label="Kanektok β")
    ax[0].fill_between(bv["R_km"], 0, bv["kan_beta"], color="#08519c", alpha=0.12)
    ax[0].set(xlabel="Distance from anchor (km, ≈ downstream)",
              ylabel="β = H_AR / H_M", ylim=(0, max(1.15, float(bv["kan_beta"].max()) * 1.1)),
              title=f"Kanektok avulsion number β (median {bv['kan_beta'].median():.2f}, "
                    f"all < 1 → not avulsion-prone)")
    ax[0].legend(fontsize=9)
    ax[1].plot(ch["R_km"], ch["kan_depth_m"], color="#6baed6", lw=1.3, label="ADCP thalweg depth")
    ax[1].plot(ch["R_km"], ch["kan_HM_m"], color="#08306b", lw=1.3, label="H_M (crest − bed)")
    ax[1].plot(ch["R_km"], ch["kan_HAR_m"], color="#31a354", lw=1.3, label="H_AR (crest − floodplain)")
    ax[1].axhline(0, color="k", lw=0.6)
    ax[1].set(xlabel="Distance from anchor (km)", ylabel="Height (m)",
              title="β ingredients: measured depth, channel depth H_M, ridge height H_AR")
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
