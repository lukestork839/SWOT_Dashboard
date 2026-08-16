"""Numerical regression gate for the swot_core extraction (dashboard split PR A/B/C).

Snapshots the numerical output of every shared scientific computation through BOTH
consumer surfaces — `dashboard_swot` (imported headless; its `__main__` guard keeps
the app from running) and `thesis_figures.core` — so a refactor that moves the math
into `swot_core` can be proven output-identical:

    python tools/regression_gate.py snapshot   # writes tools/regression_baseline.json
    python tools/regression_gate.py compare    # recomputes, diffs against baseline

`compare` exits non-zero on any mismatch outside the --allow list. Some keys are
EXPECTED to change in PR B2 (hygiene idx 33 — binning ties standardized on
half-away-from-zero, DuckDB's convention; numpy's np.round is half-to-even):

  * dashboard.slope_profile.* / thesis.<reach>.slope_profile.* — the 0.1 km
    binning inside calculate_slope_profile now sends exact-boundary points
    (dist_km is float32; e.g. 24.75) to the same bin as the SQL ROUND paths.
  * thesis.elevation_difference.* — same convention change in the 0.1 km
    binning of swot_core.stats.elevation_difference (which now agrees with the
    Elevation Difference tab's SQL binning of the same data).

14 archive points sit exactly on a 0.1/0.5 km bin boundary; 7 of them change
bins. Everything else must match exactly (same machine, same data,
deterministic code). Both surfaces read the SAME full local archive
(batch_outputs partitions / master_all_data.parquet), so their shared checks
are directly comparable.

Baseline lifecycle: the committed tools/regression_baseline.json is re-snapshotted
after each split PR's gate passes, so the next PR diffs against the accepted
current state. The committed baseline is POST-PR-B2 (verified self-consistent:
compare returns 0 diffs), which also makes the PR-B2 allowances above inert.
(The PR-A allowances — detrend-coeff domain, gap-honest slope unification, and
the finescale first/last ordering artifacts — went inert at the PR-A
re-snapshot and were retired from DEFAULT_ALLOW here.)
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)  # dashboard_swot uses relative DATA_DIR paths

BASELINE_PATH = os.path.join(ROOT, "tools", "regression_baseline.json")

# Keys allowed to differ in PR B2 (see module docstring). Prefix match.
DEFAULT_ALLOW = [
    "dashboard.slope_profile",
    "thesis.Kanektok_River.slope_profile",
    "thesis.Uyak_Creek.slope_profile",
    "thesis.elevation_difference",
]

# Floats compare with relative tolerance: DuckDB's parallel scan returns
# tie-ordered rows in nondeterministic order, so downstream float summations
# (Polynomial.fit, matrix sums) wobble in the last ulps run-to-run. 1e-9
# relative is ~6 orders tighter than any scientific claim here and ~6 orders
# looser than the observed ulp noise (~1e-15 relative).
FLOAT_RTOL = 1e-9

REACHES = ["Kanektok_River", "Uyak_Creek"]
OW_MONTHS = "4,5,6,7,8,9,10,11"


def sig(a) -> dict:
    """JSON-safe signature of a numeric array: exact nan-aware reductions."""
    a = np.asarray(a, dtype=float).ravel()
    fin = np.isfinite(a)
    out = {"n": int(a.size), "n_finite": int(fin.sum())}
    if fin.any():
        v = a[fin]
        out.update(sum=float(v.sum()), mean=float(v.mean()), std=float(v.std()),
                   min=float(v.min()), max=float(v.max()),
                   first=float(v[0]), last=float(v[-1]))
    return out


def jsafe(x):
    """Recursively convert numpy scalars/arrays for JSON."""
    if isinstance(x, dict):
        return {k: jsafe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, np.ndarray)):
        return [jsafe(v) for v in np.asarray(x).tolist()] if isinstance(x, np.ndarray) else [jsafe(v) for v in x]
    if isinstance(x, (np.floating,)):
        return float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    return x


# ---------------------------------------------------------------------------
# Dashboard surface
# ---------------------------------------------------------------------------
def dashboard_checks() -> dict:
    import dashboard_swot as dash

    con = dash.get_database_connection("gate-local")
    assert con is not None, "dashboard connection failed (need local batch_outputs partitions)"
    out = {}

    # Metadata
    dates, reaches = dash.load_metadata(con)
    out["metadata"] = {"n_dates": len(dates), "reaches": sorted(reaches),
                       "date_min": str(min(dates)), "date_max": str(max(dates))}

    # Fixed pass selection: every distinct 2026 open-water date (deterministic
    # given the data file; the dates themselves are recorded so any data change
    # is visible rather than silently shifting every downstream number).
    sel = [str(d) for d in sorted(dates) if str(d) >= "2026-01-01"]
    out["selection_dates"] = sel
    rivers_sql = "'" + "','".join(r.replace("'", "''") for r in REACHES) + "'"
    dates_sql = ",".join(f"CAST('{d}' AS DATE)" for d in sel)
    where_clause = f"""
            WHERE Reach_Name IN ({rivers_sql})
            AND CAST(Pass_Date AS DATE) IN ({dates_sql})
        """

    # Detrend frame (the cached fetch+fit path behind the Detrended Profile tab)
    bdf, method_name, total = dash.load_detrend_frame(con, where_clause, "Polynomial (2nd order)")
    out["detrend_frame"] = {"total_count": int(total), "n": int(len(bdf)),
                            "method_name": method_name,
                            "residual": sig(bdf["residual"]), "baseline": sig(bdf["baseline"])}
    out["flagged_outliers"] = int(dash.flag_residual_outliers(bdf["residual"].values).sum())

    # calculate_detrending across methods on the same frame
    dt = {}
    for method in ("Linear", "Polynomial (2nd order)", "Polynomial (3rd order)"):
        base, coeffs, name = dash.calculate_detrending(
            bdf["dist_km"].tolist(), bdf["wse"].tolist(), method)
        dt[method] = {"name": name, "baseline": sig(base),
                      "coeffs": [float(c) for c in coeffs]}
    out["detrend_methods"] = dt

    # Slope Profile tab math, per river on the selection frame
    sp = {}
    for r in REACHES:
        d = bdf[bdf["Reach_Name"] == r]
        x_eval, slope, y_fit = dash.calculate_slope_profile(
            d["dist_km"].tolist(), d["wse"].tolist())
        sp[r] = {"x_eval": sig(x_eval), "slope": sig(slope), "y_fitted": sig(y_fit)}
    out["slope_profile"] = sp

    # Fine-scale pipeline: full open-water record, fixed controls (tab defaults)
    ow_clause = f"""
            WHERE Reach_Name IN ({rivers_sql})
            AND EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) IN ({OW_MONTHS})
        """
    fine = dash.compute_finescale_pass_matrix(
        con, "gate-fixed", ow_clause, dash.FINE_RES_KM, dash.FINE_XMAX_KM)
    fs = {}
    for r, d in fine.items():
        # DuckDB GROUP BY output order is unguaranteed -> order the matrix
        # columns by pass date so the signature is deterministic run-to-run.
        # (Column order is irrelevant to every aggregate the app computes.)
        order = np.argsort(d["passes"])
        mat = d["mat"][:, order]
        med, lo, hi, n = dash._fine_aggregate(mat, min_passes=10)
        cov = dash._fine_window_coverage(mat, d["grid"], dash.FINE_WINDOW_KM)
        wsl = dash._fine_window_slope(mat, d["grid"], dash.FINE_WINDOW_KM)
        fs[r] = {"shape": list(mat.shape), "n_passes": int(d["n_passes"]),
                 "mat": sig(mat), "med": sig(med), "lo": sig(lo), "hi": sig(hi),
                 "n": sig(n), "window_coverage": sig(cov), "window_slope": sig(wsl)}
    out["finescale"] = fs

    # Reference gradient + decomposition (headline numbers)
    ref = dash.load_reference_gradient(con)
    g = ref[(ref["open_water"]) & (ref["gated"])]
    out["refgrad"] = {
        r: {"median_theilsen": float(g[g["Reach_Name"] == r]["theilsen_cm_km"].abs().median()),
            "n": int((g["Reach_Name"] == r).sum())} for r in REACHES}
    dec = dash.load_refgrad_decomposition(con)
    out["decomposition"] = {
        row["Reach_Name"]: {"pooled_raw": float(row["pooled_raw"]),
                            "pooled_nodes": float(row["pooled_nodes"])}
        for _, row in dec.iterrows()}

    # DEM profile aggregate
    dem = dash.load_dem_profile(con)
    out["dem_profile"] = ({"n": int(len(dem)), "wse_median": sig(dem["wse_median"])}
                          if dem is not None else None)
    return out


# ---------------------------------------------------------------------------
# Thesis surface
# ---------------------------------------------------------------------------
def thesis_checks() -> dict:
    from thesis_figures import core

    con = core.connect()
    out = {}

    pts = core.load_swot(con, reaches=REACHES, open_water_only=True)
    per = {}
    for r in REACHES:
        d = pts[pts["Reach_Name"] == r]
        rec = {"n": int(len(d)), "wse": sig(d["wse"])}

        base, coeffs, name = core.calculate_detrending(
            d["dist_km"].tolist(), d["wse"].tolist(), "Polynomial (2nd order)")
        resid = d["wse"].values - base
        rec["detrend"] = {"name": name, "baseline": sig(base),
                          "coeffs": [float(c) for c in coeffs]}
        rec["flagged_outliers"] = int(core.flag_residual_outliers(resid).sum())

        x_eval, slope, y_fit = core.calculate_slope_profile(
            d["dist_km"].tolist(), d["wse"].tolist())
        rec["slope_profile"] = {"x_eval": sig(x_eval), "slope": sig(slope),
                                "y_fitted": sig(y_fit)}
        per[r] = rec
    out.update(per)

    fine = core.finescale_slope_profile(con, reaches=tuple(REACHES))
    out["finescale"] = {r: {"n_passes": int(d["n_passes"]), "med": sig(d["med"]),
                            "lo": sig(d["lo"]), "hi": sig(d["hi"]), "n": sig(d["n"])}
                        for r, d in fine.items()}

    ed = core.elevation_difference(con)
    out["elevation_difference"] = {"n": int(len(ed)), "diff": sig(ed["diff"]),
                                   "lo": sig(ed["lo"]), "hi": sig(ed["hi"]),
                                   "n_passes": sig(ed["n_passes"])}

    ref = core.load_reference_gradient()
    g = ref[(ref["open_water"]) & (ref["gated"])]
    out["refgrad"] = {
        r: {"median_theilsen": float(g[g["Reach_Name"] == r]["theilsen_cm_km"].abs().median()),
            "n": int((g["Reach_Name"] == r).sum())} for r in REACHES}

    tm = core.load_temporal_metrics()
    out["temporal_metrics"] = {"n": int(len(tm)), "slope_cm_km": sig(tm["slope_cm_km"])}
    return out


def compute_all() -> dict:
    return jsafe({"dashboard": dashboard_checks(), "thesis": thesis_checks()})


# ---------------------------------------------------------------------------
# Diffing
# ---------------------------------------------------------------------------
def flatten(d, prefix=""):
    items = {}
    if isinstance(d, dict):
        for k, v in d.items():
            items.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            items.update(flatten(v, f"{prefix}[{i}]"))
    else:
        items[prefix] = d
    return items


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "compare"
    allow = DEFAULT_ALLOW if "--strict" not in sys.argv else []

    print("Computing gate values (both surfaces, full archive) ...", flush=True)
    current = json.loads(json.dumps(compute_all()))

    if mode == "snapshot":
        with open(BASELINE_PATH, "w") as f:
            json.dump(current, f, indent=1, sort_keys=True)
        print(f"Baseline written: {BASELINE_PATH}")
        return 0

    with open(BASELINE_PATH) as f:
        baseline = json.load(f)
    fb, fc = flatten(baseline), flatten(current)
    keys = sorted(set(fb) | set(fc))
    bad, allowed_diff = [], []
    for k in keys:
        b, c = fb.get(k, "<missing>"), fc.get(k, "<missing>")
        if b == c:
            continue
        if isinstance(b, float) and isinstance(c, float):
            if np.isnan(b) and np.isnan(c):
                continue
            if np.isclose(b, c, rtol=FLOAT_RTOL, atol=0.0, equal_nan=False):
                continue
        (allowed_diff if any(k.startswith(a) for a in allow) else bad).append((k, b, c))
    if allowed_diff:
        print(f"\n{len(allowed_diff)} EXPECTED differences (unification, see docstring):")
        for k, b, c in allowed_diff:
            print(f"  ~ {k}\n      baseline: {b}\n      current:  {c}")
    if bad:
        print(f"\nGATE FAILED — {len(bad)} unexpected differences:")
        for k, b, c in bad:
            print(f"  ✗ {k}\n      baseline: {b}\n      current:  {c}")
        return 1
    print(f"\nGATE PASSED — {len(keys)} values checked, "
          f"{len(allowed_diff)} expected diffs, 0 unexpected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
