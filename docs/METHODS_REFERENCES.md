# Methods ↔ References Audit

**Purpose:** one row per scientific decision in the codebase — where it lives, whether the
code matches the write-up, and its citation status. This is the working document for the
bug review (Phase B) and literature audit (Phase C). Zotero is the source of truth for
references; `docs/references.bib` is its committed mirror.

**Built:** 2026-08-12 (methods-inventory sweep of `SWOT_Pull.py`, `dashboard_swot.py`,
`temporal_analysis.py`, `thesis_figures/core.py|config.py`, `DEM_Pull.py`, `DEM_2m_Pull.py`,
`DEM_Transects/{build_arc_B,avulsion_metrics,beta_floodplain}.py`, cross-checked against
Masters Thesis draft 6 and `DEM_Transects/AVULSION_ANALYSIS.md`).

**Code↔writeup legend:** ✅ matches · ❌ mismatch (code and write-up disagree — one must change) ·
➖ not claimed in write-up · 🔍 unverified (needs Phase B)

**Citation legend:** `OK` cited & in Zotero · `FIX-ZOTERO` cited in thesis but Zotero record
missing/malformed · `GAP` methodological choice with no supporting reference yet ·
`N/A` engineering choice, no citation expected

---

## Verified facts (checked directly against data, 2026-08-12)

- Local master partitions and deployed `dashboard_data.parquet` both contain **only
  classification Classes 3 and 4** (no stale Class 5–7 pixels from the earlier 3–7
  configuration survive).
- The QC-excluded pass **2025-04-17 has zero rows** in both the local master and the
  deployed parquet — the exclusion in `SWOT_Pull.py` propagates to all consumers.
- `arcB_channels.parquet` reproduces every headline DEM number in `AVULSION_ANALYSIS.md`:
  β median 0.0571 (~0.06), H_AR median 0.141 m, superelevation −1.499 / −0.488 m,
  inter-river difference +0.963 m (SWOT pass-paired) / +1.445 m (DEM-only),
  corridor width median 2 696 m, geoid 13.7386 → 13.2802 m, 64 arcs.

---

## A. Ingestion — `SWOT_Pull.py`

