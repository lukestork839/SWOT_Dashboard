# Hygiene-Findings Triage — August 2026

Disposition of the 58 unverified hygiene findings from the Phase B code review
(`docs/phaseB_findings_UNVERIFIED.json`, minus the 22 verified findings fixed in the
August 2026 campaign, minus 4 duplicates absorbed by those fixes). Every item below
was re-verified against the post-campaign code (HEAD `9544d54`) before triage —
line numbers cited here are **current**, not the stale ones in the JSON.

**Verdict key:** FIX NOW (this sweep) · DEFER-SPLIT (fold into the dashboard-split
refactor) · DEFER-Q3 (revisit at the Sep 2026 typhoon rerun) · DEFER-REBUILD (next
arcB artifact rebuild) · RESOLVED (already fixed) · WON'T FIX (verified benign) ·
DECISION (needs owner call, see bottom).

`idx` refers to `scratchpad hygiene58_sorted.json` ordering / the review JSON items.

## Summary

| Verdict | Count |
|---|---|
| FIX NOW (all applied 2026-08-16) | 40 |
| RESOLVED (already fixed by campaign) | 4 |
| MOOT (target files already deleted) | 1 |
| Duplicates (merged into another item) | 2 |
| WON'T FIX | 4 |
| DEFER-SPLIT | 3 |
| DEFER-Q3 | 1 |
| DEFER-REBUILD | 1 |
| DECISION points inside FIX NOW items | 4 (all resolved, see bottom) |

## Already resolved (no action)

| idx | Finding | How it resolved |
|---|---|---|
| 8 | Duplicate QC registries (SWOT_Pull vs thesis_figures/config) | `qc_registry.py` single-sources; config imports it |
| 19 | Methodology claims "dashboard warnings Oct–May" | 2026-08-14 revision: enforced-at-ingestion May–Oct line |
| 41 | stats_df avg_slope computed but never shown | `slope_calc`/`avg_slope` removed file-wide in campaign |
| 53 | Stale 37/136 shoulder-month stats in temporal comment | Comment block replaced by qc_registry import |

Residual nit from idx 19 verification, folded into FIX NOW: `SCIENTIFIC_METHODOLOGY.md:307-310`
ice table still labels Oct–Nov "Caution" though Oct is inside `ICE_SAFE_MONTHS`.

## Duplicates

- idx 40 ≡ idx 5 (ice-warning-vanishes; identical lines) — triaged as idx 5.
- idx 45 ≡ idx 46 (stale detrend-method guidance text; 46 is the superset) — triaged as idx 46.

## FIX NOW — mediums

| idx | Where | Fix |
|---|---|---|
| 0 | `DEM_Transects/swot_arc_reference.py:56` | Classes filter 3–7 → 3–4; drop stale fallback parquet (still contains excluded 2025-04-17); import qc_registry |
| 1 | ~~DEPLOYMENT.md / NEXT_STEPS.md / DEPLOYMENT_SUMMARY.md~~ | **MOOT** — the three files were untracked in Feb 2026 (2e34273) and no longer exist on disk; the verify agent misreported them as present. Nothing to fix |
| 2 | `README.md:127-168` | Delete phantom "Sidebar Controls" section; fix Gradient-Profile "linear regression trendlines" claim; add missing tabs to the table (full UI rewrite deferred to split) |
| 3 | `SCIENTIFIC_METHODOLOGY.md:602,614,1469` + `SWOT_Pull.py:79` | "~70 km" → ~36 km; "confluence (where rivers meet)" → bifurcation/anchor terminology; fix stale line refs at :571. Thesis-relevant → THESIS_IMPACT_LOG entry |
| 4 | 6 files carrying "~0.34 m" differential-stage artifact | Recomputed from committed artifact: **+0.27 m** per-arc median (n=64). Restate in all 6 sites; add provenance print to swot_arc_reference.py. Thesis-relevant → THESIS_IMPACT_LOG entry |
| 5(+40) | `dashboard_swot.py:1408-1416` | Move ice-season warning above the `:1396` reload branch so it persists across reruns |
| 6 | `dashboard_swot.py:3746-3772` | Typhoon spatial-delta: fixed y-range [−0.5,0.5] now clips 4 real points (max +0.69 m); widen/auto-range and temper the "hugs zero" caption (bootstrap verdict stays "indistinguishable") |
| 7 | `requirements.txt:5`, `requirements-full.txt:13` | Streamlit floor `>=1.35`/`>=1.28` doesn't cover `width="stretch"` (25 uses); raise both pins |

