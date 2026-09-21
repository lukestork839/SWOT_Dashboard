"""
One-time temporal analysis of the SWOT river record (Kanektok, Uyak).

Answers three questions with ONE defensible methodology (the same per-pass,
density-unbiased, robust engine used for the reference gradient):

  Q1. Seasonal natural variability   -- High flow (May) vs Low flow (Jul-Aug)
  Q2. Normal interannual stability    -- Summer 2024 vs Summer 2025 (no disturbance)
  Q3. Extreme-event impact            -- Pre- vs post-Typhoon Halong:
      Jul-Aug 2025 (last low-flow season before landfall) vs Jul-Aug 2026
      (first after). DEFINITIVE window — supersedes the June-vs-June interim
      comparison used while the 2026 low-flow season was still incomplete.

Scientific logic: Q2 is the CONTROL for Q3. Interannual change under no
disturbance (2024->2025) is the natural-variability baseline; the storm signal
(2025->2026) is only meaningful if it exceeds that baseline.

Two metrics per pass, both density-unbiased (fit on 1 km node medians, not raw
pixels), both robust (Theil-Sen):
  * slope  (cm/km)  -- the hydraulic gradient (longitudinal drive for avulsion)
  * WSE@ref (m)     -- water level at a fixed reference distance (flow / storm signal)

Only "full-coverage open-water" passes are used (same gate as the reference
gradient: >=8 nodes, span >=30 km, start <=3 km, months Apr-Nov), so that
partial passes clipping the steep downstream reach cannot bias the comparison.

This is a STANDALONE one-time diagnostic. It reads the FULL local record
(batch_outputs/, 2023-2026), not the online subset. It does not touch the
dashboard.

Run: python3 temporal_analysis.py
"""

from __future__ import annotations

import json
import os

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

# Output artifacts land in temporal_results/ -- a small, git-TRACKED directory (unlike
# the gitignored batch_outputs/ raw data), so the dashboard reads the exact same files
# both locally and on Streamlit Cloud. These are tiny (KB) pre-computed results.
OUT_DIR = "temporal_results"
OUT_METRICS = f"{OUT_DIR}/temporal_metrics_per_pass.parquet"
OUT_SUMMARY = f"{OUT_DIR}/temporal_analysis_results.json"
OUT_Q3PROFILE = f"{OUT_DIR}/temporal_q3_profile.parquet"

DATA_GLOB = "batch_outputs/master_all_data_part_*.parquet"

# Definitive-Q3 supplement: the master archive was frozen at FREEZE_DATE for
# the thesis (every headline value derives from it), but the Jul-Aug 2026
# low-flow window runs past the freeze. The late-August 2026 granules are
# pulled by q3_topup_pull.py into an ISOLATED directory and combined into this
# parquet. It feeds ONLY the Q3 storm-window comparison: Q1/Q2 (and the Q2
# baseline that Q3 is judged against) are computed on passes <= FREEZE_DATE,
# so no pre-existing number can move. If the parquet is absent the analysis
# still runs, with the 2026 storm window truncated at the freeze date.
TOPUP_PARQUET = "batch_outputs/q3_topup_20260831/q3_topup.parquet"
FREEZE_DATE = "2026-08-10"

REACHES = ["Kanektok_River", "Uyak_Creek"]

# --- method parameters (locked to match the reference gradient) ---
NODE_KM = 1.0          # node bin size for per-pass aggregation
MIN_NODES = 8          # need enough nodes for a meaningful per-pass fit
MIN_SPAN_KM = 30.0     # full-coverage gate: pass must span >= this
MAX_START_KM = 3.0     # full-coverage gate: pass must start <= this (steep reach)
REF_DIST_KM = 15.0     # water-level reference distance (inside every gated pass's coverage)

# Open-water window, single-sourced from the QC registry (May-Oct hard line,
# empirically calibrated 2026-08: April breakup interference in every observed
# year, October clean, first freeze-up mid-Nov). The master parquet is already
# filtered to these months at rebuild, so this is a consistency guard, not an
# extra filter. (The earlier Apr-Nov window's shoulder-month slope validation is
# recorded in TEMPORAL_ANALYSIS.md; the shoulders are now excluded because their
# WSE — the Q1/Q3 metric — is ice-contaminated even where slope survives.)
from qc_registry import ICE_SAFE_MONTHS
OPEN_WATER_MONTHS = ICE_SAFE_MONTHS
HIGH_FLOW_MONTHS = {5}      # May freshet
LOW_FLOW_MONTHS = {7, 8}    # Jul-Aug baseflow

