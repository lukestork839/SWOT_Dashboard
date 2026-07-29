# Slope Re-analysis — Findings & Plan

**Status:** exploration complete (standalone prototype), no pipeline/thesis changes made yet.
**Prototype:** `slope_finescale_prototype.py` → outputs in `slope_finescale_prototype/`
**Date:** 2026-07-22

---

## 1. What the professor asked (meeting notes, paraphrased)

- We ultimately want **one gradient number per channel** (we have this: the Theil–Sen reference gradient).
- Uyak Creek shows noise, *maybe* from coastal pixels or tide at the channel mouth. Whatever
  happens at the coast **does not affect the bifurcation**, so it can be cut from the slope
  calculation entirely.
- **Figure 8 has issues.** We're currently looking at the *reach-average* slope (effectively a
  ~2 km view). Can we **get into it and look at slope at backwater-length intervals** (~0.5 km here)?
- If that's too noisy, go to the **smallest resolvable scale**.
- Measure **temporal changes at that smaller scale**.
- Concern: **a slope advantage could be hiding where the action is** (near the bifurcation) —
  the reach-average may be masking it.

---

## 2. The core problem with the current Figure 8

Figure 8's slope profile is built as: 100 m median WSE bins → **Gaussian smoothing** → numerical
derivative. The smoothing parameter is `sigma = 2.0 km` — but σ is the *standard deviation* of the
kernel, **not** the window width. The effective resolution is the full-width-half-max:

```
resolution ≈ 2.355 × σ = 2.355 × 2 km ≈ 4.7 km
```

So **Figure 8 cannot show any slope feature narrower than ~5 km.** The backwater length scale here
is ~0.5 km (professor's estimate; consistent with L_b ≈ depth/slope ≈ 2 m / 0.00195 ≈ 1 km). The
current figure blurs backwater-scale structure completely — which is exactly where an avulsion
slope-advantage would appear. **The caption's "2 km smoothing window" also understates the actual
~4.7 km blur and should be corrected.**

> Note: the "1 km nodes" used for the single reference-gradient number and the "100 m bins + 2 km
> smoothing" used for the Figure 8 profile are **two separate methods for two separate jobs** — not
> an inconsistency. The reference number is fine; it's the *profile resolution* that's the issue.

---

## 3. Prototype findings (on the full local archive, 123 Kanektok / 90–115 Uyak open-water passes)

Method: compute the fine-scale slope **within each pass** (stage constant), then aggregate across
passes (median + robust band). This avoids mixing stage differences into slope at fine scale.

### 3.1 We can resolve 0.5 km — even finer

SNR = spatial structure of the mean slope profile ÷ per-bin measurement error. SNR ≳ 3 means real.

| Resolution | Kanektok SNR | Uyak SNR |
|---|---|---|
| 2.0 km | 69 | 48 |
| 1.0 km | 40 | 28 |
| **0.5 km** | **20** | **15** |
| 0.25 km | 12 | 9 |

Enormous pixel density (~35k pixels per 0.5 km bin, Kanektok) makes the binned WSE precise to ~mm,
so fine-scale slope is well-determined. **0.5 km is comfortable; 0.25 km is still resolvable.**

### 3.2 The estimator barely matters — the resolution does

At 0.5 km, three estimators (Gaussian+gradient, Savitzky–Golay derivative, sliding Theil–Sen) lie
almost exactly on top of each other (`method_comparison_0p5km.png`). The fix is **not** a fancier
estimator — it's to stop over-smoothing. (Savitzky–Golay or segmented Theil–Sen preferred for the
thesis: cleaner endpoints, honest error bars, consistent with the reference-gradient ethos.)

### 3.3 THE KEY RESULT — the slope advantage is concentrated at the bifurcation

Near-bifurcation window (1–5 km), per-pass robust slope:

| | Near bifurcation (1–5 km) | Whole reach (reference) |
|---|---|---|
| Kanektok | **259 cm/km** | 195.5 |
| Uyak | **219 cm/km** | ~192 |
| **Advantage (Kanektok − Uyak)** | **~39 cm/km** | ~3 |

Kanektok is ~40 cm/km steeper than Uyak **right where the channels split**, versus only a few cm/km
reach-averaged. `temporal_near_bifurcation.png` shows this advantage is **persistent across
2023–2026** (positive in nearly every pass). This directly supports the professor's hypothesis:
**the reach-average was hiding a real, localized, persistent slope advantage at the bifurcation.**