| # | Method (params) | Code | Code↔writeup | Citation |
|---|---|---|---|---|
| A1 | Product: SWOT_L2_HR_PIXC **Version D** via Earthdata | `SWOT_Pull.py:570` | ✅ | FIX-ZOTERO — thesis cites NASA/JPL (2023) PIXC Product Description (JPL D-109532); not in Zotero |
| A2 | WSE = h_raw − geoid − solid_tide − pole_tide − load_tide | `SWOT_Pull.py:262` | ✅ | OK (Fu 2024 + product doc per A1) |
| A3 | Cross-track filter 10–60 km (abs, both swaths) | `SWOT_Pull.py:24-25,280-285` | ✅ | GAP — SWOT Handbook backs this; add Handbook to Zotero |
| A4 | Crossover-cal missing (bit 23 of geolocation_qual) excluded | `SWOT_Pull.py:27-29,287-296` | ✅ | GAP — code cites "Handbook §9.4.2"; add to Zotero |
| A5 | Standard quality bit-flags **deliberately bypassed** (too aggressive on narrow Uyak) | `SWOT_Pull.py:298-303` | ✅ (but code frames it as provisional "TODO") | GAP — needs literature/handbook support; Franze 2025 is the precedent for narrow-river adaptations |
| A6 | Classification filter: keep Classes **[3, 4]** only | `SWOT_Pull.py:21,307-308` | ✅ (verified in data, see above) | OK (Franze 2025) |
| A7 | **MAD filter on node-median WSE residuals** (threshold 3.5, per reach per granule; 1-km node medians subtracted so the filter never sees real along-stream relief; sparse nodes <3 px borrow the nearest well-populated node's median) | `SWOT_Pull.py:31-42,121-205,355-400` | ✅ **Fixed 2026-08-14** (was raw-domain — critical finding, amputated upstream Uyak on ~28% of dates). Now consistent with thesis §2.3's "detrended residuals" wording; §2.3 should be updated to say *node-median residuals* specifically. Effective after archive re-pull | OK (Iglewicz & Hoaglin 1993; Leys 2013) |
| A8 | Haversine radial distance from anchor (59.82463509, −161.33397834), R=6371.0 | `SWOT_Pull.py:78-119,266-273` | ✅ (note: *radial*, not along-channel — thesis should say "straight-line") | FIX-ZOTERO — thesis cites Sinnott (1984); not in Zotero |
| A9 | KNOWN_BAD_PASSES registry: 2025-04-17 dropped at master rebuild | `SWOT_Pull.py:64-76,485-495` | ✅ (verified absent from all products) | N/A — but registry is **duplicated** in `thesis_figures/config.py:66-73`; consolidate to one source |
| A10 | **Ice-season hard line May–Oct** (`ICE_SAFE_MONTHS`), applied once at master rebuild so ALL analysis products inherit it; daily CSVs keep all months for provenance. Replaced the Apr–Nov per-pass tag 2026-08-14: archive audit found April breakup interference in every observed year (2024-04-07; 2025-04-17/19; 2026-04-07/08/18/28, WSE anomalies to +0.9 m), October clean in all years, first freeze-up signature 2025-11-12. `REFGRAD_OPEN_WATER_MONTHS` now aliases `ICE_SAFE_MONTHS` | `SWOT_Pull.py` (ICE_SAFE_MONTHS config + rebuild filter) | ✅ empirically calibrated from archive; effective in products after next rebuild/re-pull | GAP — ice-phenology / ice-season radar-altimetry bias citation still wanted (Phase C); the empirical audit itself is now documentable as methods |
| A11 | Reference gradient: per-pass Theil–Sen on 1-km node medians; gates ≥8 nodes, span ≥30 km, start ≤3 km; headline = median of \|slope\| over gated open-water passes | `SWOT_Pull.py:44-62,377-454` | ✅ | GAP — Theil (1950) / Sen (1968) not cited anywhere |
| A12 | Legacy per-pass pixel-level OLS `slope_calc` still exported on every row | `SWOT_Pull.py:342-347` | ➖ superseded estimator ships alongside its replacement | N/A — Phase B: remove or clearly deprecate |

Phase-B seeds from this file: silent `load_tide=0` fallback (`:246-247`); cross-track filter
silently skipped if variable missing (`:281`); dead `XOVERCAL_SUSPECT_MASK` (`:28`);
`len>5` gate silently drops small valid reach/passes (`:336`); global `warnings.filterwarnings('ignore')`
(`:91`); checkpoint-resume means filter changes don't retroactively apply to old daily CSVs
(mitigated for classes/excluded-pass — verified — but a standing hazard); same-day pass collision on date-keyed CSVs.

## B. SWOT analysis — `dashboard_swot.py` + `thesis_figures/core.py`

| # | Method (params) | Code | Code↔writeup | Citation |
|---|---|---|---|---|
| B1 | Detrend baseline: pooled fit, **raw (subsampled ≤30 k) point cloud**, method arg Linear/Poly2/Poly3/"LOESS"; dashboard hardcodes Poly2 | `dashboard_swot.py:131-174,200-231,1320` | ❌ **Thesis §2.5.3 says fitted to 100-m bin medians** "to prevent point-density bias" — no binning exists in the detrend path. Either bin the fit input (preferred, matches thesis) or correct the thesis | GAP — polynomial concavity baseline: dashboard DEM analogue cites Flint (1974); not in Zotero |
| B2 | Residual MAD flag, threshold 3.5, flag-don't-delete, per reach | `dashboard_swot.py:177-197,2384-2395` | ✅ | OK (Iglewicz & Hoaglin) |
| B3 | "LOESS" option is actually a Gaussian moving average (σ = 0.15·N/3 **points**, not km) | `dashboard_swot.py:163-172`; `core.py:126-160` | ➖ mislabeled; unreachable in dashboard (Poly2 hardcoded) | N/A — rename or remove |
| B4 | Slope profile: 100-m bin medians → Gaussian **σ = 2 km** (FWHM ≈ 4.7 km) → np.gradient | `dashboard_swot.py:234-276` | ❌ thesis §2.5.2 calls it a "2-kilometer smoothing window" — it is the σ; effective resolution ~4.7 km (already flagged in SLOPE_REANALYSIS_PLAN) | N/A — wording fix + state FWHM |
| B5 | Fine-scale slope: per-pass 0.1-km bin medians (≥30 px/bin), 0.3-km gap fill, sliding ±0.25 km Theil–Sen, ≥3 pts, x ≤ 34 km | `dashboard_swot.py:288-352,369-420` | ✅ core estimator; bin-gate/gap-fill params ➖ (disclose in DEM/SWOT writeup) | GAP — 0.5-km "backwater length scale" justified only by in-code scaling argument (L_b ~ depth/slope); needs a backwater-length citation |
| B6 | Fine-scale window slope: 1–5 km window, 0.80 coverage gate, per-pass median | `dashboard_swot.py:302-317,453-487` | ✅ | N/A — justified by internal sweep (2026-08-04, in comments); make sweep reproducible |
| B7 | Elevation difference: 100-m bins, within-pass paired K−U, median across passes (SQL + verbatim pandas port) | `dashboard_swot.py:2232-2260`; `core.py:345-391` | ✅ thesis §2.5.1 exactly | N/A — paired design is standard; optional stats citation |
| B8 | Gradient profile: 0.5-km binned medians + 5–95% band | `dashboard_swot.py:34-38,1547-1581` | ✅ (thesis Fig 5 uses same convention via core.py) | N/A |
| B9 | **Sampled-data statistics**: detrended tab's baseline fit + stats table use ≤30 k systematic sample; gradient-profile line/band use 15 k viz_df | `dashboard_swot.py:1369-1385,2370-2374,2596-2639` | ❌ thesis §2.3 claims "all baseline hydrodynamic modeling … strictly utilized the complete, un-sampled dataset". True for elevation-diff/slope/fine-scale/refgrad (SQL on full data) and for thesis figures (core.py, no sampling); **false for the dashboard detrended tab and profile band** | N/A — correct the thesis sentence to name the exceptions, or compute those stats via SQL |
| B10 | Ice handling in interactive tabs: **warning only**, winter passes selectable | `dashboard_swot.py:1346-1355` | ❌ thesis §2.3 "analysis was strictly confined to April–November" — true for refgrad/temporal/thesis figures; the interactive dashboard permits ice passes | N/A — disclose, or hard-gate the village app |
| B11 | EXCLUDED_PASSES filter in thesis_figures only (belt-and-suspenders; pass already absent upstream) | `config.py:66-73`; `core.py:35-48,102` | ✅ in effect (verified) — but registry duplicated with A9 | N/A — consolidate |
| B12 | core.py "verbatim port" claim | `core.py:3-10` | ✅ for all numerical kernels (verified line-by-line); 4 documented departures (exclusion filter, retained savgol/gaussian estimators, added percentile band, auto month-gate) | N/A |

Phase-B seeds: dead `loess_smooth` (`:2347-2365`), dead `compute_finescale_slope` (`:517-529`),
unreachable method_guidance branches + "Switch to Linear or LOESS" error text for a control that
no longer exists (`:2517-2583`); two coexisting detrend fits (map coloring vs detrended tab) on
different samples; class legend 3–7 (`:3237-3241`) vs "Classes 3–4" prose (`:3833`) — legend
should match verified ingestion; ~30 hardcoded numeric results in UI prose (catalog in inventory,
item 22 of the tabs sweep) that go stale on data refresh.

## C. Temporal analysis — `temporal_analysis.py`

| # | Method (params) | Code | Code↔writeup | Citation |
|---|---|---|---|---|
| C1 | 1-km node medians → per-pass Theil–Sen; gates ≥8 nodes, span ≥30, start ≤3 km | `temporal_analysis.py:53-57,80-108` | ✅ thesis §2.4.1 | GAP — Theil/Sen |
| C2 | Virtual gauge = trendline value at 15 km | `temporal_analysis.py:57,98` | ✅ §2.4.2 (note: fitted-line value on a concave profile, not local median — fine for differences, worth one sentence) | N/A |
| C3 | Q1/Q2/Q3 designs (pooled seasonal slope, per-year WSE; 2024 vs 2025 control; June-matched typhoon vs baseline) | `temporal_analysis.py:147-290` | ✅ §2.4.3 | N/A |
| C4 | **Mann–Whitney U, two-sided, α=0.05** | `temporal_analysis.py:136-144` | ❌ **thesis Table (§3.1) labels Uyak seasonal slope "Not Significant (p=0.033)"** — the code labels p<0.05 significant, and TEMPORAL_ANALYSIS.md calls this result "marginal, not year-consistent". The thesis must either report it as significant-but-not-meaningful (year-inconsistency / multiple-comparisons argument) or as marginal — not "Not Significant" | GAP — MWU uncited (Mann & Whitney 1947); test never named in thesis |
| C5 | ~14 MWU tests, no multiple-comparison correction | (absent) | ➖ acknowledged qualitatively in TEMPORAL_ANALYSIS.md only | GAP — state in thesis or apply correction |
| C6 | Q3 spatial delta: 0.5-km bins, ≥3 px, June-only pools, 18-km up/downstream split | `temporal_analysis.py:293-348` | ✅ (18-km split undocumented in writeup) | N/A |
| C7 | Pass exclusion: none in this script — inherited from master parquet (verified: excluded pass absent upstream) | — | ✅ in effect | N/A |

## D. DEM acquisition — `DEM_Pull.py`, `DEM_2m_Pull.py`

| # | Method (params) | Code | Code↔writeup | Citation |
|---|---|---|---|---|
| D1 | Stream A: GEE asset `UMN/PGC/ArcticDEM/V4/2m_mosaic`, scale=10, EPSG:4326 | `DEM_Pull.py:61-69` | ✅ (V4-generation mosaic; writeup says "v4.1" via GEE catalog description) | FIX-ZOTERO — Zotero has Porter et al. ArcticDEM **v3**; cite the v4.1 release the code uses. Karlson 2021 (error characteristics) OK |
| D2 | Stream A geoid: EGM2008 **interpolated** from SWOT per-pixel geoid field (LinearNDInterpolator inside the SWOT hull; **nearest-neighbour extrapolation outside it** — fixed 2026-08-14, was a 13.46 m constant that put ~0.25 m datum error into the coastal Uyak bins; constant now used only if no SWOT CSVs exist at all) | `DEM_Pull.py:131-200` | ❌ `DEM_WRITEUP_PLAN.md` table calls Stream A geoid "constant" — it is interpolated; fix the plan table before the DEM write-up inherits it. Fix effective after `dem_river_elevations.parquet` regeneration | GAP — EGM2008 (Pavlis et al. 2012) uncited |
| D3 | Stream B: PGC S3 COGs v4.1, native 2 m, EPSG:3413, /vsicurl, window-snapped reads, **ellipsoidal** (geoid deferred to consumers) | `DEM_2m_Pull.py:45-131` | ✅ | OK via D1 citations |
| D4 | Fallback geoid constant 13.46 m duplicated in ≥6 files | multiple | ➖ | N/A — consolidate |

## E. DEM arc analysis — `DEM_Transects/`

| # | Method (params) | Code | Code↔writeup | Citation |
|---|---|---|---|---|
| E1 | 64 iso-radius arcs, R = 3.0–34.5 km step 0.5, bearing 248–294°, 2-m spacing | `build_arc_B.py:210,244-246` | ✅ (verified 64 rows) | FIX-ZOTERO — AVULSION_ANALYSIS.md cites Merwade 2006, Williams 2006, Edmonds 2011, Norini 2016; none in Zotero |
| E2 | Per-radius EGM2008 geoid from `swot_arc_reference.parquet` (13.74 → 13.28 m verified) | `build_arc_B.py:191-204,247-248` | ✅ (in-code comment quotes 13.77/13.27 — extrapolated R=0 endpoints; align the two) | GAP — EGM2008 per D2 |
| E3 | Channel pick: centerline prior, ±75 m snap window, thalweg = median of ≤P2 pixels, WSE = P2 within ±50 m | `build_arc_B.py:150-172,257-302` | ✅ (sensitivity documented in MD §4) | GAP — DEM-water-surface-as-P2 convention could use support |
| E4 | Floodplain reference: corridor median between channels, excl. ±250 m notches, width ≥100 m (median width 2 696 m verified) | `build_arc_B.py:285-297` | ✅ | N/A |
| E5 | Bed: SWOT survey-stage WSE (2026-05-28/30) − ADCP depth; crest: min of flank P98s, ±150 m | `build_arc_B.py:175-188,305-314` | ✅ (comment "ADCP median 1.30 m" vs stats doc 1.22 median/1.29 mean — fix comment) | OK (Gearon 2024 for crest concept) |
| E6 | **Arc β = (crest − floodplain)/(crest − bed)**, Kanektok, NaN unless H_M>0 | `build_arc_B.py:319-322` | ❌ MD §4 asserts this "is identical to the prior ArcGIS (P98−med)/(P98−P2)" — it is **analogous, not identical** (ADCP bed ≠ P2 water surface; flank-min-P98 ≠ single P98). The DEM write-up must say "analogous" and explain the improvement | OK (Gearon 2024) |
| E7 | ArcGIS-reproduction β = (P98−median)/(P98−P2), 0–700 m near-zone, no detrend | `beta_floodplain.py:41-72` | ✅ (the literal formula lives here) — **fixed 2026-08-14**: inputs now committed (`reference/avulsion_transects.gpkg` + `reference/original_beta.parquet`; `recover_original_beta.py` rebuilds both from the archived gdb); end-to-end rerun reproduces the documented naive-rebuild β 2.86 / 99% perched and the recovered original β 0.96 / H_AR 4.30 m | OK (Gearon 2024) |
| E8 | `avulsion_metrics.py` Gearon port (β, γ, Λ=2.1, Monte Carlo) | `avulsion_metrics.py:32-139` | ➖ docstring claims "production core" but only `validation/` imports it; production computes β inline twice | OK (Gearon 2024 + Zenodo code citation) |
| E9 | Superelevation quoted at SWOT median stage, p10–p90 band; **DEM-stage fallback removed 2026-08-14** (SWOT-thin arcs now gap as NaN instead of silently switching stage basis; was a no-op on committed data — 0 arcs used it) | `build_arc_B.py:377-387` | ✅ values verified; fallback removal verified value-identical on committed parquet | N/A |
| E10 | z==0 masked as nodata (GEE-era rule applied to PGC raster) | `build_arc_B.py:203` | ➖ undocumented exclusion; harmless at +13 m geoid offset but should be stated | N/A |

## F. Missing / broken references (action list for Zotero)

1. **Fix:** "Hoaglin, D. 2013" → Iglewicz & Hoaglin (1993), *How to Detect and Handle Outliers*, ASQC Vol 16.
2. **Fix:** ArcticDEM record v3 → v4.1 release (code-verified).
3. **Add (already cited in thesis):** Sinnott (1984); NASA/JPL SWOT L2 HR PIXC Product Description (JPL D-109532); SWOT Handbook (JPL D-109532 companion, cited in code §9.4.2).
4. **Add (cited in code/docs, not Zotero):** Flint (1974); Hack (1957); Merwade et al. (2006); Williams (2006); Edmonds (2011); Norini (2016).
5. **Add (methods used, never cited):** Theil (1950) / Sen (1968) — Theil–Sen estimator; Mann & Whitney (1947) — MWU test; Pavlis et al. (2012) — EGM2008.
6. **Candidates to find (Phase C):** backwater length scale for the 0.5-km fine-scale choice; ice-season WSE bias in radar altimetry (Apr–Nov window + 0.5–2 m figure); precedent for bypassing global SWOT quality flags on narrow rivers (beyond Franze 2025); DEM water-surface-as-low-percentile convention.
7. **Complete:** USACE Lower Mississippi record (no author/year); Spessart beaver-dam record (no author/year); deduplicate Leys et al. 2013.
