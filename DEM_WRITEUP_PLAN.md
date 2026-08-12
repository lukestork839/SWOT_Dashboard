# DEM Write-up — Revised Outline & Figure Plan

**Status:** planning complete, nothing built yet. Supersedes the figure list in `DEM_Figures.pdf`
and restructures the outline in `DEM_outline.pdf`.
**Date:** 2026-08-10
**Scope:** the full start-to-finish DEM (topographic) analysis of the Kanektok / Uyak system —
methods, results, and the figure set that carries them.

Companion docs: `DEM_Transects/AVULSION_ANALYSIS.md` (arc method, the science of record),
`SCIENTIFIC_METHODOLOGY.md` (validation), `SLOPE_REANALYSIS_PLAN.md` (the SWOT slope analogue
this plan mirrors), `dem_veg_filter/FINDINGS.md` (DEM quality).

---

## 1. The two DEM data streams

Everything in this write-up comes from ArcticDEM v4.1, but through **two independent extraction
paths that answer different questions**. Keeping them straight is the single most important
structural fix to the outline, because the original figure list drew all five figures from
Stream A and then asked Stream A questions it cannot answer.

The dividing line is **not primarily resolution — it is sampling geometry.**

| | **Stream A — corridor** | **Stream B — targeted** |
|---|---|---|
| Raster | `batch_outputs/arcticdem_rivers.tif` | `batch_outputs/arcticdem_rivers_2m.tif` (113.8 MB) |
| Path | Google Earth Engine, `scale = 10` | PGC S3 COGs via `/vsicurl`, native 2 m |
| Script | `DEM_Pull.py` | `DEM_2m_Pull.py` |
| CRS | EPSG:4326 | EPSG:3413 |
| Where sampled | **every pixel inside two river polygons** (`river_poly.zip`) | **along arcs / along centerlines** |
| Aggregation | median per 0.5 km radial bin | per-arc percentiles; per-station swath |
| Volume | 2.49 M px (1.08 M Kanektok, 1.40 M Uyak) → 70 bins | 64 arcs; ~1 700 stations/channel |
| Artifact | `dem_river_elevations.parquet` (48 MB) | `arcB_profiles/arcB_channels.parquet`, `centerline_*.parquet` |
| Geoid | constant | **per radius** (13.74 m anchor → 13.28 m coast) |
| Drives | dashboard DEM tabs 1–5 | dashboard ✂️ Cross-Sections; Phase-2 slope |

### 1.1 What Stream A actually measures — and why it matters

The two polygons are not channels. Measured:

| | Kanektok | Uyak |
|---|---|---|
| Polygon area | 54.3 km² | 66.8 km² |
| **Mean width** | **1 442 m** | **1 725 m** |
| Channel width (field) | ~50 m | ~30 m |
| Channel as fraction of swath | **3.5 %** | **1.7 %** |
| Mutual overlap | **2.33 km²**, polygons touch (min distance 0 m) | |

So the median of a ~1.5 km-wide swath is **the floodplain surface, not the channel** — the channel
contributes a few percent of the pixels and cannot move a median. And because the two swaths
overlap and abut across a shared floodplain, both medians converge on the *same* surface.

This is verifiable rather than merely argued. Comparing Stream A's pooled corridor median against
the arc method's independently-computed floodplain reference (`fp_ref_m`, median corridor width
2 696 m) at matched radius:

> **median difference +0.19 m** (p10 +0.03, p90 +0.81 m)

Stream A *is* the floodplain reference, reproduced at 10 m over the whole corridor. That is a
genuinely useful quantity — it is the regional valley profile, and it independently corroborates
the arc method's floodplain term. It is simply **not a channel profile**, and no amount of
differencing or detrending will make it one.

### 1.2 The consequence for the original figure list

Verified against the data this session:

- **Original Fig 4 (Elevation Difference)** — claimed "the smoking gun for sub-elevation… exactly
  how many meters below Uyak the Kanektok valley floor sits." Actual Kanektok − Uyak corridor
  difference: **median −0.17 m, range −1.13 to +1.11 m**. Near the bifurcation (1.5–5.5 km) the
  Kanektok corridor is *higher*, by up to **+1.11 m** — opposite in sign to the claim, in the reach
  that matters most. The only multi-metre values in the series are at 34.5 / 35.0 km (−2.11, −3.09 m)
  and are artifacts: the Kanektok polygon has reached the coast while the Uyak is still ~3.3 m
  inland at the same radius.
- **Original Fig 5 (Detrended Residuals)** — claimed "Kanektok deeply negative, Uyak positive…
  definitively rules out a perched primary channel." Actual: Kanektok residuals negative on **63 %**
  of bins, Uyak positive on **53 %**; medians **−0.18 m / +0.06 m**; signs *reversed* at 3.5 km.
  That is coin-flip, not a result.
- **Original Fig 2** — "Kanektok often plots lower than Uyak" is mixed by reach, and at a 0–72 m
  y-axis a ~1 m separation is 1.4 % of plot height. The figure cannot resolve its own takeaway.
- **Original Fig 3** — "no jagged knickpoints" is read off a derivative Gaussian-smoothed at
  σ = 1.5 km, which removes knickpoints by construction. Same trap as thesis Fig 8
  (σ = 2 km → 4.7 km FWHM); absence of structure cannot be claimed from a smoothed derivative.

None of these are coding errors — the dashboard computes exactly what it says. They are
**interpretation errors**, all with one root cause: asking a floodplain-wide median to distinguish
two channels 30–50 m wide.

### 1.3 Where the channel-specific evidence lives (Stream B)

