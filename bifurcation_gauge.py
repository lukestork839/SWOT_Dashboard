#!/usr/bin/env python3
"""Bifurcation virtual gauge: local stage vs local hydraulic gradient.

The temporal analysis characterises each pass with a whole-reach fit
(temporal_analysis.py). This module asks the avulsion-relevant *local*
question instead: right where an avulsion would initiate, does the
Kanektok's gradient advantage hold as stage rises?

Method
------
Two things are measured, and they deliberately use two different rulers.

**Gradient** is fitted on the project-wide radial ``dist_km`` axis (great-
circle distance from the anchor point), over the FIXED 3.5-7.5 km window:
pixel WSE is binned to 0.5 km nodes (9 node centres; round-binning, the
same convention as the 1 km nodes of the temporal analysis) and a Theil-Sen
line is fitted through the node medians. The window sits entirely below the
bifurcation (2.49 km) and entirely clear of the zone where the two reach
polygons overlap, so no shared water enters either river's fit.

Radial distance compresses a curving channel, so these gradients run ~1.47x
steeper than true along-channel water-surface slopes. That inflation is
near-identical for the two rivers on this window (1.473x Kanektok vs 1.459x
Uyak, a 0.9% mismatch), which is exactly why the radial axis is kept: it is
the fairest available ruler for a BETWEEN-river comparison. Re-origining the
radial axis to the bifurcation would widen the mismatch to 7.2% and bias the
comparison for no gain.

**Stage** is measured at a virtual gauge sited by ALONG-CHANNEL distance
from the split, one per river: the point GAUGE_S_KM downstream of the
bifurcation along that river's official centerline, with stage taken as the
observed median WSE of the river's pixels within GAUGE_RADIUS_M of it.

Along-channel siting is required here and a radial ring will not do. A ring
1 km from the split crosses the Kanektok at 0.97 channel-km but the Uyak at
1.18 channel-km; at ~1.7 m of drop per channel-km that 0.21 km mismatch is
worth ~0.35 m of water surface -- enough to reverse the sign of the
between-river stage comparison. Equal along-channel siting removes it: the
two surfaces leave the split together and separate downstream, which is the
physical behaviour STAGE_DIVERGENCE_S_KM traces out.

Two gauge sitings are computed side by side (GAUGE_S_KM) so the sensitivity
to that choice is visible rather than assumed. At both, each gauge disc
draws on one reach mask only -- zero pixels from the other river -- so the
braid-plain polygon overlap upstream of the split, which is physically real
(water there can enter either channel), is left untouched.

Because the fitting window is FIXED, the fit is immune to the coverage-
truncation artifact that displaces two 2023 Uyak passes in the whole-reach
metrics (fitting a varying span of a curved profile). A pass is gated in
only when all 9 nodes are present with >= MIN_PX_PER_NODE pixels each and
the gauge disc holds >= MIN_PX_PER_GAUGE pixels.

Outputs (git-tracked, like the temporal results)
------------------------------------------------
  temporal_results/bifurcation_gauge_per_pass.parquet  one row per river-pass
  temporal_results/bifurcation_gauge_results.json      summary statistics

Usage
-----
    python bifurcation_gauge.py
"""

from __future__ import annotations

import json
import os

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy import stats
from shapely.geometry import LineString, Point

from swot_core import config

OUT_DIR = "temporal_results"
OUT_PARQUET = f"{OUT_DIR}/bifurcation_gauge_per_pass.parquet"
OUT_SUMMARY = f"{OUT_DIR}/bifurcation_gauge_results.json"

# Frozen master archive only (no Q3 top-up: this is not a storm-window
# analysis, and every headline number should derive from the freeze).
DATA_GLOB = "batch_outputs/master_all_data_part_*.parquet"

REACHES = list(config.REACH_NAMES)

# Official channel centerlines, shared with the DEM transect work.
CENTERLINES = {
    "Kanektok_River": "DEM_Transects/data/kanektok_centerline_official.gpkg",
    "Uyak_Creek": "DEM_Transects/data/uyak_centerline_official.gpkg",
}
UTM_EPSG = 32603   # WGS84 / UTM zone 3N — metric, local, negligible distortion

