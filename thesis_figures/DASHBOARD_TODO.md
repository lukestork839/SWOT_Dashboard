# Dashboard Improvements — Deferred (surfaced during thesis-figure work)

Running list of live-dashboard (`dashboard_swot.py`) and doc changes noticed while
building thesis figures. **Do not action these until figure creation is complete.**
Each entry: what, why, where.

---

## From Figure 5 (Absolute Spatial Gradient Profile)

1. ~~Recolor the dashboard~~ — RESOLVED. Decided to match the dashboard instead:
   thesis figures now use the dashboard's own `firebrick`/`dodgerblue`. No change needed.

2. ~~Reconsider the density-biased linear trendline on the Gradient Profile tab~~ — RESOLVED
   (August 2026): the tab now draws binned-median profile lines; the headline gradient is
   the per-pass Theil–Sen value on the Hydraulic Gradient tab.
   - What: the Gradient Profile tab draws a linear OLS trendline with a cm/km slope in
     the legend. Fig 5 deliberately omits it (the honest gradient is the Theil–Sen
     value in Fig 4 / Hydraulic Gradient tab).
   - Why: the slope shown is density-biased (the dashboard's own Hydraulic Gradient tab
     explains this). Front-and-centre on the first tab, it can mislead. Consider
     de-emphasizing, annotating as "not the reference gradient", or replacing with the
     binned-median profile line used in Fig 5.
   - Where: `tab1` (~line 861–884).

3. ~~Fix stale distance convention in README~~ — RESOLVED (August 2026): README now says
   ~36 km = coast.
   - What: README says "~70 km = coast". Actual river extent from the anchor is
     **~35–36 km** (data max ≈ 36.2 km). The `~70 km` figure is wrong.
   - Why: doc accuracy; the thesis uses the correct ~35 km extent.
   - Where: `README.md` "Distance Calculation" section (convention line).

---

## From Figure 7 (Detrended Relative Elevation Profile)

4. ~~"Confluence" terminology is wrong throughout the codebase~~ — RESOLVED (August 2026
   hygiene sweep): code comments, README, and SCIENTIFIC_METHODOLOGY now say "anchor point"
   (~2.5 km upriver of the bifurcation). Original note kept below. The 0 km point is
   the **anchor point** (~2.5 km UPRIVER of the bifurcation), NOT the confluence.
   README says "0 km = anchor/confluence" and calls it the "confluence anchor point";
   dashboard docs/labels likely echo this. Correct to just "anchor point" so it does
   not contradict the bifurcation marker. (Thesis figures already fixed via
   style_distance_axis.)

5. **Verify the Uyak ~8–13 km residual hump (+2 to +2.7 m) on clean data.** The Fig 7
   detrended profile shows a broad Uyak-high stretch at 8–13 km that survives the
   per-river residual-MAD flag. May be real, or residual polygon leakage beyond the
   main lake at ~5 km. Re-check after the polygon-cleaned re-download.

## QC exclusion propagation (from Figure 4)

6. ~~Propagate the 2025-04-17 bad-pass exclusion project-wide~~ — RESOLVED (August 2026):
   `qc_registry.KNOWN_BAD_PASSES` single-sources the exclusion for SWOT_Pull,
   thesis_figures, and (via the regenerated data) the dashboard and temporal analysis.
   Original note kept below. The thesis figures now
   drop pass **2025-04-17** (spring-breakup ice: reach gradient anomalously steep on BOTH
   channels at once — Uyak 236 / Kanektok 224 cm/km) via a documented registry
   `config.EXCLUDED_PASSES` in the figure module. For consistency this same exclusion
   should also apply to:
   - **`SWOT_Pull.py`** — add a documented `KNOWN_BAD_PASSES` set, excluded when building
     the master parquet + reference-gradient artifact (keep the daily CSV checkpoint intact
     for provenance). This is the CLEANEST single source: dashboard, figures, and temporal
     all inherit it from the regenerated data. Best done during tonight's re-download.
   - **`temporal_analysis.py`** — ensure the pass is excluded from temporal metrics if not
     already inheriting from the parquet.
   - **`dashboard_swot.py`** — inherits automatically if excluded at ingestion; otherwise add.
   Principle followed: QC flag / exclusion list, NOT a raw-data edit — raw remains inspectable.

## Data observations (not necessarily dashboard changes)

- **Elevated-lake polygon leak (Uyak, ~59.837, -161.432, ~5 km downriver):** persistent
  spike across 21 passes, WSE ~10-20 m above channel. Root cause = pond captured inside
  the Uyak polygon. **Polygon refined by user 2026-07-13**; data re-download pending
  (tonight) so figures pick up the clean data via unchanged paths.
- **Mouth cluster (Kanektok, ~59.751, -161.925, ~33 km):** single contaminated pass
  (2026-04-08), NOT the lake. May persist after re-download unless the new polygon also
  clips that coastal pond. If it remains, handle via a residual-domain outlier filter
  (same Modified-Z method as the Detrended tab) rather than a polygon edit. DECIDE once
  clean data is in.
