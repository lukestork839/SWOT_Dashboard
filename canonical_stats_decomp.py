"""Decomposition + verification sub-numbers for the reference-gradient section
of SCIENTIFIC_METHODOLOGY.md (number-drift sweep, 2026-07-22)."""
import numpy as np
from thesis_figures import core, config

ref = core.load_reference_gradient()
con = core.connect()

for reach in ["Kanektok_River", "Uyak_Creek"]:
    print("\n" + "=" * 66 + f"\n{reach}\n" + "=" * 66)
    sub = ref[(ref.Reach_Name == reach) & (ref.open_water)].copy()
    gated = sub[sub.gated].copy()
    gated["abs_ts"] = gated["theilsen_cm_km"].abs()
    gated["abs_ols"] = gated["ols_cm_km"].abs()

    # --- reference-gradient table: median / May / Jul-Aug / std / n / SEM
    med = gated["abs_ts"].median()
    std = gated["abs_ts"].std()
    n = len(gated)
    sem = std / np.sqrt(n)
    may = gated[gated.month == 5]["abs_ts"].median()
    julaug = gated[gated.month.isin([7, 8])]["abs_ts"].median()
    print(f"[table] median={med:.1f}  May={may:.1f}  Jul-Aug={julaug:.1f}  "
          f"std={std:.1f}  n={n}  SEM={sem:.2f}")
    print(f"        mean|TS|={gated['abs_ts'].mean():.1f}  mean|OLS|={gated['abs_ols'].mean():.1f}")

    # --- decomposition [A] pooled OLS raw pixels, [B] pooled OLS 1km nodes
    months = ",".join(str(m) for m in core.OPEN_WATER_MONTHS)
    A = con.execute(
        f"SELECT regr_slope(wse, dist_km) FROM river_data "
        f"WHERE Reach_Name='{reach}' AND EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) IN ({months})"
    ).fetchone()[0]
    B = con.execute(
        f"SELECT regr_slope(m, node) FROM ("
        f"  SELECT ROUND(dist_km) AS node, MEDIAN(wse) AS m FROM river_data "
        f"  WHERE Reach_Name='{reach}' AND EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) IN ({months}) "
        f"  GROUP BY ROUND(dist_km))"
    ).fetchone()[0]
    print(f"[A] pooled OLS raw pixels : {abs(A)*100:.1f}")
    print(f"[B] pooled OLS 1km nodes  : {abs(B)*100:.1f}")
    print(f"[C] per-pass OLS nodes,mean: {gated['abs_ols'].mean():.1f}")
    print(f"[D] per-pass TS, mean      : {gated['abs_ts'].mean():.1f}")
    print(f"[D'] per-pass TS, median   : {med:.1f}  <- reference")

    # --- Verification 3: coverage-gate sensitivity (Uyak-relevant)
    sub["abs_ts"] = sub["theilsen_cm_km"].abs()
    old_gate = sub[(sub.n_nodes >= 8) & (sub.span_km >= 20)]   # old >=20km gate
    r_lo = np.corrcoef(sub["abs_ts"], sub["lo_km"])[0, 1]
    r_span = np.corrcoef(sub["abs_ts"], sub["span_km"])[0, 1]
    print(f"[V3] corr(slope,lo_km)={r_lo:+.2f}  corr(slope,span)={r_span:+.2f}")
    print(f"[V3] old >=20km gate: n={len(old_gate)}  median={old_gate['abs_ts'].median():.1f}  std={old_gate['abs_ts'].std():.1f}")
    print(f"[V3] new full gate  : n={n}  median={med:.1f}  std={std:.1f}")
    partial = sub[sub.span_km < 30]
    if len(partial):
        print(f"[V3] partial (span<30) median slope={partial['abs_ts'].median():.0f} cm/km (n={len(partial)})")
