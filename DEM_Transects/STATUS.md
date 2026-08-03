# DEM_Transects — status

Avulsion analysis for the Kanektok & Uyak. **Full methods, results, and caveats:
[`AVULSION_ANALYSIS.md`](AVULSION_ANALYSIS.md)** (the single source of truth for the science).
This file tracks build status only. Last updated 2026-08-03 (B#3: Kanektok-centered cross-section axis + β anatomy overlay).

---

## ✅ Done

- **Recovered the prior ArcGIS method** (β = (P98−median)/(P98−P2)) and its intended result
  from the project geodatabase (β med 0.96, H_AR 4.30 m) — the notebook run that would have
  saved it had errored.
- **Diagnosed the diagonal-transect artifact:** the straight-guide-line transects run
  obliquely, so the apparent Kanektok superelevation was ~90 % down-valley gradient. Confirmed
  against the SWOT dashboard (Uyak marginally higher at matched distance).
- **The arc method** (`build_arc_B.py`) — radial iso-distance-from-anchor cross-sections, the
  dashboard-comparable side-by-side. Sampled at native 2 m; channels snapped to the DEM low.
  **Uyak water surface +1.45 m above Kanektok on 92 % of arcs**, but superelevation vs the
  inter-channel corridor shows the **Kanektok incised on 98 % of arcs (−1.52 m)** and the
  **Uyak ≈ at grade (−0.21 m)** → against a Kanektok→Uyak avulsion. Figures `arcB_sections.png`,
  `arcB_sidebyside.png`, `arcB_validity.png`.
- **Measured Gearon β = H_AR/H_M for the Kanektok** using the boat-ADCP channel depth (bed = DEM
  water surface − depth). β median **0.24**, below the avulsion threshold of 1 on **100 %** of arcs
  (H_AR ≈ 0.87 m, H_M ≈ 3.85 m, ADCP depth ≈ 1.30 m). Reconciles + sharpens the retired DEM-only
  Approach A (β ≈ 0.41 → 0.24 once the real bed deepens H_M). Depth artifact
  `data/kanektok_thalweg_depth.parquet` (emitted by `build_kanektok_centerline.py`); figure
  `arcB_beta.png`; shown in the dashboard ✂️ Cross-Sections tab (β / H_AR / H_M metrics + bed/crest
  markers). Uyak β deferred (ADCP depth near its mouth only).
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
  metrics, long-profiles). Reads `arcB_profiles.parquet` locally; the tab hides itself when the
  artifact is absent (e.g. on Streamlit Cloud). Verified via `streamlit.testing` AppTest.
- **Kanektok-centered cross-section axis (B#3):** the arc section x-axis is re-centered on the
  Kanektok (x = 0), increasing toward the Uyak — it reads "stand in the Kanektok, walk the spill
  path toward the Uyak," and the Uyak sits at the ~3 km channel separation. The Gearon β anatomy
  now hangs off the channel at x = 0: bed ▼, crest ▲, an **H_M** measure bar (crest→bed) and an
  **H_AR** bar (crest→floodplain) with the **β** value labelled at the crest — the section *is* the
  β figure. Applied to both `arcB_sections.png` and the dashboard tab; a display-only reframe, so
  every β / superelevation number is unchanged.
- **Retired Approach A** (perpendicular-to-channel β, `beta_perpendicular.py`): superseded by the
  arc method; removed from the dashboard/map/docs. Result (β ≈ 0.41, modest levee) recorded in
  §3; code recoverable from git history.

## ⬜ Optional next steps

- **Perpendicular β re-measurement** (rigor refinement) — the current β reads the ridge crest along
  the slightly oblique arc; a flow-perpendicular section at each channel would be truer to Gearon.
  *(No Uyak depth model — dropped by design; we only needed Kanektok depth stats + the mouth comparison.)*
- Combined figure overlaying the arc side-by-side on the SWOT WSE profile (B#5).
- Downstream stack/heatmap of the arcs (B#4).

## 🗂️ Script status (see README for details)

- **Current:** `build_arc_B.py`, `build_uyak_centerline.py`, `build_kanektok_centerline.py`,
  `adcp_depth_stats.py`, `make_swot_centerline.py`, `centerline.py`, `map_transects.py`.
- **Superseded / exploratory (kept for provenance):** `reproduce_beta.py` (single-zone first
  pass), `beta_floodplain.py` (single-analysis two-zone — demonstrated the artifact),
  `prototype_B.py` + `run_B.py` (early two-rivers-with-detrend framing), `transects.py` (the
  perpendicular-transect machinery behind the retired Approach A).
- **Legacy (Gearon β/γ/Λ port, not used by the current reproduction):** `avulsion_metrics.py`,
  `build_transects.py`, `pick_features.py`, `make_avulsion_figures.py`, `validation/`.
