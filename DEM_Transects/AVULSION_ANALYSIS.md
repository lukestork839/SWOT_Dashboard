# DEM Transect Avulsion Analysis — Methods, Results & Caveats

**Rivers:** Kanektok River & Uyak Creek (near Quinhagak, Alaska)
**DEM:** ArcticDEM **v4.1, native 2 m mosaic** (`batch_outputs/arcticdem_rivers_2m.tif`, EPSG:3413), geoid-corrected to EGM2008 **per radius** (13.74 m at the anchor → 13.28 m at the coast; the earlier constant 13.46 m is fine for within-arc differences, which are datum-invariant, but tilts DEM-vs-SWOT comparisons by ~0.5 m over the reach). The mosaic is a **multi-date blend of 2010-10-03 → 2021-03-02 imagery** (PGC STAC), which matters for both channel migration and stage — see §4.
**Shared anchor (dist origin):** `59.82463509, -161.33397834` — the upstream divergence point; distance-from-anchor increases downstream toward the coast. This is the **same anchor the SWOT dashboard uses** (verified identical: Δdist_km = 0), so DEM and SWOT share one longitudinal axis.
**Last updated:** 2026-08-08.

---

## 1. Purpose

Reproduce — and, where necessary, correct — the prior ArcGIS DEM-transect **superelevation (β)** analysis of the Kanektok, on the higher-resolution 2 m ArcticDEM, and put both rivers on a common frame so the DEM story can be checked against the SWOT water-surface story.

**Superelevation β**, per cross-section:

```
P98    = alluvial-ridge crest        (98th percentile of elevation in the near-channel band)
P2     = channel bed                 (2nd percentile in the near-channel band)
median = floodplain reference        (median elevation in the floodplain band)
H_AR   = P98 - median   (ridge height above floodplain)
Hm     = P98 - P2       (total bank relief, bed to crest)
beta   = H_AR / Hm      (fraction of bank relief that is ridge standing above floodplain)
```

β → 0: ridge ≈ floodplain (not perched). β → 1: floodplain ≈ bed (strongly perched, avulsion-prone).

---

## 2. The prior ArcGIS method, recovered

The original workflow (`~/Downloads/V6…ipynb`) drew a **straight guide line** down the Kanektok, hung **parallel** transects off it, and used **two clip zones** — a near-channel `River_Elevation` zone (→ P98, P2) and a broad `Total_Elevation` zone (→ median).

We recovered the intended result directly from the intact elevation-point layers in the project geodatabase (`clean_and_complete.gdb`; the notebook run that would have saved β to `Avulsion_Lines_2` had errored, leaving those columns empty). The recovered table is committed at `reference/original_beta.parquet` and can be rebuilt from the gdb with `recover_original_beta.py`:

> **Recovered original:** β median **0.96**, H_AR median **4.30 m**, ~30 % of transects "perched" (β > 1).

This looked like a strongly perched Kanektok. **It is largely an artifact** (§3).

---

## 3. The diagonal-transect artifact (why the original over-read superelevation)

The straight guide line is not aligned with the true flow/valley axis, so its parallel transects run **diagonally** across the valley. Measured against the shared anchor:

- Each transect connects a Kanektok point to a Uyak point **4–6 km further downstream**.
- The regional down-valley gradient (~**1.83 m/km**) over that 4–6 km offset predicts an **8–11 m** drop — which **equals essentially the entire observed "Kanektok-above-Uyak" drop**.
- Removing the regional elevation-vs-distance trend collapses the cross-valley difference to **±1–2 m, with inconsistent sign** — i.e. no systematic superelevation.

**Independent check:** the SWOT dashboard, comparing the rivers at *matched* distance-from-anchor, finds the **Uyak marginally _higher_** (+0.19 m median). The diagonal transect pointed the opposite way — a geometry artifact, not a signal. Extending the floodplain zone all the way to the low Uyak inflated it further (a naive rebuild gave β ≈ 2.9, 99 % "perched").