| Result | Value | Source |
|---|---|---|
| Kanektok channel **incised** below inter-channel floodplain | **−1.50 m**, 100 % of 63 valid arcs (p10 −1.85, p90 −0.91; still −1.01 m at high stage) | arcs |
| Uyak sits ≈ at grade | −0.49 m, below on 70 % | arcs |
| Superelevation ratio **β** | **0.057** (p10 −0.31, p90 +0.30); H_AR **+0.14 m**; H_M 2.88 m; β ≤ 0 on **38 %** | arcs |
| Bankfull consistency (freeboard ÷ depth) | **1.27** at the adopted ±150 m crest window | arcs |
| Uyak − Kanektok water surface | **+0.96 m** pass-paired SWOT (100 % of passes); +1.45 m DEM-only | arcs + SWOT |
| DEM ↔ SWOT water-surface agreement | **−0.15 m** Kanektok, **+0.14 m** Uyak | arcs + SWOT |
| Near-bifurcation steepening, both channels | ~210–290 cm/km ≫ ~195 reach average — robust in every configuration tested | Phase 2 |
| Kanektok along-channel bed gradient | **213–220 cm/km**, smoothing-independent | P6 (§1.5) |
| Along-channel gradient advantage | **K/U = 1.13–1.15** in the 50–200 m band, agreeing with SWOT's centerline-free **1.158** | P6 (§1.5) |
| Uyak is the **more sinuous** channel | U/K sinuosity 1.07–1.17 through the band → escape route is the longer path | P6 (§1.5) |
| DEM cannot arbitrate boat wander | wander 2–5 m std vs DEM channel-location scatter 35–43 m — a hard limit | P6 (§1.5) |
| Kanektok thalweg depth | median **1.22 m** (p10–p90 0.79–1.88, max 3.9), 39.5 k pings | ADCP |
| Depth at the mouth (31–33 km, only reach both surveyed) | Kanektok **1.26× deeper** (1.37 vs 1.08 m) | ADCP |

### 1.4 The centerline switch (P2.1), and what it withdrew — 2026-08-10

Switching Phase 2 from the SWOT-derived centerlines to the official field centerlines was run
first, as agreed. It changed the answer, and then a sensitivity test withdrew it.

**The SWOT centerlines were missing the meanders almost entirely.** They carry 77–79 vertices over
~38 km; the field lines carry 17 143 / 7 364. Sinuosity at 1–5 km:

| | Kanektok | Uyak |
|---|---|---|
| SWOT centerline | 1.075 | 1.097 |
| Field centerline | **1.455** | **1.715** |

Simplifying the field lines to 200 m tolerance still leaves sinuosity at 1.27 / 1.32, so this is
**real meandering, not GPS jitter** — the SWOT lines were cutting straight chords across it.

Because along-channel gradient = drop ÷ path length, a longer path means a gentler gradient. With
the field lines the near-bifurcation along-channel gradients drop from 253 / 214 to roughly
**220 / 179 cm/km**, and the K/U ratio rose from 1.18 to 1.23.

**But the ratio does not survive a smoothing sensitivity test** (z_p05, 1–5 km means):

| simplify tol | K sin | K along | U sin | U along | **K/U along** | K/U radial |
|---|---|---|---|---|---|---|
| 0 m | 1.473 | 212.8 | 1.767 | 181.7 | **1.171** | 1.079 |
| 20 m | 1.455 | 220.4 | 1.715 | 178.9 | **1.232** | 1.175 |
| 50 m | 1.433 | 213.4 | 1.638 | 191.2 | **1.116** | 1.103 |
| 100 m | 1.411 | 213.0 | 1.552 | 195.8 | **1.088** | 0.998 |
| 200 m | 1.368 | 216.5 | 1.445 | 211.5 | **1.023** | 0.987 |

The Kanektok is stable (212.8 → 216.5 cm/km across the whole sweep). **The Uyak is not** — it
climbs 181.7 → 211.5 as its short-wavelength sinuosity washes out. So the gradient advantage ranges
**1.02 to 1.23 purely as a function of an arbitrary smoothing parameter**, and the radial-frame ratio
even crosses below 1.0. That is not a publishable number.

**Why the two lines are not equally trustworthy.** The Kanektok line is an ADCP *longitudinal
thalweg run* — the boat was deliberately tracking the deep thread. The Uyak line is a hunter's boat
track, which may wander bank-to-bank within a ~30 m channel. Lateral excursions of 15–30 m survive
20 m simplification and inflate path length. The Uyak's excess sinuosity being concentrated at short
wavelengths is exactly the signature of wander rather than meandering.

**Consequences.**
1. **The "two sensors agree almost exactly" claim was a frame artifact.** The old 253 vs 252 and
   214 vs 218 compared DEM *along-channel* against SWOT *radial*, and only agreed because the SWOT
   centerline's sinuosity (~1.09) made the two frames nearly the same thing. In a matched radial
   frame the DEM channel bed runs **25–33 cm/km steeper** than the SWOT water surface — a real,
   explainable offset (bed vs water surface, single epoch vs 100+ passes, DSM canopy), but not the
   near-exact agreement previously recorded here and in `AVULSION_ANALYSIS.md`.
2. **The gradient advantage should be headlined from SWOT, not the DEM.** SWOT gives K 252.4 vs
   U 218.0 cm/km (ratio 1.158) and, pass-paired, **+25 cm/km positive in 41/42 passes** — multi-pass,
   stage-cancelling, and requiring no centerline at all. The DEM cannot match that precision.
3. **What the DEM does robustly show** survives and is worth keeping: near-bifurcation steepening in
   both channels far above the reach average, confirmed by an independent sensor; and the sinuosity
   contrast itself, which is a *qualitative* reinforcement — a more tortuous escape route has a
   gentler true gradient, so the sign of the advantage is supported even where the magnitude is not.
4. **`z_p05` replaces `z_min`** as the bed proxy (P2.2). It is more stable than the swath minimum and
   consistent with the arc method's P2 pick; the ratio varies less across proxies under the field
   lines (1.219–1.243) than under the SWOT lines (1.106–1.183).

