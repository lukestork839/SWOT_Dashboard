"""
Per-arc SWOT water-surface reference for the DEM cross-section analysis.

Condenses the full SWOT pixel archive (millions of rows, gitignored) into ONE small committed
artifact keyed by the same iso-distance-from-anchor radii `build_arc_B.py` uses, so the arc
analysis and the hosted dashboard can both lean on SWOT without shipping the archive.

Three jobs, each answering a question the DEM alone cannot:

1. GEOID. `build_arc_B.py` historically subtracted a CONSTANT 13.46 m to go ellipsoidal ->
   orthometric. EGM2008 actually runs ~13.77 m at the anchor to ~13.27 m at the coast (0.50 m of
   drift over the reach). That constant is harmless for WITHIN-arc differences (beta,
   superelevation, Uyak-Kanektok all cancel it), but it puts a spurious ~0.5 m tilt into any
   DEM-vs-SWOT comparison. We take the geoid straight from the SWOT product's own `geoid` column.

2. STAGE DISTRIBUTION. A river has no single water surface: at a fixed radius the SWOT WSE spans
   ~0.7 m between p10 and p90 across overpasses. We publish median/p10/p90 per river per radius so
   the dashboard can show superelevation at a DECLARED stage with an honest band around it, rather
   than at whatever stage the DEM happened to catch.

3. STAGE-MATCHED BED + PASS-PAIRED COMPARISON.
   - The ArcticDEM v4.1 mosaic is a MULTI-DATE blend (2010-2021 over this corridor) and it caught
     the two rivers at different stages -- the Kanektok near the 29th percentile of observed
     stages, the Uyak near the 76th. A DEM-derived "Uyak minus Kanektok" therefore carries a ~0.34 m
     differential stage artifact. Pairing the rivers WITHIN a single overpass removes stage
     entirely, so `diff_pass_paired_m` is the trustworthy version of that comparison.
   - SWOT overflew on 2026-05-28 and 2026-05-30, INSIDE the 2026-05-28..06-03 boat-ADCP survey
     window. `kan_wse_survey_m` is the water surface at the stage the depths were measured at, so
     bed = kan_wse_survey_m - ADCP depth is a same-stage bed rather than one that mixes a
     2010-2021 DEM stage with a 2026 depth.

Run:  python3 DEM_Transects/swot_arc_reference.py   ->  data/swot_arc_reference.parquet
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(HERE, "data")

# The full pixel archive is gitignored (it lives in a GitHub Release for the hosted app); this
# script is the only thing that needs it, and it runs locally.
SWOT_CANDIDATES = [
    os.path.join(ROOT, "dashboard_data.parquet"),
    os.path.join(ROOT, "swot_apr_jul_2025_2026.parquet"),
]
OUT = os.path.join(DATA, "swot_arc_reference.parquet")

RADII = np.arange(3.0, 35.0, 0.5)        # must match build_arc_B.py
BIN_KM = 0.5
CLASS_MIN, CLASS_MAX = 3, 7              # validated SWOT water-classification filter
MIN_PIX = 15                             # min water pixels for a (pass, river, radius) estimate
MIN_PASSES = 8                           # min overpasses before we quote a stage distribution
# Boat-ADCP survey window; SWOT passes inside it give a water surface at the depth-measurement stage.
SURVEY_PASSES = ["2026-05-28", "2026-05-30"]

KAN, UYAK = "Kanektok_River", "Uyak_Creek"


def load_swot():
    for p in SWOT_CANDIDATES:
        if os.path.exists(p):
            print(f"reading {os.path.relpath(p, ROOT)}")
            return pd.read_parquet(p)
    raise SystemExit(
        "No SWOT archive found. Expected one of:\n  "
        + "\n  ".join(os.path.relpath(p, ROOT) for p in SWOT_CANDIDATES)
    )


def main():
    d = load_swot()
    d = d[d["classification"].between(CLASS_MIN, CLASS_MAX)].copy()
    d["Pass_Date"] = pd.to_datetime(d["Pass_Date"])
    # Snap each water pixel to the nearest arc radius -- the same 0.5 km grid the DEM arcs use.
    d["R_km"] = (d["dist_km"] / BIN_KM).round() * BIN_KM
    d = d[d["R_km"].between(RADII.min(), RADII.max())]

    # One WSE per (pass, river, radius): the median of that overpass's water pixels in the bin.
    per_pass = (d.groupby(["Pass_Date", "Reach_Name", "R_km"])
                 .agg(wse=("wse", "median"), geoid=("geoid", "median"), n_pix=("wse", "size"))
                 .reset_index())
    per_pass = per_pass[per_pass["n_pix"] >= MIN_PIX]

    rows = []
    for R in RADII:
        rec = {"R_km": float(R)}
        at_R = per_pass[per_pass["R_km"] == R]

        # (1) Geoid: EGM2008 height at this radius, from SWOT's own geoid field.
        rec["geoid_m"] = float(at_R["geoid"].median()) if len(at_R) else np.nan

        # (2) Stage distribution per river.
        for river, tag in ((KAN, "kan"), (UYAK, "uyak")):
            s = at_R[at_R["Reach_Name"] == river]["wse"]
            if len(s) >= MIN_PASSES:
                rec[f"swot_{tag}_wse_med_m"] = float(s.median())
                rec[f"swot_{tag}_wse_p10_m"] = float(s.quantile(0.10))
                rec[f"swot_{tag}_wse_p90_m"] = float(s.quantile(0.90))
            else:
                rec[f"swot_{tag}_wse_med_m"] = np.nan
                rec[f"swot_{tag}_wse_p10_m"] = np.nan
                rec[f"swot_{tag}_wse_p90_m"] = np.nan
            rec[f"swot_{tag}_n_pass"] = int(len(s))

        # (3a) Pass-paired Uyak - Kanektok: both rivers measured in the SAME overpass at the SAME
        # radius, so stage cancels exactly. This is the defensible inter-river comparison.
        w = at_R.pivot_table(index="Pass_Date", columns="Reach_Name", values="wse")
        if {KAN, UYAK}.issubset(w.columns):
            pair = (w[UYAK] - w[KAN]).dropna()
            rec["diff_pass_paired_m"] = float(pair.median()) if len(pair) else np.nan
            rec["diff_pass_paired_n"] = int(len(pair))
            rec["diff_pass_paired_frac_uyak_higher"] = float((pair > 0).mean()) if len(pair) else np.nan
        else:
            rec["diff_pass_paired_m"] = np.nan
            rec["diff_pass_paired_n"] = 0
            rec["diff_pass_paired_frac_uyak_higher"] = np.nan

        # (3b) Water surface at the boat-ADCP survey stage -> a same-stage channel bed.
        surv = at_R[(at_R["Reach_Name"] == KAN)
                    & at_R["Pass_Date"].isin(pd.to_datetime(SURVEY_PASSES))]["wse"]
        rec["swot_kan_wse_survey_m"] = float(surv.median()) if len(surv) else np.nan
        rec["swot_kan_survey_n_pass"] = int(len(surv))
        rows.append(rec)

    ref = pd.DataFrame(rows)
    # Radii with thin SWOT coverage leave gaps; the geoid is a smooth field, so interpolating it
    # across them is safe (and it must never be NaN -- it sets the DEM's vertical datum).
    ref["geoid_m"] = ref["geoid_m"].interpolate(limit_direction="both")
    ref.to_parquet(OUT, index=False)

    print(f"wrote data/swot_arc_reference.parquet ({len(ref)} radii)")
    print(f"  geoid (EGM2008): {ref['geoid_m'].iloc[0]:.2f} m at {ref['R_km'].iloc[0]:.1f} km "
          f"-> {ref['geoid_m'].iloc[-1]:.2f} m at {ref['R_km'].iloc[-1]:.1f} km "
          f"(drift {ref['geoid_m'].max() - ref['geoid_m'].min():.2f} m; "
          f"the old constant was 13.46 m)")
    for tag, name in (("kan", "Kanektok"), ("uyak", "Uyak")):
        band = (ref[f"swot_{tag}_wse_p90_m"] - ref[f"swot_{tag}_wse_p10_m"]).median()
        print(f"  {name:9s} stage band (p10-p90) median {band:.2f} m "
              f"over {ref[f'swot_{tag}_n_pass'].median():.0f} passes/radius")
    dp = ref.dropna(subset=["diff_pass_paired_m"])
    print(f"  pass-paired Uyak - Kanektok: median {dp['diff_pass_paired_m'].median():+.2f} m "
          f"on {len(dp)} radii ({int(dp['diff_pass_paired_n'].sum())} pass-radius pairs); "
          f"Uyak higher on {dp['diff_pass_paired_frac_uyak_higher'].median()*100:.0f}% of passes")
    sv = ref.dropna(subset=["swot_kan_wse_survey_m"])
    print(f"  survey-stage Kanektok WSE ({'/'.join(SURVEY_PASSES)}) on {len(sv)} radii "
          f"-> the same-stage bed reference for H_M")


if __name__ == "__main__":
    main()
