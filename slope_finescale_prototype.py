"""
Fine-scale slope re-analysis PROTOTYPE (standalone, touches nothing in the pipeline).

Purpose (from the professor's slope re-analysis notes):
  * The published Figure 8 slope profile uses a 2 km Gaussian *sigma* -> ~4.7 km
    effective resolution (FWHM = 2.355*sigma). That blurs away backwater-scale
    structure (~0.5 km here), which is exactly where an avulsion slope-advantage
    would show up. This script explores whether we can resolve slope at ~0.5 km.
  * Coastal/tidal noise sits at the far (sea) end and does not affect the
    bifurcation (2.493 km from the anchor), so we detect + trim it.
  * We want (a) an honest fine-scale slope PROFILE, (b) the smallest resolvable
    scale, (c) a bifurcation-zoom, and (d) how the near-bifurcation slope
    advantage changes over time.

Key method choice: compute the fine-scale slope WITHIN each pass first (stage is
constant within a pass), then aggregate across passes. Pooling all passes before
differencing would mix stage differences into slope at fine scale.

Estimators compared:
  * Gaussian pre-smooth + np.gradient  (the current Figure-8 method, at fine sigma)
  * Savitzky-Golay 1st derivative       (proper local-polynomial derivative filter)
  * Sliding Theil-Sen                    (robust, matches reference-gradient ethos)

Outputs: printed tables + PNGs in slope_finescale_prototype/. Nothing is written
back into the dashboard, thesis_figures, or the data artifacts.

Run: python3 slope_finescale_prototype.py
"""
from __future__ import annotations

import os
import numpy as np
import pandas as pd
import duckdb
from scipy import stats
from scipy.signal import savgol_filter
from scipy.ndimage import gaussian_filter1d

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# --- config -----------------------------------------------------------------
DATA_GLOB = "batch_outputs/master_all_data_part_*.parquet"
OUTDIR = "slope_finescale_prototype"
REACHES = ["Kanektok_River", "Uyak_Creek"]
COLOR = {"Kanektok_River": "firebrick", "Uyak_Creek": "dodgerblue"}
OPEN_WATER = (4, 5, 6, 7, 8, 9, 10, 11)
EXCLUDED_PASSES = {"2025-04-17"}          # matches thesis_figures/config.py

BASE_BIN_KM = 0.1                         # fine base grid for per-pass profiles
MIN_PIX_BIN = 30                          # trust a bin's median only with >= this many pixels
BIFURCATION_KM = 2.493                    # from dashboard_swot.py / config.py
RESOLUTIONS = [0.25, 0.5, 1.0, 2.0]       # effective slope resolutions to sweep (km)
NEAR_BIF = (1.0, 5.0)                     # near-bifurcation window for temporal tracking (km)
FILL_GAP_KM = 0.3                         # per pass, interpolate internal gaps up to this wide

os.makedirs(OUTDIR, exist_ok=True)


# --- data -------------------------------------------------------------------
def load_pass_bins() -> pd.DataFrame:
    """Per (pass, reach, 0.1 km bin): median WSE + pixel count, open-water, QC-clean."""
    con = duckdb.connect()
    excl = " AND ".join(f"CAST(Pass_Date AS DATE) <> DATE '{d}'" for d in EXCLUDED_PASSES)
    df = con.execute(f"""
        SELECT CAST(Pass_Date AS DATE) AS pass,
               Reach_Name AS reach,
               ROUND(dist_km / {BASE_BIN_KM}) * {BASE_BIN_KM} AS bin,
               MEDIAN(wse) AS wse,
               COUNT(*) AS npix
        FROM read_parquet('{DATA_GLOB}')
        WHERE EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) IN {tuple(OPEN_WATER)}
          AND {excl}
        GROUP BY pass, reach, bin
        ORDER BY reach, pass, bin
    """).fetchdf()
    df = df[df["npix"] >= MIN_PIX_BIN].copy()
    df["ibin"] = (df["bin"] / BASE_BIN_KM).round().astype(int)   # integer 0.1 km index
    df["bin"] = df["ibin"] * BASE_BIN_KM                          # clean float grid
    return df