**Resolved by P6 — see §1.5.**

### 1.5 P6 result — the gradient advantage is recovered, in a stated band — 2026-08-10

`DEM_Transects/build_dem_centerline.py` (new, tracked). Two methods were built; the first two
attempts failed for instructive reasons, and the third settled it.

**Attempt 1 — radial nodes at 50 m spacing. Reproduces the arc analysis exactly, but cannot measure
sinuosity.** The snap was re-run at 50 m radial spacing (621 radii) and validated against
`arcB_channels.parquet` on the 63 shared radii: **|ΔWSE| median 0.000 m, p90 0.038 m; |Δposition|
median 0.6 m.** So the reimplementation is faithful. But path length in this frame is meaningless:
the prior lookup takes the globally-nearest centerline vertex by radius, and where the channel
meanders, radius is not monotonic, so consecutive radii select vertices on *different meander limbs*
— adjacent-radius jumps exceed 100 m on **9.5 % (Kanektok) / 16.5 % (Uyak)** of steps, worst cases
near 1 km. The path zigzags, so its length is a wild **over**-estimate. Sinuosity is therefore not
reported from this frame. It is kept for what it is good at: a validated 50 m-resolution channel
water-surface profile, epoch-consistent with the DEM, plus fine-grained migration QC.

**Attempt 2 — snap the field line perpendicular to the DEM channel. Fails, and the reason is a hard
limit.** Walking the field line in its own order and snapping each 10 m station to the DEM channel
low did *not* remove the wander: `corr(snap offset, guide wander)` is **−0.37 (Kanektok) and +0.00
(Uyak)**. The arithmetic says why. The wander to be removed has a standard deviation of only
**2.1 m (Kanektok) / 5.0 m (Uyak)**, while the DEM's channel-location scatter is **43 / 35 m**. You
cannot measure a 5 m path perturbation with an instrument whose channel-position noise is 35 m. **The
DEM cannot arbitrate the wander at all** — a genuine limit, not a tuning problem, and worth stating
in the write-up.

**Attempt 3 — band-limited smoothing. This is the answer.** Since the DEM cannot verify the sub-100 m
content, remove it on physical grounds: boxcar-smooth the centerline at a stated window, above the
wander band (2–5 m amplitude at ~100 m wavelength) and below the meander band a 30–50 m channel
should have (~10–14 channel widths → 300–500 m), and re-parameterise arc length along the smoothed
path. Boxcar, **not** Douglas–Peucker — DP with a 200 m tolerance deletes real meanders (amplitude
~100 m) along with the wander, which is exactly why the earlier DP sweep looked unstable.

| smooth | K sin | U sin | U/K sin | **K along** | **U along** | **K/U along** | K/U radial |
|---|---|---|---|---|---|---|---|
| 0 m | 1.480 | 1.789 | 1.209 | 216.3 | 174.5 | 1.240 | 1.074 |
| 50 m | 1.475 | 1.731 | 1.174 | 219.5 | 190.4 | **1.153** | 1.100 |
| **100 m** | 1.463 | 1.652 | 1.130 | **213.2** | **187.8** | **1.135** | 1.166 |
| 200 m | 1.426 | 1.529 | 1.073 | 216.0 | 191.6 | **1.127** | 1.131 |
| 400 m | 1.340 | 1.368 | 1.021 | 217.4 | 205.8 | 1.056 | 0.990 |

Three things fall out:
1. **The Kanektok is rock-solid: 213–220 cm/km across the entire sweep**, smoothing-independent.
2. **In the defensible 50–200 m band the ratio is tight — 1.153 / 1.135 / 1.127** — where the raw and
   DP-mangled versions ranged 1.02–1.24. Only at 400 m, which starts eating real meanders, does it
   fall away.
3. **That band agrees with SWOT's independent, centerline-free 1.158.** This is a real two-sensor
   convergence, earned in a declared band — unlike the earlier 253-vs-252 coincidence (§1.4), which
   only agreed because a chord-cutting centerline made two different frames look alike.

**So the gradient advantage is quotable after all: ~1.13–1.15 along-channel, corroborating SWOT's
1.158.** Report it with the band stated and the sensitivity table alongside, never as a bare number.
The radial frame stays unstable (1.07–1.17, crossing below 1.0 at 400 m), confirming it is the wrong
frame for a sinuous channel.

**The Uyak is also genuinely the more sinuous channel** — U/K sinuosity 1.07–1.17 through the band,
not the 1.21 the raw track claimed but real. So the escape route is the longer path for the same drop,
which reinforces the conclusion qualitatively as well as numerically.

**Epoch consistency (the temporal point).** Two checks make the cross-epoch comparison defensible
rather than assumed. (i) Method 1 measures the DEM channel sitting a median **36 m (Kanektok) / 10 m
(Uyak)** from the 2026 field line — well inside the ±80 m sampling swath, so the bed proxy captures
the channel even where it has shifted, and a 10–40 m lateral discrepancy is negligible in along-channel
distance over 0.5 km windows. (ii) Comparing a 2010–2021 DEM gradient against a 2023–2026 SWOT
gradient assumes the gradient is temporally stable, which the temporal analysis and the paired
slope work independently support (advantage positive in 41/42 passes, steady per year). **State that
assumption explicitly rather than letting the agreement imply it.**

Plus the negative result that motivated Phase 2: applying the fine-scale estimator to Stream A's
corridor median gives Uyak **257.8 cm/km** against SWOT's **218.0** — wrong by ~40 cm/km, and
nearly identical to the Kanektok's, because both are the shared valley surface. Phase 2's
channel-specific sampling closes that gap to 4 cm/km. This belongs in the write-up as a
methodological result, not hidden.

---

## 2. Revised write-up outline

Changes from `DEM_outline.pdf` are marked **[NEW]**, **[CHANGED]**, **[CUT]**.

