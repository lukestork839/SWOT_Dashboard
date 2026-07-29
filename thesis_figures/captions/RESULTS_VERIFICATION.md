# Results — single authoritative values for Sections 3.1–3.4 (2026-07-15)

All numbers recomputed from the current data + repo code on 2026-07-15 (not from
memory). One value per metric — this is the recommended set to standardize on.
Rationale: the thesis now uses the **figure-module methods** everywhere. Those
methods are statistically stronger than the interactive dashboard's (paired
within-pass differencing, robust medians, and internally consistent residual
statistics — see "Why these methods" at the end). Cite these numbers; describe
these methods in the Methods chapter.

Change flags vs the previously drafted text: ✓ effectively unchanged ·
~ minor · ⚠ changed · 🔴 notable / touches the Discussion argument.

---

## Pass / point counts (used throughout)

- Temporal & gradient analysis (3.1, 3.2): **155** gated full-coverage open-water
  passes (88 Kanektok + 67 Uyak).  [was "136"] ⚠
- Spatial profiles (3.3, 3.4): **123** open-water passes (Kanektok 123, Uyak 115).
  [was "121"] ⚠
- Total WSE measurements (3.3): **over 4.4 million** (4,420,299).  [was ">4.5M"] ~
- Study record: 2023-07-31 → 2026-07-09, 188 passes in the full master archive.
- NOTE: the live dashboard shows only 60 passes because that is a reduced
  *deployment subset* (Apr–Jul, all years) chosen for hosting speed. The analysis
  and thesis use the full Apr–Nov open-water archive above. Do not quote 60.

---

## Section 3.1 — Temporal / seasonal / interannual stability

- Total passes analyzed: **155** full-coverage open-water. ⚠

Seasonal slope contrast (May vs Jul–Aug), cm/km:
- Kanektok: **195.6** (May) vs **195.2** (Jul–Aug); swing **+0.3** (p=0.30, n.s.). ~
- Uyak: **193.5** (May) vs **191.2** (Jul–Aug); swing **+2.3** (p=0.033). ~

Seasonal WSE swing (May − Jul/Aug), m:
- Kanektok 2024 **−0.24**; 2025 **+0.23**. ✓
- Uyak 2024 **−0.31** (was −0.52) ⚠; 2025 **+0.45**. ~
- Variance range still ~0.2–0.5 m.

Interannual (2024 vs 2025):
- Kanektok slope Δ **+0.76**; WSE Δ **−0.22**. ✓
- Uyak slope Δ **−1.01** (was −0.7) ⚠; WSE Δ **−0.38** (was −0.54). ⚠
- ⚠ STATS CAVEAT: Kanektok interannual p-values are tiny (slope p≈0.0, WSE
  p=0.0019) but the magnitudes are hydraulically trivial — a large-n artifact.
  Do not imply a meaningful trend from significance alone.

Typhoon window (June 2025 vs June 2026, interim):
- Kanektok slope Δ **+0.04**; WSE Δ **−0.09**. 🔴 (both ≈ 0; sign of WSE Δ flipped)
- Uyak slope Δ **−0.55**; WSE Δ **−0.29**. ~
- Conclusion unchanged: no detectable typhoon signal, both within baseline.
  Still requires the Jul–Aug 2026 window to be conclusive.

---

## Section 3.2 — Reference hydraulic gradients

Median of per-pass |Theil–Sen| slopes over gated full-coverage open-water passes:
- Kanektok: **195.4 cm/km** (was 195.5). ✓
- Uyak: **191.7 cm/km** (was 192.4). ⚠  [exact median 191.749 → rounds to 191.7; earlier 191.8 was an over-round]
- Core finding intact: the two gradients agree to within ~3.6 cm/km.

---

## Section 3.3 — Spatial gradient profiles & elevation difference

Kanektok − Uyak WSE, per-pass within-pass median then median across passes:
- Passes: **123**; measurements: **over 4.4 million**.
- Average elevation deficit (Kanektok below Uyak): **0.95 m** (mean diff −0.946). ⚠
- Kanektok maximum superelevation: **+0.38 m**. 🔴 (was +0.025 m)
- Uyak maximum sub-elevation: **−2.24 m** (was −2.343). ~
- 🔴 The maximum-superelevation value jumps from ~0 to +0.38 m — Kanektok now shows
  a clearly positive superelevated reach. This feeds the avulsion-risk argument in
  the Discussion; re-check that chapter reads correctly against +0.38 m.

---

## Section 3.4 — Detrended relative elevation

Residuals about a single 2nd-order polynomial fit to both rivers pooled; all
statistics computed on outlier-removed residuals (Modified Z ≤ 3.5, per reach):
- Kanektok: mean **−0.39 m**, median **−0.41 m**, P99 (max + deviation) **+1.26 m** (was +1.05). 🔴
- Uyak: mean **+0.56 m**, median **+0.49 m**, P99 (max + deviation) **+2.75 m** (was +2.42). 🔴
- The ~1 m structural gap (Uyak above baseline, Kanektok below) is intact; centre
  statistics barely moved.
- 🔴 P99 max deviations grew. If the Discussion cites Uyak's P99 as evidence of
  superelevation, the value is now larger (stronger for the argument) — update it.
- (P1 max-negative deviations, if needed: Kanektok −1.81 m, Uyak −1.55 m.)

---

## Methods chapter — changes to reflect

1. **Reference hydraulic gradient (canonical metric).** Median of per-pass
   Theil–Sen slopes fit to 1 km node medians, over gated full-coverage open-water
   passes (gate: ≥8 nodes, ≥30 km span, start ≤3 km). Replaces any earlier
   single-trendline / pooled-OLS gradient (point-density biased).
2. **Channel polygon refinement.** Uyak Creek mask tightened to exclude a small
   lake leaking into the extent near ~5 km; the Uyak profile is now monotonic
   0–8 km. Remove any description of a lower-Uyak anomaly.
3. **Known-bad-pass exclusion.** 2025-04-17 spring-breakup (river-ice) pass dropped
   from all products via a QC exclusion list, applied once at aggregation.
4. **Residual-domain outlier filter.** Final QC outlier filter is a MAD-based
   Modified Z-Score (|Z| > 3.5; Iglewicz & Hoaglin 1993) on DETRENDED residuals per
   reach — not on raw WSE.
5. **Open-water window = April–November** (empirically justified). Apr–Jul is only
   the dashboard deployment subset; do not describe it as the analysis window.
6. **Elevation-difference method (3.3).** Within-pass differencing (both channels
   imaged near-simultaneously) then median across passes — replaces pooled AVG.
7. **Detrending baseline (3.4).** One 2nd-order polynomial fit to both rivers pooled
   defines the shared regional baseline; each river's residual is its offset from it.
8. **New Figure 2** — data-processing pipeline flowchart (caption + detailed
   Section 4.2 description in this folder).

---

## Why these methods (Methods-chapter rationale)

- **3.3 within-pass median vs pooled AVG:** each pass images both channels
  near-simultaneously, so a within-pass difference is a *paired* comparison that
  cancels the shared water stage; pooling means differencing bins built from
  different sets of passes (unpaired), letting uneven high-/low-flow sampling bias
  the result. The per-bin *median* is also robust to residual contamination that a
  mean is not.
- **3.4 consistent outlier removal:** reporting all dispersion statistics on the
  same outlier-removed residual set is internally consistent; computing P99 over
  residuals that still contain flagged contamination would let the extreme
  percentile measure that contamination rather than true structural deviation.
