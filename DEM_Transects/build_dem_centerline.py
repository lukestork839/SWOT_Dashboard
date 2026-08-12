"""P6 — a channel centerline derived from the DEM itself, owing nothing to a boat track.

WHY THIS EXISTS
---------------
The along-channel gradient advantage measured in the Phase-2 channel-slope work
(`dem_channel_slope_phase2.py`) turned out not to be robust: it ranged 1.02-1.23 purely
as a function of how much the field centerlines were smoothed, because the Uyak's
apparent sinuosity is far higher than the Kanektok's (1.72 vs 1.46 at 1-5 km). The two
field lines are not equally trustworthy for PATH LENGTH:

  * Kanektok — a boat-ADCP *longitudinal thalweg run*: the boat was deliberately
    tracking the deep thread. Deviation from a 100 m-smoothed version: RMS 5.4 m,
    path only 1.3 % longer.
  * Uyak — a hunter's boat GPS track: free to wander bank-to-bank inside a ~30 m
    channel. Same measure: RMS 7.2 m, path 8.9 % longer, and 15.4 % of its steps move
    back toward the anchor (vs the Kanektok's 6.2 %).

A ~10 m-amplitude wiggle at ~100 m wavelength is well below the meander scale expected
for a 30 m channel (~10-14 channel widths, so 300-420 m), so the Uyak's excess is
short-wavelength — the signature of wander, not meandering. At true meander scale
(800-1600 m smoothing) the two lines converge. This script measures the channel path
from the DEM so the question does not rest on a boat's steering.

TEMPORAL CAVEAT — CENTRAL TO READING THIS OUTPUT
------------------------------------------------
The ArcticDEM v4.1 mosaic is a **2010-10-03 -> 2021-03-02** multi-date blend; the field
centerlines are **2026**. So there are 5-16 years between them, and a DEM-vs-field path
difference has two possible causes that this script cannot separate on its own:

  (a) boat wander in the 2026 track (what we are testing for), or
  (b) real channel migration / meander growth since the DEM epoch.

Two things help. First, scale: wander is short-wavelength and bounded by the channel
half-width, migration is a systematic lateral shift. Second, the offsets are small
(median 38 m Kanektok / 12 m Uyak at 0.5 km spacing) relative to meander amplitudes of
100 m+, so wholesale meander migration is not what is on the table here.

The temporal split also cuts the other way, in our favour: this centerline is derived
from the DEM, and the elevations sampled along it are from the same DEM, so path and
elevation are **epoch-consistent**. Pairing a 2026 boat path with 2010-2021 elevations
(what Phase 2 did) is the mismatched combination. Any along-channel gradient computed
here is internally consistent in time in a way Phase 2's was not.

TWO METHODS, FOR TWO DIFFERENT JOBS
-----------------------------------
**Method 1 — radial nodes (long profile + migration QC).** Re-run the arc-method channel
snap from `build_arc_B.py` at **50 m radial spacing** instead of 500 m. At each radius the
channel is located exactly as the arc analysis locates it: the centroid of the deepest
LOCATE_PCTL of terrain within a tight search window around the field prior, clipped at the
midpoint between the two channels so the picks cannot cross-contaminate. This yields a
50 m-resolution channel water-surface profile in the radial frame, epoch-consistent with
the DEM, plus a fine-grained record of how far the DEM channel sits from the 2026 boat
line. Verified to reproduce `build_arc_B.py` on the radii they share (|ΔWSE| median
0.000 m).

**Method 1 CANNOT measure sinuosity, and the reason is worth recording.** The path is
parameterised by radius, one point per radius, and the prior lookup (`nearest_bearing`)
takes the globally-nearest centerline vertex by radius. Where the channel meanders, radius
is not monotonic along it, so consecutive radii can select vertices on *different meander
limbs* — measured here, the along-arc position jumps >100 m between adjacent 50 m radii on
9.5 % (Kanektok) / 16.5 % (Uyak) of steps, with worst cases near 1 km. The resulting
"path" zigzags across the floodplain, so its length is a wild **over**-estimate, not a
lower bound. Sinuosity is therefore NOT reported from Method 1.

**Method 2 — along-channel DEM snap (the sinuosity arbiter).** Walk the field line in its
own along-channel order, so ordering is never in question, and let the DEM set the
position: resample at 10 m, take local normals from a ~100 m-smoothed copy of the line
(smoothing the *guide* only, so tangents are stable), sample the 2 m DEM across ±75 m
perpendicular, and snap each station to the channel low by the same deepest-percentile
rule the arc method uses. If the boat zigzagged bank-to-bank inside a ~30 m channel, every
one of those stations snaps onto the same thalweg and the zigzag collapses — so the drop
in path length from raw field line to DEM-snapped line *is* the wander, measured rather
than assumed. Lengths are reported raw / guide-smoothed / snapped / snapped-then-smoothed,
because the snap itself can add jitter (each thalweg estimate carries noise) and that has
to be separated from real path length.

Settling the river's ABSOLUTE sinuosity would need a non-radial channel trace digitised
from imagery; that is outside this script. What Method 2 settles is the question that
actually blocked the analysis: **are the two field lines equally trustworthy for path
length, or is the Uyak's excess an artifact of how it was collected?**

Outputs (to data/, tracked — small):
  data/dem_centerline_nodes.parquet   Method 1 — per-radius snapped channel position +
                                      water surface, both rivers, vs the field prior
  data/dem_centerline_snapped.parquet Method 2 — per-station DEM-snapped channel path
Run:  python3 DEM_Transects/build_dem_centerline.py
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer

# Reuse the arc-method geometry and snap constants verbatim -- this must be the SAME
# channel definition the superelevation/beta analysis uses, or the two disagree by
# construction. Importing rather than copying is what keeps them in lockstep.
from build_arc_B import (  # noqa: E402  (same-directory import; see __main__ guard)
    ANCHOR, BEAR_MIN, ARC_STEP_M, MEAS_WIN_M, LOCATE_PCTL, WSE_PCTL,
    SNAP_WIN_KAN_M, SNAP_WIN_UYAK_M, FP_MIN_PTS, GEOID_FALLBACK,
    KAN_CL, UYAK_CL, SWOT_REF, RASTER, DATA,
    dest, dist_bear, hand_centerline_dbr, nearest_bearing, _to3413,
)

R_MIN, R_MAX = 3.0, 34.0
R_STEP = 0.05                    # 50 m radial spacing (arc analysis uses 500 m)
# Sampling span each side of the prior: the search window plus the measurement window,
# because `meas` may legitimately reach beyond the search window (as it does in
# build_arc_B, where arc_m spans the whole bearing sector).
SPAN_PAD_M = MEAS_WIN_M + 4.0
OUT_NODES = os.path.join(DATA, "dem_centerline_nodes.parquet")

# --- Method 2 (along-channel snap) -----------------------------------------------------
STATION_M = 10.0                 # along-channel resampling of the field guide
GUIDE_SMOOTH_M = 100.0           # boxcar window for the guide used to take local normals.
                                 # Above the wander band (~10 m amplitude at ~100 m
                                 # wavelength), below the meander band (300 m+), so normals
                                 # point across the channel rather than along a wiggle.
PERP_HALF_M = 75.0               # perpendicular search half-width = the arc method's snap window
PERP_STEP_M = 2.0                # native DEM resolution
REPORT_SMOOTH_M = 100.0          # smoothing applied to OUTPUT paths when reporting lengths,
                                 # to separate real path length from snap jitter
UTM = 32604
OUT_SNAP = os.path.join(DATA, "dem_centerline_snapped.parquet")


def _arc_grid(R, center_m, half_m):
    """2 m-spaced along-arc sample positions and bearings around `center_m` at radius R."""
    n = max(int(2 * half_m / ARC_STEP_M) + 1, 8)
    arc_m = np.linspace(center_m - half_m, center_m + half_m, n)
    bearings = BEAR_MIN + np.degrees(arc_m / (R * 1000.0))
    return arc_m, bearings


def _sample(src, R, bearings, geoid):
    lat, lon = dest(ANCHOR[0], ANCHOR[1], R, bearings)
    x, y = _to3413.transform(lon, lat)
    z = np.array([v[0] for v in src.sample(np.column_stack([x, y]))], float)
    z[(z == src.nodata) | (z == 0)] = np.nan
    return z - geoid


def _snap(src, R, prior_m, mid_m, win, geoid):
    """Locate the channel and read its water surface -- build_arc_B.snap_wse, narrow-sampled.

    Returns (thalweg_arc_m, water_surface_m, n_search).
    """
    if not np.isfinite(prior_m):
        return np.nan, np.nan, 0
    arc_m, bearings = _arc_grid(R, prior_m, win + SPAN_PAD_M)
    z = _sample(src, R, bearings, geoid)

    lo, hi = prior_m - win, prior_m + win
    if np.isfinite(mid_m):                     # clip at the inter-channel midpoint
        if prior_m <= mid_m:
            hi = min(hi, mid_m)
        else:
            lo = max(lo, mid_m)
    search = (arc_m >= lo) & (arc_m <= hi) & np.isfinite(z)
    if search.sum() < FP_MIN_PTS:
        return prior_m, np.nan, int(search.sum())
    thr = np.percentile(z[search], LOCATE_PCTL)
    center = float(np.median(arc_m[search & (z <= thr)]))
    meas = (np.abs(arc_m - center) <= MEAS_WIN_M) & np.isfinite(z)
    if not meas.any():
        return center, np.nan, int(search.sum())
    return center, float(np.percentile(z[meas], WSE_PCTL)), int(search.sum())


def _latlon(R, arc_m):
    """Snapped along-arc position -> (lat, lon)."""
    if not np.isfinite(arc_m):
        return np.nan, np.nan
    br = BEAR_MIN + np.degrees(arc_m / (R * 1000.0))
    la, lo = dest(ANCHOR[0], ANCHOR[1], R, br)
    return float(la), float(lo)


def _boxcar(a, win_pts):
    """Centred moving average with edge padding (used only to stabilise normals/report)."""
    if win_pts < 2:
        return np.asarray(a, float).copy()
    k = np.ones(win_pts) / win_pts
    pad = win_pts // 2
    ap = np.pad(np.asarray(a, float), pad, mode="edge")
    return np.convolve(ap, k, mode="same")[pad:pad + len(a)]


def _planar_len_km(x, y):
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 2:
        return np.nan
    return float(np.hypot(np.diff(x[ok]), np.diff(y[ok])).sum() / 1000.0)


def snap_along_channel(path, src, geoid_at):
    """Method 2 — walk the field line in along-channel order and snap each station to the DEM low.

    Returns a DataFrame of stations with the raw guide position, the snapped position, the
    channel water surface, and the perpendicular offset applied.
    """
    import geopandas as gpd

    g = gpd.read_file(path).to_crs(UTM).geometry.iloc[0]
    line = max(g.geoms, key=lambda s: s.length) if g.geom_type == "MultiLineString" else g

    s_m = np.arange(0.0, line.length, STATION_M)
    pts = [line.interpolate(v) for v in s_m]
    x = np.array([p.x for p in pts])
    y = np.array([p.y for p in pts])

    # Normals from a SMOOTHED copy: raw trackpoint-to-trackpoint tangents on a jittery boat
    # line point in near-random directions, which would aim the search window along the
    # channel instead of across it.
    wp = max(2, int(round(GUIDE_SMOOTH_M / STATION_M)))
    xs, ys = _boxcar(x, wp), _boxcar(y, wp)
    tx, ty = np.gradient(xs), np.gradient(ys)
    tn = np.hypot(tx, ty)
    tn[tn == 0] = 1.0
    nx, ny = -ty / tn, tx / tn

    offs = np.arange(-PERP_HALF_M, PERP_HALF_M + 1e-6, PERP_STEP_M)
    px = x[:, None] + nx[:, None] * offs[None, :]
    py = y[:, None] + ny[:, None] * offs[None, :]

    to_ras = Transformer.from_crs(UTM, src.crs, always_xy=True)
    rx, ry = to_ras.transform(px.ravel(), py.ravel())
    z = np.array([v[0] for v in src.sample(np.column_stack([rx, ry]))], float)
    z[(z == src.nodata) | (z == 0)] = np.nan
    z = z.reshape(px.shape)

    # Radius per station (for the geoid and for reporting), from the guide position.
    to_ll = Transformer.from_crs(UTM, 4326, always_xy=True)
    lon0, lat0 = to_ll.transform(x, y)
    d0, _ = dist_bear(lat0, lon0)
    z = z - np.array([geoid_at(r) for r in d0])[:, None]

    # Snap: thalweg = centroid of the deepest LOCATE_PCTL within the window; water surface =
    # WSE_PCTL within MEAS_WIN_M of it. Same rule as the arc method, in the perpendicular frame.
    n_st = len(s_m)
    off_snap = np.full(n_st, np.nan)
    wse = np.full(n_st, np.nan)
    for i in range(n_st):
        zi = z[i]
        ok = np.isfinite(zi)
        if ok.sum() < FP_MIN_PTS:
            continue
        thr = np.percentile(zi[ok], LOCATE_PCTL)
        sel = ok & (zi <= thr)
        if not sel.any():
            continue
        c = float(np.median(offs[sel]))
        off_snap[i] = c
        meas = ok & (np.abs(offs - c) <= MEAS_WIN_M)
        if meas.any():
            wse[i] = float(np.percentile(zi[meas], WSE_PCTL))

    sx = x + nx * np.nan_to_num(off_snap)
    sy = y + ny * np.nan_to_num(off_snap)
    sx[~np.isfinite(off_snap)] = np.nan
    sy[~np.isfinite(off_snap)] = np.nan
    slon, slat = to_ll.transform(sx, sy)
    d_snap, _ = dist_bear(slat, slon)

    return pd.DataFrame(dict(
        s_m=s_m, guide_x=x, guide_y=y, guide_dist_km=d0,
        snap_x=sx, snap_y=sy, snap_lat=slat, snap_lon=slon, snap_dist_km=d_snap,
        perp_offset_m=off_snap, wse_m=wse,
    ))


def main():
    kd, kb = hand_centerline_dbr(KAN_CL)
    ud, ub = hand_centerline_dbr(UYAK_CL)
    radii = np.round(np.arange(R_MIN, R_MAX + 1e-9, R_STEP), 3)

    # Per-radius EGM2008 geoid from the SWOT reference. Irrelevant to path length and
    # sinuosity; it matters for the long profile, which would otherwise carry a ~0.5 m
    # along-reach tilt against SWOT. Fall back to a flat geoid rather than failing.
    try:
        swot = pd.read_parquet(SWOT_REF).set_index("R_km")
        geo_r = swot.index.to_numpy(float)
        geo_v = swot["geoid_m"].to_numpy(float)
    except Exception:
        geo_r = np.array([R_MIN, R_MAX], float)
        geo_v = np.full(2, GEOID_FALLBACK, float)
        print(f"WARNING: {SWOT_REF} missing -- using constant geoid {GEOID_FALLBACK} m. "
              f"Harmless for path/sinuosity; the long profile will carry a ~0.5 m tilt.")

    def geoid_at(R):
        return float(np.interp(R, geo_r, geo_v))

    rows = []
    with rasterio.open(RASTER) as src:
        for R in radii:
            g = geoid_at(R)
            kbr = nearest_bearing(kd, kb, R)
            ubr = nearest_bearing(ud, ub, R)
            pk = np.radians(kbr - BEAR_MIN) * R * 1000.0 if np.isfinite(kbr) else np.nan
            pu = np.radians(ubr - BEAR_MIN) * R * 1000.0 if np.isfinite(ubr) else np.nan
            mid = 0.5 * (pk + pu) if (np.isfinite(pk) and np.isfinite(pu)) else np.nan

            kcm, kz, kn = _snap(src, R, pk, mid, SNAP_WIN_KAN_M, g)
            ucm, uz, un = _snap(src, R, pu, mid, SNAP_WIN_UYAK_M, g)
            klat, klon = _latlon(R, kcm)
            ulat, ulon = _latlon(R, ucm)
            pklat, pklon = _latlon(R, pk)
            pulat, pulon = _latlon(R, pu)

            rows.append(dict(
                R_km=R, geoid_m=g,
                kan_arc_m=kcm, kan_wse_m=kz, kan_lat=klat, kan_lon=klon,
                kan_prior_arc_m=pk, kan_prior_lat=pklat, kan_prior_lon=pklon,
                kan_offset_m=kcm - pk if np.isfinite(kcm) and np.isfinite(pk) else np.nan,
                kan_clipped=bool(np.isfinite(kcm) and np.isfinite(pk)
                                 and abs(kcm - pk) >= SNAP_WIN_KAN_M - ARC_STEP_M),
                kan_n_search=kn,
                uyak_arc_m=ucm, uyak_wse_m=uz, uyak_lat=ulat, uyak_lon=ulon,
                uyak_prior_arc_m=pu, uyak_prior_lat=pulat, uyak_prior_lon=pulon,
                uyak_offset_m=ucm - pu if np.isfinite(ucm) and np.isfinite(pu) else np.nan,
                uyak_clipped=bool(np.isfinite(ucm) and np.isfinite(pu)
                                  and abs(ucm - pu) >= SNAP_WIN_UYAK_M - ARC_STEP_M),
                uyak_n_search=un,
            ))

    df = pd.DataFrame(rows)
    os.makedirs(DATA, exist_ok=True)
    df.to_parquet(OUT_NODES, index=False, compression="zstd")
    print(f"wrote {os.path.relpath(OUT_NODES)}  ({len(df)} radii, {R_STEP*1000:.0f} m spacing)")

    # ---------------- Method 1 report: profile + migration QC only ----------------
    net = df.R_km.max() - df.R_km.min()
    print(f"\n=== Method 1: radial nodes ({df.R_km.min():.2f}-{df.R_km.max():.2f} km, "
          f"net {net:.2f} km) ===")
    print(f"{'':10s} {'valid':>6s} {'clip%':>6s} {'off_med':>8s} {'off_p90':>8s} {'hop>100m':>9s}")
    for tag, lab in (("kan", "Kanektok"), ("uyak", "Uyak")):
        off = df[f"{tag}_offset_m"].abs()
        step = np.abs(np.diff(df[f"{tag}_prior_arc_m"].to_numpy()))
        print(f"{lab:10s} {df[f'{tag}_wse_m'].notna().sum():6d} "
              f"{100*df[f'{tag}_clipped'].mean():6.1f} {off.median():8.1f} "
              f"{off.quantile(0.9):8.1f} {100*np.nanmean(step > 100):8.1f}%")
    print("  off_* = DEM channel vs 2026 field line (migration + wander, cannot be separated here).")
    print("  hop = adjacent-radius jumps in the PRIOR position: the limb-hopping that makes this")
    print("  frame useless for path length. Sinuosity is deliberately NOT reported from Method 1.")

    # cross-check against the 0.5 km arc analysis on the radii they share
    try:
        arc = pd.read_parquet(os.path.join(DATA, "arcB_channels.parquet"))
        j = df.merge(arc[["R_km", "kan_wse_m", "uyak_wse_m", "kan_arc_m", "uyak_arc_m"]],
                     on="R_km", suffixes=("", "_arcB"))
        print(f"\ncross-check vs arcB on {len(j)} shared radii (should be ~0):")
        for tag in ("kan", "uyak"):
            dz = (j[f"{tag}_wse_m"] - j[f"{tag}_wse_m_arcB"]).abs()
            dp = (j[f"{tag}_arc_m"] - j[f"{tag}_arc_m_arcB"]).abs()
            print(f"  {tag:5s} |dWSE| med {dz.median():.3f} m  p90 {dz.quantile(.9):.3f} m | "
                  f"|dpos| med {dp.median():.1f} m  p90 {dp.quantile(.9):.1f} m")
    except Exception as e:
        print(f"(arcB cross-check skipped: {e})")

    # ---------------- Method 2: along-channel snap, the sinuosity arbiter ----------------
    print("\n=== Method 2: along-channel DEM snap ===")
    snaps = {}
    with rasterio.open(RASTER) as src:
        for tag, lab, path in (("kan", "Kanektok", KAN_CL), ("uyak", "Uyak", UYAK_CL)):
            s = snap_along_channel(path, src, geoid_at)
            s.insert(0, "reach", lab)
            snaps[tag] = s
            print(f"  {lab}: {len(s)} stations, snapped {s.perp_offset_m.notna().sum()}, "
                  f"|offset| med {s.perp_offset_m.abs().median():.1f} m "
                  f"p90 {s.perp_offset_m.abs().quantile(.9):.1f} m")

    allsnap = pd.concat(snaps.values(), ignore_index=True)
    allsnap.to_parquet(OUT_SNAP, index=False, compression="zstd")
    print(f"  wrote {os.path.relpath(OUT_SNAP)}")

    wp_rep = max(2, int(round(REPORT_SMOOTH_M / STATION_M)))
    print(f"\n{'':10s} {'raw_km':>8s} {'rawSm':>8s} {'snap_km':>8s} {'snapSm':>8s} "
          f"{'net_km':>7s} {'sin_raw':>8s} {'sin_snapSm':>11s} {'wander%':>8s}")
    res = {}
    for tag, lab in (("kan", "Kanektok"), ("uyak", "Uyak")):
        s = snaps[tag]
        raw = _planar_len_km(s.guide_x.to_numpy(), s.guide_y.to_numpy())
        rawsm = _planar_len_km(_boxcar(s.guide_x.to_numpy(), wp_rep),
                               _boxcar(s.guide_y.to_numpy(), wp_rep))
        ok = np.isfinite(s.snap_x.to_numpy())
        sx, sy = s.snap_x.to_numpy()[ok], s.snap_y.to_numpy()[ok]
        snap = _planar_len_km(sx, sy)
        snapsm = _planar_len_km(_boxcar(sx, wp_rep), _boxcar(sy, wp_rep))
        netr = np.nanmax(s.guide_dist_km) - np.nanmin(s.guide_dist_km)
        res[tag] = dict(raw=raw, rawsm=rawsm, snap=snap, snapsm=snapsm, net=netr,
                        sin_raw=raw / netr, sin_snapsm=snapsm / netr)
        print(f"{lab:10s} {raw:8.2f} {rawsm:8.2f} {snap:8.2f} {snapsm:8.2f} {netr:7.2f} "
              f"{raw/netr:8.3f} {snapsm/netr:11.3f} {100*(1 - snapsm/raw):7.1f}%")
    print("  raw    = field line as collected;  rawSm = field line smoothed at "
          f"{REPORT_SMOOTH_M:.0f} m")
    print("  snap   = DEM-snapped path;  snapSm = DEM-snapped then smoothed (removes snap jitter)")
    print("  wander% = path length removed by snapping to the DEM channel and de-jittering")

    k, u = res["kan"], res["uyak"]
    print(f"\n  sinuosity ratio Uyak/Kanektok:  raw field {u['sin_raw']/k['sin_raw']:.3f}"
          f"   ->  DEM-snapped {u['sin_snapsm']/k['sin_snapsm']:.3f}")
    print("  If that ratio collapses toward 1, the Uyak's excess sinuosity was collection")
    print("  artifact, and the two field lines are NOT equally usable for path length.")


if __name__ == "__main__":
    main()