### 1. Introduction
- Background: floodplain topography as a control on avulsion.
- Research gap: water-surface measurement (SWOT) alone cannot resolve whether a channel is
  *perched*; that is a topographic question requiring a continuous surface model.
- Objective **[CHANGED]**: not just "extract profiles" — *test whether the Kanektok is
  superelevated relative to the floodplain it would spill into, and whether it holds a gradient
  advantage over the Uyak escape route.* Two testable propositions, both from Gearon's framework.

### 2. Methodology
- **2.1 Two extraction paths [CHANGED]** — the §1 table. Both the 10 m GEE corridor export *and*
  the native 2 m PGC S3 read. State explicitly what each can and cannot resolve.
- **2.2 Spatial normalization** — radial `dist_km` from the shared anchor; note this is the fan/delta
  convention (Williams 2006; Edmonds 2011) and shared verbatim with the SWOT analysis (Δ = 0).
- **2.3 Vertical datum [CHANGED]** — WGS84 ellipsoidal → EGM2008. The geoid is **per radius**
  (13.74 → 13.28 m), taken from the same per-pixel NASA EGM2008 values used inside SWOT's own
  `wse = height − geoid − tides`, so the datasets align by construction. A constant offset is
  datum-invariant *within* an arc but tilts DEM-vs-SWOT comparison by ~0.5 m over the reach.
- **2.4 Corridor aggregation and DSM nuances [CHANGED]** — 0.5 km binned medians; **state plainly
  that this is a floodplain/valley surface, per §1.1, with the +0.19 m cross-check**. Vegetation:
  raw DSM retained, with the justification from §2.7.
- **2.5 Arc cross-sections and the superelevation measurement [NEW — the core methods section]**
  - iso-distance-from-anchor arcs, 3–34.5 km at 0.5 km, sampled at native 2 m along-arc.
  - Field centerlines as *priors only*: Uyak from hunter boat-GPS, Kanektok from boat-ADCP Day-03
    thalweg run; channel located by snapping to the DEM low within ±75 m.
  - Channel water surface = P2 in a ±50 m window on the snapped thalweg (ArcticDEM images water
    surface, not bed).
  - Floodplain reference = median terrain of the corridor strictly between the channels, ±250 m
    notches excluded (median width 2 696 m).
  - **Bed = survey-stage water surface − boat-ADCP thalweg depth.** SWOT overflew 2026-05-28/05-30
    inside the 05-28→06-03 survey window, so depth and stage are contemporaneous.
  - β = H_AR/H_M = (crest − floodplain)/(crest − bed); identical to the prior ArcGIS
    (P98 − median)/(P98 − P2), which is why it is reported.
  - **Crest window set by the bankfull check**, ±150 m (§3.4).
- **2.6 Channel-specific longitudinal sampling [NEW]** — 20 m stations along each field centerline,
  ±80 m perpendicular swath, low-percentile bed proxy; radial **and** along-channel frames;
  sliding Theil–Sen at 0.5 km, the same estimator as SWOT Fig 9.
- **2.7 DEM quality: LiDAR validation and the vegetation question [CHANGED — was 2.6]**
  - vs NOAA 2024 QL1 LiDAR: **RMSE 0.51 m at 10 m, 0.55 m at native 2 m**, bare-ground RMSE 0.165 m
    (10 m). Quote the 2 m number where the arc analysis is concerned — that is the raster it uses.
  - Vegetation inflation is real but localized: ~4 % of pixels, +0.83 m where present.
  - **Every filter tested degrades the DEM**; NDVI-gated variants delete real fluvial relief because
    levees and cutbanks are themselves locally high *and* vegetated. NLCD class 41 reads −0.30 m vs
    LiDAR, i.e. not inflated. **Decision: keep raw, document the uncertainty.**
  - Coverage caveat: the LiDAR strip is ~17 % of the Kanektok and **0 % of the Uyak**.
- **2.8 Stage, epoch, and migration — three honest caveats [NEW]**
  - The mosaic is a **2010-10-03 → 2021-03-02 blend**, and it caught the Kanektok near the **29th**
    percentile of observed stages and the Uyak near the **76th** — a ~0.34 m differential bias
    pointing exactly the way that inflates "Uyak higher." Hence inter-river difference is taken from
    **pass-paired SWOT**, not from the DEM.
  - A river has no single water surface: p10–p90 spans ~0.7 m at fixed radius. Superelevation is
    quoted at the median observed stage with that band carried alongside.
  - Field lines are 2026, DEM is 2010–2021: snap offsets median **38 m / 12 m**, at the ±75 m wall on
    **9 % / 8 %** of arcs. WSE is insensitive (0.00 m from ±75 → ±400 m); channel *position* is not.
- **2.9 Coastal trim [NEW]** — all DEM figures cut at **34 km**. Beyond that the radial frame
  compares a Kanektok already at the coast against a Uyak still inland (the −3 m spurious spike).

### 3. Results
- **3.1 The valley profile and its concavity [CHANGED — was 3.1]** — ~72 m to sea level over ~36 km;
  concave-up (Hack 1957; Flint 1974). Framed as the *shared valley*, per §1.1. **[CUT]** the
  per-river distinction and the "Kanektok plots lower" claim.
- **3.2 Superelevation: is the Kanektok perched? [NEW — the headline result]** — −1.50 m on 100 % of
  arcs; Uyak −0.49 m; still −1.01 m at high stage.
- **3.3 The superelevation ratio β [NEW]** — 0.06, H_AR +0.14 m, β ≤ 0 on 38 %. Reported as the
  reproduction of the ArcGIS metric. **No alluvial ridge exists to superelevate.**
- **3.4 Crest-window sensitivity and the bankfull check [NEW]** — β never plateaus (−0.16 → 0.28
  across ±75 → ±500 m) and the crest pixel tracks the window boundary (57 → 292 m): the signature
  of no local maximum. Freeboard ÷ depth reaches **1.87** at ±350 m — a bank the river could never
  overtop. ±150 m is the bankfull-consistent choice.
