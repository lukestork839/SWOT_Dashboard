# Results of Record

Canonical results of the Kanektok River / Uyak Creek avulsion-risk assessment, as reported
in the accompanying thesis. Every number below is computed by code in this repository from
the tracked or released data artifacts; the thesis is the authoritative narrative, and this
page is its public mirror. Methods: [`SCIENTIFIC_METHODOLOGY.md`](../SCIENTIFIC_METHODOLOGY.md).

**Question.** The village of Quinhagak, Alaska asked whether the Kanektok River (locally the
Qanirtuuq) — their water source and subsistence artery — is about to jump course into Uyak
Creek. The assessment tests the three measurable physical warning signs of avulsion setup.

**Verdict.** None of the three signs points toward a course change. The gradient advantage
favors the channel the river already occupies, and the topographic precursor (channel
superelevation) is absent. Monitoring continues because setup absent today can develop.

---

## The three warning signs

| # | Warning sign | Result | Reading |
|---|---|---|---|
| 1 | Reach-scale gradient advantage toward the alternative path | Kanektok **195.3 cm/km** (93 passes) vs Uyak **192.4 cm/km** (95 passes) — a **+2.9 cm/km (~1.5%)** advantage to the *currently occupied* channel | Present but small, and pointing the wrong way for avulsion |
| 2 | Localized gradient advantage at the bifurcation | **+24.6 cm/km** pass-paired advantage in the 1–5 km window; Kanektok steeper on **44 of 45** paired passes (ratio 1.110) | Concentrated exactly where flow divides — and it belongs to the Kanektok |
| 3 | Channel superelevation above the floodplain | Kanektok water surface **−1.50 m below** floodplain grade at median stage, on **100% of arcs**, still below (−1.01 m) at the high end of observed stage; **β median 0.06** | Absent — there is no alluvial ridge to perch on |

## Reference hydraulic gradient (reach scale)

Per-pass Theil–Sen fit on 1 km node medians; the reference gradient is the median across
coverage-gated open-water passes (May–October 2023–2026).

| | Kanektok River | Uyak Creek |
|---|---|---|
| Reference gradient | **195.3 cm/km** | **192.4 cm/km** |
| Gated full-coverage passes | 93 | 95 |
| IQR across passes | 195.06–195.61 (0.55 wide) | 191.42–193.16 (1.74 wide) |
| Per-pass standard deviation | 0.4 cm/km | 3.0 cm/km |

The 2.9 cm/km offset between the medians is several times larger than the entire width of
the Kanektok IQR.

## Bifurcation zone (fine scale)

Per-pass sliding Theil–Sen (0.5 km window on 100 m bins, ≥80% window coverage), evaluated
in the 1–5 km window at the channel split:

- Pass-paired medians **255.6 vs 229.2 cm/km** → **+24.6 cm/km**, Kanektok steeper on
  **44/45** paired passes.
- Immediately downstream (5–7 km) the same method gives **+41.0 cm/km** (17/18 passes).
- The advantage is stationary: per-year medians +24.1 / +26.0 / +23.5 cm/km (2024–2026),
  Theil–Sen trend −1.8 cm/km per year with a 95% CI spanning zero.

An independent terrain cross-check (ArcticDEM corridor medians) tracks the SWOT water slope
(Pearson r 0.43 Kanektok / 0.70 Uyak, bias +3–4 cm/km) and corroborates the direction of the
advantage; its between-channel magnitude is unstable against centerline preparation
(ratio 1.03–1.43), so the quantitative advantage is quoted from the centerline-free SWOT
measurement.

## Superelevation and β (topographic setup)

64 iso-distance DEM arcs (3–35 km at 0.5 km), channel picks snapped ±75 m to field
centerlines; superelevation = channel water surface minus the inter-channel floodplain
median; β = H_AR/H_M after Gearon et al. (2024), bed from the boat-ADCP survey.

| Metric | Value |
|---|---|
| Kanektok superelevation at median stage | **−1.50 m** (below floodplain on 100% of arcs) |
| … across observed stage (p10–p90) | −1.75 m (low water) to **−1.01 m** (high water) |
| Uyak superelevation at median stage | −0.49 m (≈ floodplain grade; above it on ~30% of arcs) |
| β median (Kanektok) | **0.06** — H_AR median +0.14 m, H_M median 2.86 m |
| Arcs with β ≤ 0 (no ridge at all) | 38% (24/63); maximum arc β 0.495, none reach 0.5 |
| Robustness | β median unchanged (0.06) under all three Gearon depth rules |