# Typhoon Halong landfall (the extratropical remnant struck western Alaska on
# this date). The Q3 windows follow from it: PRE = the last complete low-flow
# (Jul-Aug) season before landfall = 2025; POST = the first one after = 2026.
TYPHOON_DATE = "2025-10-12"
Q3_PRE_YEAR = 2025
Q3_POST_YEAR = 2026


def _source_expr():
    """DuckDB read_parquet() source: the frozen master, plus the isolated
    Q3 top-up parquet when it exists (see TOPUP_PARQUET note above)."""
    if os.path.exists(TOPUP_PARQUET):
        return f"read_parquet(['{DATA_GLOB}', '{TOPUP_PARQUET}'])"
    return f"read_parquet('{DATA_GLOB}')"


def per_pass_metrics(con, reach, src):
    """One row per pass: robust slope + water level, both from 1 km node medians."""
    nodes = con.execute(f"""
        SELECT CAST(Pass_Date AS DATE) AS d,
               EXTRACT(YEAR  FROM CAST(Pass_Date AS DATE)) AS yr,
               EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) AS mo,
               ROUND(dist_km / {NODE_KM}) * {NODE_KM} AS node,
               MEDIAN(wse) AS wse
        FROM {src}
        WHERE Reach_Name = '{reach}'
        GROUP BY d, yr, mo, node
        ORDER BY d, node
    """).fetchdf()

    rows = []
    for d, g in nodes.groupby("d"):
        x = g["node"].to_numpy(dtype=float)
        y = g["wse"].to_numpy(dtype=float)
        if len(x) < MIN_NODES:
            continue
        span = float(x.max() - x.min())
        lo = float(x.min())
        ts = stats.theilslopes(y, x)             # (slope, intercept, lo_ci, hi_ci) in m/km
        slope_cm_km = ts[0] * 100.0
        wse_ref = ts[1] + ts[0] * REF_DIST_KM     # WSE at the fixed reference distance (m)
        rows.append({
            "reach": reach,
            "date": pd.Timestamp(d),
            "year": int(g["yr"].iloc[0]),
            "month": int(g["mo"].iloc[0]),
            "n_nodes": len(x),
            "lo_km": lo, "span_km": span,
            "slope_cm_km": abs(slope_cm_km),
            "wse_ref_m": wse_ref,
            "gated": (span >= MIN_SPAN_KM) and (lo <= MAX_START_KM),
            "open_water": int(g["mo"].iloc[0]) in OPEN_WATER_MONTHS,
            # True for top-up passes after the archive freeze: used by Q3 only,
            # excluded from Q1/Q2 so every frozen-archive number stays put.
            "post_freeze": pd.Timestamp(d) > pd.Timestamp(FREEZE_DATE),
        })
    return pd.DataFrame(rows)


def _fmt(vals):
    """median [IQR], n -- for a 1-D array of a metric."""
    v = np.asarray(vals, dtype=float)
    v = v[~np.isnan(v)]
    if len(v) == 0:
        return "   n=0"
    q1, q3 = np.percentile(v, [25, 75])
    return f"{np.median(v):7.2f}  [{q1:6.2f}, {q3:6.2f}]  n={len(v)}"


def _med(vals):
    """JSON-safe median (None if empty)."""
    v = np.asarray(vals, dtype=float)
    v = v[~np.isnan(v)]
    return round(float(np.median(v)), 3) if len(v) else None


def _round(p):
    """JSON-safe p-value round (None if nan)."""
    return round(float(p), 4) if np.isfinite(p) else None


def _mwu(a, b):
    """Mann-Whitney U (two-sided) with small-n guard. Returns (p, note).

    The note reports the RAW p only — per-test verdicts at raw alpha=0.05 are
    not meaningful across a family of ~14 tests. Significance is decided once,
    family-wise, by holm_adjust() before export (see the FAMILY-WISE block in
    the output)."""
    a = np.asarray(a, float); b = np.asarray(b, float)
    a = a[~np.isnan(a)]; b = b[~np.isnan(b)]
    if len(a) < 3 or len(b) < 3:
        return np.nan, f"(n too small: {len(a)} vs {len(b)})"
    p = stats.mannwhitneyu(a, b, alternative="two-sided").pvalue
    return p, f"raw p={p:.3f} (n={len(a)} vs {len(b)}; family-wise verdict below)"