### 3.4 The "coastal noise" — CONFIRMED, and it has three distinct sources (step 2, 2026-07-22)

Diagnostic: `coastal_noise_diagnostic.py` (cross-pass WSE spread per 0.5 km bin, Uyak vs Kanektok
control; PNG in `coastal_noise_diagnostic/`). The professor's instinct was partly right, but the
"noise" is three separable things, all downstream of the bifurcation (2.5 km):

1. **A real, confined tidal/coastal effect at the very mouth (Uyak).** Uyak's far reach (30–34.5 km)
   is actually *quieter* than its interior (0.6–0.8× the 3–20 km baseline); pass-to-pass WSE spread
   only rises in the final ~1 km (35–36 km, ~2× baseline). That spread is **broad, not a few
   outliers** (robust std ~0.6 m at 35 km, only 8 % MAD-flagged) — i.e. a genuine systematic
   water-level effect at the sea, consistent with tide. So the professor's tide hypothesis holds,
   **but only for the last ~1 km.**
2. **Isolated contaminated passes (Kanektok).** Kanektok's control shows a sharp 5× spike at 33 km
   that is **1–2 outlier passes** (robust std collapses 1.50 → 0.33 m once MAD-flagged), not
   systematic — a QC candidate, unrelated to tide.
3. **Derivative amplification in Figure 8.** Near-mouth interval-slope scatter is 6.8× the interior
   for Kanektok (the gradient decays to ~40–80 cm/km and the numerical derivative gets wiggly on the
   gentle tail). For Uyak the mouth is *not* the noisy part — its slope scatter is interior-dominated
   (coverage/concavity, 0.7× at the mouth), which is what the full-coverage gate already addresses.

**Bottom line:** trimming the final ~1–2 km removes the only genuine coastal signal, does not touch
the bifurcation region, and (per §3.3 + the reference-gradient gate) does not change the reference
gradient. The fine-scale profile should display 0–~34 km and either drop or caption the tidal mouth;
the Kanektok 33 km passes are a separate QC item.

### 3.5 Number drift — RESOLVED (2026-07-22, full sweep)

Canonical set adopted (archive dated 2026-07-14; artifact current relative to the data):

| Metric | Kanektok | Uyak | Offset |
|---|---|---|---|
| **Reference gradient** | **195.4** cm/km (std 0.9, SEM 0.10, n=88) | **191.7** cm/km (std 4.3, SEM 0.53, n=67) | **3.6** cm/km |

Superseded values: thesis/methodology said 195.5 / 192.4 (Uyak stale); older notes 194.9 / 190.8.
The drift was **document staleness**, not a stale artifact (data + artifact both 2026-07-14). Two
non-obvious changes since the earlier archive: scatter tightened a lot (Kanektok std 3.3→0.9, Uyak
8.2→4.3) and Uyak's gated n grew 48→67 (data growth).

**Reconciled everywhere:** SCIENTIFIC_METHODOLOGY.md (table + A→D′ decomposition + Verification 3/4 +
caveats), figure_04 & figure_07 captions, TEMPORAL_ANALYSIS.md (188→155 passes, Q1/Q2/Q3 + adversarial
appendix), memories, and a thesis `.docx` edit list. Recompute anytime: `python3 canonical_stats.py`
and `canonical_stats_decomp.py` (standalone, read the local artifact).

**Two findings surfaced by the sweep that need an advisor decision (not just numbers):**
1. **Fig 6 max super-elevation is now +0.38 m @ 17.7 km** (was ~0). A short Kanektok reach now sits
   *above* Uyak — a mild counter-signal to "near-continuously sub-elevated." Feeds the Discussion.
2. **Uyak seasonal slope is now partly real:** on clean full-coverage passes, May−(Jul–Aug) = +2.3
   cm/km at p=0.016 (Kanektok +0.3, n.s.). The old "purely a coverage artifact" reading is revised
   in TEMPORAL_ANALYSIS.md. Doesn't overturn "rivers stable," but the framing is a scientific call.

---

## 4. Plan forward

Revised so we **build an interactive dashboard tab first**, use it to choose the best reach window,
*then* commit to a static thesis figure.

1. ~~**Consistency / number-drift audit.**~~ ✓ **DONE 2026-07-22** — canonical set 195.4 / 191.7
   adopted; all repo docs + memories reconciled; thesis `.docx` edit list produced (see §3.5).