Pass-paired inter-river comparison: Uyak Creek runs **+0.96 m higher** than the Kanektok at
matched radii on 100% of passes (2,495 pass-radius pairs, 49 passes). Water escaping the
Uyak corridor would move down-elevation into the Kanektok — the trunk channel is the
topographic attractor, not the escape route.

ADCP survey (May–June 2026, ~39,500 pings): Kanektok median thalweg depth 1.22 m
(mean 1.29 ± 0.46, p10–p90 0.79–1.88, max 3.9 m); at the river mouth — the only reach
surveyed on both rivers — Kanektok 1.37 m vs Uyak 1.08 m (1.26× deeper).

Planform: full-length sinuosity Kanektok 1.484 vs Uyak 1.812 (DEM-snapped ratio 1.226) —
Uyak takes a substantially longer path to the same base level.

## Temporal stability and ex-Typhoon Halong

2023–2026 record (194 gated open-water passes: 96 Kanektok, 98 Uyak), Mann–Whitney tests
with a family-wise Holm correction over the 16-test family:

- Pooled cross-year gradient shifts: +0.11 cm/km Kanektok, +1.37 cm/km Uyak — neither
  significant even before correction. Seasonal (May vs July–August) swings of 0.2–0.4 m are
  predominantly not separable per year.
- **Ex-Typhoon Halong (landfall 2025-10-12):** comparing the full low-flow seasons on either
  side of landfall, water surfaces sat slightly *higher* after the storm (+0.09 m Kanektok,
  +0.35 m Uyak) — opposite in sign to channel-bed scour. The bootstrap 95% CI on the
  storm-versus-baseline excess fell at or below zero for the Kanektok ([−0.262, −0.002] m)
  and spanned zero for Uyak ([−0.374, +0.340] m): **the storm response did not exceed
  natural year-to-year variability.**
- Stage dependence: the Kanektok gradient is stage-invariant for practical purposes
  (−0.58 cm/km per meter of stage); Uyak carries +3.96 cm/km per meter (Spearman ρ = 0.72),
  which fully explains its small storm-window gradient shift.

## Dataset

| | |
|---|---|
| Archive | SWOT L2 HR PIXC, 2023-07-31 → 2026-08-10 |
| Granules | 209 May–October granules ingested; 120 with valid river pixels |
| Master dataset | 95 distinct pass-dates, **4,840,557** WSE measurements |
| Coverage gate | 188 full-coverage open-water passes (93 Kanektok, 95 Uyak) |
| Terrain | ArcticDEM v4.1 (2 m native; 10 m corridor sampling), EGM2008 per-radius geoid |
| Field | Boat ADCP survey 2026-05-28 → 2026-06-03; boat-GPS Uyak centerline 2023/2024 |

## Where each number comes from

| Result | Script | Artifact |
|---|---|---|
| Reference gradient, per-pass distribution | `SWOT_Pull.py` → `swot_core/stats.py` | `batch_outputs/reference_gradient_per_pass.parquet`; Fig. 5 via `thesis_figures/make_figures.py` |
| Fine-scale / pass-paired bifurcation advantage | `swot_core/stats.py::fine_slope_theilsen` (dashboard Fine-Scale Slope tab; thesis figures) | full master archive |
| β, superelevation, arcs | `DEM_Transects/build_arc_B.py` | `DEM_Transects/data/arcB_profiles.parquet`, `arcB_channels.parquet` |
| ADCP depths | `DEM_Transects/ingest_adcp.py`, `adcp_depth_stats.py` | `DEM_Transects/data/adcp_velocity_depth.parquet` |
| Sinuosity / DEM centerline | `DEM_Transects/build_dem_centerline.py` | `DEM_Transects/data/dem_centerline_*.parquet` |
| Temporal analysis, Halong bootstrap | `temporal_analysis.py` (verified by `verify_temporal_method.py`) | `temporal_results/` (tracked) |
| Numerical integrity | `tools/regression_gate.py` | `tools/regression_baseline.json` (515 gated outputs) |

---

*Supported by National Science Foundation Award 2527256 ("Dynamic Modeling of River
Ecosystem Stability"). SWOT L2 data: NASA/CNES via PO.DAAC. ArcticDEM: Polar Geospatial
Center (NSF-OPP 1043681, 1559691, 1542736).*
