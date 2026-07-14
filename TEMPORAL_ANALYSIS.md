# Temporal Stability Analysis — Kanektok River & Uyak Creek

**A one-time analysis of how the two rivers' long-profiles change over time.**
Companion to the reference-gradient work. The analysis is computed once (offline); its
pre-computed results are displayed read-only in the dashboard's **⏳ Temporal Results** tab
(no live per-selection computation).

- **Code:** `temporal_analysis.py` (standalone, reads the full local record)
- **Data:** `batch_outputs/master_all_data_part_*.parquet` — full SWOT record, 2023-07-31 → 2026-06-20 (186 passes)
- **Outputs** (git-tracked in `temporal_results/`, read by the dashboard): `temporal_metrics_per_pass.parquet` (per-pass metrics), `temporal_q3_profile.parquet` (along-river ΔWSE curve for the typhoon figure), `temporal_analysis_results.json` (summary numbers)
- **Status:** Q1 & Q2 complete; Q3 (typhoon) is an **interim June-only** result — the definitive answer needs the summer-2026 pull (Jul–Aug).

---

## Plain-language summary

We asked three questions of the satellite record:

1. **Does the river change between spring high water and summer low water?** (seasonal)
2. **Is the river the same from one year to the next when nothing unusual happens?** (normal year-to-year)
3. **Did Typhoon Halong (Oct 2025) change the river?** (extreme event)

**The short answer: both rivers are very stable.** Their steepness (the "hydraulic
gradient") barely moves — season to season, year to year, or before/after the storm.
Water level wobbles only a few tens of centimetres, and the storm's effect on the
river upstream is **no larger than the normal year-to-year wobble.** Typhoon Halong's
damage was coastal shoreline erosion at Quinhagak — we do **not** see it reshaping the
river's upstream profile. *(The storm result is interim: it uses June data only; the
full check waits for summer-2026 measurements.)*

---

## Why this is a separate analysis (and how it stays honest)

These comparisons only mean something if every measurement is made the *same way*.
Earlier dashboard tabs (Seasonal Comparison, Typhoon Impact) drew slopes with ordinary
least-squares on **raw pixels**, which is **point-density biased** — the same flaw we
retired for the reference gradient — and pooled every pass in a period into one line
with **no coverage gate**. They also, at the time of writing, compared genuine summer
2025 against an **ice-contaminated** March–June 2026 "summer." Any conclusion drawn
that way is unreliable.

This analysis instead reuses the **locked reference-gradient engine** for every number:

| Choice | What it does |
|---|---|
| Aggregate each pass to **1 km node medians** before fitting | Removes along-stream point-density bias |
| **Theil–Sen** slope per pass | Robust to outliers (breakdown ≈ 29 %) |
| **Full-coverage gate** (≥ 8 nodes, span ≥ 30 km, start ≤ 3 km) | Every pass measures the *same* concave profile — no partial-pass artifact |
| **Open-water only** (Apr–Nov) | Excludes ice-inflated WSE (Dec–Mar). Window validated empirically (see note below) |
| Compare **matched seasons / months** | Removes the seasonal cycle from year-over-year and storm comparisons |

**Two metrics per pass**, both density-unbiased (from the node fit, not raw pixels):

- **Slope** (cm/km) — the hydraulic gradient (longitudinal drive relevant to avulsion).
- **WSE@15 km** (m) — water level at a fixed reference distance inside every gated pass's
  coverage; carries the flow / storm signal without being confounded by which reach a pass imaged.

**The key design idea — Q2 is the control for Q3.** Normal year-to-year change under *no*
disturbance (2024 → 2025) is the **natural-variability baseline**. The storm signal
(2025 → 2026) only counts as an impact if it **exceeds** that baseline. This turns a
vague "did it change?" into a signal-vs-noise test.

Of 186 passes, **136 full-coverage open-water passes** enter the analysis.