def holm_adjust(row_lists):
    """Holm step-down adjustment over the WHOLE family of Mann-Whitney tests.

    Walks every result row, collects each valid raw p (p_wse / p_slope), and
    writes back the Holm-adjusted value as p_wse_holm / p_slope_holm. Holm
    controls the family-wise error rate with no independence assumption, so a
    single verdict rule (adjusted p < 0.05) is defensible across all Q1/Q2/Q3
    contrasts. Returns the (test_label, raw_p, adj_p) list for reporting.
    """
    tests = []
    for rows in row_lists:
        for row in rows:
            for key in ("p_wse", "p_slope"):
                if row.get(key) is not None:
                    label = f"{row['question']}/{row['reach']}" + \
                            (f"/{row['year']}" if "year" in row else "") + f"/{key}"
                    tests.append((row, key, label))
    if not tests:
        return []
    m = len(tests)
    order = sorted(range(m), key=lambda i: tests[i][0][tests[i][1]])
    adj, running_max = [1.0] * m, 0.0
    for rank, i in enumerate(order):
        p = tests[i][0][tests[i][1]]
        running_max = max(running_max, min(1.0, (m - rank) * p))  # step-down, monotone
        adj[i] = running_max
    report = []
    for (row, key, label), a in zip(tests, adj):
        row[key + "_holm"] = round(float(a), 4)
        report.append((label, row[key], row[key + "_holm"]))
    return report


def q1_seasonal(df):
    """Seasonal variability, High flow (May) vs Low flow (Jul-Aug).

    Same split logic as Q2, for the same reasons:
      * slope -- ONE pooled all-years contrast (May vs Jul-Aug over the whole record).
        Slope is season-invariant and coverage-sensitive, so a per-YEAR slope contrast on
        3-5 passes is dominated by a marginal-coverage pass or two (e.g. a spurious +8.3 cm/km
        Uyak-2025 "swing" from two passes starting 3 km downstream). Pooling years is justified
        because Q2 showed slope is stable across years; it gives robust n for the season contrast.
      * WSE@ref -- resolved per YEAR (WSE is the seasonal/flow signal, and is coverage-robust).
    """
    print("=" * 90)
    print("Q1. SEASONAL NATURAL VARIABILITY  --  High flow (May) vs Low flow (Jul-Aug)")
    print("    slope: pooled all-years (season-invariant) | WSE: resolved per year")
    print("=" * 90)
    rows = []
    for reach in REACHES:
        r = df[df["reach"] == reach]
        print(f"\n{reach}")

        # (a) SLOPE -- robust pooled all-years seasonal contrast
        s_hi = r[r["month"].isin(HIGH_FLOW_MONTHS)]["slope_cm_km"]
        s_lo = r[r["month"].isin(LOW_FLOW_MONTHS)]["slope_cm_km"]
        print(f"   slope seasonal contrast (all years pooled):")
        print(f"     High(May): {_fmt(s_hi)}")
        print(f"     Low(J-A) : {_fmt(s_lo)}")
        dslp = np.median(s_hi) - np.median(s_lo) if len(s_hi) and len(s_lo) else np.nan
        ps, ss = _mwu(s_hi, s_lo)
        print(f"     -> seasonal slope swing {dslp:+.1f} cm/km [{ss}]")
        rows.append({"question": "Q1_slope_pooled", "reach": reach,
                     "n_high": len(s_hi), "n_low": len(s_lo),
                     "slope_high": _med(s_hi), "slope_low": _med(s_lo),
                     "dslope_cm_km": round(dslp, 2) if np.isfinite(dslp) else None,
                     "p_slope": _round(ps)})

        # (b) WSE -- per-year seasonal swing
        print(f"   WSE@{REF_DIST_KM:.0f}km seasonal swing, by year:")
        for yr in sorted(r["year"].unique()):
            hi = r[(r["year"] == yr) & (r["month"].isin(HIGH_FLOW_MONTHS))]["wse_ref_m"]
            lo = r[(r["year"] == yr) & (r["month"].isin(LOW_FLOW_MONTHS))]["wse_ref_m"]
            if len(hi) == 0 or len(lo) == 0:
                continue
            dwse = np.median(hi) - np.median(lo)
            pw, ns = _mwu(hi, lo)
            print(f"     {yr}: May {np.median(hi):.2f} - JulAug {np.median(lo):.2f} = {dwse:+.2f} m  [{ns}]")
            rows.append({"question": "Q1_wse_seasonal", "reach": reach, "year": int(yr),
                         "n_high": len(hi), "n_low": len(lo),
                         "wse_high": _med(hi), "wse_low": _med(lo),
                         "dwse_m": round(dwse, 3), "p_wse": _round(pw)})
    return rows


