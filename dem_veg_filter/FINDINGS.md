# Vegetation-inflation filtering of ArcticDEM — findings

**Question:** The dashboard's DEM data file (`dem_river_elevations.parquet`, from `DEM_Pull.py`)
is raw ArcticDEM V4 — a photogrammetric **DSM** that sits on top of vegetation. A manager
flagged a sinuous "snaky high" of apparent vegetation inflation in the hillshade. Can a
moving-window **median or low-percentile filter** recover bare-earth and improve the DEM,
validated against NOAA QL1 LiDAR ground truth? And does it beat the previously-tried,
MERIT-calibrated NLCD×EVI correction (which *degraded* accuracy: RMSE 0.55 → 0.65 m)?

**TL;DR:** Vegetation inflation is **real but spatially localized** (~4% of pixels in the
tested area, ~+0.8 m where present). **No global filter improves the DEM** — median and
low-percentile filters all damage the abundant already-accurate bare ground to fix a small
inflated fraction. A **vegetation-gated low-percentile filter** beat raw at 10 m — **but only
with an *oracle* gate** (veg pixels labelled by the LiDAR residual itself). When rebuilt at
2 m with a *deployable* gate (Sentinel-2 NDVI + top-hat), it **degraded** the DEM: the gate
unavoidably selects real fluvial relief (cutbanks, levees, ridges — which are locally-high
*and* vegetated) and flattens it. **Final verdict: keep raw ArcticDEM, do not filter.** A DEM+NDVI
filter cannot separate vegetation-highs from terrain-highs; a true correction needs independent
canopy-height data (ICESat-2 / WorldView CHM / extended LiDAR), which we don't have corridor-wide.
The manager's instinct was sound and worth testing — the data just shows the signal isn't cleanly
separable here. See the 2 m follow-up section below for the numbers.

---

## Method

- **DEM under test:** `batch_outputs/arcticdem_rivers.tif` (ArcticDEM V4, ~10 m, WGS84
  ellipsoidal).
- **Ground truth:** `/home/luke/University/ArcticDEM/lidar_dem_wgs84.tif` (NOAA 2024 QL1
  LiDAR, 1 m bare-earth, NAVD88), resampled (averaged) onto the ArcticDEM grid.
- **Datum alignment:** single bare-ground offset **12.765 m** (the GEE NLCD-bare-ground
  value, validated at 2 m). A low percentile of (ArcticDEM−LiDAR) gives 12.26 m but is
  biased low by negative photogrammetric noise at cutbanks/water edges — *not* used.
- **Pixel stratification** (after alignment): **bare/matched** = |residual| ≤ 0.3 m;
  **vegetated/inflated** = residual > 0.5 m. A good filter must cut veg bias/RMSE toward 0
  **without** harming bare ground (no new negative bias).
- **Filters swept:** median + percentile{10,20,30,40} × windows{50,100,150,200,300 m},
  plus vegetation-**gated** variants. Script: [`filter_experiment.py`](filter_experiment.py).

Coverage: the LiDAR strip is the coastal reach near Quinhagak — **238,571 valid pixels**,
58% bare, 4% inflated. (It covers only ~17% of the Kanektok corridor and 0% of Uyak — see
Caveats.)

## Results (residual = candidate − LiDAR, metres)

| filter | all RMSE | all mean | bare RMSE | bare mean | veg RMSE | veg mean |
|---|---|---|---|---|---|---|
| **raw ArcticDEM (aligned)** | **0.442** | −0.046 | **0.165** | +0.040 | 0.949 | +0.825 |
| median 50 m | 0.463 | −0.056 | 0.210 | +0.044 | 0.826 | +0.670 |
| median 300 m | 0.635 | −0.085 | 0.458 | +0.048 | 0.799 | +0.350 |
| p20 50 m (global) | 0.582 | −0.241 | 0.314 | −0.108 | 0.631 | +0.259 |
| p10 50 m (global) | 0.682 | −0.340 | 0.415 | −0.191 | 0.654 | +0.090 |
| **GATED p20 50 m (oracle)** | **0.417** | −0.070 | 0.165 | +0.040 | 0.631 | +0.259 |
| GATED p30 50 m (oracle) | 0.418 | −0.065 | 0.165 | +0.040 | 0.648 | +0.366 |
| GATED p20 100 m (oracle) | 0.423 | −0.083 | 0.165 | +0.040 | 0.714 | −0.038 |