- **3.5 Channel gradient and sinuosity [CHANGED per §1.5]** — Kanektok along-channel bed gradient
  **213–220 cm/km** (smoothing-independent); Uyak **188–192** in the 50–200 m band; advantage
  **1.13–1.15**, converging with SWOT's independent centerline-free **1.158**. Report with the band
  stated and the sensitivity table. Add: the Uyak is the **more sinuous** channel (U/K 1.07–1.17), so
  the escape route is the longer path for the same drop; and the methodological limit that the DEM
  cannot arbitrate sub-10 m centerline error because its own channel-location scatter is 35–43 m.
  Note the radial frame is unstable for sinuous channels (ratio 1.07–1.17, crossing below 1.0) and is
  used only for the matched-frame SWOT comparison.
- **3.6 Channel depth [NEW]** — 1.22 m median, quasi-uniform; Kanektok 1.26× deeper at the mouth.
- **3.7 Two-sensor agreement [NEW]** — DEM channel water surface within 0.15 m of SWOT median stage;
  DEM along-channel bed slope within 1–4 cm/km of SWOT water slope. Includes the Stream-A negative
  result (Uyak 257.8 vs 218.0) as evidence that the agreement is earned by the sampling geometry,
  not assumed.
- **[CUT] 3.3 Localized Terrain Elevation Difference** and **[CUT] 3.4 Detrended Residuals** as
  standalone results — both fail §1.2. The detrend survives only as a methods-limitation panel.

### 4. Discussion
- **4.1 Topographic barriers to avulsion [CHANGED]** — build on Gearon's **βγ ≥ Λ** (Λ median 2.1,
  range 0.2–11), not on a β = 1 threshold. State that γ is deliberately not evaluated, so β alone is
  not a pass/fail. Slingerland & Smith (1998) cited for perched-channel *preconditions*, which is
  what it actually establishes.
- **4.2 Synthesis of hydrodynamic and topographic evidence [CHANGED]** — replace the assertion with
  the four quantitative agreements from §3.7 and the three-method concurrence on Uyak-above-Kanektok
  (arcs +1.45 m, pass-paired SWOT +0.96 m, Phase-2 profiles ~+1 m).
- **4.3 Why corridor-wide statistics cannot answer a channel-scale question [NEW]** — generalize
  §1.1/§1.2 into a transferable methodological point. This is a real contribution: it is the reason
  the preliminary analysis over-read superelevation, in a second guise.
- **4.4 Limitations [CHANGED]** — radial vs sinuous flow path (Merwade 2006); DSM images water, not
  bed; vegetation localized and Uyak-unvalidated; multi-date mosaic stage and epoch; crest read along
  a slightly oblique arc; corridor reference is broad (~2.7 km); no γ, no Uyak depth model.

### 5. Conclusions
Terrain-enforced stability. The Kanektok is **incised, not perched**, on every arc; it has **no
alluvial ridge**; and it holds an **18 % gradient advantage** over the escape route — so there is no
gradient-driven push to avulse. The prior β ≈ 0.96 / "30 % perched" reading was diagonal-transect
geometry. State the null result plainly and as a strength: it is consistent across three independent
datasets (2 m DEM, boat ADCP, SWOT).

---

## 3. Figure plan

**Numbering & layout — decided 2026-08-10.** The DEM and SWOT write-ups are separate documents, so
they get **separate figure series in separate folders**. DEM figures are **D1–D7 + A1–A2**; the SWOT
series keeps `figure_01…09` untouched.

```
thesis_figures/
  config.py               # shared style; gains SWOT_OUTPUT_DIR + DEM_OUTPUT_DIR
  core.py                 # SWOT computations (unchanged)
  dem_core.py             # NEW — DEM computations (arcs, channel slope, corridor, depth, LiDAR)
  make_figures.py         # SWOT builders  → output/SWOT_Figures/figure_01…09
  make_dem_figures.py     # NEW — DEM builders → output/DEM_Figures/figure_D1…D7, A1, A2
  captions/SWOT_Figures/  # existing captions move here
  captions/DEM_Figures/   # new
  output/SWOT_Figures/
  output/DEM_Figures/
```

Style stays shared and single-source (`config.apply_style`, `savefig`) so the two series remain
visually consistent — same serif type, same river colours, same dimensions. Only the numbering,
output folder, and caption folder split. `savefig` gains a subdirectory argument; moving the existing
SWOT outputs is a path change to audit for references before it lands.

Every figure builds through `thesis_figures/` — `config.apply_style()`, `savefig()`, 6.5 in text width, serif,
Wong/dashboard colours (Kanektok firebrick, Uyak dodgerblue), PDF + 300 dpi PNG, coast left / anchor
right, bifurcation dashed at 2.493 km, **x cut at 34 km**.

**Scope narrowed — decided 2026-08-11.** This is the DEM-only write-up. The DEM↔SWOT *comparison*
("does the water slope agree with the terrain slope?") moves to a later document. SWOT stays in this
one only as **instrumentation** — per-arc geoid, stage distribution, and the survey-stage bed that β
is defined against — never as an independent sensor to be cross-checked. That kills the old D6 and
A2 outright, and with them the along-channel frame, the sinuosity correction, and the whole
path-length problem (§1.4). Net: **6 main + 2 appendix**, and almost every panel already exists as a
script or PNG, so this is a presentation job, not new analysis.

