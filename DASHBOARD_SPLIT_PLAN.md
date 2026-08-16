# Dashboard Split Plan

*Drafted 2026-08-16, after PR #20 (hygiene sweep) merged. Decisions confirmed: full
restructure; `thesis_figures/` consumes the shared core; village app built now on the
provisional tab set (professor may adjust tabs later — cheap to swap once tabs are modules).*

## Goal

Two Streamlit apps from **one repo, one `main` branch**:

1. **Researcher app** — the existing dashboard, unchanged in behavior and URL.
   Entrypoint stays `dashboard_swot.py` so the current Streamlit Cloud deployment
   needs no reconfiguration.
2. **Village app** — a simplified outward-facing page for Quinhagak community use
   (NSF Award 2527256 Phase-2 community deliverable). New entrypoint
   `dashboard_village.py`, deployed as a second Streamlit Cloud app pointed at the
   same repo/branch.

Both apps and the thesis figures compute from **one implementation** of the math —
that is the whole point. No long-lived divergent branches (science drift risk).

## Target layout

```
swot_core/                  # PURE package: no streamlit import, headless-safe
    __init__.py
    config.py               # anchor point, reach names, thresholds, data URLs,
                            # RESIDUAL_MAD_THRESHOLD, ice months (re-export qc_registry)
    data.py                 # DuckDB connect (local + httpfs), loaders:
                            # swot points, reference gradient, decomposition,
                            # metadata, DEM profile/points, temporal results
    stats.py                # calculate_detrending, flag_residual_outliers,
                            # calculate_slope_profile, fine-scale grid/slope/aggregate
                            # helpers, elevation_difference
dashboard_tabs/             # streamlit tab renderers, shared by both apps
    common.py               # bifurcation line/marker, distance-axis styling,
                            # VerticalColorbar, pass checklist, cached wrappers
    tab_gradient_profile.py … tab_temporal.py, dem tabs, cross_sections.py
dashboard_swot.py           # researcher entrypoint: page config + welcome + full tab set
dashboard_village.py        # village entrypoint: welcome + subset of tabs
thesis_figures/
    core.py                 # shrinks to thin re-exports + figure-only helpers;
                            # all shared math imported from swot_core
```

**Caching design rule:** `st.cache_data` cannot live in `swot_core` (must import
headlessly for thesis figures). Pattern: pure functions in `swot_core`, thin cached
wrappers in `dashboard_tabs/common.py`. Cache keys keep the existing
`url_version` / selection-fingerprint discipline from the caching audit.

## Numerical regression gate (blocks every PR)

`tools/regression_gate.py` — computed **before** the refactor from current `main`,
snapshot committed; re-run after each PR and diffed to zero:

- Gated open-water refgrad medians + n (currently Kanektok 195.3 / Uyak 192.4).
- Binned-median gradient profile values for a fixed pass selection.
- Detrended-tab stats (baseline coefficients, residual quantiles, MAD flag count)
  for the same fixed selection.
- Fine-scale pass-matrix checksum + honest `n_passes` at a fixed resolution/window.
- Elevation-difference paired series summary stats.
- Thesis-figure numbers: regenerate SWOT Figs 4/5/7/9 inputs via `thesis_figures`
  and compare the underlying arrays (not the PNGs) to pre-refactor values.

## PR sequence

**PR A — extract `swot_core` (math + loaders + config).** *(IN PROGRESS 2026-08-16,
branch `refactor/swot-core`.)*
Both `dashboard_swot.py` and `thesis_figures/core.py` import from it; duplicated
functions deleted at both sites. No UI change, no behavior change. Regression gate
snapshot created first, verified after.
Extraction findings: the copies HAD drifted — thesis core still carried the
pre-fix pooled-Gaussian `calculate_slope_profile` (smooths across coverage holes;
dashboard got the NaN-aware gap-honest rewrite 2026-08-14) and scaled-domain
`poly.coef` detrend coefficients. Unified on the dashboard's validated versions;
thesis Fig 8 regenerates under the gap-honest slope. Also resolved here: hygiene
idx 32 (dead LOESS branch — core raises on unknown detrend methods).