def _period(df, reach, year, months):
    r = df[(df["reach"] == reach) & (df["year"] == year) & (df["month"].isin(months))]
    return r


def q2_interannual(df, low_months, low_label):
    """Normal 2024 vs 2025 change = the natural-variability baseline for Q3.

    Two metrics compared on DIFFERENT samples, by design:
      * slope -- FULL open-water year (n~18/yr). Q1 showed slope is season-invariant,
        so we don't season-match; using the whole year avoids the small-sample coverage
        artifact that a Jul-Aug-only slice suffers (a marginal-coverage pass or two can
        swing a 3-5 pass median). This is the robust, defensible interannual slope test.
      * WSE@ref -- season-matched (low flow), because water level IS strongly seasonal.
    """
    print("\n" + "=" * 90)
    print("Q2. NORMAL INTERANNUAL STABILITY  --  2024 vs 2025")
    print(f"    slope: FULL open-water year (season-invariant per Q1) | WSE: {low_label}")
    print("    (this is the NATURAL-VARIABILITY BASELINE / control for Q3)")
    print("=" * 90)
    baseline = {}
    rows = []
    for reach in REACHES:
        # slope on full open-water year; WSE on season-matched low flow
        s24 = df[(df["reach"] == reach) & (df["year"] == 2024)]["slope_cm_km"]
        s25 = df[(df["reach"] == reach) & (df["year"] == 2025)]["slope_cm_km"]
        w24 = _period(df, reach, 2024, low_months)["wse_ref_m"]
        w25 = _period(df, reach, 2025, low_months)["wse_ref_m"]
        print(f"\n{reach}")
        print(f"     slope  (cm/km, full yr)  2024: {_fmt(s24)}")
        print(f"                              2025: {_fmt(s25)}")
        print(f"     WSE@{REF_DIST_KM:.0f}km (m, {low_label[:7]})  2024: {_fmt(w24)}")
        print(f"                              2025: {_fmt(w25)}")
        dwse = np.median(w25) - np.median(w24) if len(w24) and len(w25) else np.nan
        dslp = np.median(s25) - np.median(s24) if len(s24) and len(s25) else np.nan
        pw, ns = _mwu(w24, w25)
        ps, ss = _mwu(s24, s25)
        print(f"     -> normal year-over-year change  WSE {dwse:+.2f} m   [{ns}]")
        print(f"                                      slope {dslp:+.1f} cm/km [{ss}]")
        baseline[reach] = {"dwse": dwse, "dslope": dslp,
                           # raw season-matched WSE samples, kept so Q3 can bootstrap
                           # the baseline median alongside the storm-window median
                           "w24": w24.to_numpy(), "w25": w25.to_numpy()}
        rows.append({"question": "Q2_interannual", "reach": reach,
                     "slope_basis": "full_open_water_year", "wse_basis": low_label,
                     "n_slope_2024": len(s24), "n_slope_2025": len(s25),
                     "n_wse_2024": len(w24), "n_wse_2025": len(w25),
                     "slope_2024": _med(s24), "slope_2025": _med(s25),
                     "wse_2024": _med(w24), "wse_2025": _med(w25),
                     "dwse_m": round(dwse, 3) if np.isfinite(dwse) else None,
                     "dslope_cm_km": round(dslp, 2) if np.isfinite(dslp) else None,
                     "p_wse": _round(pw), "p_slope": _round(ps)})
    return baseline, rows