Full sweep: [`outputs/filter_results.md`](outputs/filter_results.md) /
[`.csv`](outputs/filter_results.csv). Maps: [`outputs/inflation_maps.png`](outputs/inflation_maps.png).

## Interpretation

1. **Raw ArcticDEM is already excellent on bare ground** (RMSE 0.165 m, +0.04 m bias) and
   near-zero in aggregate (−0.046 m) — reproducing the earlier whole-footprint finding.
2. **The inflation is real and localized.** On the ~4% inflated pixels ArcticDEM is **+0.83 m**
   high (RMSE 0.95 m). Averaged over everything this nearly vanishes — which is exactly why
   aggregate RMSE hid it and the hillshade did not. These are the "snaky high" pixels, and
   they are the alluvial-ridge-relevant geometry.
3. **Median filters** barely dent the veg bias unless the window is large, and large windows
   wreck bare ground (300 m: bare RMSE 0.165→0.458). This is the manager's "overestimates
   bulk areas / smooths real terrain."
4. **Global low-percentile filters** do cut veg bias (p10-50 m: veg mean 0.83→0.09) **but**
   introduce a negative bias on bare ground (−0.19 m) and raise overall RMSE — the
   documented failure mode (Baugh 2013; Lee/Kang 2025). They over-cut the 58% good ground to
   fix the 4% bad.
5. **Vegetation-gated wins, and is the only thing that beats raw.** GATED p20-50 m:
   overall RMSE **0.442 → 0.417**, bare ground **untouched** (identical to raw), veg bias
   **0.825 → 0.259 m** (−69%). Surgical correction of inflated pixels only.

## Follow-up: 2 m all-in-GEE test with a REAL gate — the gated approach does NOT survive

The 10 m winner used an **oracle** gate (LiDAR residual labels the veg pixels). We rebuilt it
at native 2 m in GEE with a *deployable* gate (Sentinel-2 NDVI + water-masked percentile),
script `ArcticDEM/kanektok_bareearth_filter.js`. Two configurations, both vs LiDAR:

| config | all RMSE | all mean | bare(NLCD) RMSE | bare mean | gated-px mean |
|---|---|---|---|---|---|
| raw ArcticDEM (2 m) | **0.549** | −0.048 | **0.433** | ~0 | — |
| NDVI>0.2 gate, p20/50 m | 0.711 | −0.294 | 0.568 | −0.207 | −0.30 |
| + top-hat (excess>0.5 m) | 0.672 | −0.166 | 0.541 | −0.090 | **−0.94** |

**Both degrade raw.** Why:
1. **NDVI>0.2 is too broad.** Raw ArcticDEM over NDVI-vegetated pixels is *already unbiased*
   (mean −0.04 m) — most low shrub/sedge is at bare-earth. Lowering it all injects a −0.3 m
   bias and even hurts NLCD-"bare" sedge/moss (which are green in summer).
2. **The top-hat selector (`NDVI AND locally-high`) selects REAL fluvial relief** — cutbanks,
   levee crests, alluvial ridges — because they are locally high *and* vegetated (willow grows
   on banks). Replacing them with the local p20 (which includes the lower channel/floodplain)
   over-lowers them by ~0.94 m. **We flatten the very features the avulsion analysis measures.**

### Per-class check: is NLCD 41 (densest deciduous) the inflated culprit? — No.
Hypothesis: apply a small per-class *constant offset* (shape-preserving, unlike the filter)
to NLCD class 41, the densest riparian deciduous, co-located with the manager's snaky high.
Per-class raw ArcticDEM−LiDAR within the strip (2 m):