**PR B — split `render_dashboard()` (~2,600 lines) into `dashboard_tabs/` modules.**
One module per tab; fragments stop closing over ambient locals (explicit params).
Strictly mechanical (decided 2026-08-16): the regression gate must show ZERO
diffs — that is the proof the move changed nothing. No visual change; gate
re-run; manual smoke of every tab locally + on Cloud after merge. (Hygiene
idx 32 was already resolved in PR A.)
EXECUTED 2026-08-16. dashboard_swot.py 3,651 → ~450 lines (welcome page,
selection preamble, TabContext build, tab dispatch, summary block); ten tab
modules + dem_cross_sections.py + common.py (TabContext, presentation
constants, plot/map helpers, all Streamlit cache wrappers). Bodies moved
verbatim (audited line-by-line against the pre-split file); regression gate
passed in --strict mode with 0 diffs on the untouched gate code, and an
AppTest smoke rendered all 17 tabs without exceptions. One genuine bug found
by the smoke and fixed: the cross-section artifact paths were __file__-relative
and broke when the code moved into the package — now anchored to the repo root.
Also removed six dead swot_core imports left by PR A and a stray f-prefix.

**PR B2 — the two numbers-touching hygiene deferrals, isolated.**
Split out of PR B (2026-08-16) so the tiny numerical shifts are the ONLY change
in their diff. idx 33: one shared binning helper, standardized on
half-away-from-zero (DuckDB's convention — the 6 SQL sites do the heavy binning;
the 4 `np.round` banker's sites adopt the helper; moves 24 exact-boundary
points). idx 42: Map View reuses the canonical detrend fit instead of its own
2nd-order fit (≤9 cm apart today). Gate re-run with these as the pre-declared
allowances; baseline re-snapshot.
EXECUTED 2026-08-16. `swot_core.stats.round_half_away` added (only exact .5
ties are overridden — no floor(x+0.5) drift) and adopted at the 5 numpy binning
sites found on main (the triage's "4" predates the split: the two thesis-figure
node binnings counted as one). Boundary count re-measured and matches the
triage: 14 ties at the 0.1/0.5 km widths (7 change bins) + 10 at 1.0 km
(SQL-only) = 24. Map View residuals now evaluate the `load_detrend_frame` fit
at the plot sample's points (removes a measured ≤2.7 cm map-vs-tab
disagreement on the 2026 selection; both calls are cache hits, no added work).
Gate: PR-A allowances retired, PR-B2 families pre-declared in DEFAULT_ALLOW;
compare passed with 21 expected diffs / 0 unexpected (all thesis-surface,
≤1e-5 cm/km — nothing at reported precision; `dashboard.slope_profile` was
declared but showed zero diffs since its sampled 2026 frame keeps no tie
points); baseline re-snapshotted, --strict now 0 diffs; AppTest smoke 17 tabs
clean; THESIS_IMPACT_LOG entry 14 (no touchpoints).

**PR C — village app.**
`dashboard_village.py` composing the provisional set: Welcome (plain-language),
Map View, Gradient Profile, Elevation Difference, Temporal bottom-line.
Researcher-only tabs excluded: Fine-Scale Slope, Cross-Sections, Detrended,
decomposition, Raw Data. Plain-language captions; NSF Award 2527256 attribution
on the welcome page (required in all project metadata). Deploy as second
Streamlit Cloud app; both read the same v2.0-data release parquet.

## Notes / open items

- Village tab set is provisional pending professor feedback; because tabs are
  modules after PR B, swapping the set is a few lines in `dashboard_village.py`.
- `qc_registry.py` stays importable at repo root (SWOT_Pull depends on it);
  `swot_core.config` re-exports rather than moves it, to avoid touching ingestion.
- Map performance ceiling at all-passes (caching audit) may bite harder on the
  village app's default view — pick a lighter default pass selection there.
- Village-app content/tone (what question a resident is asking, translation
  needs) to be discussed before PR C polish; the tab skeleton doesn't block it.
