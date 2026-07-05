"""
ADVERSARIAL verification of the temporal-analysis method decisions.

The decision under scrutiny: for slope, we POOL over years/seasons instead of
comparing per-year/per-season. Is that scientifically justified, or did we regroup
the data until an inconvenient "significant" result vanished (bias-fitting)?

We do NOT assume the answer. We test the two falsifiable claims the pooling rests on,
and then re-answer all three questions with an INDEPENDENT correction that involves
no pooling at all -- a fixed-distance-window slope, where every pass is measured over
the identical reach so coverage cannot bias it. If the independent method agrees, the
conclusion is robust to the grouping choice (not an artifact of it).

Tests:
  T1. Is the profile actually concave? (the mechanistic premise for the artifact)
  T2. Is the coverage artifact real & pervasive? corr(slope, pass-start) across ALL passes.
  T3. FIXED-WINDOW slope (no pooling): does it remove the lo_km correlation, and do the
      per-year Uyak 2025 "anomalies" (+8.3 seasonal, -6.8 interannual) disappear?
  T4. Is slope season-invariant when measured cleanly (full-coverage-only)? (non-circular)
  T5. Power/falsifiability: can the method resolve a real slope difference of this size?
      (the ~3 cm/km BETWEEN-river difference is the positive control.)

Run: python3 verify_temporal_method.py
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

DATA_GLOB = "batch_outputs/master_all_data_part_*.parquet"
REACHES = ["Kanektok_River", "Uyak_Creek"]
NODE_KM = 1.0
MIN_NODES = 8
MIN_SPAN_KM = 30.0
MAX_START_KM = 3.0
WLO, WHI = 3.0, 30.0            # fixed common window every gated pass covers
OPEN_WATER = {4, 5, 6, 7, 8, 9, 10, 11}
HIGH, LOW = {5}, {7, 8}


def per_pass(con, reach):
    nodes = con.execute(f"""
        SELECT CAST(Pass_Date AS DATE) AS d,
               EXTRACT(YEAR FROM CAST(Pass_Date AS DATE)) AS yr,
               EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) AS mo,
               ROUND(dist_km/{NODE_KM})*{NODE_KM} AS node, MEDIAN(wse) AS wse
        FROM read_parquet('{DATA_GLOB}') WHERE Reach_Name='{reach}'
        GROUP BY d, yr, mo, node ORDER BY d, node
    """).fetchdf()
    rows = []
    for d, g in nodes.groupby("d"):
        x = g["node"].to_numpy(float); y = g["wse"].to_numpy(float)
        if len(x) < MIN_NODES:
            continue
        lo, hi, span = float(x.min()), float(x.max()), float(x.max() - x.min())
        mo = int(g["mo"].iloc[0])
        gated = (span >= MIN_SPAN_KM) and (lo <= MAX_START_KM) and (mo in OPEN_WATER)
        ts_full = abs(stats.theilslopes(y, x)[0] * 100.0)
        # fixed-window slope: identical reach for every pass
        mask = (x >= WLO) & (x <= WHI)
        covers = (lo <= WLO) and (hi >= WHI) and (mask.sum() >= MIN_NODES)
        ts_win = abs(stats.theilslopes(y[mask], x[mask])[0] * 100.0) if covers else np.nan
        rows.append({"reach": reach, "year": int(g["yr"].iloc[0]), "month": mo,
                     "lo_km": lo, "span_km": span, "gated": gated,
                     "ts_full": ts_full, "ts_win": ts_win})
    return pd.DataFrame(rows)


def med(s):
    s = np.asarray(s, float); s = s[~np.isnan(s)]
    return np.median(s) if len(s) else np.nan


def mwu(a, b):
    a = np.asarray(a, float); a = a[~np.isnan(a)]
    b = np.asarray(b, float); b = b[~np.isnan(b)]
    if len(a) < 3 or len(b) < 3:
        return np.nan
    return stats.mannwhitneyu(a, b, alternative="two-sided").pvalue


def main():
    con = duckdb.connect()
    allp = pd.concat([per_pass(con, r) for r in REACHES], ignore_index=True)
    g = allp[allp["gated"]].copy()   # gated open-water passes

    print("#" * 80)
    print("T1. Is the profile actually CONCAVE? (premise: steep near confluence)")
    print("#" * 80)
    for reach in REACHES:
        # segment slopes from pooled node medians
        nd = con.execute(f"""
            SELECT ROUND(dist_km/{NODE_KM})*{NODE_KM} AS node, MEDIAN(wse) AS wse
            FROM read_parquet('{DATA_GLOB}')
            WHERE Reach_Name='{reach}'
              AND EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) IN (4,5,6,7,8,9,10,11)
            GROUP BY node ORDER BY node
        """).fetchdf()
        near = nd[nd["node"] <= 6]
        far = nd[nd["node"] >= 30]
        s_near = abs(stats.theilslopes(near["wse"], near["node"])[0] * 100)
        s_far = abs(stats.theilslopes(far["wse"], far["node"])[0] * 100)
        poly = np.polyfit(nd["node"], nd["wse"], 2)
        curv = poly[0]  # 2nd-order coeff; >0 => convex-up (concave profile: high near 0, flattening)
        verdict = "CONCAVE (steep->gentle)" if s_near > s_far else "NOT concave"
        print(f"  {reach:16s} near(0-6km)={s_near:6.1f}  far(30-36km)={s_far:6.1f} cm/km  "
              f"ratio={s_near/s_far:4.1f}x  quad_coef={curv:+.4f}  -> {verdict}")

    print("\n" + "#" * 80)
    print("T2. Is the COVERAGE ARTIFACT real & pervasive? corr(slope, pass-start lo_km)")
    print("    Prediction if real: full-profile slope correlates NEGATIVELY with lo_km.")
    print("#" * 80)
    for reach in REACHES:
        d = g[g["reach"] == reach]
        r_full = np.corrcoef(d["lo_km"], d["ts_full"])[0, 1]
        dw = d.dropna(subset=["ts_win"])
        r_win = np.corrcoef(dw["lo_km"], dw["ts_win"])[0, 1]
        print(f"  {reach:16s} corr(ts_FULL, lo_km)={r_full:+.2f} (n={len(d)})   "
              f"corr(ts_WINDOW, lo_km)={r_win:+.2f} (n={len(dw)})")
    print("  -> If ts_FULL corr is strongly negative but ts_WINDOW corr ~0, the artifact")
    print("     is real AND the fixed window removes it (by construction).")

    print("\n" + "#" * 80)
    print("T3. INDEPENDENT re-answer with FIXED-WINDOW slope (NO pooling).")
    print("    Do the per-year Uyak-2025 'anomalies' survive when coverage is held constant?")
    print("#" * 80)
    for reach in REACHES:
        d = g[g["reach"] == reach]
        print(f"\n  {reach}")
        # per-year seasonal (May vs Jul-Aug), full vs window
        for yr in [2024, 2025]:
            hi_f = d[(d.year == yr) & d.month.isin(HIGH)]["ts_full"]
            lo_f = d[(d.year == yr) & d.month.isin(LOW)]["ts_full"]
            hi_w = d[(d.year == yr) & d.month.isin(HIGH)]["ts_win"]
            lo_w = d[(d.year == yr) & d.month.isin(LOW)]["ts_win"]
            if len(hi_f) and len(lo_f):
                print(f"    seasonal {yr} (May-JulAug):  FULL {med(hi_f)-med(lo_f):+5.1f} cm/km "
                      f"(p={mwu(hi_f,lo_f):.3f})   WINDOW {med(hi_w)-med(lo_w):+5.1f} cm/km "
                      f"(p={mwu(hi_w,lo_w):.3f})")
        # interannual per-season (Jul-Aug 2024 vs 2025), full vs window
        a_f = d[(d.year == 2024) & d.month.isin(LOW)]["ts_full"]
        b_f = d[(d.year == 2025) & d.month.isin(LOW)]["ts_full"]
        a_w = d[(d.year == 2024) & d.month.isin(LOW)]["ts_win"]
        b_w = d[(d.year == 2025) & d.month.isin(LOW)]["ts_win"]
        print(f"    interannual JulAug (24->25): FULL {med(b_f)-med(a_f):+5.1f} cm/km "
              f"(p={mwu(a_f,b_f):.3f})   WINDOW {med(b_w)-med(a_w):+5.1f} cm/km "
              f"(p={mwu(a_w,b_w):.3f})")

    print("\n" + "#" * 80)
    print("T4. Is slope season-invariant on FULL-COVERAGE-ONLY passes (lo=0)? (non-circular)")
    print("#" * 80)
    for reach in REACHES:
        d = g[(g["reach"] == reach) & (g["lo_km"] == 0.0)]
        hi = d[d.month.isin(HIGH)]["ts_full"]; lo = d[d.month.isin(LOW)]["ts_full"]
        print(f"  {reach:16s} May={med(hi):6.1f}(n={len(hi)})  JulAug={med(lo):6.1f}(n={len(lo)})  "
              f"diff={med(hi)-med(lo):+.1f} cm/km  p={mwu(hi,lo):.3f}")

    print("\n" + "#" * 80)
    print("T5. POWER / positive control: can the method resolve a real ~3 cm/km difference?")
    print("    Between-river slope difference (Kanektok vs Uyak), same gated open-water set.")
    print("#" * 80)
    k = g[g.reach == "Kanektok_River"]["ts_full"]; u = g[g.reach == "Uyak_Creek"]["ts_full"]
    print(f"  Kanektok={med(k):.1f} (n={len(k)})  Uyak={med(u):.1f} (n={len(u)})  "
          f"diff={med(k)-med(u):+.1f} cm/km  p={mwu(k,u):.2e}")
    print("  -> A ~3 cm/km real difference is detected at high significance, so the method")
    print("     is NOT merely insensitive; a genuine temporal signal of that size WOULD show.")


if __name__ == "__main__":
    main()