# --- coastal cutoff detection ----------------------------------------------
def detect_coastal_cutoff(df: pd.DataFrame) -> dict:
    """Find where cross-pass WSE scatter blows up near the sea (tidal contamination).

    For each 0.5 km bin we take the per-pass median WSE, then the IQR of those
    per-pass medians ACROSS passes. In the stable interior this cross-pass spread
    is small (just stage variability); near the coast, tides inflate it. We scan
    inland from the sea and flag the contaminated tail as bins whose cross-pass
    spread exceeds 2x the interior baseline.
    """
    out = {}
    for reach in REACHES:
        d = df[df["reach"] == reach].copy()
        d["b5"] = (d["bin"] / 0.5).round() * 0.5
        per = d.groupby(["b5", "pass"])["wse"].median().reset_index()
        g = per.groupby("b5")["wse"]
        spread = (g.quantile(0.75) - g.quantile(0.25)).rename("cross_pass_iqr")
        prof = spread.reset_index().sort_values("b5")
        interior = prof[(prof["b5"] >= 8) & (prof["b5"] <= prof["b5"].max() - 8)]
        baseline = interior["cross_pass_iqr"].median()
        thresh = 2.0 * baseline
        # scan inland from the sea end; contaminated tail = contiguous run above thresh
        cutoff = prof["b5"].max()
        for b5 in sorted(prof["b5"], reverse=True):
            val = float(prof.loc[prof["b5"] == b5, "cross_pass_iqr"].iloc[0])
            if val > thresh:
                cutoff = b5
            else:
                break
        out[reach] = {"baseline": baseline, "thresh": thresh,
                      "cutoff": cutoff, "profile": prof}
    return out


# --- per-pass fine-scale slope ---------------------------------------------
def _regular_grid(sub: pd.DataFrame):
    """One pass -> (integer 0.1 km bin index, wse) on a regular grid, small gaps filled."""
    sub = sub.sort_values("ibin")
    i0, i1 = int(sub["ibin"].min()), int(sub["ibin"].max())
    idx = np.arange(i0, i1 + 1)
    s = pd.Series(np.nan, index=idx, dtype=float)
    s.loc[sub["ibin"].values] = sub["wse"].values
    # interpolate only short internal gaps
    max_gap = int(round(FILL_GAP_KM / BASE_BIN_KM))
    s = s.interpolate(limit=max_gap, limit_area="inside")
    return idx.astype(int), s.to_numpy(dtype=float)


def slope_savgol(x, y, res_km):
    """Savitzky-Golay 1st-derivative slope (cm/km) at effective resolution res_km."""
    win = max(3, int(round(res_km / BASE_BIN_KM)))
    if win % 2 == 0:
        win += 1
    if win > len(y):
        return np.full_like(y, np.nan)
    dydx = savgol_filter(y, window_length=win, polyorder=2, deriv=1,
                         delta=BASE_BIN_KM, mode="interp")
    return dydx * 100.0  # m/km -> cm/km


def slope_gaussian(x, y, res_km):
    """Current Fig-8 method: Gaussian smooth then np.gradient, matched to res_km FWHM."""
    sigma_km = res_km / 2.355            # so FWHM == res_km
    sigma_bins = sigma_km / BASE_BIN_KM
    ys = gaussian_filter1d(y, sigma=sigma_bins, mode="nearest")
    return np.gradient(ys, x) * 100.0


def slope_theilsen_sliding(x, y, res_km):
    """Robust sliding Theil-Sen slope (cm/km); window width = res_km."""
    half = res_km / 2.0
    out = np.full_like(y, np.nan)
    for i, xc in enumerate(x):
        m = np.abs(x - xc) <= half
        if m.sum() >= 3 and np.isfinite(y[m]).sum() >= 3:
            xs, ys = x[m], y[m]
            good = np.isfinite(ys)
            out[i] = stats.theilslopes(ys[good], xs[good])[0] * 100.0
    return out