**Why Apr–Nov and not a stricter May–Oct core?** Checked empirically (2026-07). SWOT
returns gated passes in all 12 months, so the window is a real filter, not a no-op. The
two shoulder months contribute **37 of 136 (27 %)** of the open-water passes — meaningful
statistical power — and their per-pass slopes are indistinguishable from the core May–Oct
summer (Kanektok Apr 196.7 / Nov 195.5 vs core 195.3 cm/km; Uyak Apr 191.2 / Nov 190.4 vs
core 192.7), i.e. **no ice-inflation signature**, so they are kept. Dec–Mar are dropped:
the gradient is season-invariant enough that even winter slopes match (~195 / ~192 cm/km),
but winter WSE is ice-affected and must be excluded from the freshet/baseflow (Q1) and
typhoon (Q3) water-level comparisons.

---

## Q1 — Seasonal natural variability (May high flow vs Jul–Aug low flow)

As in Q2, the two metrics use different samples: **slope pooled across all years** (season-
invariant and coverage-sensitive → pool for robust n), **WSE resolved per year** (the actual
seasonal/flow signal, and coverage-robust). Median [IQR]; Mann–Whitney U.

**Seasonal slope contrast (May vs Jul–Aug, all years pooled):**

| River | May | Jul–Aug | Swing | Significant? |
|---|---|---|---|---|
| Kanektok | 195.7 (n=11) | 195.2 (n=19) | +0.5 cm/km | no (p=0.23) |
| Uyak | 193.0 (n=8) | 190.5 (n=11) | +2.5 cm/km | no (p=0.05) |

**Seasonal water-level swing (May − Jul–Aug, per year):**

| River | Year | WSE swing | Significant? |
|---|---|---|---|
| Kanektok | 2024 | −0.24 m | no (p=0.38) |
| Kanektok | 2025 | +0.24 m | no (p=0.11) |
| Uyak | 2024 | −0.52 m | no (p=0.10) |
| Uyak | 2025 | +0.42 m | no (p=0.25) |

**Finding.** The seasonal signal is **small and inconsistent.** Slope is essentially
season-invariant (+0.5 / +2.5 cm/km, neither significant) — matching the reference gradient's
own season split. Water level swings only ±0.2–0.5 m, and **the sign flips between years**
(May was *below* summer in 2024, *above* it in 2025), so there is no repeatable high-flow/
low-flow profile shift at this scale.