| # | Figure | Panels | Data | Prereq | Status |
|---|---|---|---|---|---|
| **D1** | Study area, centerlines & arc geometry | 2 | 10 m DEM + basemap + `arcB_channels` | — | ✅ **DONE 2026-08-11** |
| **D2** | Valley long profile & concavity (corridor) | 2–3 | Stream A | — | next |
| **D3** | **Arc cross-sections with β anatomy** ← flagship | 4 | `arcB_profiles.parquet` | — | |
| **D4** | Superelevation, β and H_AR/H_M vs radius | 3 | `arcB_channels.parquet` | — | |
| **D5** | Valley terrain slope | 1–2 | Stream A | — | |
| **D6** | ADCP channel depth *(was D7)* | 2 | depth parquets | — | |
| **A1** | ArcticDEM vs LiDAR & why no filter | 3 | veg-filter outputs | P3 | |
| **A2** | Crest-window sweep & bankfull check *(was D5)* | 2 | new sweep artifact | **P1** | |

**Cut 2026-08-11:** channel bed slope DEM vs SWOT (→ comparison write-up); sinuosity / frame validity
(machinery no longer needed). P2.4 and P6 outputs are retained in-repo but are not cited by any
figure in this document.

### D1 as built — variant D, locked 2026-08-11

Four variants were rendered for selection (A satellite-minimal, B satellite+corridor, C topographic,
D two-panel). **D chosen**, with A/B/C kept on disk to show the professor alongside it.

- `(a)` Esri imagery + field centerlines + corridor polygons + anchor/bifurcation + Alaska locator.
- `(b)` 10 m ArcticDEM as hillshade + hypsometric tint + arc fan + DEM-located thalweg points.
- Both panels share one extent (`_dem_extent`, the DEM footprint) and are pixel-aligned; `_map_layout`
  solves the figure height so equal-aspect axes fill their slots instead of floating in white bands.
- Verified numbers now in the caption: corridor areas 54.3 / 66.8 km², mean width ≈1.1 km
  (area ÷ enclosed centerline length — state the definition, the three plausible ones give 1.1 / 1.55
  / 1.86 km), overlap 2.33 km², channels 30–50 m.
- Survey epochs: **Uyak centerline 2025, Kanektok 2026**; ArcticDEM v4.1 mosaic 2010–2021.

**Cartographic conventions established here, inherited by every later map figure** (all in
`make_figures.py` so both series share them):

- `_locator_inset` marks the study area as a **point, not an extent box**. The old box enforced a
  minimum on-screen size and drew 132 × 168 km for a 37 × 13 km map — 46× too large by area. The
  SWOT Figure 1 had the same defect; both are fixed and `figure_01_caption.txt` was amended, since it
  described a "white box" that no longer exists.
- Point is placed at the centre of the mapped extent, not the anchor (which sits ~18 km off centre).
- `_mercator_scalebar` and `_north_arrow` take a `stroke` argument. Dark ink needs a white halo on
  pale topography; the imagery default (black stroke) draws black-on-black and renders a blob.
- Hypsometric ramp is `terrain` **truncated to its land portion** (`HYPSO`). The full ramp starts in
  deep blue and renders the near-sea-level coastal plain as though inundated.
- Radius labels ride each arc's lowest in-view point. A fixed bearing throws the long-radius labels
  off the map, because the sector's northern limb exits the frame well before 30 km.

### D1 — Study area, centerlines and arc geometry
*Merges original Fig 1 with the arcs-and-centerlines idea from your note.*
Single panel, ESRI satellite basemap. Layers: both field centerlines (firebrick / dodgerblue);
every 4th arc drawn as a thin grey trace with radius labels at 5, 10, 20, 30 km; anchor ★;
bifurcation ○; both corridor polygons as faint outlines; NOAA LiDAR strip footprint hatched (makes
the 17 %/0 % coverage caveat visual); Quinhagak labelled. North icon + scalebar via the existing
`_north_arrow` / `_mercator_scalebar` helpers.
**Takeaway:** establishes the geometry *and* documents that the arcs are the measurement frame.
**Source:** `make_figures.build_fig1` machinery + `data/transect_map_overlay.geojson`.

### D2 — Valley profile and channel long profiles
*Replaces original Figs 2, 4 and 5 with one honest figure.*
- (a) Absolute elevation, 0–34 km: Stream A corridor median as a single grey **valley** band
  (pooled, with the p25–p75 corridor spread), plus the two channel bed profiles from Phase 2 in
  river colours. Concavity annotated (2nd-order fit R², Hack/Flint) rather than plotted as three
  competing trend lines.
- (b) Channel difference, own y-axis at ±3 m: Uyak − Kanektok channel elevation. **This is where a
  1 m signal becomes visible** — the failure mode of original Fig 2.
- (c) Corridor difference, same ±3 m scale: Kanektok − Uyak corridor median, with the ±1 m envelope
  shaded and a note that this is the floodplain, not the channels.
**Takeaway:** the valley is smooth and concave and the two corridors are the same surface to ~±1 m;
the *channels* separate by ~1 m with the Uyak consistently higher. Panels (b) and (c) side by side
make the Stream A / Stream B distinction self-evident to a reader.

### D3 — Arc cross-sections with the β anatomy  ← flagship
2×2 panels at four radii spanning the reach: one just below the bifurcation (~4 km), two mid-reach
(~12, ~20 km), one downstream (~30 km). Each panel: x re-centred on the Kanektok (x = 0, increasing
toward the Uyak, so it reads "stand in the channel, walk the spill path"); 2 m terrain trace;
Kanektok bed ▼, ridge crest ▲, floodplain reference as a horizontal dashed line; **H_M** measure bar
(crest→bed) and **H_AR** bar (crest→floodplain) with β labelled at the crest; Uyak water surface
marked at its ~3 km offset; SWOT p10–p90 stage band on each channel; ±250 m corridor-exclusion
notches shaded.
**Takeaway:** the section *is* the measurement — a reader sees H_AR ≈ 0 directly, and sees the
Kanektok water surface sitting below the floodplain line.
**Source:** `build_arc_B._sections_fig`, upgraded to thesis style.