# --- gradient parameters (radial dist_km axis, project convention) ---
NODE_KM = 0.5            # node bin size (finer than the 1 km whole-reach nodes)
WIN_LO_KM = 3.5          # fixed fit window, entirely below the split and
WIN_HI_KM = 7.5          # entirely clear of the reach-polygon overlap
MIN_PX_PER_NODE = 20     # per-node pixel floor
N_NODES = int(round((WIN_HI_KM - WIN_LO_KM) / NODE_KM)) + 1   # 9

# --- gauge parameters (along-channel siting from the split) ---
GAUGE_S_KM = (1.00, 1.25)   # both sitings reported; PRIMARY_S_KM drives headlines
PRIMARY_S_KM = 1.00
GAUGE_RADIUS_M = 300.0      # sampling disc around the centerline gauge point
MIN_PX_PER_GAUGE = 20

# Along-channel stations for the stage-divergence profile (the two water
# surfaces leaving one split and separating downstream). The ladder starts at
# 0.75 km because that is where the channels are far enough apart (529 m) for
# the two GAUGE_RADIUS_M discs to stop sharing pixels: closer in they overlap
# (965 shared pixels at 0.50 km, 5,167 at 0.25 km) and the "gap" is partly the
# same water differenced against itself. SHARED_PX_TOLERANCE enforces this.
STAGE_DIVERGENCE_S_KM = (0.75, 1.00, 1.25, 1.50, 1.75,
                         2.00, 2.25, 2.50, 2.75, 3.00)
SHARED_PX_TOLERANCE = 0   # stations sharing any pixel between discs are dropped


# ---------------------------------------------------------------------------
# Geometry: centerlines, gauge siting
# ---------------------------------------------------------------------------
def _to_utm():
    return Transformer.from_crs(4326, UTM_EPSG, always_xy=True)


def load_centerlines():
    """Each river's centerline in UTM, with s = 0 at the bifurcation.

    Returns {reach: (LineString, s0_m)}, where s0_m is the arc-length
    position of the bifurcation point along that line. Both official
    centerlines begin at the split (the bifurcation projects to 0 m and 7 m
    from their starts), so s0 is essentially zero — it is computed rather
    than assumed so the siting stays correct if a centerline is re-cut.
    """
    tf = _to_utm()
    ax, ay = tf.transform(config.ANCHOR_LON, config.ANCHOR_LAT)
    bif = Point(*tf.transform(config.BIFURCATION_LON, config.BIFURCATION_LAT))
    out = {}
    for reach, path in CENTERLINES.items():
        xy = np.asarray(gpd.read_file(path).to_crs(UTM_EPSG).geometry.iloc[0].coords)
        # Orient downstream: the end nearest the anchor is the upstream end.
        if (np.hypot(xy[-1, 0] - ax, xy[-1, 1] - ay)
                < np.hypot(xy[0, 0] - ax, xy[0, 1] - ay)):
            xy = xy[::-1]
        line = LineString(xy)
        out[reach] = (line, line.project(bif))
    return out


def gauge_points(cls, s_km):
    """{reach: (lon, lat, x_utm, y_utm)} at s_km along-channel past the split."""
    inv = Transformer.from_crs(UTM_EPSG, 4326, always_xy=True)
    pts = {}
    for reach, (line, s0) in cls.items():
        p = line.interpolate(s0 + s_km * 1000.0)
        lon, lat = inv.transform(p.x, p.y)
        pts[reach] = (float(lon), float(lat), float(p.x), float(p.y))
    return pts


def centerline_separation(cls, s_km):
    """Distance between the two channels at the s_km gauge stations (m)."""
    pts = gauge_points(cls, s_km)
    (ka, ua) = REACHES
    pk = Point(pts[ka][2], pts[ka][3])
    pu = Point(pts[ua][2], pts[ua][3])
    return float(min(cls[ua][0].distance(pk), cls[ka][0].distance(pu)))


