"""Canonical thesis-number recomputation (number-drift reconciliation, 2026-07-22).

Recomputes every headline statistic the thesis figures/captions/prose cite, using
the SAME methods as thesis_figures/make_figures.py, from the current local archive.
Prints ONE authoritative value per metric so all documents can be reconciled to it.

Run: python3 canonical_stats.py
"""
import numpy as np
import pandas as pd
from thesis_figures import core, config


def hr(t):
    print("\n" + "=" * 70 + f"\n{t}\n" + "=" * 70)


# ---- Fig 4: reference hydraulic gradient -------------------------------------
hr("FIG 4 / Section 5.2 -- Reference hydraulic gradient")
ref = core.load_reference_gradient()
ow_gated = ref[(ref["open_water"]) & (ref["gated"])].copy()
ow_gated["abs"] = ow_gated["theilsen_cm_km"].abs()
ow_all = ref[ref["open_water"]].copy()
for reach in ["Kanektok_River", "Uyak_Creek"]:
    vals = ow_gated[ow_gated["Reach_Name"] == reach]["abs"].to_numpy()
    q25, med, q75 = np.percentile(vals, [25, 50, 75])
    print(f"{reach:16s} median={med:6.2f}  IQR=[{q25:.2f},{q75:.2f}] (width {q75-q25:.2f})  n_gated={len(vals)}")
n_gated_total = len(ow_gated)
n_ow_total = ow_all.groupby("Reach_Name").size().to_dict()
print(f"gated open-water passes total: {n_gated_total} "
      f"(Kanektok { (ow_gated.Reach_Name=='Kanektok_River').sum() } + "
      f"Uyak { (ow_gated.Reach_Name=='Uyak_Creek').sum() })")
print(f"ALL open-water passes (pre-gate) per reach: {n_ow_total}")

# ---- Fig 5/6/7: need the point table -----------------------------------------
con = core.connect()
df = core.load_swot(con, reaches=list(config.COLOR_MAP), open_water_only=True)
n_meas = len(df)
n_ow_passes = df.groupby("Reach_Name")["Pass_Date"].nunique().to_dict()
print(f"\nSpatial-profile passes (open-water, per reach): {n_ow_passes}")
print(f"Total WSE measurements (open-water): {n_meas:,}")

# ---- Fig 6: elevation difference ---------------------------------------------
hr("FIG 6 / Section 5.3 -- Elevation difference (Kanektok - Uyak)")
ediff = core.elevation_difference(con, open_water_only=True, bin_km=0.1, band=(25, 75))
y = ediff["diff"].to_numpy()
x = ediff["dist_bin"].to_numpy()
imin = int(np.argmin(y)); imax = int(np.argmax(y))
print(f"n bins: {len(ediff)}")
print(f"max sub-elevation (min diff): {y[imin]:+.3f} m at {x[imin]:.1f} km")
print(f"max super-elevation (max diff): {y[imax]:+.3f} m at {x[imax]:.1f} km")
print(f"mean diff across bins: {y.mean():+.3f} m ; median-of-bins: {np.median(y):+.3f} m")

# ---- Fig 7: detrended residuals ----------------------------------------------
hr("FIG 7 / Section 5.4 -- Detrended residuals (2nd-order pooled poly)")
base, _, _ = core.calculate_detrending(
    df["dist_km"].tolist(), df["wse"].tolist(), "Polynomial (2nd order)")
df = df.copy()
df["resid"] = df["wse"].to_numpy() - base
for reach in ["Kanektok_River", "Uyak_Creek"]:
    d = df[df["Reach_Name"] == reach]
    resid = d["resid"].to_numpy()
    keep = ~core.flag_residual_outliers(resid)
    r = resid[keep]
    print(f"{reach:16s} mean={r.mean():+.3f}  median={np.median(r):+.3f}  "
          f"P99={np.percentile(r,99):+.3f}  P1={np.percentile(r,1):+.3f}  "
          f"(n={len(r)}, dropped {len(resid)-len(r)})")

# ---- Fig 8: interval slope profile -------------------------------------------
hr("FIG 8 / Section 5.3 -- Interval slope profile (2 km smoothing)")
for reach in ["Kanektok_River", "Uyak_Creek"]:
    d = df[df["Reach_Name"] == reach]
    xe, slope, _ = core.calculate_slope_profile(
        d["dist_km"].tolist(), d["wse"].tolist(), smooth_km=2.0)
    s = np.abs(slope)
    print(f"{reach:16s} near-anchor (x<3km) ~{s[xe < 3].mean():.0f}  "
          f"near-mouth (x>30km) ~{s[xe > 30].mean():.0f}  "
          f"range [{s.min():.0f}, {s.max():.0f}] cm/km")

print("\n" + "=" * 70)
print("Study record range:")
allp = con.execute(
    "SELECT MIN(CAST(Pass_Date AS DATE)), MAX(CAST(Pass_Date AS DATE)), "
    "COUNT(DISTINCT CAST(Pass_Date AS DATE)) FROM river_data").fetchone()
print(f"  {allp[0]} -> {allp[1]}, {allp[2]} distinct pass-dates (all months)")
