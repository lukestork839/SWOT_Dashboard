# Temporal Stability Analysis — Kanektok River & Uyak Creek

**A one-time analysis of how the two rivers' long-profiles change over time.**
Companion to the reference-gradient work. The analysis is computed once (offline); its
pre-computed results are displayed read-only in the dashboard's **⏳ Temporal Results** tab
(no live per-selection computation).

- **Code:** `temporal_analysis.py` (standalone, reads the full local record)
- **Data:** `batch_outputs/master_all_data_part_*.parquet` — full SWOT record, 2023-07-31 → 2026-07-09 (188 passes)
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

Of 188 passes, **155 full-coverage open-water passes** enter the analysis.

**Why Apr–Nov and not a stricter May–Oct core?** Checked empirically (2026-07). SWOT
returns gated passes in all 12 months, so the window is a real filter, not a no-op. The
two shoulder months contribute **37 of 155 (24 %)** of the open-water passes — meaningful
statistical power — and their per-pass slopes are indistinguishable from the core May–Oct
summer (Kanektok Apr 196.3 / Nov 195.5 vs core 195.3 cm/km; Uyak Apr 191.9 / Nov 191.0 vs
core 192.0), i.e. **no ice-inflation signature**, so they are kept. Dec–Mar are dropped:
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
| Kanektok | 195.6 (n=11) | 195.2 (n=19) | +0.3 cm/km | no (p=0.30) |
| Uyak | 193.5 (n=10) | 191.2 (n=15) | +2.3 cm/km | marginal pooled (p=0.03); not year-consistent (2024 reversed) |

**Seasonal water-level swing (May − Jul–Aug, per year):**

| River | Year | WSE swing | Significant? |
|---|---|---|---|
| Kanektok | 2024 | −0.24 m | no (p=0.38) |
| Kanektok | 2025 | +0.24 m | no (p=0.11) |
| Uyak | 2024 | −0.31 m | no (p=0.07) |
| Uyak | 2025 | +0.45 m | no (p=0.11) |

**Finding.** The seasonal signal is **small and inconsistent.** Slope is essentially
season-invariant (+0.3 / +2.3 cm/km; Kanektok not significant, Uyak marginally so in the pooled
test (p=0.03) but not consistent year-to-year — 2024 reversed, dominated by 2025, see note below)
— broadly matching the reference gradient's own season split. Water level swings only ±0.2–0.5 m, and **the sign flips between years**
(May was *below* summer in 2024, *above* it in 2025), so there is no repeatable high-flow/
low-flow profile shift at this scale.

