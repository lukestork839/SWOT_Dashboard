"""
Prototype: a defensible "reference gradient" for the SWOT river profiles.

Method (per the SWOT/SWORD convention + our discussion):
  1. Per pass (one Pass_Date), per reach: aggregate WSE to ~1 km "nodes"
     (median WSE per node) -- this is the pixels->nodes step.
  2. Fit a single reach slope per pass with the robust Theil-Sen estimator
     (median of pairwise slopes), in cm/km. OLS is also computed for comparison.
  3. Gate out passes whose along-stream coverage is too short -- short passes
     here sit on the steep upstream tail and would bias the mean upward.
  4. Average the per-pass slopes (mean AND median across passes) for three scopes:
        - all open-water (Apr-Nov)
        - high flow (May)
        - low flow (Jul-Aug)

This is a STANDALONE diagnostic. It does not touch the dashboard. It also reports
the two existing dashboard numbers (pooled-OLS trendline, broadcast slope_calc mean)
so we can compare apples to apples.

Run: python3 gradient_prototype.py
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

DATA_GLOB = "batch_outputs/master_all_data_part_*.parquet"
REACHES = ["Kanektok_River", "Uyak_Creek"]

# --- method parameters (the knobs we may want to tune) ---
NODE_KM = 1.0          # node bin size for per-pass aggregation
MIN_NODES = 8          # need enough nodes for a meaningful per-pass fit
MIN_SPAN_KM = 30.0     # full-coverage gate: pass must span >= this (near full ~35-36 km)
MAX_START_KM = 3.0     # full-coverage gate: pass must start <= this (includes steep downstream reach)

OPEN_WATER_MONTHS = {4, 5, 6, 7, 8, 9, 10, 11}
HIGH_FLOW_MONTHS = {5}        # May freshet (matches dashboard SEASONAL_PERIODS)
LOW_FLOW_MONTHS = {7, 8}      # Jul-Aug baseflow


def per_pass_slopes(con, reach):
    """Return a DataFrame: one row per pass with Theil-Sen & OLS slope (cm/km) + coverage."""
    # Pull node medians for every (pass, node) in one query, then fit in python.
    nodes = con.execute(f"""
        SELECT CAST(Pass_Date AS DATE) AS d,
               EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) AS mo,
               ROUND(dist_km / {NODE_KM}) * {NODE_KM} AS node,
               MEDIAN(wse) AS wse,
               COUNT(*) AS npix
        FROM read_parquet('{DATA_GLOB}')
        WHERE Reach_Name = '{reach}'
        GROUP BY d, mo, node
        ORDER BY d, node
    """).fetchdf()

    rows = []
    for d, g in nodes.groupby("d"):
        x = g["node"].to_numpy(dtype=float)
        y = g["wse"].to_numpy(dtype=float)
        if len(x) < MIN_NODES:
            continue
        span = x.max() - x.min()
        ts = stats.theilslopes(y, x)          # (slope, intercept, lo, hi) in m/km
        ols = stats.linregress(x, y)           # OLS on the same nodes
        rows.append({
            "date": d,
            "month": int(g["mo"].iloc[0]),
            "n_nodes": len(x),
            "n_pix": int(g["npix"].sum()),
            "lo_km": x.min(), "hi_km": x.max(), "span_km": span,
            "theilsen_cm_km": ts[0] * 100.0,
            "ols_cm_km": ols.slope * 100.0,
            "ols_r2": ols.rvalue ** 2,
        })
    return pd.DataFrame(rows)


def summarize(df, label):
    """Mean & median of per-pass Theil-Sen slope (abs cm/km) over a pass subset."""
    if len(df) == 0:
        return {"scope": label, "n_passes": 0}
    ts = df["theilsen_cm_km"].abs()
    return {
        "scope": label,
        "n_passes": len(df),
        "REFERENCE (TS median)": ts.median(),   # <-- chosen truth definition
        "TS mean": ts.mean(),
        "TS std": ts.std(),
        "TS SEM": ts.std() / np.sqrt(len(df)),
    }


def existing_dashboard_numbers(con, reach):
    """Reproduce the two numbers currently shown, for direct comparison."""
    # (a) pooled-OLS trendline: single regression over ALL points (all passes pooled)
    pts = con.execute(f"""
        SELECT dist_km, wse FROM read_parquet('{DATA_GLOB}')
        WHERE Reach_Name = '{reach}'
    """).fetchdf()
    pooled = stats.linregress(pts["dist_km"], pts["wse"]).slope * 100.0

    # (b) summary stat: AVG over 1km bins of MEDIAN(slope_calc) -- broadcast per-pass OLS
    summary = con.execute(f"""
        WITH binned AS (
            SELECT ROUND(dist_km) AS b, MEDIAN(slope_calc) AS s
            FROM read_parquet('{DATA_GLOB}')
            WHERE Reach_Name = '{reach}'
            GROUP BY ROUND(dist_km)
        )
        SELECT AVG(s) FROM binned
    """).fetchone()[0]
    return abs(pooled), abs(summary)


def main():
    con = duckdb.connect()
    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", 20)

    for reach in REACHES:
        print("=" * 78)
        print(reach)
        print("=" * 78)

        allp = per_pass_slopes(con, reach)
        full = (allp["span_km"] >= MIN_SPAN_KM) & (allp["lo_km"] <= MAX_START_KM)
        gated = allp[full]
        dropped = allp[~full]

        print(f"passes fit: {len(allp)} | full-coverage gate (span>={MIN_SPAN_KM:.0f}km & start<={MAX_START_KM:.0f}km) "
              f"-> keep {len(gated)}, drop {len(dropped)} (median slope of dropped/partial = "
              f"{dropped['theilsen_cm_km'].abs().median():.1f} cm/km)")

        # --- new reference gradient, three scopes (gated passes only) ---
        scopes = [
            ("ALL open-water (Apr-Nov)", gated[gated["month"].isin(OPEN_WATER_MONTHS)]),
            ("HIGH flow (May)", gated[gated["month"].isin(HIGH_FLOW_MONTHS)]),
            ("LOW flow (Jul-Aug)", gated[gated["month"].isin(LOW_FLOW_MONTHS)]),
        ]
        out = pd.DataFrame([summarize(d, lbl) for lbl, d in scopes])
        print("\n-- Per-pass-then-average reference gradient (Theil-Sen on 1km nodes) --")
        print(out.to_string(index=False,
              float_format=lambda v: f"{v:.2f}"))

        # --- sensitivity: what if we DON'T gate coverage? ---
        ow_nogate = allp[allp["month"].isin(OPEN_WATER_MONTHS)]
        print(f"\n   [sensitivity] open-water WITHOUT coverage gate: "
              f"TS mean = {ow_nogate['theilsen_cm_km'].abs().mean():.2f} cm/km "
              f"(n={len(ow_nogate)})  vs gated {out.iloc[0]['TS mean']:.2f}")

        # --- existing dashboard numbers ---
        pooled, summary = existing_dashboard_numbers(con, reach)
        print(f"\n-- Existing dashboard numbers (all data, all seasons) --")
        print(f"   pooled-OLS trendline (tab1 line)      : {pooled:.2f} cm/km")
        print(f"   summary stat (AVG bin MEDIAN slope_calc): {summary:.2f} cm/km")

        # --- decomposition: isolate node-aggregation vs per-pass-averaging vs robust ---
        ow = gated[gated["month"].isin(OPEN_WATER_MONTHS)]
        # pooled OLS on GLOBAL 1km node medians (density-unbiased, but still pooled)
        gnodes = con.execute(f"""
            SELECT ROUND(dist_km / {NODE_KM}) * {NODE_KM} AS node, MEDIAN(wse) AS wse
            FROM read_parquet('{DATA_GLOB}')
            WHERE Reach_Name = '{reach}'
              AND EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) IN (4,5,6,7,8,9,10,11)
            GROUP BY node ORDER BY node
        """).fetchdf()
        pooled_nodes = abs(stats.linregress(gnodes["node"], gnodes["wse"]).slope * 100.0)
        print(f"\n-- Decomposition (open-water) --")
        print(f"   [A] pooled OLS, raw points       : {pooled:.2f}  (density-biased toward dense ends)")
        print(f"   [B] pooled OLS, global 1km nodes : {pooled_nodes:.2f}  (removes density bias)")
        print(f"   [C] per-pass OLS, nodes, averaged: {ow['ols_cm_km'].abs().mean():.2f}  (adds per-pass averaging)")
        print(f"   [D] per-pass Theil-Sen, averaged : {ow['theilsen_cm_km'].abs().mean():.2f}  (adds robustness)  <-- proposed")
        print()


if __name__ == "__main__":
    main()