def per_pass_slope_matrix(df, reach, res_km, method, xmax=None):
    """Build a (grid x pass) slope matrix by fitting each pass independently.

    Returns (grid, matrix). Aggregating across the pass axis (median) gives an
    honest fine-scale profile: each pass is fit at constant stage.
    """
    d = df[df["reach"] == reach]
    if xmax is not None:
        d = d[d["bin"] <= xmax]
    imax = int(d["ibin"].max())
    grid = np.arange(1, imax + 1) * BASE_BIN_KM        # 0.1, 0.2, ... km
    passes = d["pass"].unique()
    mat = np.full((len(grid), len(passes)), np.nan)
    fn = {"savgol": slope_savgol, "gaussian": slope_gaussian,
          "theilsen": slope_theilsen_sliding}[method]
    for j, p in enumerate(passes):
        ix, y = _regular_grid(d[d["pass"] == p])
        if len(ix) < 5:
            continue
        sl = fn(ix * BASE_BIN_KM, y, res_km)
        pos = ix - 1                                    # grid position (ibin 1 -> index 0)
        ok = (pos >= 0) & (pos < len(grid))
        mat[pos[ok], j] = sl[ok]
    return grid, mat


def aggregate(grid, mat):
    """Median-across-pass slope profile + robust spread + per-bin pass count."""
    med = np.nanmedian(mat, axis=1)
    n = np.sum(np.isfinite(mat), axis=1)
    q25 = np.nanquantile(np.where(np.isfinite(mat), mat, np.nan), 0.25, axis=1)
    q75 = np.nanquantile(mat, 0.75, axis=1)
    sigma = (q75 - q25) / 1.349                       # robust std across passes
    se = np.where(n > 0, sigma / np.sqrt(np.maximum(n, 1)), np.nan)  # SE of median slope
    return med, q25, q75, se, n


# --- analyses ---------------------------------------------------------------
def resolution_sweep(df, cutoffs):
    """SNR vs resolution: can we resolve 0.5 km (or finer)?"""
    print("\n" + "=" * 78)
    print("RESOLUTION FEASIBILITY SWEEP (per-pass Savitzky-Golay, coast-trimmed)")
    print("  signal = spatial std of the mean slope profile (structure we want to see)")
    print("  noise  = median per-bin standard error of the slope (how well we know it)")
    print("  SNR>~3 => the fine-scale structure at that resolution is real, not noise")
    print("=" * 78)
    for reach in REACHES:
        xmax = cutoffs[reach]["cutoff"]
        print(f"\n{reach}  (trimmed to <= {xmax:.1f} km)")
        print(f"  {'res(km)':>8} {'signal':>8} {'noise':>8} {'SNR':>6} {'medN':>6}")
        for res in RESOLUTIONS:
            grid, mat = per_pass_slope_matrix(df, reach, res, "savgol", xmax=xmax)
            med, _, _, se, n = aggregate(grid, mat)
            core = n >= 10                              # bins covered by >=10 passes
            signal = np.nanstd(np.abs(med[core]))
            noise = np.nanmedian(se[core])
            snr = signal / noise if noise else np.nan
            print(f"  {res:>8.2f} {signal:>8.1f} {noise:>8.2f} {snr:>6.1f} {int(np.nanmedian(n[core])):>6}")


def method_comparison(df, cutoffs, res=0.5):
    """Overlay the three estimators at 0.5 km for both rivers (full trimmed reach)."""
    fig, axes = plt.subplots(2, 1, figsize=(11, 9), sharex=True)
    for ax, reach in zip(axes, REACHES):
        xmax = cutoffs[reach]["cutoff"]
        for method, ls, lab in [("gaussian", ":", "Gaussian+gradient (current Fig 8 method)"),
                                ("savgol", "-", "Savitzky-Golay derivative"),
                                ("theilsen", "--", "Sliding Theil-Sen")]:
            grid, mat = per_pass_slope_matrix(df, reach, res, method, xmax=xmax)
            med, _, _, _, n = aggregate(grid, mat)
            m = n >= 10
            ax.plot(grid[m], np.abs(med[m]), ls, color=COLOR[reach], lw=1.8, label=lab)
        ax.axvline(BIFURCATION_KM, color="gray", ls="-.", lw=1, label="Bifurcation")
        ax.set_title(f"{reach.replace('_',' ')} — fine-scale slope estimators @ {res} km")
        ax.set_ylabel("|slope| (cm/km)")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
    axes[-1].set_xlabel("Distance from anchor (km)")
    fig.tight_layout()
    p = os.path.join(OUTDIR, "method_comparison_0p5km.png")
    fig.savefig(p, dpi=140); plt.close(fig)
    print(f"\n  saved {p}")