### D4 — Superelevation and β vs radius
- (a) Superelevation (channel water surface − floodplain reference) vs radius, both rivers, with
  p10–p90 stage bands and a zero line. Annotate "Kanektok below floodplain on 100 % of arcs".
- (b) β vs radius with a β = 0 reference line; shade β ≤ 0; annotate median 0.06 and the 38 %.
- (c) H_AR and H_M vs radius, to show H_M is carried by channel depth while H_AR hovers at zero.
**Takeaway:** the decisive avulsion panel. Not "β is under a threshold" but "there is no ridge."
**Source:** `_sidebyside_fig` + `_beta_fig`.

### D5 — Crest-window sweep and the bankfull check
- (a) Twin y-axes vs crest half-window (±60 → ±500 m): β and H_AR on the left, mean crest-pixel
  distance from the thalweg on the right. The crest distance tracking the window boundary
  (57 → 292 m) is the visual proof of no local maximum.
- (b) Freeboard ÷ depth vs the same x, with a horizontal line at 1.0 (bankfull) and the ADCP median
  depth annotated. Mark the adopted ±150 m and the rejected ±350 m.
**Takeaway:** defends the β 0.24 → 0.06 correction and pre-empts "why this window?" — the reviewer
question this analysis is most exposed to.
**Prereq P1** — the sweep must be re-run to emit a plottable artifact.

### D6 — Channel bed slope: DEM vs SWOT  *(restructured per §1.4)*
The original design headlined an along-channel K/U ratio that did not survive testing. Rebuilt to
show only what is robust, and to make the frame problem visible rather than hidden.
- (a)/(b) **Matched radial frame, one panel per river:** SWOT fine-scale water slope (median + IQR
  band, Fig-9 method) with the DEM channel bed slope (`z_p05`, field centerline) overplotted in
  near-black, and the reach-average reference (195.4 / 191.7 cm/km) dashed. Annotate the near-bif
  steepening and the +25 to +33 cm/km DEM−SWOT offset with its explanation. **This is the honest
  two-sensor panel:** same frame, real offset, stated cause.
- (c) **Band-limited along-channel panel (per §1.5):** K/U along-channel ratio vs centerline
  smoothing window, with SWOT's centerline-free 1.158 as a horizontal reference and the defensible
  50–200 m band shaded. Shows the Kanektok flat at 213–220 cm/km, the ratio settling at 1.13–1.15
  inside the band, and the fall-off past 400 m where smoothing starts eating real meanders.
**Takeaway:** two sensors converge on the gradient advantage — DEM 1.13–1.15, SWOT 1.158 — with the
band stated. Panel (c) is what makes that a measurement rather than a coincidence, and it doubles as
the honest record of how sensitive the number is.
**Source:** rewritten Phase 2 on the band-limited method. **Prereq P2.**

### D7 — ADCP channel depth
- (a) Kanektok thalweg depth vs radius: 0.5 km binned median + p10–p90 band, 39.5 k pings, gentle
  downstream deepening annotated.
- (b) Mouth reach (31–33 km) Kanektok vs Uyak depth distributions as paired violins or box plots,
  annotated 1.37 vs 1.08 m, **1.26×**.
**Takeaway:** supplies the H_M term independently of the DEM, and shows the subordinate distributary
is also the shallower one.
**Source:** `adcp_depth_stats.py`.

### A1 — ArcticDEM vs LiDAR, and why no filter was applied (appendix)
- (a) Residual histogram (ArcticDEM − LiDAR) with RMSE and bias annotated, bare vs vegetated
  stratification overlaid.
- (b) Per-NLCD-class mean residual as a horizontal bar chart, showing class 41 at −0.30 m — i.e. the
  suspected culprit is not inflated.
- (c) Filter sweep: overall RMSE vs window for median / p10 / p20 / gated, with the raw baseline as a
  horizontal line, showing every deployable configuration sits above it.
**Takeaway:** the DEM is fit for purpose at 0.5 m, the vegetation question was tested properly, and
"keep raw" is a measured decision. **Prereq P3.**

### A2 — Sinuosity and frame validity (appendix)
- (a) Along-channel vs radial distance for both rivers with the 1:1 line; sinuosity 1.087 / 1.085
  annotated; note the ~1:1 agreement over the first 11 km.
- (b) Bearing-from-anchor vs radius for both channels, showing the ~20° drift but steady 10–15°
  separation.
**Takeaway:** defends the radial frame where it is used and quantifies where it distorts
(Merwade 2006). Cheap, and it closes the obvious methodological objection to D2/D4.
**Source:** Phase 2 fig3 + `_validity_fig`.

### Cut, and why
- **Detrended profile** — as a result. The arc analysis deliberately uses no detrend, because
  matched-radius comparison already removes the down-valley gradient, which is the correct route.
  Detrending corridor medians and reading the residual as "structural entrenchment" is a softer
  version of the diagonal-transect artifact `AVULSION_ANALYSIS.md` §3 warns about. *If* the professor
  wants it retained, it becomes a single limitation panel titled "why corridor detrending cannot
  separate the channels", showing the 63 % / 53 % sign split.
- **Terrain slope (original Fig 3)** as a standalone — superseded by D6, which is channel-specific,
  per-pass, and resolution-honest. The σ = 1.5 km corridor derivative can appear inside A1 or D2 as
  context, but must not carry a "no knickpoints" claim.

---

## 4. Analysis work required before figures (prerequisites)

### P1 — Crest-window sweep artifact  → D5
New `DEM_Transects/crest_window_sweep.py`: re-run the arc crest extraction over half-windows
{60, 75, 100, 150, 250, 350, 500} m, emitting per-window median β, H_AR, H_M, crest-offset distance,
and freeboard ÷ depth to `data/crest_window_sweep.parquet`. Must reproduce the values already
recorded in `AVULSION_ANALYSIS.md` §4 (β −0.16 / 0.06 / 0.21 / 0.24 / 0.28; A/B 0.66 / 1.02 / 1.27 /
1.72 / 1.87) — treat any mismatch as a bug to resolve before plotting.

