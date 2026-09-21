# DEM_Transects — status

Avulsion analysis for the Kanektok & Uyak. **Full methods, results, and caveats:
[`AVULSION_ANALYSIS.md`](AVULSION_ANALYSIS.md)** (the single source of truth for the science).
This file tracks build status only. Last updated 2026-08-19 (ADCP ingest committed;
preliminary-ArcGIS β removed, β reframed on CIVIC warning sign 1).

---

## ✅ Done

- **ADCP survey brought into the repo** (2026-08-19). New `ingest_adcp.py` → tracked
  `data/adcp_velocity_depth.parquet` (40 815 pings, 339 transects, 6 survey days, both rivers, all
  export columns, ~1.8 MB zstd) + `data/adcp_velocity_depth.manifest.json`. `build_kanektok_centerline.py`
  and `adcp_depth_stats.py` now read that parquet instead of globbing
  `/home/luke/Downloads/ADCP Data`, so **the whole β chain reproduces from a clean clone** — the last
  hardcoded personal path in the analysis is gone (`build_uyak_centerline.py`'s onX GPX is the one
  remaining, for the Uyak centerline draft only; the official centerline is committed). Verified:
  `kanektok_thalweg_depth.parquet` and `uyak_mouth_depth.parquet` rebuild **byte-identical**, and
  `adcp_depth_stats.py` reproduces every published number (median 1.22 m, mean 1.29 ± 0.46,
  p10–p90 0.79–1.88, max 3.9 m; mouth 1.37 vs 1.08 m = 1.26×). β is untouched. The raw ~386 MB
  archive (`.PD0`, NetCDF, CSV intermediates, discharge workbooks) is deliberately **not** committed.

- **SWOT validation + stage handling, and a β correction** (2026-08-08). New
  `swot_arc_reference.py` → tracked `data/swot_arc_reference.parquet` (per-radius EGM2008 geoid,
  per-river stage median/p10/p90, pass-paired Uyak−Kanektok, survey-stage water surface). Changes:
  - **Geoid** constant 13.46 m → **per radius** (13.74 anchor → 13.28 coast). Within-arc differences
    are unchanged; this is what puts the DEM on SWOT's datum. DEM vs SWOT then agrees to
    **−0.15 m** (Kanektok) / **+0.14 m** (Uyak).
  - **Crest window ±350 → ±150 m** (~3 channel widths), set by the bankfull check that freeboard
    should ≈ channel depth (A/B was 1.87 at ±350 m — an unfillable bank; 1.27 at ±150 m).
    **β 0.24 → 0.06, H_AR 0.87 → +0.14 m**, β ≤ 0 on 38 % of arcs → **no alluvial ridge**.
  - **β = 1 is no longer presented as the avulsion threshold** anywhere (Gearon's criterion is
    βγ ≥ Λ; γ deliberately not evaluated). β is framed as CIVIC warning sign 1 (β > ~0.5, Ganti
    et al. 2016), a one-directional test — see the 2026-08-19 entry above.
  - **Uyak − Kanektok now from pass-paired SWOT: +0.96 m** (100 % of passes). The DEM-only +1.45 m
    carried a ~0.27 m differential-stage artifact (per-arc median, recomputed 2026-08) — the mosaic caught the Kanektok at the 29th
    percentile of stages and the Uyak at the 76th. (The old docs compared against "+0.19 m (SWOT)",
    which was actually a DEM corridor-median — corrected.)
  - **Superelevation quoted at the median observed stage with a p10–p90 band**: Kanektok −1.50 m
    (−1.75 low / −1.01 high, incised on 100 % of arcs), Uyak −0.49 m.
  - **Stage-matched bed**: SWOT overflew 2026-05-28/05-30 *inside* the ADCP survey window, so
    bed = survey-stage WSE − ADCP depth. Survey stage was +0.04 m from the all-pass median (typical).
  - **Migration QC** columns (`kan/uyak_snap_offset_m`, `_snap_clipped`). DEM mosaic is **2010–2021**
    vs 2026 field lines; offsets median 38 m / 12 m, at the ±75 m wall on 9 % / 8 % of arcs. WSE is
    insensitive (0.00 m across ±75→±400 m windows); channel *position* is not.
  - Dashboard tab shows SWOT water-surface markers with p10–p90 error bars, stage bands on the long
    profiles, stage-aware superelevation tooltips, and migration/threshold caveats. AppTest clean.

- **Established the iso-distance-arc frame** as the methods requirement: an oblique cross-valley
  transect measures the ~1.83 m/km down-valley gradient (8–11 m over a 4–6 km end-to-end offset)
  rather than the ~1 m superelevation signal. Confirmed against the SWOT dashboard (Uyak marginally
  higher at matched distance). Recorded in `AVULSION_ANALYSIS.md` §2.
- **The arc method** (`build_arc_B.py`) — radial iso-distance-from-anchor cross-sections, the
  dashboard-comparable side-by-side. Sampled at native 2 m; channels snapped to the DEM low.
  Established the Uyak water surface sits above the Kanektok while the Kanektok is incised below the
  inter-channel corridor → against a Kanektok→Uyak avulsion. Figures `arcB_sections.png`,
  `arcB_sidebyside.png`, `arcB_validity.png`. *(The numbers first quoted here — +1.45 m / −1.52 m /
  −0.21 m — were superseded by the 2026-08-08 SWOT/stage work above; the conclusion was not.)*