# ---------------------------------------------------------------------------
# Per-pass measurements
# ---------------------------------------------------------------------------
def per_pass_gradient(con, reach):
    """One row per pass: Theil-Sen gradient over the fixed radial window."""
    nodes = con.execute(f"""
        SELECT CAST(Pass_Date AS DATE) AS d,
               ROUND(dist_km / {NODE_KM}) * {NODE_KM} AS node,
               MEDIAN(wse) AS wse,
               COUNT(*) AS n_px
        FROM read_parquet('{DATA_GLOB}')
        WHERE Reach_Name = '{reach}'
          AND dist_km >= {WIN_LO_KM - NODE_KM / 2}
          AND dist_km <  {WIN_HI_KM + NODE_KM / 2}
        GROUP BY d, node
        ORDER BY d, node
    """).fetchdf()

    rows = []
    for d, g in nodes.groupby("d"):
        ok = g[g["n_px"] >= MIN_PX_PER_NODE]
        if len(ok) < 3:
            continue
        x = ok["node"].to_numpy(dtype=float)
        y = ok["wse"].to_numpy(dtype=float)
        # (slope, intercept, ci_lo, ci_hi) in m/km; slope < 0 downstream
        ts = np.asarray(stats.theilslopes(y, x), dtype=float)
        rows.append({
            "reach": reach,
            "date": pd.Timestamp(d),
            "year": int(pd.Timestamp(d).year),
            "month": int(pd.Timestamp(d).month),
            "n_nodes": len(ok),
            "min_px": int(ok["n_px"].min()),
            "slope_cm_km": abs(ts[0]) * 100.0,
            "slope_lo_cm_km": abs(ts[3]) * 100.0,   # CI endpoints of a
            "slope_hi_cm_km": abs(ts[2]) * 100.0,   # negative slope swap
            "nodes_complete": len(ok) == N_NODES,
        })
    return pd.DataFrame(rows)


def reach_pixels(con, reach, max_dist_km=8.0):
    """Reach pixels near the bifurcation, in UTM, for gauge-disc sampling."""
    df = con.execute(f"""
        SELECT CAST(Pass_Date AS DATE) AS d, latitude, longitude, wse
        FROM read_parquet('{DATA_GLOB}')
        WHERE Reach_Name = '{reach}' AND dist_km < {max_dist_km}
    """).fetchdf()
    x, y = _to_utm().transform(df["longitude"].to_numpy(), df["latitude"].to_numpy())
    df["x"], df["y"] = x, y
    return df


def gauge_stage(px, gx, gy):
    """Per-pass observed median WSE inside the gauge disc."""
    d = px[np.hypot(px["x"] - gx, px["y"] - gy) < GAUGE_RADIUS_M]
    g = d.groupby("d")["wse"].agg(stage_m="median", n_px_gauge="size")
    return g[g["n_px_gauge"] >= MIN_PX_PER_GAUGE]


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------
def _med_iqr(v):
    v = np.asarray(v, dtype=float)
    return {"median": round(float(np.median(v)), 3),
            "q1": round(float(np.percentile(v, 25)), 3),
            "q3": round(float(np.percentile(v, 75)), 3),
            "n": int(len(v))}


def _stage_trend(stage, grad):
    """Sensitivity of gradient to stage: Theil-Sen (cm/km per m) + Kendall tau."""
    ts = np.asarray(stats.theilslopes(grad, stage), dtype=float)
    kt = np.asarray(stats.kendalltau(stage, grad), dtype=float)
    return {"cm_km_per_m": round(ts[0], 1),
            "ci_lo": round(ts[2], 1), "ci_hi": round(ts[3], 1),
            "kendall_tau": round(kt[0], 3),
            "p": round(kt[1], 4)}


def _disc(px, gx, gy):
    return px[np.hypot(px["x"] - gx, px["y"] - gy) < GAUGE_RADIUS_M]


def _shared_pixels(a, b):
    """How many identical pixels (same pass, same position) two discs share."""
    def key(d):
        return set(zip(d["d"].astype(str),
                       d["latitude"].round(6), d["longitude"].round(6)))
    return len(key(a) & key(b))