def profile_and_zoom(df, cutoffs, res=0.5):
    """Publication-style fine-scale profile (Savgol, per-pass median + IQR band)
    for both rivers, plus a bifurcation zoom, at 0.5 km vs the old 4.7 km."""
    fig, (axf, axz) = plt.subplots(1, 2, figsize=(14, 6))
    for reach in REACHES:
        xmax = cutoffs[reach]["cutoff"]
        # fine (0.5 km)
        grid, mat = per_pass_slope_matrix(df, reach, res, "savgol", xmax=xmax)
        med, q25, q75, _, n = aggregate(grid, mat)
        m = n >= 10
        axf.plot(grid[m], np.abs(med[m]), "-", color=COLOR[reach], lw=2,
                 label=f"{reach.replace('_',' ')} (0.5 km)")
        axf.fill_between(grid[m], np.abs(q75[m]), np.abs(q25[m]),
                         color=COLOR[reach], alpha=0.15)
        # old (4.7 km) for contrast
        g2, m2 = per_pass_slope_matrix(df, reach, 4.7, "savgol", xmax=xmax)
        med2, _, _, _, n2 = aggregate(g2, m2)
        mm = n2 >= 10
        axf.plot(g2[mm], np.abs(med2[mm]), ":", color=COLOR[reach], lw=1.5,
                 label=f"{reach.replace('_',' ')} (4.7 km, old)")
        # zoom near bifurcation
        mz = m & (grid <= 10)
        axz.plot(grid[mz], np.abs(med[mz]), "-", color=COLOR[reach], lw=2,
                 label=reach.replace("_", " "))
        axz.fill_between(grid[mz], np.abs(q75[mz]), np.abs(q25[mz]),
                         color=COLOR[reach], alpha=0.15)
    for ax in (axf, axz):
        ax.axvline(BIFURCATION_KM, color="gray", ls="-.", lw=1)
        ax.set_xlabel("Distance from anchor (km)")
        ax.set_ylabel("|slope| (cm/km)")
        ax.grid(alpha=0.3); ax.legend(fontsize=8)
    axf.set_title("Fine-scale slope profile (0.5 km) vs old 4.7 km smoothing")
    axz.set_title("Bifurcation zoom (0–10 km)")
    fig.tight_layout()
    p = os.path.join(OUTDIR, "profile_and_zoom.png")
    fig.savefig(p, dpi=140); plt.close(fig)
    print(f"  saved {p}")


def temporal_near_bifurcation(df, cutoffs):
    """Per-pass robust slope in the near-bifurcation window over time, + the
    Kanektok-minus-Uyak advantage per pass (paired within date where possible)."""
    lo, hi = NEAR_BIF
    recs = {}
    for reach in REACHES:
        d = df[(df["reach"] == reach) & (df["bin"] >= lo) & (df["bin"] <= hi)]
        rows = []
        for p, g in d.groupby("pass"):
            if g["bin"].nunique() >= 5 and (g["bin"].max() - g["bin"].min()) >= (hi - lo) * 0.6:
                s = stats.theilslopes(g["wse"].values, g["bin"].values)[0] * 100.0
                rows.append({"pass": p, "slope": abs(s)})
        recs[reach] = pd.DataFrame(rows)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    for reach in REACHES:
        r = recs[reach].sort_values("pass")
        a1.plot(pd.to_datetime(r["pass"]), r["slope"], "o-", ms=3, lw=1,
                color=COLOR[reach], label=reach.replace("_", " "))
        print(f"  {reach} near-bifurcation ({lo}-{hi} km): "
              f"median {r['slope'].median():.0f} cm/km, "
              f"std {r['slope'].std():.0f}, n={len(r)}")
    a1.set_title(f"Near-bifurcation slope per pass ({lo}-{hi} km)")
    a1.set_ylabel("|slope| (cm/km)"); a1.legend(fontsize=8); a1.grid(alpha=0.3)
    # paired advantage
    k = recs["Kanektok_River"].set_index("pass")["slope"]
    u = recs["Uyak_Creek"].set_index("pass")["slope"]
    adv = (k - u).dropna().sort_index()
    a2.axhline(0, color="k", lw=0.8)
    a2.plot(pd.to_datetime(adv.index), adv.values, "o-", ms=3, lw=1, color="darkgreen")
    a2.set_title("Kanektok − Uyak slope advantage near bifurcation (paired per date)")
    a2.set_ylabel("Δ|slope| (cm/km)"); a2.set_xlabel("Date"); a2.grid(alpha=0.3)
    if len(adv):
        print(f"  paired advantage (Kanektok-Uyak): median {adv.median():.0f} cm/km, n={len(adv)}")
    fig.tight_layout()
    p = os.path.join(OUTDIR, "temporal_near_bifurcation.png")
    fig.savefig(p, dpi=140); plt.close(fig)
    print(f"  saved {p}")


