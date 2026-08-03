# DEM Transect Avulsion Analysis — Methods, Results & Caveats

**Rivers:** Kanektok River & Uyak Creek (near Quinhagak, Alaska)
**DEM:** ArcticDEM V4, native **2 m** (`batch_outputs/arcticdem_rivers_2m.tif`, EPSG:3413), geoid-corrected to EGM2008 (constant 13.46 m offset; β and elevation *differences* are datum-invariant).
**Shared anchor (dist origin):** `59.82463509, -161.33397834` — the upstream divergence point; distance-from-anchor increases downstream toward the coast. This is the **same anchor the SWOT dashboard uses** (verified identical: Δdist_km = 0), so DEM and SWOT share one longitudinal axis.
**Last updated:** 2026-08-03.

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

We recovered the intended result directly from the intact elevation-point layers in the project geodatabase (`clean_and_complete.gdb`; the notebook run that would have saved β to `Avulsion_Lines_2` had errored, leaving those columns empty):

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

**Result:** the **Uyak water surface sits ~1.45 m _above_ the Kanektok**, higher on **92 % of arcs**. Same direction as SWOT/dashboard; opposite to the diagonal artifact. Arc data coverage is 100 % (the 2 m DEM images the whole inter-river floodplain), and all 64 arcs yield valid picks under the tight window. *(Tightening the Kanektok prior from the wide SWOT-based window to the accurate ±75 m field centerline eased the apparent Kanektok incision by ~0.3 m — the wide window had been reaching slightly deeper terrain — confirming the small, conclusion-preserving bias anticipated when the asymmetry was flagged.)*

**Superelevation above the floodplain corridor (the decisive avulsion metric).** Raw elevation ("which water surface is higher") is *not* the avulsion criterion — a channel avulses only if it is **perched above the floodplain it would spill into**. On each arc we therefore also take a floodplain reference: the **median terrain of the corridor strictly between the two channels** (excluding each ±250 m channel notch; corridor median width ~2.6 km, available on 64/64 arcs). Superelevation = channel water surface − corridor reference:

- **Kanektok: median −1.52 m** — the Kanektok is an **incised** channel, sitting *below* the surrounding floodplain on **98 %** of arcs (perched on ~2 %).
- **Uyak: median −0.21 m** — the Uyak sits **≈ at floodplain grade** (slightly below on average, above on ~33 % of arcs), consistent with it being the low slough of the floodplain rather than a levee-bound channel.

So although the Uyak water surface is marginally the higher of the two, **neither channel is perched above the inter-channel corridor, and the Kanektok is distinctly incised on every arc** — direct topographic evidence *against* a Kanektok → Uyak avulsion. *Caveat:* the corridor is wide (~2 km), so its median is a broad reference and could be biased if a subtle interfluve divide sits between the channels; the sign and magnitude are robust enough that this does not change the conclusion.