2. ~~**Pin down the "coastal noise."**~~ ✓ **DONE 2026-07-22** — three sources identified (confined
   tidal mouth on Uyak; 1–2 contaminated passes on Kanektok @33 km; derivative amplification in
   Fig 8); none reach the bifurcation. See §3.4 + `coastal_noise_diagnostic.py`.
3. ~~**Interactive fine-scale slope dashboard tab.**~~ ✓ **DONE 2026-07-23** — new "🔬 Fine-Scale
   Slope" tab in dashboard_swot.py: per-pass-then-aggregate, resolution selector (default 0.5 km),
   estimator selector (Sliding Theil–Sen default + Sav–Gol + Gaussian), IQR band, bifurcation marker,
   distance-trim (default 34 km), bifurcation-zoom toggle, and a near-bifurcation advantage metric
   (Kanektok ≈259 / Uyak ≈229 cm/km at 1–5 km). Helpers `compute_finescale_slope` + `_fine_slope_*`
   ported from the prototype; cached per (selection, resolution, estimator, xmax). **Use this tab to
   pick the figure window before step 4.**
   - ⚠️ **Requires the full multi-pass record** (validated 2026-07-29). The method aggregates a
     per-pass slope with an `n ≥ 3` display gate, so it needs many overlapping passes; the welcome
     page's *quick-start* option loads only the most-recent handful of passes, which starves the gate
     — the mid-reach collapses into straight-line interpolation across dropped bins and the three
     estimators diverge (a selection artifact, not a data problem). Select the **full pass set**
     (Uyak 90 / Kanektok 123 open-water passes); coverage is then ~100 % core across 1–34 km and the
     estimators reconverge (Uyak 1–5 km |slope| ≈ 228 for all three). The near-coast steepening at
     ~26–30 km is a **real, repeatable** WSE feature (present in dozens of independent passes at
     ~300–360 cm/km), distinct from the tidal flattening in the final ~1 km.
4. ~~**New/revised Figure 8.**~~ ✓ **DONE 2026-07-29** — added a *fresh* **Figure 9** (kept Fig 8 as
   the reach-scale envelope) rather than reworking Fig 8. `core.finescale_slope_profile` (ported from
   the tab) + `build_fig9`: two stacked panels (full reach + 0–8 km bifurcation zoom), median line +
   25–75 % pass band, dashed reach-average reference overlay (195/192), sliding Theil–Sen at **0.5 km**
   (backwater scale — chosen over the cleaner 1.0 km for physical fidelity; advantage is +31 vs +27, so
   resolution-robust). **Key result:** near the bifurcation both channels steepen to ~250–300 cm/km,
   far above their ~195/192 reach averages — the reach-average understates the local gradient; Kanektok
   modestly steeper (1–5 km median 259 vs 228, +31 cm/km) but the profiles interweave (a tendency, not
   a persistent separation). Fig 8 caption corrected (σ=2 km → ~4.7 km FWHM; now cross-refs Fig 9).
5. **Temporal fine-scale result.** Near-bifurcation advantage over time as a supporting figure.
6. **Legacy cleanup.** Retire/relabel `slope_calc` (still shown as a biased number on the dashboard
   summary table; not used in any thesis figure).

---

## 5. Open questions for the professor

- **Backwater length:** confirmed ~0.5 km — target resolution. Go finer (0.25 km) anywhere?
- **Near-bifurcation window:** we used 1–5 km. Is that the right definition of "the bifurcation
  region," or should it be tied to backwater length (e.g. bifurcation ± 1–2 L_b)?
- **Does the ~40 cm/km localized advantage change the thesis conclusion?** The thesis currently
  argues near-equal reach gradients → stable system. A persistent *localized* steepening at the
  split may be a more nuanced (or stronger) avulsion-predisposition signal worth foregrounding.
- **The "coastal noise":** what specifically did you see on Figure 8 that read as noise? (Helps us
  confirm §3.4.)

---

## 6. Files

- `slope_finescale_prototype.py` — standalone exploration script (safe to re-run).
- `slope_finescale_prototype/method_comparison_0p5km.png` — three estimators agree at 0.5 km.
- `slope_finescale_prototype/profile_and_zoom.png` — 0.5 km vs old 4.7 km; bifurcation zoom.
- `slope_finescale_prototype/temporal_near_bifurcation.png` — advantage persistent 2023–2026.