| NLCD class | mean (m) | std | count px |
|---|---|---|---|
| 41 deciduous | **−0.30** | 0.72 | 148,896 |
| 52 shrub/scrub | −0.30 | 0.57 | 11,576 |
| 51 dwarf scrub | +0.29 | 0.24 | 305,104 |
| 90 woody wetlands | −0.16 | 0.57 | 993,400 |
| 95 emergent herb wetland | −0.06 | 0.49 | 920,055 |
| 31 barren | −0.21 | 0.51 | 110,332 |
| 72 sedge | +0.04 | 0.40 | 466,299 |
| 74 moss | +0.27 | 0.11 | 22,416 |

**Class 41 is NEGATIVE (−0.30 m) vs LiDAR — not inflated; it's among the lowest classes.** A
downward offset would make it worse. The earlier **+0.716 m for class 41 was a pure MERIT
artifact** (MERIT reads low in the valley); LiDAR shows the opposite sign. Per-class biases are
all small (±0.3 m), inconsistent in sign, and don't track canopy height — no coherent
class-correlated inflation exists. Caveats: bare-class datum disagrees ±0.25 m (31:−0.21,
72:+0.04, 74:+0.27); the strip holds only ~0.6 of ~14.5 km² of corridor class 41 (rest upstream,
unvalidated). **Reframe:** a sinuous channel-hugging high co-located with riparian veg is the
textbook signature of a real **alluvial ridge/levee** — the ground truth supports the snaky
high being largely *real topography*, so filtering it would delete signal, not noise.

### Conclusion: keep raw ArcticDEM; do not filter
A DEM+NDVI filter **cannot separate vegetation-highs from terrain-highs**, because real
levees/ridges/banks are themselves locally-high and vegetated. Every *safe* configuration
converges to a no-op (≈ raw); every configuration that removes real inflation also shaves real
relief. There is **no useful operating point**. The 10 m "win" required a LiDAR-defined oracle
gate that is unavailable corridor-wide. **Recommendation: keep raw ArcticDEM in the dashboard
and document the localized vegetation uncertainty.** Both the MERIT-calibrated correction
(degrades vs LiDAR) and the morphological/percentile filters (this section) are rejected.

### What COULD work (needs new data, not a cleverer filter)
A real bare-earth correction needs an independent **canopy-height** signal, not DEM geometry:
- **Meddens et al. (2018)** ArcticDEM + WorldView-2 canopy-height model for Alaska (RMSE 1.8–2.4 m
  — coarser than our 0.5 m target, so likely not worth it here).
- **ICESat-2 ATL08** `h_canopy` / `h_te_best_fit` ground photons along-track (sparse but true).
- Extend the **NOAA QL1 LiDAR** coverage upstream (the clean solution; none currently exists).

See [`PRIOR_ART.md`](PRIOR_ART.md) for method lineage (SMRF/Pingel 2013, progressive
morphological/Zhang 2003, Baugh 2013 50–60% rule, FABDEM/Hawker 2022, Meddens 2018 ArcticDEM-Alaska).

## Caveats

- **LiDAR coverage:** all validation is in the coastal strip — ~17% of Kanektok, **0% of
  Uyak**. The *method* generalises; the specific numbers are coastal. Uyak (narrower, more
  vegetated) is unvalidated and is where a gated correction may matter most.
- **Oracle gate = upper bound.** A real NDVI gate is imperfect; expect a smaller-than-ideal
  aggregate gain. The mechanism (preserve bare, fix veg) is what's proven.
- **Aggregate gain is small here (0.025 m)** because veg is only 4% of the coastal strip.
  Upstream/Uyak vegetation fractions are likely far higher, so the practical benefit — and
  the benefit to the avulsion ridge-height signal — is expected to be larger there.