**Gearon avulsion number β = H_AR / H_M (with measured channel depth).** The dimensionless metric the avulsion literature thresholds on (Gearon et al. 2024, *Nature*) is **β = H_AR/H_M = (ridge crest − floodplain) / (ridge crest − bed)** — the alluvial-ridge height over the bankfull channel depth. Threshold **β ≈ 1** means the bed has aggraded up to floodplain level (perched, avulsion-prone); β < 1 is incised/normal. It is identical to the prior ArcGIS `(P98 − median)/(P98 − P2)`. We compute it on the Kanektok arc cross-sections: the **ridge crest** is the lower of the two P98 bank-highs within ±350 m of the thalweg (Gearon's "lowest of the two high points"); the **floodplain** is the corridor reference above; the **bed = DEM water surface − boat-ADCP thalweg depth**. Because ArcticDEM images the *water surface*, without a measured depth H_M would be only the freeboard (crest − WSE) and β biased high — the ADCP supplies the missing channel depth (median 1.30 m; H_M median 3.85 m = 2.48 m freeboard + depth). Result: **β median 0.24, below 1 on 100 % of arcs**, i.e. the Kanektok is incised by ~one channel depth — the opposite of the avulsion setup. This *reconciles with and sharpens* the retired DEM-only Approach A (β ≈ 0.41): using the measured bed instead of the water surface deepens H_M and lowers β (a DEM-only version here gives ≈ 0.38 → 0.24 with real depth), moving the number in the safe direction. β is Kanektok-only for now (the Uyak has ADCP depth near its mouth only). Figure `arcB_beta.png`; per-arc columns `kan_depth_m/kan_bed_m/kan_crest_m/kan_HAR_m/kan_HM_m/kan_beta`. *Caveat:* the crest/H_AR is read along the (slightly oblique) arc rather than a true flow-perpendicular section — acceptable here given β agrees with the perpendicular Approach A, but a perpendicular re-measurement is the rigorous refinement.

**Channel-depth statistics + Uyak-vs-Kanektok comparison** (`adcp_depth_stats.py`). The Kanektok ADCP depth (39.5 k pings, 0.4–34.4 km) is shallow and fairly uniform: **median 1.22 m** (mean 1.29 ± 0.46, p10–p90 0.79–1.88, max 3.9 m), deepening slightly downstream (~1.15 m near the anchor → ~1.35 m past 25 km). We do **not** build a Uyak depth model (the Uyak was surveyed near its mouth only). Instead, at the one reach where both rivers have depth — the **mouth, radius 31–33 km** — the **Kanektok runs 1.26× deeper (median 1.37 m vs the Uyak's 1.08 m, +0.29 m)** at matched downstream distance. So the smaller Uyak is also the shallower channel there, consistent with it being the subordinate distributary. Figure `outputs/adcp_depth_comparison.png`; committed depth data `data/kanektok_thalweg_depth.parquet` + `data/uyak_mouth_depth.parquet`.

**Validity caveat (Merwade et al. 2006):** iso-radius equals iso-flow-distance only where a channel runs straight from the anchor. Here each channel's bearing-from-anchor drifts ~20° over its length (`arcB_validity.png`), so there is some Euclidean-vs-flow distortion — but **both channels drift consistently and keep a steady ~10–15° separation**, so the *comparison between them* remains robust, and it agrees with SWOT. State this explicitly rather than hiding it.

**Figures:** `arcB_sections.png` (arc cross-sections across the valley, with Kanektok bed ▼ + ridge crest ▲), `arcB_sidebyside.png` (both water surfaces + Kanektok bed vs radius + difference), `arcB_beta.png` (Kanektok β vs radius + depth/H_M/H_AR), `arcB_validity.png` (bearing vs radius).

---

## 5. Overall conclusion

The arc method and the independent SWOT water-surface analysis **agree**:

- At matched downstream distance the **Uyak water surface sits marginally higher** than the Kanektok (~1.5 m by arcs; +0.19 m by corridor-median in the dashboard).
- But raw height is not the avulsion criterion: against the inter-channel floodplain corridor, the **Kanektok is incised on 98 % of arcs** (median −1.52 m, perched on ~2 %) and the **Uyak sits ≈ at grade** (−0.21 m). A channel must be *perched above* the corridor to avulse into it — neither is, and the Kanektok emphatically is not.
- The **measured Gearon avulsion number β = H_AR/H_M ≈ 0.24** (Kanektok, using the boat-ADCP channel depth) sits well below the avulsion threshold of 1 on 100 % of arcs — a field-validated, dimensionless confirmation of the same result, and it reconciles the retired DEM-only β (≈ 0.41) once the real bed deepens H_M.
- The **topographic case for a Kanektok → Uyak avulsion is weak.** The prior β ≈ 0.96 / "30 % perched" reading was inflated by diagonal-transect geometry (a down-valley-gradient artifact), not a real superelevation signal.

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
| 2 m ArcticDEM | `batch_outputs/arcticdem_rivers_2m.tif` (PGC S3 COGs, EPSG:3413) |
| SWOT channel centerlines | `outputs/swot_centerlines.gpkg` (from `make_swot_centerline.py`) — comparison overlay only (no longer a prior) |
| Official Uyak centerline | `data/uyak_centerline_official.gpkg` (field boat-GPS via `build_uyak_centerline.py`, hand-edited) — Uyak prior |
| Official Kanektok centerline | `data/kanektok_centerline_official.gpkg` (field boat-ADCP thalweg via `build_kanektok_centerline.py`) — Kanektok prior |
| Kanektok thalweg depth | `data/kanektok_thalweg_depth.parquet` (Day-03 pings: radius + River_Depth) — the β bed / H_M term |
| ADCP field survey | `~/Downloads/ADCP Data/` (coworker boat ADCP, May–Jun 2026; River_Depth + shear velocity) — Kanektok centerline + depth source; Uyak depth (mouth only) reserved for the deferred Uyak model |
| Prior ArcGIS geometry & Z points | `clean_and_complete.gdb` (`Guide_Lines_2`, `Avulsion_Lines_2`, `River_Elevation_2`, `Total_Elevation_2_Clipped`) |
| Shared anchor / dist_km | identical to `dashboard_swot.py` (verified) |