def _boot_excess_ci(pre, post, base_a, base_b, n_boot=10000, seed=42):
    """Bootstrap 95% CI on |storm dWSE| − |baseline dWSE| (the 'excess' over natural
    variability), resampling all four small samples. Returns (dwse_ci, excess_ci) as
    (lo, hi) tuples, or None if any sample is too small to resample meaningfully.

    With n=3–4 passes per window the resampling grid is coarse — this is not a
    precise interval, but it makes the verdict's sensitivity to single passes
    explicit instead of comparing two bare point medians. Fixed seed: the exported
    JSON must be reproducible run-to-run."""
    arrs = [np.asarray(v, float) for v in (pre, post, base_a, base_b)]
    arrs = [a[~np.isnan(a)] for a in arrs]
    if any(len(a) < 2 for a in arrs):
        return None
    pre, post, base_a, base_b = arrs
    rng = np.random.default_rng(seed)
    d = (np.median(rng.choice(post, (n_boot, len(post))), axis=1)
         - np.median(rng.choice(pre, (n_boot, len(pre))), axis=1))
    bb = (np.median(rng.choice(base_b, (n_boot, len(base_b))), axis=1)
          - np.median(rng.choice(base_a, (n_boot, len(base_a))), axis=1))
    excess = np.abs(d) - np.abs(bb)
    dwse_ci = tuple(np.percentile(d, [2.5, 97.5]))
    excess_ci = tuple(np.percentile(excess, [2.5, 97.5]))
    return dwse_ci, excess_ci


def _monthday_matched(a, b):
    """Clip two same-season pass sets to their common month-day overlap.

    Sensitivity check for asymmetric window coverage (e.g. the pre year sampled
    through Aug 30 but the post year only through Aug 21): keeps only passes
    whose month-day falls in [latest first pass, earliest last pass] across the
    two years, so baseflow recession inside the window cannot bias the medians.
    Descriptive only — its medians are reported, but it contributes no test to
    the Holm family."""
    md = lambda s: s["date"].dt.strftime("%m-%d")
    if len(a) == 0 or len(b) == 0:
        return a, b, None
    lo = max(md(a).min(), md(b).min())
    hi = min(md(a).max(), md(b).max())
    return a[md(a).between(lo, hi)], b[md(b).between(lo, hi)], (lo, hi)