**Lesson (recorded):** the down-valley gradient must be removed — here by comparing at **matched downstream distance** along iso-anchor arcs (§4). *(An earlier perpendicular-to-channel superelevation method, "Approach A" — Gearon-standard β from ⟂ transects — gave a consistent modest-levee result, β ≈ 0.41, but has been retired now that the arc method is the accurate, field-centerline-based approach; it lives in git history if needed.)*

---

## 4. The arc method — radial "iso-distance-from-anchor" cross-sections

Each transect is the **arc of points at a constant straight-line distance (radius) from the shared anchor**, so every point is at the same "downstream" coordinate the SWOT dashboard uses. An arc spans **Kanektok → floodplain → Uyak** in one cut, letting the two rivers be compared at a matched downstream position.

**Precedent:** the fan/delta convention of radial distance-from-apex as the longitudinal axis (Williams et al. 2006; Edmonds et al. 2011 radial swaths; Norini et al. 2016). Our anchor is effectively the shared divergence apex.

**Implementation** (`build_arc_B.py`): for radii 3–35 km (0.5 km steps), sample the 2 m DEM along the arc over the bearing sector spanning both rivers (~248–294°). Each channel is located by **snapping to the actual DEM channel**, not by trusting the centerline: the centerline serves only as a *prior*. Within a search window (clipped at the midpoint between the two channels so the picks can't cross-contaminate) the thalweg is the centroid of the deepest terrain; the channel **water-surface elevation** is then a low percentile in a tight ±50 m window on that thalweg. The arc is sampled at **2 m along-arc spacing — the native DEM resolution** (an earlier 10 m step skipped 4/5 of the pixels, blurring the floodplain, banks and ridge); at 2 m a ~30–50 m channel spans ~15–25 samples, so the pick genuinely resolves the water rather than leaning on a single lowest pixel. Because the channels are **narrow** (Uyak ~30 m, Kanektok ~50 m — both braided with a narrow main thread), the pick uses the **2nd percentile** (the deepest sliver = the water) for *both* the thalweg location and the water-surface value; a tight window plus P2 isolates the channel water rather than the surrounding bars/banks. *(This choice is not delicate: refining from 10 m/±100 m to 2 m/±50 m moved the water surfaces <0.1 m and the superelevations <0.1 m, and earlier tests showed the value stable to <0.25 m — below the DEM's ~0.5 m accuracy — across percentiles P2–P5 and windows ±30–250 m, because a low percentile self-selects the water regardless. The corridor exclusion stays wider, ±250 m, to keep the channel **and its banks** out of the floodplain reference.)* Both channels now use an **official field-surveyed centerline** (below) accurate to ~20–50 m, so both take the same **tight ±75 m** search half-width — it snaps to the DEM low (correcting residual GPS / DEM-date channel shift) with no room to wander onto nearby ponds and sloughs. The symmetric window also removes the last method asymmetry between the rivers (the Kanektok previously leaned on the smoother SWOT line behind a wide ±1200 m reach). ArcticDEM is a *surface* model — over a channel it images the water surface, not the true bed — so this quantity is directly comparable to the SWOT water surface.

**The Uyak centerline** (`data/uyak_centerline_official.gpkg`, built by `build_uyak_centerline.py`) is derived from **field boat-GPS tracks** a hunter ran down the Uyak (two onX exports, 2024 near-reach + 2023 far-reach) plus a hand sketch filling the one gap — a boat can only run where the channel is deep, so every trackpoint sits on the channel thread. The three sources are concatenated in along-channel order (no radial binning, which would collapse meanders running tangential to an arc), lightly de-jittered, and the 2023 track's far-end doubleback (the boat turned around and took another branch) is truncated at its turnaround. The result tracks every meander, unlike the SWOT line that cut straight chords ~500 m off the real channel. The per-arc prior takes the **nearest centerline crossing by radius** (not an interpolation across limbs), so meanders that swing tangentially to an arc still yield an on-channel prior.