## FIX NOW — ingestion hardening (SWOT_Pull.py, no re-pull required)

| idx | Where | Fix |
|---|---|---|
| 20 | `:28`, `:295` | Delete dead `XOVERCAL_SUSPECT_MASK` + unused `height_cor_xover_qual` extraction |
| 21 | `qc_registry.py:40` | Date-qualify the hardcoded exclusion medians ("as of the 2026-07 archive") |
| 22 | `:92` | Scope the blanket `warnings.filterwarnings("ignore")` to known noisy categories |
| 23 | `:188` | Hard-fail when polygon CRS is missing instead of silently assuming 4326 |
| 24 | `:262,:417,:676-712` | Count and report failed/empty downloads in the run summary (**DECISION A**: also write skip-sentinels?) |
| 25 | `:288` | Silent `load_tide=0` fallback (**DECISION B**: warn+flag column vs NaN) |
| 26 | `:329` | Warn when the cross-track filter is skipped (absent/all-NaN variable) |
| 27 | `:397` | `> 5` → `>= MIN_POINTS_AFTER_FILTER` (off-by-one vs the named constant; admits exactly-5-point sets at next pull; refgrad unaffected — can't reach REFGRAD_MIN_NODES) |
| 28 | `:256,:234` | Skip unparseable granule names instead of colliding on `Unknown_Date` (which now aborts rebuild via DateParseError); the master/refgrad divergence half is moot |

## FIX NOW — dashboard cleanups

| idx | Where | Fix |
|---|---|---|
| 29 | `:10,:13` + repo root | Delete unused `gc`/`MeasureControl` imports. `dashboard_swot.py.backup` is **untracked** — deletion unrecoverable (**DECISION C**) |
| 30 | `:225,:1494` | Guard `calculate_detrending` against <3-point (degenerate) inputs at both call sites |
| 31 | `:156,:161` | `poly.coef` → `poly.convert().coef` (coefficients currently in numpy's scaled domain — latent trap; no consumer today) |
| 34 | `:448` | `n_passes` counts passes that contributed no data; count finite columns instead (reliability gate + legend become honest; gate may fire on selections that previously passed) |
| 36 | `:548` | Delete orphaned `compute_finescale_slope` (zero callers, diverged gating, missing cache decorator); update `core.py:211` comment |
| 38 | `:1332` | Correct the Return-to-Homepage comment (checkbox states are NOT preserved); leave UX behavior as is |
| 39 | `:1398` | Escape single quotes in reach names interpolated into SQL (byte-identical for current names; cache keys unchanged) |
| 43 | `:2281,:2464` | Remove dead `!= 2` gate; reword misleading "Single river selected" warning (fires per-pass, not per-selection) |
| 44 | `:2407,:3672` | Delete dead `loess_smooth`; unused correlation `r` handled under **DECISION D** |
| 46(+45) | `:2585,:2605,:2613-2641` | Detrend guidance text recommends switching to methods that no longer exist; rewrite for the single hardcoded method (full detrend-UI restructure deferred to split with idx 32) |
| 47 | `:3304` | Trim map Classification legend to classes {3,4} (5–7 cannot occur post-ingestion) |
| 48 | `:3343,:3383` | Disclose the ±3 m residual clip in the colorbar caption |
| 49 | `:3672-3684` | Stage-invariance correlation computed, never shown (**DECISION D**: display it or delete it) |
| 50 | `:3766` | Typhoon spatial-delta is the only distance chart without the reversed x-axis convention; add `autorange="reversed"` |
| 51 | `:3877` | "Passes Analyzed" metric counts from the sampled viz_df; use the selection's true pass count |

## FIX NOW — DEM scripts, figures, small docs

| idx | Where | Fix |
|---|---|---|
| 9 | `.streamlit/config.toml:47` | Comment mislabels #1f77b4 as "Dodger blue (matches Uyak Creek)" (Uyak is #1E90FF); fix the comment |
| 10 | `DEM_Pull.py:210` | Add `gdf = gdf.to_crs(4326)` (identity today; guards future polygon swaps) |
| 11 | `DEM_Transects/avulsion_metrics.py:6` | Docstring claims "production core"; it's validation-only — correct it (routing production through it is a refactor we're not doing) |
| 12 | `build_arc_B.py:24,:194` + `swot_arc_reference.py:11` | Geoid comment endpoints 13.77/13.27 are extrapolations; artifact's actual endpoints are 13.74 @ R=3.0 / 13.28 @ R=34.5 |
| 15 | `SCIENTIFIC_METHODOLOGY.md` | Document the spherical-distance convention (~0.36 % understatement, uniform across both rivers — comparisons unaffected). Do NOT switch to ellipsoidal Geod (would shift every published cm/km and force lockstep artifact regeneration). THESIS_IMPACT_LOG entry |
| 16 | `build_arc_B.py:203` | Add rationale comment on the z==0 mask (it is load-bearing: rejects rasterio boundless fills — never remove) |
| 18 | `swot_arc_reference.py:4,:135` | Docstring says "full SWOT pixel archive" but source is dashboard_data.parquet (50 of 95 ice-safe passes, 2025+); fix docstring + write source/pass-count/date-range provenance into the output. Repointing to the master is a science decision we are NOT making here |
| 52 | `requirements.txt:20-21` | tqdm claimed "used by dashboard loading indicator"; dashboard never imports it — remove (stays in requirements-full) |
| 55 | `thesis_figures/DASHBOARD_TODO.md` | Strike implemented items 2, 3, 6 (item 4 = idx 3, genuinely open, being fixed now) |
| 56 | `thesis_figures/core.py:222-259` | Delete savgol/gaussian fine-slope estimators (dashboard deleted them in the campaign; sole caller uses theilsen); fix stale "Ported VERBATIM" comment |
| 57 | `thesis_figures/core.py:359` | Docstring claims dashboard still uses pooled AVG; dashboard adopted the identical paired method — fix docstring |

## Deferred

| idx | Verdict | Rationale |
|---|---|---|
| 32 | DEFER-SPLIT → RESOLVED (split PR A, 2026-08-16) | LOESS detrend branch was dead (method hardcoded); the swot_core extraction removed it — `swot_core.stats.calculate_detrending` raises on unknown methods instead of silently falling through to LOESS |
| 33 | DEFER-SPLIT | np.round (banker's) vs DuckDB ROUND (half-away) binning convention — needs one shared helper across 6 SQL + 4 Python sites; natural swot_core consolidation. Affects only exact-.5-boundary points (24 today) |
| 42 | DEFER-SPLIT | Two coexisting 2nd-order detrend fits (map vs tab, ≤9 cm apart) — coefficient plumbing through the cache layer is a swot_core job |
| 54 | DEFER-Q3 | `TYPHOON_DATE` doesn't drive the June comparison windows; derive windows from it when the definitive Q3 rerun happens (~Sep 2026). Trivial comment demotion applied now |
| 17 | DEFER-REBUILD | Snap-window "clipped" QC flag can miss wall-limited picks; fixing changes an artifact QC column and breaks byte-identity checks — batch into the next arcB rebuild |

## Won't fix

| idx | Rationale |
|---|---|
| 13 | R_EARTH 6371.0088 vs 6371.0 → ≤5 cm over 35 km; standardizing would invalidate byte-identity of cached artifacts for zero scientific gain |
| 14 | "ADCP median 1.30 m" comment verified accurate; nothing to change |
| 35 | Fine-grid `pos = ix-1` bin-0 drop is structurally unreachable (min dist_km ≈ 0.30 km ≥ grid start); paired-edit risk exceeds benefit |
| 37 | `CH_WIN_M = 250.0` duplicated dashboard↔build script but values agree and it only draws a highlight band; plumbing it through the parquet is not worth an artifact rebuild |

## Decision points (resolved 2026-08-14)

- **A (idx 24):** RESOLVED — write skip-sentinels for permanently-empty granules. Caveat documented: delete sentinels if the river polygons ever change.
- **B (idx 25):** RESOLVED — warn + boolean `load_tide_missing` flag column; keep the 0 substitution.
- **C (idx 29):** RESOLVED — delete `dashboard_swot.py.backup`.
- **D (idx 49):** RESOLVED — delete the unused correlation computation; the caption stands on the visual.