def q3_typhoon(df, baseline):
    print("\n" + "=" * 90)
    print("Q3. EXTREME-EVENT IMPACT  --  Typhoon Halong (landfall 2025-10-12)")
    print(f"    DEFINITIVE: Jul-Aug {Q3_PRE_YEAR} (pre) vs Jul-Aug {Q3_POST_YEAR} (post)")
    print("    -- the matched low-flow seasons either side of landfall; same season")
    print("       as the Q2 natural-variability baseline it is judged against.")
    print("=" * 90)
    rows = []
    sens_rows = []
    for reach in REACHES:
        a = _period(df, reach, Q3_PRE_YEAR, LOW_FLOW_MONTHS)    # Jul-Aug pre-storm
        b = _period(df, reach, Q3_POST_YEAR, LOW_FLOW_MONTHS)   # Jul-Aug post-storm
        print(f"\n{reach}")
        if len(a) and len(b):
            print(f"     window coverage  pre : {a['date'].min().date()} .. {a['date'].max().date()}  (n={len(a)})")
            print(f"                      post: {b['date'].min().date()} .. {b['date'].max().date()}  (n={len(b)})")
        print(f"     slope  (cm/km)  JulAug-{Q3_PRE_YEAR}: {_fmt(a['slope_cm_km'])}")
        print(f"                     JulAug-{Q3_POST_YEAR}: {_fmt(b['slope_cm_km'])}")
        print(f"     WSE@{REF_DIST_KM:.0f}km (m)  JulAug-{Q3_PRE_YEAR}: {_fmt(a['wse_ref_m'])}")
        print(f"                     JulAug-{Q3_POST_YEAR}: {_fmt(b['wse_ref_m'])}")
        dwse = np.median(b["wse_ref_m"]) - np.median(a["wse_ref_m"]) if len(a) and len(b) else np.nan
        dslp = np.median(b["slope_cm_km"]) - np.median(a["slope_cm_km"]) if len(a) and len(b) else np.nan
        pw, ns = _mwu(a["wse_ref_m"], b["wse_ref_m"])
        ps, ss = _mwu(a["slope_cm_km"], b["slope_cm_km"])
        print(f"     -> storm-window change  WSE {dwse:+.2f} m   [{ns}]")
        print(f"                             slope {dslp:+.1f} cm/km [{ss}]")
        base = baseline.get(reach, {})
        bw, bs = base.get("dwse", np.nan), base.get("dslope", np.nan)
        print(f"     -> vs natural baseline (Q2)  WSE change {dwse:+.2f} m  vs  normal {bw:+.2f} m")
        print(f"                                  slope change {dslp:+.1f} cm/km  vs  normal {bs:+.1f} cm/km")
        # Verdict on |storm change| vs |natural baseline|, with a bootstrap CI instead
        # of comparing two bare point medians (n=3-4 passes each; a single pass moving
        # ~0.1 m flips the point comparison). Three-way, decided by the excess CI:
        #   exceeds           — CI of |storm| − |baseline| entirely > 0
        #   within            — CI entirely < 0
        #   indistinguishable — CI spans 0 (the honest small-n outcome)
        verdict, dwse_ci, excess_ci = None, None, None
        if np.isfinite(dwse) and np.isfinite(bw):
            boot = _boot_excess_ci(a["wse_ref_m"], b["wse_ref_m"],
                                   base.get("w24", []), base.get("w25", []))
            if boot is not None:
                dwse_ci, excess_ci = boot
                if excess_ci[0] > 0:
                    verdict = "exceeds"
                elif excess_ci[1] < 0:
                    verdict = "within"
                else:
                    verdict = "indistinguishable"
                print(f"        => WSE storm-window change is {verdict.upper()} vs the normal "
                      f"interannual swing (excess 95% CI [{excess_ci[0]:+.2f}, {excess_ci[1]:+.2f}] m; "
                      f"dWSE 95% CI [{dwse_ci[0]:+.2f}, {dwse_ci[1]:+.2f}] m, bootstrap n=10000)")
            else:
                verdict = "exceeds" if abs(dwse) > abs(bw) else "within"
                print(f"        => WSE storm-window change {verdict.upper()} the normal interannual "
                      f"swing (point medians only — samples too small to bootstrap)")
        rows.append({"question": "Q3_typhoon", "reach": reach,
                     "window": "Jul-Aug (definitive)",
                     "pre_dates": [str(a["date"].min().date()), str(a["date"].max().date())] if len(a) else None,
                     "post_dates": [str(b["date"].min().date()), str(b["date"].max().date())] if len(b) else None,
                     "n_2025": len(a), "n_2026": len(b),
                     "slope_2025": _med(a["slope_cm_km"]), "slope_2026": _med(b["slope_cm_km"]),
                     "wse_2025": _med(a["wse_ref_m"]), "wse_2026": _med(b["wse_ref_m"]),
                     "dwse_m": round(dwse, 3) if np.isfinite(dwse) else None,
                     "dslope_cm_km": round(dslp, 2) if np.isfinite(dslp) else None,
                     "p_wse": _round(pw), "p_slope": _round(ps),
                     "baseline_dwse_m": round(bw, 3) if np.isfinite(bw) else None,
                     "baseline_dslope_cm_km": round(bs, 2) if np.isfinite(bs) else None,
                     "dwse_ci95_m": [round(float(x), 3) for x in dwse_ci] if dwse_ci else None,
                     "excess_vs_baseline_ci95_m": [round(float(x), 3) for x in excess_ci] if excess_ci else None,
                     "wse_vs_baseline": verdict})

        # Date-matched sensitivity: same comparison on the common month-day
        # overlap of the two windows (guards against asymmetric coverage).
        am, bm, span = _monthday_matched(a, b)
        if span and len(am) and len(bm):
            dwse_m = np.median(bm["wse_ref_m"]) - np.median(am["wse_ref_m"])
            dslp_m = np.median(bm["slope_cm_km"]) - np.median(am["slope_cm_km"])
            print(f"     -> date-matched sensitivity (month-days {span[0]}..{span[1]}): "
                  f"WSE {dwse_m:+.2f} m, slope {dslp_m:+.1f} cm/km "
                  f"(n={len(am)} vs {len(bm)}; descriptive only)")
            sens_rows.append({"question": "Q3_sensitivity_date_matched", "reach": reach,
                              "monthday_lo": span[0], "monthday_hi": span[1],
                              "n_pre": len(am), "n_post": len(bm),
                              "dwse_m": round(float(dwse_m), 3),
                              "dslope_cm_km": round(float(dslp_m), 2)})
    return rows, sens_rows


