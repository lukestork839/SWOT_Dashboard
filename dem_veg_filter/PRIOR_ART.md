# Prior Art: DSM-to-DTM Vegetation Removal via Morphological & Percentile Filters

Context: ArcticDEM V4 (2 m photogrammetric DSM, captures canopy top) over an Alaskan
river floodplain with low-stature riparian vegetation (willow, alder, tundra shrub,
sedge). Goal: recover a bare-earth DTM to resolve sub-meter floodplain / alluvial-ridge
relief for avulsion analysis. Method under test: moving-window low-percentile /
morphological filters on the gridded DSM, validated against LiDAR bare-earth.

---

## 1. Morphological & percentile ground filters (the established core)

### Progressive Morphological Filter (PMF)
- **Method**: Iterative morphological *opening* (erosion then dilation) on the surface.
  Window size grows progressively each pass; the elevation-difference threshold grows
  with it (and with terrain slope) so larger/taller objects are removed step by step
  while ground is preserved. Originally for airborne LiDAR point clouds, but the
  operation is the same on a gridded DSM.
- **Key parameters**: initial/max window size, elevation-difference threshold (often
  slope-scaled), and a max-slope term. Window must exceed the largest non-ground object
  to be removed; threshold must exceed object height but stay below real terrain relief.
- **Findings**: ~3% Type I/II error on mixed urban/mountain LiDAR. Known weakness:
  step-like artifacts on continuous slopes and loss of abrupt terrain features when
  windows get large.
- **Citation**: Zhang, K., Chen, S.-C., Whitman, D., Shyu, M.-L., Yan, J., Zhang, C.
  (2003). "A progressive morphological filter for removing nonground measurements from
  airborne LIDAR data." *IEEE Trans. Geoscience and Remote Sensing*, 41(4), 872–882.
  doi:10.1109/TGRS.2003.810682

### Simple Morphological Filter (SMRF)
- **Method**: Builds a minimum surface, applies a *linearly increasing* morphological
  opening with a single, slope-controlled threshold, then uses image inpainting to fill
  the provisional ground surface; points are kept if within a slope-scaled distance of
  that surface.
- **Key parameters (PDAL `filters.smrf`)**: `slope` 0.15 (rise/run), `threshold`
  (elevation) 0.15–0.5 m, `window` (max) ~18–21 m, `cell` ~1 m, `scalar` 1.25.
  Permissible distance = fixed threshold + scalar × local slope.
- **Findings**: Mean Kappa 85.4% (single parameter set) / 90% (tuned) on the ISPRS
  benchmark. In UAV-photogrammetry riparian/river-bank studies, SMRF was repeatedly the
  best general performer (e.g. RMSE ~0.19–0.21 m on SfM, ~0.13 m on LiDAR), effectively
  removing vegetation while preserving bank terrain. The single slope parameter makes it
  much easier to tune than PMF.
- **Citation**: Pingel, T.J., Clarke, K.C., McBride, W.A. (2013). "An improved simple
  morphological filter for the terrain classification of airborne LIDAR data." *ISPRS
  J. Photogrammetry and Remote Sensing*, 77, 21–30. doi:10.1016/j.isprsjprs.2012.12.002

### Minimum / low-percentile moving-window filters & morphological opening
- **Method**: Take the minimum (0th percentile) or a low percentile (e.g. 5th–30th) of
  the DSM in a moving window as a ground estimate; a morphological *opening* is a
  minimum filter (erosion) followed by a maximum filter (dilation). Often used as the
  seed step inside PMF/SMRF rather than as a standalone product.
- **Key tradeoff**: the window must be **larger than the widest vegetation patch** (so
  some ground falls inside it) but **smaller than the wavelength of real terrain you
  want to keep** (levees, ridges). Pure minimum/opening introduces a **negative bias**
  on bare ground and **segments slopes into step-like terraces**; performance is highly
  sensitive to window size. A low percentile (vs. strict minimum) trades robustness to
  outliers/noise against residual vegetation bias.
- **Citation (general)**: see Zhang 2003 and Pingel 2013 above; morphological-opening
  sensitivity discussed broadly in the LiDAR-filtering literature (e.g. Pingel 2013 §2).

---

## 2. Vegetation removal from DSMs over floodplains / wetlands / tundra

These works don't use a moving-window percentile per se; they estimate a vegetation-height
*bias layer* and subtract it. They establish the magnitude of the problem and validation norms.

- **Baugh et al. (2013)** — SRTM over the Amazon floodplain. Subtracted a fraction of a
  global vegetation-height map from the DSM and found the **best hydraulic-model results
  came from removing ~50–60% of the vegetation height** (not 100%), because SRTM C-band
  penetrates partway into canopy. Water-elevation error dropped 6.61 m → 1.84 m.
  *Lesson*: optimal subtraction is partial and must be tuned, not assumed.
  *Water Resources Research* 49(9), 5276–5289. doi:10.1002/wrcr.20412
- **O'Loughlin et al. (2016)** — multi-sensor global bare-earth SRTM. Regressed
  vegetation-continuous-field + canopy-height predictors to correct bias; reduced mean
  vegetation bias 14.1 m → 5.9 m. *Remote Sensing of Environment* 182, 49–59.
  doi:10.1016/j.rse.2016.04.018
- **Yamazaki et al. (2017) — MERIT DEM**. Separated tree-height bias (from tree-density
  + height maps), absolute bias, stripe and speckle noise from SRTM/AW3D; biggest gains
  in flat floodplains. *Geophysical Research Letters* 44. doi:10.1002/2017GL072874
- **Hawker et al. (2022) — FABDEM**. Random-forest model trained on GEDI/ICESat-2 canopy
  heights estimates and subtracts forest+building height from Copernicus GLO-30 DSM.
  Roughly **halved vertical error in forested areas**. The dominant modern approach: an
  ML-predicted height layer, not a spatial filter. *Environmental Research Letters*
  17, 024016. doi:10.1088/1748-9326/ac4d4f