def one_number_trim_effect(df, cutoffs):
    """Does trimming the coast change the single reference gradient?
    Theil-Sen on 1 km nodes per pass (gated span>=30, start<=3), median across passes,
    computed full vs coast-trimmed."""
    print("\n" + "=" * 78)
    print("ONE-NUMBER REFERENCE GRADIENT — full reach vs coast-trimmed")
    print("=" * 78)
    for reach in REACHES:
        cut = cutoffs[reach]["cutoff"]
        d = df[df["reach"] == reach].copy()
        d["node"] = (d["bin"]).round().astype(float)  # 1 km nodes from 0.1 km medians
        for label, xmax in [("full", d["bin"].max()), (f"trim<= {cut:.0f}km", cut)]:
            dd = d[d["bin"] <= xmax]
            nodes = dd.groupby(["pass", "node"])["wse"].median().reset_index()
            slopes = []
            for p, g in nodes.groupby("pass"):
                x = g["node"].values; y = g["wse"].values
                if len(x) >= 8 and (x.max() - x.min()) >= 30 and x.min() <= 3:
                    slopes.append(abs(stats.theilslopes(y, x)[0] * 100))
            if slopes:
                print(f"  {reach:16s} {label:12s}: {np.median(slopes):6.1f} cm/km "
                      f"(n={len(slopes)} gated passes)")
            else:
                print(f"  {reach:16s} {label:12s}: no gated passes (trim removed coverage)")


def main():
    print("Loading per-pass 0.1 km bins from local archive ...")
    df = load_pass_bins()
    print(f"  {df['reach'].nunique()} reaches, "
          f"{df.groupby('reach')['pass'].nunique().to_dict()} passes")

    print("\n" + "=" * 78)
    print("COASTAL CUTOFF DETECTION (cross-pass WSE IQR per 0.5 km bin)")
    print("=" * 78)
    cutoffs = detect_coastal_cutoff(df)
    for reach in REACHES:
        c = cutoffs[reach]
        print(f"\n{reach}: interior baseline IQR={c['baseline']:.2f} m, "
              f"threshold={c['thresh']:.2f} m")
        print(f"  --> suggested coastal cutoff: keep dist <= {c['cutoff']:.1f} km "
              f"(trim the seaward tail beyond it)")
        tail = c["profile"][c["profile"]["b5"] >= c["cutoff"] - 3]
        print("  last bins (b5 km : cross-pass IQR m):",
              ", ".join(f"{r.b5:.1f}:{r.cross_pass_iqr:.2f}" for r in tail.itertuples()))

    resolution_sweep(df, cutoffs)
    one_number_trim_effect(df, cutoffs)
    print("\nRendering figures ...")
    method_comparison(df, cutoffs)
    profile_and_zoom(df, cutoffs)
    temporal_near_bifurcation(df, cutoffs)
    print(f"\nDone. See ./{OUTDIR}/ for plots.")


if __name__ == "__main__":
    main()