> **Methods note (same as Q2).** A *per-year* slope contrast first showed a **+8.3 cm/km
> Uyak-2025 "swing"** flagged significant. This is *largely* a coverage artifact (two of the five
> Jul–Aug 2025 passes start 3 km downstream and clip the steep reach): full-coverage-only shrinks
> it to +4.5, and a fixed-window slope shrinks it to +2.4. A small residual persists but is not
> robust (see [Method verification](#method-verification-is-the-pooling-justified-or-bias-fitting)).
> Pooling all years gives the robust +2.5. Hence the pooled slope basis here.

---

## Q2 — Normal interannual stability (2024 vs 2025)

This establishes the **natural-variability baseline** (no known disturbance between these years).
The two metrics use **different samples by design** (see the box below):

- **Slope:** full open-water year (n ≈ 18–32 per year). Q1 showed slope is season-invariant,
  so we do not season-match — and using the whole year avoids a small-sample coverage artifact
  (see below).
- **WSE@15 km:** season-matched to low flow (Jul–Aug), because water level *is* strongly seasonal.

| River | Slope 2024 → 2025 (full yr) | WSE 2024 → 2025 (Jul–Aug) | Significant? |
|---|---|---|---|
| Kanektok | +0.8 cm/km (n=31 vs 32) | −0.22 m (n=8 vs 8) | slope yes (p<0.001); WSE yes (p=0.003) |
| Uyak | **−0.7 cm/km** (n=18 vs 18) | −0.54 m (n=3 vs 5) | slope **no (p=1.00)**; WSE no (p=0.14) |

**Finding.** Both rivers are stable year-over-year. Slope changes are trivially small
(Kanektok +0.8, Uyak −0.7 cm/km, against a ~3 cm/km between-river difference). Kanektok's
values are *statistically* significant only because the river is so stable its variance is
tiny — **statistical significance ≠ geomorphic significance**. Normal water-level movement is
**~0.2 m (Kanektok) to ~0.5 m (Uyak)**. These are the yardsticks for Q3.

> **Why slope uses the full year, not Jul–Aug (a methods note).** A season-matched Jul–Aug
> slope comparison first suggested a large Uyak drop (−6.8 cm/km, "significant"). This is
> *largely* a coverage artifact — within that 5-pass sample, slope correlated −0.94 with where the
> pass *started* (`lo_km`); two 2025 passes began 3 km downstream, clipping the steep reach. An
> independent fixed-window slope (coverage held constant, no pooling) shrinks the drop to −2.0
> cm/km; the small residual is not robust (does not replicate at the annual level — Uyak medians
> are flat at 192.4 → 191.7 → 192.4 for 2024/25/26 — and fails multiple-testing). Because slope is
> independently shown to be season- and year-invariant, the full open-water year (n ≈ 18) is the
> robust interannual slope test. Full adversarial check:
> [Method verification](#method-verification-is-the-pooling-justified-or-bias-fitting).

---

## Q3 — Extreme-event impact: Typhoon Halong (interim, June 2025 vs June 2026)

Typhoon Halong made landfall **2025-10-12**, eroding ~60 ft of shoreline at Quinhagak.
Matched open-water month (June) before and after; full Jul–Aug comparison pending the summer-2026 pull.

| River | Slope Δ (storm) | WSE Δ (storm) | Normal baseline (Q2) | Verdict |
|---|---|---|---|---|
| Kanektok | −0.1 cm/km | **+0.02 m** | −0.22 m | within normal |
| Uyak | −0.4 cm/km | **−0.33 m** | −0.54 m | within normal |

**WSE change by distance (June 2025 → June 2026, binned medians):** essentially flat
everywhere — Kanektok +0.07 m overall (downstream +0.07 / upstream +0.06), Uyak +0.01 m
(downstream +0.00 / upstream +0.01). No localized upstream or downstream shift.

**Finding (interim).** **No detectable typhoon signal in the upstream river long-profile.**
Both rivers' post-storm gradient *and* water level fall **within — indeed below — normal
interannual variability**, and the along-river change is flat (no local scour/deposition
signature). The storm's dramatic effect was coastal; the river gradient and level upstream
are unchanged beyond ordinary year-to-year noise. This null result is trustworthy
*precisely because* it used the de-biased robust method with a natural-variability control —
the retired density-biased tab (summer 2025 vs ice-contaminated Mar–Jun 2026) would likely
have shown a spurious change.

---

## Method verification (is the pooling justified, or bias-fitting?)

Pooling slope (across years in Q1, across the full year in Q2) instead of comparing per-year is a
*researcher degree of freedom* — it could be regrouping the data until an inconvenient
"significant" result vanishes. To guard against that, `verify_temporal_method.py` tests the claims
the pooling rests on and re-answers the questions with an **independent** correction: a
**fixed-distance-window slope** ([3, 30] km, identical for every pass), where coverage cannot bias
the result and no pooling is involved. Findings:

1. **Profile is concave — mechanism confirmed.** Near-confluence slope (0–6 km) is ~3× the far
   slope (30–36 km): Kanektok 252 vs 80, Uyak 218 vs 77 cm/km. A pass clipping the steep reach
   *must* read gentler — real geomorphology.
2. **The artifact concentrates in small samples, not dataset-wide.** Across all gated passes the
   slope↔`lo_km` correlation is weak (Kanektok −0.13, Uyak −0.07); the gate already limits coverage
   variation. The strong −0.94 was *within the 5-pass Jul–Aug 2025 subsample*. So the artifact bites
   precisely when n is small — which is exactly the per-year/per-season slices.
3. **Independent fixed-window correction removes most of the anomaly.** With coverage held constant
   (no pooling), the Uyak-2025 anomalies shrink ~4×: seasonal +8.3 → **+2.4**, interannual −6.8 →
   **−2.0** cm/km. Most of the apparent signal was coverage. A ~2 cm/km residual remains, *still
   nominally significant* (p=0.036) in that 5-pass sample — reported honestly, not hidden.
4. **The residual is not robust.** It does not replicate at the annual level (Uyak annual medians
   flat: 192.4 / 191.7 / 192.4 for 2024/25/26), rests on n=5 as one of many comparisons (fails any
   multiple-testing correction), and lies inside Uyak's ±8 cm/km pass-to-pass scatter. It is one
   slightly-low late-summer-2025 cluster, not a season or year property.
5. **Season-invariance holds on clean data (non-circular).** Using full-coverage-only passes
   (start = 0 km; no artifact, no season-pooling): May−(Jul–Aug) slope is +0.5 (Kanektok, p=0.23)
   and +0.7 (Uyak, p=0.32) — small, not significant. Slope really is ~stage-invariant.
6. **Positive control — the method is not merely insensitive.** The real ~3 cm/km *between-river*
   slope difference is detected at p ≈ 2×10⁻¹⁶. A genuine temporal signal of that size would show;
   the temporal changes are simply smaller (< 1 cm/km at the annual grain).

**Verdict.** Pooling is justified on four independent legs, not the coverage artifact alone:
(i) the pooled metric (slope) is independently shown season- and year-invariant, so pooling blends
like with like; (ii) an independent coverage correction reaches the same "stable" conclusion with
no pooling; (iii) the only residual is small, non-replicating, and within noise; (iv) the method
provably detects real differences of the relevant size. The conclusion reflects the data's
structure, not a desired answer. Reproduce: `python3 verify_temporal_method.py`.

---

## Limitations

- **Q3 is interim.** June-only, with just **2–3 passes per river** (low statistical power;
  Uyak WSE change couldn't even be tested). The definitive pre/post comparison needs
  **Jul–Aug 2026 open-water data** — re-run `temporal_analysis.py` after that pull.
- **WSE reflects discharge, which SWOT does not measure.** Matching the same month across
  years, plus using the Q2 baseline as the control, is our defense against flow-driven
  differences masquerading as change — but it is not a discharge correction.
- **Small samples in the season-matched comparisons.** Month-level pass counts after gating are
  single digits (WSE and June-window slopes), so those medians and rank tests are used
  deliberately for robustness, and "not significant" often means "underpowered," not "proven
  equal." The full-year interannual slope test (n ≈ 18–32) is the exception and is well-powered.
- **Whole-reach quantities.** Both metrics summarize the full profile; sub-kilometre local
  behavior is a separate question (Slope Profile tab) at/below SWOT's slope-resolution scale.

---

## Reproduce

```bash
python3 temporal_analysis.py
```

Prints the full report and writes the three git-tracked artifacts to `temporal_results/`
(`temporal_metrics_per_pass.parquet`, `temporal_q3_profile.parquet`,
`temporal_analysis_results.json`) — the exact files the dashboard's ⏳ Temporal Results tab
reads, so re-running the script and committing `temporal_results/` refreshes the dashboard on
both local and Streamlit Cloud. Method parameters (top of the script) mirror
the reference gradient: `NODE_KM=1.0`, `MIN_NODES=8`, `MIN_SPAN_KM=30.0`, `MAX_START_KM=3.0`,
open-water = Apr–Nov, high flow = May, low flow = Jul–Aug, water-level reference `REF_DIST_KM=15`.

See `SCIENTIFIC_METHODOLOGY.md → Reference Gradient` for the shared engine's full verification.