> **Methods note (same as Q2).** A *per-year* slope contrast shows a **+4.3 cm/km Uyak-2025
> "swing."** This is *partly* a coverage artifact (two of the five Jul–Aug 2025 passes start 3 km
> downstream and clip the steep reach): a fixed-distance-window slope shrinks it to +2.2 cm/km
> (p=0.038). Unlike in the earlier archive, a ~2 cm/km residual now persists on clean full-coverage
> passes (Uyak +2.3, p=0.016 — see
> [Method verification](#method-verification-is-the-pooling-justified-or-bias-fitting)), so Uyak's
> late-summer steepening is small but no longer purely an artifact. Pooling all years gives the
> robust +2.3. Hence the pooled slope basis here.

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
| Kanektok | +0.8 cm/km (n=31 vs 31) | −0.22 m (n=8 vs 8) | slope yes (p<0.001); WSE yes (p=0.002) |
| Uyak | **−1.0 cm/km** (n=23 vs 24) | −0.38 m (n=5 vs 6) | slope **no (p=0.32)**; WSE no (p=0.13) |

**Finding.** Both rivers are stable year-over-year. Slope changes are trivially small
(Kanektok +0.8, Uyak −1.0 cm/km, against a ~3.6 cm/km between-river difference). Kanektok's
values are *statistically* significant only because the river is so stable its variance is
tiny — **statistical significance ≠ geomorphic significance**. Normal water-level movement is
**~0.2 m (Kanektok) to ~0.4 m (Uyak)**. These are the yardsticks for Q3.

> **Why slope uses the full year, not Jul–Aug (a methods note).** A season-matched Jul–Aug
> slope comparison suggests a Uyak drop (−3.0 cm/km). This is *partly* a coverage artifact — Uyak's
> per-pass slope correlates −0.58 with where the pass *starts* (`lo_km`) even across all gated passes;
> some 2025 passes began downstream, clipping the steep reach. An independent fixed-window slope
> (coverage held constant, no pooling) shrinks the drop to −2.0 cm/km (p=0.082, not significant), and
> it does not replicate at the annual level (Uyak medians 191.9 → 190.9 → 192.6 for 2024/25/26).
> Because slope is independently shown to be season- and year-invariant for the interannual test, the
> full open-water year (n ≈ 23) is the robust interannual slope test. Full adversarial check:
> [Method verification](#method-verification-is-the-pooling-justified-or-bias-fitting).

---

## Q3 — Extreme-event impact: Typhoon Halong (interim, June 2025 vs June 2026)

Typhoon Halong made landfall **2025-10-12**, eroding ~60 ft of shoreline at Quinhagak.
Matched open-water month (June) before and after; full Jul–Aug comparison pending the summer-2026 pull.

| River | Slope Δ (storm) | WSE Δ (storm) | Normal baseline (Q2) | Verdict |
|---|---|---|---|---|
| Kanektok | +0.04 cm/km | **−0.09 m** | −0.22 m | within normal |
| Uyak | −0.55 cm/km | **−0.29 m** | −0.38 m | within normal |

**WSE change by distance (June 2025 → June 2026, binned medians):** essentially flat
everywhere — Kanektok +0.01 m overall (downstream +0.01 / upstream −0.00), Uyak −0.01 m
(downstream −0.01 / upstream −0.02). No localized upstream or downstream shift.

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
the result and no pooling is involved.

> ⚠ **Revision note (2026-07-22, current archive).** Re-running `verify_temporal_method.py` on the
> larger archive changes two supporting claims below. (1) Coverage sensitivity does **not** vanish
> after gating — the gated-pass slope↔`lo_km` correlation is now moderate (Kanektok −0.41, Uyak
> −0.58), not "weak." (2) On clean full-coverage passes the *pooled* Uyak May−(Jul–Aug) contrast is
> +2.3 cm/km (steeper in May / high flow) at p=0.016 — but this does **NOT persist year-to-year**:
> per-year swings are 2024 **−0.9 (reversed)**, 2025 **+4.3**, 2026 +1.8 (n=1 late summer). The
> pooled significance conflates a *year* effect with a *season* effect (non-exchangeable years) and
> is dominated by 2025, so it is **not a robust seasonal cycle** — better read as year-to-year
> variability. Kanektok is flat every year (±0.0, a clean control). So the earlier "purely a
> coverage artifact" wording was wrong on *mechanism*, but the practical conclusion — not a stable
> seasonal property — stands. None of this overturns the top-line result (both rivers stable; no
> typhoon signal). Framing for the thesis is a scientific call (discuss with advisor).
> Numbers below are updated to the current run.

Findings:

1. **Profile is concave — mechanism confirmed.** Near-confluence slope (0–6 km) is ~3× the far
   slope (30–36 km): Kanektok 252 vs 78, Uyak 219 vs 78 cm/km. A pass clipping the steep reach
   *must* read gentler — real geomorphology.
2. **Coverage sensitivity persists after gating, more so for Uyak.** Across all gated passes the
   slope↔`lo_km` correlation is moderate (Kanektok −0.41, Uyak −0.58) — the gate limits but does not
   eliminate it. A fixed-distance window removes it for Kanektok (−0.06) and roughly halves it for
   Uyak (−0.38). The artifact is real and dataset-wide; the fixed-window re-answer (point 3) is the
   check that it is not driving the conclusions, and it bites hardest in the small per-year slices.
3. **Independent fixed-window correction removes about half the anomaly.** With coverage held constant
   (no pooling), the Uyak-2025 anomalies shrink ~2×: seasonal +4.3 → **+2.2**, interannual −3.0 →
   **−2.0** cm/km. Roughly half the apparent signal was coverage. The seasonal residual (+2.2) is
   *still nominally significant* (p=0.038); the interannual residual (−2.0) is not (p=0.082) —
   reported honestly, not hidden.
4. **The residual is not robust.** It does not replicate at the annual level (Uyak annual medians
   flat: 191.9 / 190.9 / 192.6 for 2024/25/26), rests on n=5 as one of many comparisons (fails any
   multiple-testing correction), and lies inside Uyak's ±8 cm/km pass-to-pass scatter. It is one
   slightly-low late-summer-2025 cluster, not a season or year property.
5. **Season-invariance holds for Kanektok; Uyak's pooled seasonal signal is a year effect, not a cycle.**
   Using full-coverage-only passes (start = 0 km): the *pooled* May−(Jul–Aug) slope is +0.3 (Kanektok,
   p=0.30, n.s.) and +2.3 (Uyak, p=0.016; steeper in May / high flow). But per-year the Uyak swing is
   inconsistent — 2024 **−0.9 (reversed)**, 2025 **+4.3**, 2026 +1.8 (n=1) — so the pooled significance
   conflates a year effect with a season effect and is dominated by 2025, **not a robust seasonal cycle**.
   Kanektok is flat every year. ⚠ See the revision note above.
6. **Positive control — the method is not merely insensitive.** The real ~3.6 cm/km *between-river*
   slope difference is detected at p ≈ 1×10⁻²². A genuine temporal signal of that size would show;
   the temporal changes are simply smaller (≈ 1 cm/km at the annual grain).

**Verdict.** Pooling is justified on four independent legs, not the coverage artifact alone:
(i) the pooled metric (slope) is independently shown season- and year-invariant, so pooling blends
like with like; (ii) an independent coverage correction reaches the same "stable" conclusion with
no pooling; (iii) the residuals are small (≤ ~2 cm/km) and within Uyak's pass-to-pass scatter —
though Uyak's seasonal component is now marginally replicable on clean data and worth revisiting
(revision note above); (iv) the method provably detects real differences of the relevant size. The conclusion reflects the data's
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