**The Kanektok centerline** (`data/kanektok_centerline_official.gpkg`, built by `build_kanektok_centerline.py`) is derived from a **boat ADCP survey** our coworkers ran down the Kanektok (late May–early Jun 2026). Of the survey days, Day 03 is a single continuous **longitudinal thalweg run** (~1.9→34.4 km radius) — the same "boat rides the deep thread" logic as the Uyak, so it is treated identically: keep the longitudinal transects in along-channel order, light de-jitter, meanders preserved (the other days are discrete bank-to-bank *discharge* crossings, excluded from the centerline). Versus the old SWOT prior it agrees at reach scale (**median offset ~56 m**) but resolves the meanders SWOT cut as straight chords. The same nearest-crossing-by-radius prior applies.

**Result:** the **Uyak water surface sits above the Kanektok** at matched radius — **+0.96 m** by the pass-paired SWOT measure (below), or +1.45 m read off the DEM alone. Arc data coverage is 100 % (the 2 m DEM images the whole inter-river floodplain), and all 64 arcs yield valid picks under the tight window. *(Tightening the Kanektok prior from the wide SWOT-based window to the accurate ±75 m field centerline eased the apparent Kanektok incision by ~0.3 m — the wide window had been reaching slightly deeper terrain — confirming the small, conclusion-preserving bias anticipated when the asymmetry was flagged.)*

**Cross-check and correction against SWOT** (`swot_arc_reference.py` → `data/swot_arc_reference.parquet`). The DEM channel water surface holds up well against the satellite's direct measurement: once the geoid is applied per radius, the DEM sits **−0.15 m** from the SWOT median stage on the Kanektok and **+0.14 m** on the Uyak — inside ArcticDEM's ~0.5 m accuracy, and on the Uyak with no residual along-reach trend. But two stage effects have to be handled honestly:

- **A river has no single water surface.** At a fixed radius the SWOT water surface spans **~0.7 m between p10 and p90** across ~40 overpasses. Any "is it perched?" number is therefore a statement about a *stage*, not about the river. We quote superelevation at the **median observed stage** and carry the p10–p90 band alongside.
- **The mosaic caught the two rivers at different stages.** Being a multi-date blend, it imaged the Kanektok near the **29th percentile** of observed stages and the Uyak near the **76th** — a ~0.34 m differential bias pointing exactly the way that inflates "Uyak higher." So the inter-river difference is taken from **pass-paired SWOT** (both rivers in the *same* overpass, so stage cancels exactly): **+0.96 m, Uyak higher on 100 % of passes**, over 2 495 pass-radius pairs from 49 passes. The DEM-only +1.45 m is retained in the parquet for continuity but is not the number to quote. *(An earlier draft of this write-up compared the arc result against "+0.19 m" attributed to SWOT; that figure was a DEM corridor-median, not SWOT, and it made the arc method look far worse than it is.)*

**Superelevation above the floodplain corridor (the decisive avulsion metric).** Raw elevation ("which water surface is higher") is *not* the avulsion criterion — a channel avulses only if it is **perched above the floodplain it would spill into**. On each arc we therefore also take a floodplain reference: the **median terrain of the corridor strictly between the two channels** (excluding each ±250 m channel notch; corridor median width ~2.6 km, available on 64/64 arcs). Superelevation = channel water surface − corridor reference:

- **Kanektok: median −1.50 m** at the median observed stage (**−1.75 m** at low water, **−1.01 m** at high water) — the Kanektok is an **incised** channel, sitting *below* the surrounding floodplain on **100 %** of arcs, and it stays below even at the high end of the observed stage range.
- **Uyak: median −0.49 m** (**−0.77 m** low water, **−0.14 m** high water) — the Uyak sits **≈ at floodplain grade**, above the corridor on ~30 % of arcs, consistent with it being the low slough of the floodplain rather than a levee-bound channel.

So although the Uyak water surface is marginally the higher of the two, **neither channel is perched above the inter-channel corridor, and the Kanektok is distinctly incised on every arc** — direct topographic evidence *against* a Kanektok → Uyak avulsion. *Caveat:* the corridor is wide (~2 km), so its median is a broad reference and could be biased if a subtle interfluve divide sits between the channels; the sign and magnitude are robust enough that this does not change the conclusion.

