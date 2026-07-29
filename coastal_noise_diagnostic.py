"""Coastal-noise diagnostic (SLOPE_REANALYSIS_PLAN step 2, 2026-07-22).

Professor's hypothesis: Uyak Creek's noise comes from coastal pixels / tide at the
channel mouth. Prototype §3.4 hinted the coast is not badly contaminated in aggregate
and the "noise" is really the erratic gentle far reach. This settles it:

  Q1. WHERE along each river does cross-pass WSE spread spike? (last bin only, or a
      broad far reach?)  -> tidal backwater grows toward the mouth; contamination is
      a few spiky bins.
  Q2. Is Uyak's mouth noisier than Kanektok's? (Kanektok = control)
  Q3. Is the far-reach spread driven by a FEW passes (contamination) or ALL passes
      (systematic, e.g. tide)?
  Q4. Is the noise in raw WSE, or only in the DERIVED slope near the mouth?

Standalone; reads the local master parquet; writes a PNG + prints tables.
Run: python3 coastal_noise_diagnostic.py
"""
import os
import numpy as np
import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATA = "batch_outputs/master_all_data.parquet"
OUTDIR = "coastal_noise_diagnostic"
REACHES = ["Kanektok_River", "Uyak_Creek"]
COLOR = {"Kanektok_River": "firebrick", "Uyak_Creek": "dodgerblue"}
OPEN_WATER = (4, 5, 6, 7, 8, 9, 10, 11)
EXCLUDED = ("2025-04-17",)
BIN_KM = 0.5
os.makedirs(OUTDIR, exist_ok=True)

con = duckdb.connect()
months = ",".join(str(m) for m in OPEN_WATER)
excl = ",".join(f"'{d}'" for d in EXCLUDED)
pts = con.execute(f"""
    SELECT Reach_Name, CAST(Pass_Date AS DATE) AS pass, dist_km, wse
    FROM '{DATA}'
    WHERE EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) IN ({months})
      AND CAST(Pass_Date AS DATE) NOT IN ({excl})
""").fetchdf()
pts["bin"] = (pts["dist_km"] / BIN_KM).round() * BIN_KM

# per (reach, pass, bin) median WSE
per = (pts.groupby(["Reach_Name", "pass", "bin"])["wse"].median().reset_index())

fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

for reach in REACHES:
    d = per[per.Reach_Name == reach]
    g = d.groupby("bin")["wse"]
    spread = g.std()            # cross-pass std of per-pass median WSE
    iqr = g.quantile(0.75) - g.quantile(0.25)
    npass = g.size()
    x = spread.index.to_numpy()
    mouth = x.max()

    print("\n" + "=" * 66 + f"\n{reach}  (mouth at {mouth:.1f} km)\n" + "=" * 66)
    # interior baseline = median spread over the 3-20 km core
    core_mask = (x >= 3) & (x <= 20)
    base = np.nanmedian(spread.to_numpy()[core_mask])
    print(f"interior (3-20km) baseline cross-pass WSE std: {base*100:.1f} cm")
    # far reach breakdown, last 6 km
    print(f"{'bin_km':>7} {'std_cm':>7} {'iqr_cm':>7} {'n_pass':>6} {'x/base':>7}")
    for b in x[x >= mouth - 6]:
        s = spread.loc[b]; q = iqr.loc[b]; n = int(npass.loc[b])
        print(f"{b:7.1f} {s*100:7.1f} {q*100:7.1f} {n:6d} {s/base:7.1f}")

    axes[0].plot(x, spread.to_numpy() * 100, color=COLOR[reach], lw=2, label=reach)
    axes[1].plot(x, npass.to_numpy(), color=COLOR[reach], lw=2, label=reach)

axes[0].set_ylabel("cross-pass WSE std (cm)")
axes[0].set_title("Q1/Q2: where does WSE spread spike? (Uyak vs Kanektok control)")
axes[0].legend(); axes[0].grid(alpha=0.3)
axes[1].set_ylabel("# passes per bin"); axes[1].set_xlabel("distance from anchor (km)")
axes[1].grid(alpha=0.3); axes[1].legend()
fig.tight_layout()
fig.savefig(f"{OUTDIR}/wse_spread_vs_distance.png", dpi=130)
print(f"\nsaved {OUTDIR}/wse_spread_vs_distance.png")

# Q3: within each river's noisiest mouth bin, is the spread a FEW outlier passes
# (contamination) or a broad/symmetric spread (tide)?  Center each pass's WSE on the
# bin median so the natural elevation is removed; then MAD-flag outliers.
print("\n" + "=" * 66 + "\nQ3. Mouth-bin spread: few outliers (contamination) vs broad (tide)?\n" + "=" * 66)
for reach, bin_km in [("Uyak_Creek", 35.0), ("Kanektok_River", 33.0)]:
    d = per[(per.Reach_Name == reach) & (np.isclose(per["bin"], bin_km))]
    v = d["wse"].to_numpy()
    med = np.median(v); mad = np.median(np.abs(v - med))
    mz = 0.6745 * (v - med) / mad if mad > 0 else np.zeros_like(v)
    nout = int((np.abs(mz) > 3.5).sum())
    resid = v - med
    print(f"\n{reach} @ {bin_km} km (n={len(v)} passes):")
    print(f"  centered spread: std={resid.std():.2f} m  IQR={np.percentile(resid,75)-np.percentile(resid,25):.2f} m")
    print(f"  MAD outliers (|Z|>3.5): {nout} of {len(v)}  ({100*nout/len(v):.0f}%)")
    print(f"  robust std (excl. outliers): {resid[np.abs(mz)<=3.5].std():.2f} m")
    # a few outliers driving it -> contamination; broad even after removing them -> tide
    verdict = "FEW OUTLIERS (contamination-like)" if nout and resid[np.abs(mz)<=3.5].std() < 0.5*resid.std() else "BROAD spread (tide/systematic-like)"
    print(f"  -> {verdict}")

# Q4: is the far-reach noise in raw WSE, or amplified in the DERIVED slope?
print("\n" + "=" * 66 + "\nQ4. Per-pass interval-slope spread: interior vs near-mouth\n" + "=" * 66)
for reach in REACHES:
    d = per[per.Reach_Name == reach].sort_values(["pass", "bin"])
    slopes_int, slopes_mouth = [], []
    mouth = d["bin"].max()
    for p, grp in d.groupby("pass"):
        x = grp["bin"].to_numpy(); y = grp["wse"].to_numpy()
        if len(x) < 5:
            continue
        s = np.gradient(y, x) * 100  # cm/km
        slopes_int.append(np.nanmedian(s[(x >= 3) & (x <= 20)]))
        slopes_mouth.append(np.nanmedian(s[x >= mouth - 4]))
    si = np.array(slopes_int, float); sm = np.array(slopes_mouth, float)
    print(f"{reach}: interior slope std={np.nanstd(si):.0f} cm/km ; "
          f"near-mouth slope std={np.nanstd(sm):.0f} cm/km  "
          f"(mouth/interior = {np.nanstd(sm)/np.nanstd(si):.1f}x)")