def elevation_change_by_distance(con, reach, src, pre_start, pre_end, post_start, post_end):
    """Binned-median WSE profile difference (post - pre), density-unbiased."""
    q = f"""
        WITH pre AS (
            SELECT ROUND(dist_km / 0.5) * 0.5 AS b, MEDIAN(wse) AS w
            FROM {src}
            WHERE Reach_Name='{reach}'
              AND CAST(Pass_Date AS DATE) BETWEEN CAST('{pre_start}' AS DATE) AND CAST('{pre_end}' AS DATE)
            GROUP BY b HAVING COUNT(*) >= 3
        ),
        post AS (
            SELECT ROUND(dist_km / 0.5) * 0.5 AS b, MEDIAN(wse) AS w
            FROM {src}
            WHERE Reach_Name='{reach}'
              AND CAST(Pass_Date AS DATE) BETWEEN CAST('{post_start}' AS DATE) AND CAST('{post_end}' AS DATE)
            GROUP BY b HAVING COUNT(*) >= 3
        )
        SELECT pre.b AS dist_km, post.w - pre.w AS dwse
        FROM pre JOIN post ON pre.b = post.b
        ORDER BY pre.b
    """
    return con.execute(q).fetchdf()


def q3_profile(con, src):
    """Return (summary_rows, per_bin_curve_df).

    summary_rows -> JSON scalars (median/upstream/downstream dWSE).
    per_bin_curve_df -> the full [reach, dist_km, dwse] zero-line delta curve
    that the dashboard's spatial-delta figure (Fig 2) draws directly.
    """
    print("\n" + "-" * 90)
    print(f"Q3 detail: WSE change by distance, Jul-Aug {Q3_PRE_YEAR} -> "
          f"Jul-Aug {Q3_POST_YEAR} (binned medians)")
    print("-" * 90)
    rows = []
    curves = []
    for reach in REACHES:
        d = elevation_change_by_distance(
            con, reach, src,
            f"{Q3_PRE_YEAR}-07-01", f"{Q3_PRE_YEAR}-08-31",
            f"{Q3_POST_YEAR}-07-01", f"{Q3_POST_YEAR}-08-31")
        if len(d) == 0:
            print(f"  {reach}: no overlapping bins")
            continue
        # dist_km is radial from the INLAND anchor point (WSE ~66 m there,
        # ~0 m at the 35 km mouths): small distance = upstream/upper river,
        # large distance = downstream/lower river toward the coast.
        up = d[d["dist_km"] <= 18]["dwse"]    # upstream half (near the anchor)
        dn = d[d["dist_km"] > 18]["dwse"]     # downstream half (toward the coast)
        print(f"  {reach}: bins={len(d)}  overall median dWSE={d['dwse'].median():+.2f} m  "
              f"(upstream<=18km {up.median():+.2f} m | downstream>18km {dn.median():+.2f} m)")
        rows.append({"question": "Q3_profile", "reach": reach, "n_bins": len(d),
                     "median_dwse_m": round(float(d["dwse"].median()), 3),
                     "downstream_dwse_m": round(float(dn.median()), 3) if len(dn) else None,
                     "upstream_dwse_m": round(float(up.median()), 3) if len(up) else None})
        c = d.copy()
        c.insert(0, "reach", reach)
        curves.append(c)
    curve_df = pd.concat(curves, ignore_index=True) if curves else pd.DataFrame(
        columns=["reach", "dist_km", "dwse"])
    return rows, curve_df