### P2 — Promote Phase 2 from exploratory to production  → D2, D6, A2
**P2.1 (centerline switch) is DONE — run 2026-08-10, findings in §1.4.** Field centerlines confirmed
as the correct source; the ratio it produced was then withdrawn as non-robust. Remaining:
1. ~~Switch to the official field centerlines~~ — **done**. Reproject to EPSG:32604 before any
   `interpolate`/`length` call (field lines ship as EPSG:4326, so `line.length` is otherwise in
   degrees); simplify at 20 m to strip GPS jitter without touching meanders (<2 % length change).
2. **`z_min` → `z_p05`** as the bed proxy — **decided** (§1.4 item 4). More stable than the swath
   minimum, consistent with the arc method's P2 pick.
3. **Constant `GEOID = 13.46`** — harmless for slope (<2 cm/km) but should use the per-radius geoid
   for the elevation panels in D2, and the code should say which quantity tolerates which.
4. Rewrite as a tracked script emitting committed per-station artifacts, so D2/D6/A2 are reproducible
   from tracked data. Keep the sinuosity-sensitivity sweep in the artifact — D6 panel (c) needs it.

### P3 — LiDAR validation artifact  → A1
The residual statistics currently live only in `dem_veg_filter/FINDINGS.md` prose and
`outputs/filter_results.csv`. Emit a compact tracked parquet holding the residual histogram bins,
the per-NLCD-class means, and the filter sweep, so A1 does not require the 49 MB LiDAR raster at
figure-build time.

### P4 — Coastal trim, applied consistently
Adopt `DEM_XMAX_KM = 34.0` as a module constant (matching `FINE_XMAX_KM`) and apply it to every DEM
figure and to the dashboard's DEM tabs. Document it in §2.9 rather than silently truncating.

### P6 — DEM-derived centerline  → D6 panel (c), §3.5  ✅ **DONE 2026-08-10**
`DEM_Transects/build_dem_centerline.py`, results in §1.5. Outcome: the DEM **cannot** arbitrate the boat
wander (its channel-location scatter is 35–43 m against a 2–5 m wander), so the resolution is
band-limited boxcar smoothing at 50–200 m, which recovers a stable along-channel advantage of
**1.13–1.15**, agreeing with SWOT's independent 1.158. Artifacts: `data/dem_centerline_nodes.parquet`
(621 radii, validated against arcB to |ΔWSE| median 0.000 m) and `data/dem_centerline_snapped.parquet`.
Follow-on folded into P2.4: the production channel-slope script must use the **band-limited boxcar**
method with arc length re-parameterised along the smoothed path — not raw and not Douglas–Peucker.

### P5 — Verification note
Following the SWOT precedent (`thesis_figures/captions/RESULTS_VERIFICATION.md`): every number
quoted in a DEM caption gets recomputed from the tracked artifacts by a smoke check, so caption and
figure cannot drift.

---

## 5. Dashboard changes implied

Deliberately deferred until the figures settle, then applied so the dashboard and thesis agree.

1. **Terrain Profile / Elevation Difference / Detrended tabs** — relabel from "river" to
   **valley / corridor**, and add the §1.1 explanation that these are floodplain-wide medians ~1.5 km
   across. The Elevation Difference tab's help text currently invites the perched reading
   ("when one river sits higher… gravity gives its water a reason to spill over") on a series whose
   median is −0.17 m; it should point to the Cross-Sections tab for the channel-scale answer.
2. **Terrain Slope tab** — state the effective resolution (σ = 3 bins = 1.5 km) and drop any
   implication that absent structure means absent knickpoints.
3. **Coastal trim** at 34 km (P4), removing the −3 m spurious spike now visible in the difference tab.
4. **Optional: a channel-slope view** in the Cross-Sections tab or a new subtab, exposing the Phase-2
   DEM-vs-SWOT comparison — currently the strongest DEM result with no dashboard presence.

---

## 6. Open questions

**Q1 — Figure numbering. RESOLVED 2026-08-10:** own D-series, own `DEM_Figures/` folder, shared style.
See §3 for the layout.

**Q4 — Phase-2 centerline switch. RESOLVED 2026-08-10:** run first, as agreed. See §1.4 — it confirmed
the field centerlines are correct and withdrew the K/U ratio as non-robust. Follow-on work is P6.

**Q2 — How much Stream A survives.** The plan keeps it as §3.1 regional context with one panel of
D2, on the grounds that it *is* the valley profile and independently corroborates the arc floodplain
reference to +0.19 m. The alternative is cutting it to a methods paragraph. Five dashboard tabs
currently rest on it.

**Q3 — Does the professor need the original Figures 4 and 5 addressed explicitly?** They have seen
those tabs, and the preliminary analysis they came from. Options: retire silently, or make the
corridor-vs-channel distinction an explicit methodological contribution (§4.3 + D2 panels b/c). The
second is more defensible and turns a correction into a result, but it does put the earlier reading
in the write-up.

**Q6 — Does the withdrawn agreement need correcting upstream? [NEW]** §1.4 item 1 means
`AVULSION_ANALYSIS.md` and `project_slope_reanalysis` memory both record a "strong 2-sensor
validation — Kanektok 253 vs 252, Uyak 214 vs 218" that was a frame artifact. Those need amending.
Note this does **not** touch the arc analysis's own DEM↔SWOT validation (−0.15 / +0.14 m on *water
surface elevation*), which is measured in a single matched frame and stands.

**Q5 — γ.** Currently not evaluated, and `AVULSION_ANALYSIS.md` explains why (the corridor-median
floodplain has no location, so S_AR has no defensible run length). Worth a short subsection stating
that explicitly, since a reader who knows Gearon will ask why βγ is not computed.