def stage_divergence(cls, pixels):
    """Both water surfaces along the channel below the split, and their gap.

    One row per along-channel station: each river's median gauge stage plus
    the paired per-pass difference. Stations whose two discs share pixels are
    dropped (see STAGE_DIVERGENCE_S_KM) so the gap is never partly the same
    water differenced against itself.
    """
    ka, ua = REACHES
    rows = []
    for s in STAGE_DIVERGENCE_S_KM:
        pts = gauge_points(cls, s)
        discs = {r: _disc(pixels[r], pts[r][2], pts[r][3]) for r in REACHES}
        shared = _shared_pixels(discs[ka], discs[ua])
        if shared > SHARED_PX_TOLERANCE:
            print(f"    [skip] s={s:.2f} km: discs share {shared} pixels")
            continue
        stages = {r: gauge_stage(pixels[r], pts[r][2], pts[r][3])["stage_m"]
                  for r in REACHES}
        both = pd.DataFrame(stages).dropna()
        if both.empty:
            continue
        gap = both[ka] - both[ua]
        rows.append({
            "s_km": s,
            "separation_m": round(centerline_separation(cls, s), 0),
            "n_passes": int(len(both)),
            "shared_px": shared,
            "kanektok_wse_m": round(float(both[ka].median()), 3),
            "uyak_wse_m": round(float(both[ua].median()), 3),
            "kanektok_q1_m": round(float(both[ka].quantile(0.25)), 3),
            "kanektok_q3_m": round(float(both[ka].quantile(0.75)), 3),
            "uyak_q1_m": round(float(both[ua].quantile(0.25)), 3),
            "uyak_q3_m": round(float(both[ua].quantile(0.75)), 3),
            "gap_median_m": round(float(gap.median()), 3),
            "gap_q1_m": round(float(gap.quantile(0.25)), 3),
            "gap_q3_m": round(float(gap.quantile(0.75)), 3),
        })
    return pd.DataFrame(rows)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    con = duckdb.connect()
    cls = load_centerlines()

    # --- gradient (radial axis) + stage (along-channel gauges) ------------------
    per = pd.concat([per_pass_gradient(con, r) for r in REACHES], ignore_index=True)
    pixels = {r: reach_pixels(con, r) for r in REACHES}

    gauge_meta = {}
    for s in GAUGE_S_KM:
        pts = gauge_points(cls, s)
        col = f"stage_s{int(round(s * 100)):d}_m"
        npx = f"n_px_s{int(round(s * 100)):d}"
        gauge_meta[f"{s:.2f}"] = {
            "s_km": s,
            "separation_m": round(centerline_separation(cls, s), 0),
            "radius_m": GAUGE_RADIUS_M,
            "points": {r: {"lon": round(pts[r][0], 6), "lat": round(pts[r][1], 6)}
                       for r in REACHES},
            "stage_col": col,
        }
        for r in REACHES:
            st = gauge_stage(pixels[r], pts[r][2], pts[r][3])
            m = per["reach"] == r
            per.loc[m, col] = per.loc[m, "date"].map(st["stage_m"]).to_numpy()
            per.loc[m, npx] = per.loc[m, "date"].map(st["n_px_gauge"]).to_numpy()

    primary_col = gauge_meta[f"{PRIMARY_S_KM:.2f}"]["stage_col"]
    per["stage_m"] = per[primary_col]          # headline stage
    per["gated"] = per["nodes_complete"] & per["stage_m"].notna()
    per.to_parquet(OUT_PARQUET, index=False)

    g = per[per["gated"]]
    print(f"Bifurcation virtual gauge")
    print(f"  gradient: radial dist_km, {WIN_LO_KM}-{WIN_HI_KM} km, "
          f"{NODE_KM} km nodes ({N_NODES} required)")
    print(f"  stage:    along-channel gauges at s = "
          f"{', '.join(f'{s:.2f}' for s in GAUGE_S_KM)} km past the split, "
          f"{GAUGE_RADIUS_M:.0f} m disc (primary s = {PRIMARY_S_KM:.2f} km)")
    for k, meta in gauge_meta.items():
        print(f"    s={k} km: channels {meta['separation_m']:.0f} m apart; "
              + "; ".join(f"{r.split('_')[0]} "
                          f"{meta['points'][r]['lat']:.6f},{meta['points'][r]['lon']:.6f}"
                          for r in REACHES))

    summary = {
        "gradient": {"axis": "radial dist_km from the anchor point",
                     "window_km": [WIN_LO_KM, WIN_HI_KM], "node_km": NODE_KM,
                     "min_px_per_node": MIN_PX_PER_NODE, "n_nodes": N_NODES},
        "gauges": gauge_meta,
        "primary_s_km": PRIMARY_S_KM,
        "rivers": {}, "paired": {}, "paired_by_gauge": {},
        "stage_divergence": [],
    }

    for reach in REACHES:
        d = g[g["reach"] == reach]
        s = _med_iqr(d["slope_cm_km"])
        trend = _stage_trend(np.asarray(d["stage_m"], dtype=float),
                             np.asarray(d["slope_cm_km"], dtype=float))
        summary["rivers"][reach] = {
            "gradient_cm_km": s,
            "stage_m": _med_iqr(d["stage_m"]),
            "gradient_vs_stage": trend,
        }
        print(f"  {reach}: gradient median {s['median']} cm/km "
              f"[IQR {s['q1']}-{s['q3']}], n={s['n']} gated passes")
        print(f"    gradient vs stage: {trend['cm_km_per_m']:+.1f} cm/km per m "
              f"(tau={trend['kendall_tau']:+.3f}, p={trend['p']:.4f})")

    # Paired per-pass comparison on dates where BOTH rivers gate in. The two
    # gauges sit the same channel distance below one shared water surface, so
    # the per-pass mean of their stages is the shared stage axis.
    for key, meta in gauge_meta.items():
        col = meta["stage_col"]
        sub = per[per["nodes_complete"] & per[col].notna()]
        wide = sub.pivot(index="date", columns="reach",
                         values=["slope_cm_km", col]).dropna()
        dslope = (wide[("slope_cm_km", REACHES[0])]
                  - wide[("slope_cm_km", REACHES[1])])
        stage_shared = wide[col].mean(axis=1)
        stage_gap = wide[(col, REACHES[0])] - wide[(col, REACHES[1])]
        block = {
            "s_km": meta["s_km"],
            "n_paired_passes": int(len(wide)),
            "advantage_cm_km": _med_iqr(dslope),
            "pct_passes_kanektok_steeper": round(100.0 * float((dslope > 0).mean()), 1),
            "advantage_vs_stage": _stage_trend(np.asarray(stage_shared, dtype=float),
                                               np.asarray(dslope, dtype=float)),
            "stage_gap_kan_minus_uyak_m": _med_iqr(stage_gap),
            "stage_corr_kan_uyak": round(float(np.corrcoef(
                wide[(col, REACHES[0])], wide[(col, REACHES[1])])[0, 1]), 3),
        }
        summary["paired_by_gauge"][key] = block
        if meta["s_km"] == PRIMARY_S_KM:
            summary["paired"] = block
        adv, tr = block["advantage_cm_km"], block["advantage_vs_stage"]
        print(f"  Paired @ s={key} km (n={block['n_paired_passes']}): advantage median "
              f"{adv['median']:+.1f} cm/km [IQR {adv['q1']:+.1f}..{adv['q3']:+.1f}], "
              f"Kanektok steeper on {block['pct_passes_kanektok_steeper']}%")
        print(f"    advantage vs stage: {tr['cm_km_per_m']:+.1f} cm/km per m "
              f"(tau={tr['kendall_tau']:+.3f}, p={tr['p']:.4f}); "
              f"stage gap K-U {block['stage_gap_kan_minus_uyak_m']['median']:+.3f} m, "
              f"stage corr {block['stage_corr_kan_uyak']:.3f}")

    div = stage_divergence(cls, pixels)
    summary["stage_divergence"] = div.to_dict("records")
    print("  Water surfaces below the split (median across passes):")
    for _, r in div.iterrows():
        print(f"    s={r.s_km:4.2f} km ({r.separation_m:4.0f} m apart, n={r.n_passes:3.0f}): "
              f"Kanektok {r.kanektok_wse_m:6.2f} m, Uyak {r.uyak_wse_m:6.2f} m, "
              f"gap {r.gap_median_m:+.3f} [{r.gap_q1_m:+.3f}..{r.gap_q3_m:+.3f}]")

    with open(OUT_SUMMARY, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nwrote {OUT_PARQUET} ({len(per)} river-passes) and {OUT_SUMMARY}")


if __name__ == "__main__":
    main()