- **Meddens et al. (2018) — most directly comparable.** Estimated 5 m canopy height
  across interior Alaska from ArcticDEM + WorldView, then **subtracted it from ArcticDEM
  to make a bare-earth ArcticDTM**, validated against airborne-LiDAR CHM (RMSE 2.2–2.6 m,
  R² 0.59–0.76). Confirms ArcticDEM carries a real, removable canopy signal in exactly
  our setting — but their residual error (2+ m) is larger than our sub-meter target,
  so a regression-subtraction alone may be insufficient for fine fluvial relief.
  *Remote Sensing of Environment* 218, 174–188. doi:10.1016/j.rse.2018.09.024

---

## 3. Is a low-percentile moving-window filter a recognized/validated method?

Yes — as the *seed/ground-estimation step* inside morphological pipelines (PMF, SMRF)
and in UAV-SfM DTM workflows, but rarely published as a standalone named product.
Documented failure modes:
- **Terrain erosion on slopes**: minimum/opening pulls the surface down to local minima,
  terracing real slopes — directly damaging cutbanks and ridge flanks.
- **Negative bias on bare ground**: taking a low percentile of a noisy DSM systematically
  under-estimates elevation even where there is no vegetation (worst near our sub-meter
  signal).
- **Window-vs-feature tradeoff**: too small → vegetation survives; too large → real
  features (levees, alluvial ridges) are smoothed/removed. There is no single safe size
  when feature wavelength overlaps vegetation-patch width — common on floodplains.
- For UAV-SfM in shrub/tree cover, a TIN-based ground filter reported RMSE 5 cm (bare),
  33 cm (shrub), 78 cm (tree); SMRF was the best general morphological performer
  (RMSE ~0.16–0.21 m) — useful order-of-magnitude expectations.
- **Citation**: Anders, N., Valente, J., Masselink, R., Keesstra, S. (2019). "Comparing
  Filtering Techniques for Removing Vegetation from UAV-Based Photogrammetric Point
  Clouds." *Drones* 3(3), 61. doi:10.3390/drones3030061

---

## 4. Vegetation-index-gated (NDVI/EVI) filtering

Precedent exists and is directly relevant to a multispectral/imagery-paired DSM:
- **Lee/Kang et al. (2025)** developed a stream-DTM method combining **vegetation-index
  filters (NDVI, NDI) with morphological filters (ATIN, CSF)** on drone SfM clouds.
  Best result: **NDVI ∧ CSF in vegetated areas**, but in *bare* areas the morphological
  filter *added* error, so **NDVI alone (i.e., gate the ground filter to only where
  vegetation is present) gave the lowest error on bare ground.** This is the explicit
  precedent for "only filter where NDVI says vegetation," precisely to avoid eroding bare
  fluvial surfaces. A common NDVI vegetation threshold is ~0.2.
  *Scientific Reports* 15, article 96477 (2025). doi:10.1038/s41598-025-96477-7

Implication: if we have contemporaneous NDVI (Sentinel-2/Landsat/multispectral), gating
the percentile correction to vegetated pixels would protect bare bars, channels, and
cutbanks from the negative-bias and slope-erosion failure modes in §3.

---

## 5. Preserving fine fluvial features while removing vegetation

- The window/threshold that removes canopy is the same operation that smooths levees and
  alluvial ridges — the core tension. Feature-preserving DEM smoothing (Sun et al.) uses
  a normal-difference angle threshold to keep sharp breaks while denoising; PMF/SMRF use
  slope-scaled thresholds for the same purpose.
- Resolution/aggregation studies show choosing a grid/window that "reflects the main
  ridges and depressions but smooths microtopography" is an explicit, sensitive choice;
  in flat wetlands microtopography is hydrologically meaningful and should *not* be
  smoothed away. Practically: keep the window as small as vegetation patch size allows,
  and validate feature amplitude (ridge height) against LiDAR, not just bulk RMSE.
- Slope-scaled thresholds (SMRF `scalar`, PMF slope term) are the standard mechanism to
  avoid clipping ridge crests and cutbank edges.

---

## Implications for our percentile-filter experiment

- **Starting points**: test low percentiles (try **10th, 20th, 30th**, plus strict min)
  in windows of **~50–150 m first**, not 100–300 m — Alaskan riparian willow/alder/shrub
  patches are small, and a smaller window better preserves levee/ridge wavelength. Sweep
  window size as the primary parameter; expect a clear RMSE-vs-feature-preservation knee.
- **Don't expect 100% subtraction to be optimal** (Baugh): the right percentile likely
  removes *most* but slightly under-corrects; tune the percentile against LiDAR rather
  than assuming the minimum is "ground."
- **Watch the two named failure modes**: negative bias on bare ground (check median bias
  over known-bare bars/channels — should be ~0) and slope terracing on ridge flanks and
  cutbanks (inspect profiles across features, not just aggregate stats).
- **Add an NDVI gate** (Lee/Kang 2025): apply the percentile correction only where NDVI
  exceeds a threshold (~0.2), leaving bare fluvial surfaces untouched — this directly
  mitigates both failure modes and is published precedent in a near-identical setting.
- **Validate two ways against LiDAR**: (1) elevation RMSE/MAE stratified by cover class
  (bare / sedge / shrub / alder), and (2) **preservation of fine relief amplitude** —
  measure modeled levee/alluvial-ridge height vs. LiDAR, since bulk RMSE can look good
  while the sub-meter avulsion signal is smoothed away. Benchmark against a simple
  Meddens-style canopy-subtraction and SMRF (PDAL, slope≈0.15) as references.