**Gearon superelevation ratio β = H_AR / H_M.** The dimensionless form of the same idea (Gearon et al. 2024, *Nature*) is **β = H_AR/H_M = (ridge crest − floodplain) / (ridge crest − bed)** — alluvial-ridge height over channel depth. It is identical to the prior ArcGIS `(P98 − median)/(P98 − P2)`, which is why we report it: **β here is the reproduction of the preliminary analysis**, not an attempt to replicate Gearon's study design.

Note that all three terms are **topographic** surfaces. The water surface is *not* a term in β — in Gearon it appears only as an instrument for locating the bed, because lidar cannot see through water ("ICESat-2 can rarely resolve channel bed elevations owing to strong absorption of near-infrared laser pulses by turbid water"). We have the bed directly: **bed = water surface − boat-ADCP thalweg depth**, and since SWOT overflew on **2026-05-28 and 05-30, inside the 2026-05-28→06-03 survey window**, the water surface used is the one measured *at the stage the depths were sounded at*. That removes the stage mismatch in pairing a 2026 depth with a 2010–2021 DEM (worth +0.05 m on the bed here). The survey itself caught a typical stage — **+0.04 m** from the all-pass median — so β is not stage-biased.

**Setting the crest window: the bankfull check.** The crest is the lower of the two P98 bank-highs beside the thalweg (Gearon's "lowest of the two high points"), read within **±150 m** — about three channel widths on a ~50 m river, the scale Gearon works at. The earlier ±350 m was ~7 channel widths, and two independent diagnostics say it was reaching regional high ground rather than a bank:

- The P98 never settles. Sweeping the window, β climbs monotonically (−0.16 at ±75 m, 0.06 at ±150, 0.21 at ±250, 0.24 at ±350, 0.28 at ±500) and the crest pixel's distance from the thalweg tracks the window boundary (57 m → 292 m) — the signature of no local maximum, i.e. **no levee**.
- A bank the river can actually fill should have freeboard **A = (crest − water surface) comparable to the channel depth B** (ADCP median 1.30 m). Measured A/B by window: 0.66 @ ±60 m, 1.02 @ ±100, **1.27 @ ±150**, 1.72 @ ±250, **1.87 @ ±350**. At ±350 m the "bank" stood 1.9× the channel depth above the water — a bank the Kanektok could never overtop, and Gearon's own anomalous rule-3 regime. At ±150 m it is bankfull-consistent.

**Result: β median 0.06, with H_AR median +0.14 m**, and on **38 %** of arcs the near-channel high ground sits *below* the floodplain reference outright (β ≤ 0). The honest reading is not "β is safely under a threshold" but **there is no alluvial ridge to superelevate** — the same fact the −1.50 m incision reports, in dimensionless form. H_M median 2.86 m (freeboard + measured depth 1.30 m). This supersedes the earlier β ≈ 0.24, which was an artifact of the over-wide crest window; about a third of that H_AR was also a datum offset, the ~2.7 km-wide corridor median sitting ~0.29 m below the floodplain immediately beside the Kanektok.

**β = 1 is not the operative avulsion threshold, and we do not claim it is.** Gearon's criterion is **βγ ≥ Λ** (their eq. 4), with Λ median **2.1** (range 0.2–11); the paper is explicit that "β only accounts for half of Λ" and that "roughly 60 % of deltas in our dataset have β < 0.5" — near the sink, rivers that *did* avulse carry low β because the gradient term γ is high. This analysis deliberately does **not** evaluate γ, so β alone cannot be read as a pass/fail against avulsion; it is reported as the reproduction of the ArcGIS metric, and the avulsion argument rests on the incision result. *(For scale only: with S_M = 195.4 cm/km and a ridge-flank run of 150–500 m, γ would be ≈ 0.9–3.0 and βγ ≈ 0.2–0.7, still well under Λ — but the corridor-median floodplain has no location, so S_AR has no defensible run length and we do not publish a γ.)*

β is Kanektok-only (the Uyak has ADCP depth near its mouth only). Figure `arcB_beta.png`; per-arc columns `kan_depth_m/kan_bed_m/kan_bed_dem_m/kan_crest_m/kan_HAR_m/kan_HM_m/kan_beta/kan_freeboard_over_depth`. *Caveat:* the crest/H_AR is read along the (slightly oblique) arc rather than a true flow-perpendicular section — a perpendicular re-measurement remains the rigorous refinement.

**Channel-migration caveat.** The field centerlines are **2026**; the DEM mosaic is **2010–2021**, so the river has had 5–16 years to shift, and the boat line is a prior for a channel the DEM may not show in the same place. Measured: the DEM channel sits a median **38 m** (Kanektok) and **12 m** (Uyak) from the field line, and on **9 % / 8 %** of arcs the snap runs into the edge of its ±75 m search window — meaning the DEM channel may lie further out still. Importantly this does **not** propagate into the water surface: widening the search from ±75 m to ±400 m moves the picked WSE by **0.00 m**, because the floodplain low is a broad flat wet surface and the P2 pick finds it wherever it lands. What it does leave uncertain is the channel *position* — the x = 0 origin of the sections, the crest window anchored on it, and the corridor edges — at the few-tens-of-metres level. Per-arc QC columns `kan/uyak_snap_offset_m` and `kan/uyak_snap_clipped`.

**Channel-depth statistics + Uyak-vs-Kanektok comparison** (`adcp_depth_stats.py`). The Kanektok ADCP depth (39.5 k pings, 0.4–34.4 km) is shallow and fairly uniform: **median 1.22 m** (mean 1.29 ± 0.46, p10–p90 0.79–1.88, max 3.9 m), deepening slightly downstream (~1.15 m near the anchor → ~1.35 m past 25 km). We do **not** build a Uyak depth model (the Uyak was surveyed near its mouth only). Instead, at the one reach where both rivers have depth — the **mouth, radius 31–33 km** — the **Kanektok runs 1.26× deeper (median 1.37 m vs the Uyak's 1.08 m, +0.29 m)** at matched downstream distance. So the smaller Uyak is also the shallower channel there, consistent with it being the subordinate distributary. Figure `outputs/adcp_depth_comparison.png`; committed depth data `data/kanektok_thalweg_depth.parquet` + `data/uyak_mouth_depth.parquet`.

**Validity caveat (Merwade et al. 2006):** iso-radius equals iso-flow-distance only where a channel runs straight from the anchor. Here each channel's bearing-from-anchor drifts ~20° over its length (`arcB_validity.png`), so there is some Euclidean-vs-flow distortion — but **both channels drift consistently and keep a steady ~10–15° separation**, so the *comparison between them* remains robust, and it agrees with SWOT. State this explicitly rather than hiding it.

**Figures:** `arcB_sections.png` (arc cross-sections **re-centered on the Kanektok, x = 0, increasing toward the Uyak** — "stand in the Kanektok, walk the spill path" — with the β anatomy hung off the channel: bed ▼, ridge crest ▲, an **H_M** measure bar crest→bed, an **H_AR** bar crest→floodplain, and the **β** value at the crest, so the section itself reads as β = H_AR/H_M), `arcB_sidebyside.png` (both water surfaces + Kanektok bed vs radius + difference), `arcB_beta.png` (Kanektok β vs radius + depth/H_M/H_AR), `arcB_validity.png` (bearing vs radius).

---

## 5. Overall conclusion

The arc method and the independent SWOT water-surface analysis **agree**:

- At matched downstream distance the **Uyak water surface sits higher** than the Kanektok: **+0.96 m**, measured from SWOT overpasses that caught both rivers at the same moment (higher on 100 % of passes). The DEM arcs give +1.45 m; the gap is a differential-stage artifact of the multi-date mosaic.
- But raw height is not the avulsion criterion: against the inter-channel floodplain corridor, the **Kanektok is incised on 100 % of arcs** (median −1.50 m at the median observed stage, and still −1.01 m at high water) while the **Uyak sits ≈ at grade** (−0.49 m). A channel must be *perched above* the corridor to avulse into it — neither is, and the Kanektok emphatically is not.
- The **superelevation ratio β = H_AR/H_M ≈ 0.06 with H_AR ≈ +0.14 m** says the same thing dimensionlessly: **the Kanektok has no alluvial ridge** to perch on, and on 38 % of arcs the near-channel high ground is below the floodplain outright. β is reported as the reproduction of the preliminary ArcGIS metric — **not** as a pass/fail against a β = 1 threshold, which is not Gearon's operative criterion (§4).
- The **topographic case for a Kanektok → Uyak avulsion is weak.** The prior β ≈ 0.96 / "30 % perched" reading was inflated by diagonal-transect geometry (a down-valley-gradient artifact), not a real superelevation signal.
- The DEM is **independently corroborated by SWOT**: the DEM channel water surface lands within **0.15 m** of the SWOT median stage on both rivers, on a shared EGM2008 datum — three datasets (2 m DEM, boat ADCP, SWOT) telling one story.

A well-supported near-grade / null result, consistent across three independent datasets (2 m DEM arcs + boat-ADCP depth + SWOT), is a defensible thesis finding.

---

## 6. References

- Gearon, J. H. et al. (2024) *Rules of river avulsion change downstream.* **Nature** 634. doi:10.1038/s41586-024-07964-2 — perpendicular-to-channel cross-sections; along-channel normalized distance; β = H_AR/H_M.
- Gearon, J. H. et al. (2025) *River avulsion precursors encoded in alluvial-ridge geometry.* **GRL.** doi:10.1029/2024GL114047 — channel-perpendicular sections every 200 m.
- Valenza / Brooke et al. (2020) **Nat. Communications** 11. doi:10.1038/s41467-020-15859-9 — along-channel-belt distance from the mountain front, normalized by channel width.
- Jerolmack & Mohrig (2007) **Geology** — superelevation via channel-belt cross-section.
- Williams et al. (2006) **GRL** doi:10.1029/2005GL025618; Norini et al. (2016) **Geomorphology**; Edmonds et al. (2011) **JGR** doi:10.1029/2010JF001955 — radial distance-from-apex coordinate on fans/deltas.
- Merwade, Legleiter & Kyriakidis (2006) **Math. Geosciences** — Euclidean distance inappropriate for meandering channels; channel-fitted (s,n) coordinates.

---

## 7. Data provenance

| Item | Source |
|---|---|
| 2 m ArcticDEM | `batch_outputs/arcticdem_rivers_2m.tif` (PGC S3 COGs, v4.1 mosaic, EPSG:3413; source imagery 2010-10-03 → 2021-03-02 per PGC STAC) |
| SWOT per-arc reference | `data/swot_arc_reference.parquet` (from `swot_arc_reference.py`) — per-radius EGM2008 geoid, per-river stage distribution (median/p10/p90), pass-paired Uyak−Kanektok difference, and the survey-stage water surface used for the bed |
| SWOT channel centerlines | `outputs/swot_centerlines.gpkg` (from `make_swot_centerline.py`) — comparison overlay only (no longer a prior) |
| Official Uyak centerline | `data/uyak_centerline_official.gpkg` (field boat-GPS via `build_uyak_centerline.py`, hand-edited) — Uyak prior |
| Official Kanektok centerline | `data/kanektok_centerline_official.gpkg` (field boat-ADCP thalweg via `build_kanektok_centerline.py`) — Kanektok prior |
| Kanektok thalweg depth | `data/kanektok_thalweg_depth.parquet` (Day-03 pings: radius + River_Depth) — the β bed / H_M term |
| ADCP field survey | `~/Downloads/ADCP Data/` (coworker boat ADCP, May–Jun 2026; River_Depth + shear velocity) — Kanektok centerline + depth source; Uyak depth (mouth only) reserved for the deferred Uyak model |
| Prior ArcGIS geometry & Z points | `clean_and_complete.gdb` (`Guide_Lines_2`, `Avulsion_Lines_2`, `River_Elevation_2`, `Total_Elevation_2_Clipped`). The gdb is too large to commit; it is archived at `~/Downloads/clean_and_complete.gdb.zip`. Committed extracts: `reference/avulsion_transects.gpkg` (the two vector layers) and `reference/original_beta.parquet` (the recovered β table; rebuild with `recover_original_beta.py`) |
| Shared anchor / dist_km | identical to `dashboard_swot.py` (verified) |