- **Measured Gearon β = H_AR/H_M for the Kanektok** using the boat-ADCP channel depth. Depth artifact
  `data/kanektok_thalweg_depth.parquet` (emitted by `build_kanektok_centerline.py`); figure
  `arcB_beta.png`; shown in the dashboard ✂️ Cross-Sections tab (β / H_AR / H_M metrics + bed/crest
  markers). Uyak β deferred (ADCP depth near its mouth only). *(The β ≈ 0.24 / H_AR ≈ 0.87 m first
  reported here came from a ±350 m crest window and was superseded on 2026-08-08: at a
  bankfull-consistent ±150 m window β ≈ 0.06 and H_AR ≈ 0, i.e. no alluvial ridge. The
  "below the avulsion threshold of 1" framing was also retired — that is not Gearon's criterion.)*
- **Kanektok depth statistics + mouth depth comparison** (`adcp_depth_stats.py`). Kanektok depth
  median **1.22 m** (p10–p90 0.79–1.88, max 3.9 m), ~uniform, slight downstream deepening. At the
  mouth (31–33 km, the only reach both rivers were surveyed) the **Kanektok is 1.26× deeper** than
  the Uyak (1.37 vs 1.08 m). Figure `adcp_depth_comparison.png`; depth data committed to `data/`.
- **Official field centerlines drive both channel picks** behind a symmetric ±75 m snap window:
  Uyak (`data/uyak_centerline_official.gpkg`, via `build_uyak_centerline.py`) from a hunter's boat
  tracks (onX GPX) + a gap sketch, hand-edited; Kanektok (`data/kanektok_centerline_official.gpkg`,
  via `build_kanektok_centerline.py`) from the coworker boat-ADCP Day-03 longitudinal thalweg run.
  Both preserve meanders; both overlaid on `map_transects.py`. This removed the last method
  asymmetry (the Kanektok's old ±1200 m SWOT-prior window) and eased apparent Kanektok incision
  ~0.3 m — the small, conclusion-preserving bias predicted from the wide window.
- **Literature grounding** (deep-research pass): the radial coordinate is the fan/delta
  convention (Williams 2006, Edmonds 2011) with the Euclidean-vs-flow caveat (Merwade 2006).
  Citations in `AVULSION_ANALYSIS.md`.
- **Interactive dashboard tab** (`dashboard_swot.py` → DEM Data → **✂️ Cross-Sections**): scrub
  the arcs by radius (Kanektok/Uyak water-surface vlines, floodplain corridor band, superelevation
  metrics, long-profiles). Reads the committed `data/arcB_profiles.parquet` + `arcB_channels.parquet`
  (float32/zstd, ~2.9 MB), so the tab is **live on the hosted app**; still gated on presence so it
  degrades gracefully if the artifacts are absent. Verified via `streamlit.testing` AppTest.
- **Kanektok-centered cross-section axis (B#3):** the arc section x-axis is re-centered on the
  Kanektok (x = 0), increasing toward the Uyak — it reads "stand in the Kanektok, walk the spill
  path toward the Uyak," and the Uyak sits at the ~3 km channel separation. The Gearon β anatomy
  now hangs off the channel at x = 0: bed ▼, crest ▲, an **H_M** measure bar (crest→bed) and an
  **H_AR** bar (crest→floodplain) with the **β** value labelled at the crest — the section *is* the
  β figure. Applied to both `arcB_sections.png` and the dashboard tab; a display-only reframe, so
  every β / superelevation number is unchanged.
- **Retired Approach A** (perpendicular-to-channel β, `beta_perpendicular.py`): superseded by the
  arc method; removed from the dashboard/map/docs. Result (β ≈ 0.41, modest levee) recorded in
  `AVULSION_ANALYSIS.md` §2; code recoverable from git history.

## ⬜ Optional next steps

- **Perpendicular β re-measurement** (rigor refinement) — the current β reads the ridge crest along
  the slightly oblique arc; a flow-perpendicular section at each channel would be truer to Gearon.
  *(No Uyak depth model — dropped by design; we only needed Kanektok depth stats + the mouth comparison.)*
- Combined figure overlaying the arc side-by-side on the SWOT WSE profile (B#5).
- Downstream stack/heatmap of the arcs (B#4).

## 🗂️ Script status (see README for details)

- **Current:** `build_arc_B.py`, `swot_arc_reference.py`, `ingest_adcp.py`,
  `build_uyak_centerline.py`, `build_kanektok_centerline.py`, `adcp_depth_stats.py`,
  `make_swot_centerline.py`, `centerline.py`, `map_transects.py`.
- **Legacy (Gearon β/γ/Λ port, not used by the current analysis):** `avulsion_metrics.py`,
  `build_transects.py`, `transects.py`, `pick_features.py`, `make_avulsion_figures.py`,
  `validation/`.
- **Removed 2026-08-19** (preliminary-ArcGIS β reproduction, no longer part of the analysis):
  `reproduce_beta.py`, `beta_floodplain.py`, `prototype_B.py`, `run_B.py`, `make_beta_figures.py`,
  `recover_original_beta.py`, `reference/original_beta.parquet`,
  `reference/avulsion_transects.gpkg`. Recoverable from git history.