def main():
    con = duckdb.connect()
    pd.set_option("display.width", 160)

    src = _source_expr()
    topup = os.path.exists(TOPUP_PARQUET)
    parts = [per_pass_metrics(con, r, src) for r in REACHES]
    allp = pd.concat(parts, ignore_index=True)
    df = allp[(allp["gated"]) & (allp["open_water"])].copy()
    # Q1/Q2 (and the Q2 baseline Q3 is judged against) see ONLY the frozen
    # archive; the post-freeze top-up passes reach the Q3 windows alone.
    df_frozen = df[~df["post_freeze"]].copy()

    print(f"Full record: {len(allp)} passes fit; {len(df)} full-coverage open-water passes used")
    print(f"  ({len(df_frozen)} frozen-archive passes for Q1/Q2; "
          f"{len(df) - len(df_frozen)} post-freeze top-up passes, Q3 only).")
    print(f"Date range: {allp['date'].min().date()} .. {allp['date'].max().date()}")
    if not topup:
        print(f"NOTE: top-up parquet absent ({TOPUP_PARQUET}) — the {Q3_POST_YEAR} "
              f"storm window is truncated at the archive freeze ({FREEZE_DATE}).")
    print(f"Reference distance for water level (WSE@ref): {REF_DIST_KM:.0f} km\n")

    q1 = q1_seasonal(df_frozen)
    baseline, q2 = q2_interannual(df_frozen, LOW_FLOW_MONTHS, "Jul-Aug low flow")
    q3, q3_sens = q3_typhoon(df, baseline)
    q3p, q3_curve = q3_profile(con, src)

    # One family-wise significance decision across ALL Mann-Whitney tests above.
    holm_report = holm_adjust([q1, q2, q3])
    print("\n" + "=" * 90)
    print(f"FAMILY-WISE SIGNIFICANCE (Holm step-down over {len(holm_report)} "
          f"Mann-Whitney tests, alpha=0.05)")
    print("=" * 90)
    for label, raw, adj in sorted(holm_report, key=lambda t: t[1]):
        sig = "SIGNIFICANT" if adj < 0.05 else "not significant"
        print(f"  {label:<45s} raw p={raw:.4f}  Holm p={adj:.4f}  -> {sig}")
    print()

    # --- export results for the writeup + dashboard display ---
    os.makedirs(OUT_DIR, exist_ok=True)
    df.to_parquet(OUT_METRICS, index=False)
    q3_curve.to_parquet(OUT_Q3PROFILE, index=False)
    summary = {
        "method": {
            "node_km": NODE_KM, "min_nodes": MIN_NODES,
            "min_span_km": MIN_SPAN_KM, "max_start_km": MAX_START_KM,
            "ref_dist_km": REF_DIST_KM,
            "open_water_months": sorted(OPEN_WATER_MONTHS),
            "high_flow_months": sorted(HIGH_FLOW_MONTHS),
            "low_flow_months": sorted(LOW_FLOW_MONTHS),
            "typhoon_date": TYPHOON_DATE,
            "q3_window": (
                f"DEFINITIVE: Jul-Aug {Q3_PRE_YEAR} (last low-flow season before "
                f"landfall) vs Jul-Aug {Q3_POST_YEAR} (first after); same season "
                "as the Q2 baseline. Supersedes the June-vs-June interim run."),
            "q3_topup": (
                f"post-freeze {Q3_POST_YEAR} passes from {TOPUP_PARQUET} "
                "(isolated pull, q3_topup_pull.py; frozen master untouched)"
                if topup else
                f"NONE — {Q3_POST_YEAR} window truncated at the archive freeze "
                f"({FREEZE_DATE}); rerun after q3_topup_pull.py"),
            "slope_estimator": "Theil-Sen on 1km node medians (abs cm/km)",
            "level_metric": f"WSE at {REF_DIST_KM:.0f} km from Theil-Sen fit (m)",
            "multiple_comparison": (
                f"Holm step-down over all {len(holm_report)} Mann-Whitney tests "
                "(one family across Q1/Q2/Q3); significance = adjusted p < 0.05; "
                "adjusted values exported as p_wse_holm / p_slope_holm"),
            "q3_verdict": (
                "bootstrap 95% CI (n=10000, seed=42) on |storm dWSE| - |baseline dWSE|; "
                "verdict exceeds/within only if the CI excludes 0, else indistinguishable"),
        },
        "record": {
            "n_passes_fit": int(len(allp)),
            "n_full_coverage_open_water": int(len(df)),
            "n_frozen_archive_q1_q2": int(len(df_frozen)),
            "n_post_freeze_topup_q3_only": int(len(df) - len(df_frozen)),
            "freeze_date": FREEZE_DATE,
            "date_min": str(allp["date"].min().date()),
            "date_max": str(allp["date"].max().date()),
        },
        "Q1_seasonal": q1,
        "Q2_interannual": q2,
        "Q3_typhoon": q3,
        "Q3_sensitivity": q3_sens,
        "Q3_profile": q3p,
    }
    with open(OUT_SUMMARY, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Wrote {OUT_METRICS} ({len(df)} rows), {OUT_Q3PROFILE} "
          f"({len(q3_curve)} bins), and {OUT_SUMMARY}")


if __name__ == "__main__":
    main()
