# DEM_Transects — alluvial-ridge / avulsion analysis

DEM cross-section avulsion analysis for the Kanektok River and Uyak Creek, on the 2 m ArcticDEM.
Measures the **superelevation ratio β** — warning sign 1 of the parent CIVIC project's three — on a
radial side-by-side frame consistent with the SWOT dashboard.

**Read [`AVULSION_ANALYSIS.md`](AVULSION_ANALYSIS.md) for the methods, results, and caveats.**
Build status: [`STATUS.md`](STATUS.md).

## The analysis — the arc method (`build_arc_B.py`)

| What it answers | Method | Headline |
|---|---|---|
| How do the two rivers compare at matched downstream distance, and is either **perched** above the floodplain it would spill into? | Cross-sections along **arcs of constant distance-from-anchor** (fan/delta radial frame); each arc spans Kanektok→floodplain→Uyak. Channels located by snapping to the DEM low from a field-centerline prior; superelevation measured vs the inter-channel floodplain corridor, at a declared SWOT stage. | Uyak water surface **+0.96 m** above the Kanektok (pass-paired SWOT, 100 % of passes), **but** the Kanektok is **incised on 100 % of arcs** (−1.50 m at median stage, −1.01 m even at high water), the Uyak sits ≈ at grade (−0.49 m), and **β = H_AR/H_M ≈ 0.06 with H_AR ≈ 0** — there is no alluvial ridge to perch on. Topographic case **against** a Kanektok→Uyak avulsion |

This agrees with the SWOT/dashboard finding. The cross-sections are **iso-distance arcs** rather
than straight cross-valley lines because an oblique transect measures the ~1.83 m/km down-valley
gradient instead of superelevation — an 8–11 m artifact against a ~1 m signal; see
`AVULSION_ANALYSIS.md` §2. Both channel picks use accurate **field centerlines** — boat-GPS
Uyak and boat-ADCP Kanektok — behind a symmetric ±75 m snap window. *(An earlier
perpendicular-to-channel β method, "Approach A", has been retired; it lives in git history.)*

## Run

```bash
# prerequisites: outputs/swot_centerlines.gpkg, data/uyak_centerline_official.gpkg,
#                data/kanektok_centerline_official.gpkg
python3 DEM_2m_Pull.py                             # fetch PGC ArcticDEM 2 m COGs -> batch_outputs/arcticdem_rivers_2m.tif
python3 DEM_Transects/ingest_adcp.py --check       # verify the tracked ADCP ingest (re-ingest only needs the raw archive)
python3 DEM_Transects/make_swot_centerline.py      # (re)build SWOT centerlines (now a reference overlay)
python3 DEM_Transects/build_uyak_centerline.py     # (re)build the Uyak field-GPS centerline DRAFT
python3 DEM_Transects/build_kanektok_centerline.py # (re)build Kanektok centerline DRAFT + thalweg-depth parquet
python3 DEM_Transects/swot_arc_reference.py        # per-arc SWOT geoid / stage bands / bed reference
python3 DEM_Transects/build_arc_B.py               # the analysis -> arcB_*.png, arcB_channels/profiles.parquet
python3 DEM_Transects/map_transects.py             # satellite placement-check map -> transect_map.html
```

`arcB_profiles.parquet` holds the full elevation-vs-arc cross-sections and drives the interactive
**✂️ Cross-Sections** tab in the main dashboard (`dashboard_swot.py` → DEM Data). Both it and
`arcB_channels.parquet` are published to **`data/`** (tracked, `float32`/zstd, ~2.9 MB), so the tab
is **live on the hosted app** — no longer local-only. `build_arc_B.py` writes those two to `data/`
and leaves the figures as scratch in `outputs/`.

Both channel priors are **official** field centerlines in `data/`: `uyak_centerline_official.gpkg`
(boat GPS) and `kanektok_centerline_official.gpkg` (boat ADCP thalweg). The `build_*_centerline.py`
scripts only refresh a `*_draft` copy in `outputs/` and never overwrite the official files.

## Layout

**Current pipeline**
| Path | What |
|---|---|
| `AVULSION_ANALYSIS.md` | methods, results, caveats, references (authoritative) |
| `build_arc_B.py` | the arc analysis — radial iso-distance-from-anchor cross-sections |
| `swot_arc_reference.py` | condenses the SWOT archive to one small per-arc artifact: EGM2008 geoid, per-river stage distribution, pass-paired Uyak−Kanektok, survey-stage water surface |
| `data/swot_arc_reference.parquet` | **tracked** output of the above — the SWOT side of the analysis |
| `ingest_adcp.py` | the only script that reads the raw ADCP archive; consolidates all 339 velocity_depth transects into one tracked parquet. `--check` validates the committed file with no archive present |
| `data/adcp_velocity_depth.parquet` | **tracked** ADCP ingest — 40 815 pings, 6 survey days, both rivers, all export columns (~1.8 MB zstd). The field side of the analysis |
| `data/adcp_velocity_depth.manifest.json` | provenance for the above: archive path, the 339 source files, per-day ping counts, and what was deliberately left out |
| `build_uyak_centerline.py` | build the field boat-GPS Uyak centerline (draft; official is hand-edited) |
| `build_kanektok_centerline.py` | build the field boat-ADCP Kanektok centerline (draft; Day-03 thalweg) + thalweg-depth parquet |
| `data/uyak_centerline_official.gpkg` | **official** Uyak centerline prior (tracked, canonical) |
| `data/kanektok_centerline_official.gpkg` | **official** Kanektok centerline prior (tracked, canonical) |
| `data/kanektok_thalweg_depth.parquet` | Kanektok boat-ADCP thalweg depth vs radius — the Gearon β bed / H_M term. Curated subset of the ingest: Day-03 longitudinal transects only, depth > 0 |
| `data/uyak_mouth_depth.parquet` | Uyak boat-ADCP depth near its mouth (radius 31–33 km) — the only Uyak depth |
| `adcp_depth_stats.py` | Kanektok depth statistics + Uyak-vs-Kanektok mouth depth comparison → `adcp_depth_comparison.png` |
| `map_transects.py` | satellite placement-check map (centerlines + arcs + anchor) |
| `make_swot_centerline.py` | build SWOT channel centerlines from water pixels → gpkg (reference overlay) |
| `build_dem_centerline.py` | P6 — channel centerline derived from the DEM itself (no boat-track dependence); path-length / sinuosity check behind the along-channel gradient discussion |
| `data/dem_centerline_nodes.parquet`, `data/dem_centerline_snapped.parquet` | **tracked** outputs of the above (per-radius channel positions; per-station DEM-snapped path), used by the DEM writeup figures |
| `centerline.py` | centerline utilities (load / SWOT-points / polygon skeleton) |
| `outputs/` | figures + parquet + `swot_centerlines.gpkg` (scratch; parquet gitignored) |

**Legacy** (Gearon β/γ/Λ port + validation harness, not used by the current analysis)
`avulsion_metrics.py`, `build_transects.py`, `transects.py`, `pick_features.py`,
`make_avulsion_figures.py`, `validation/`, `reference/`.

*(The earlier preliminary-ArcGIS β reproduction — `reproduce_beta.py`, `beta_floodplain.py`,
`prototype_B.py`, `run_B.py`, `make_beta_figures.py`, `recover_original_beta.py` and the recovered
`reference/original_beta.parquet` — was removed 2026-08-19. The current β stands on its own as the
Gearon superelevation ratio; the preliminary results live outside this repo. All of it is
recoverable from git history.)*

## Key parameters

- Anchor (dist origin): `59.82463509, -161.33397834` — same as the SWOT dashboard.
- Geoid: EGM2008 **per radius** (13.74 m anchor → 13.28 m coast) from `data/swot_arc_reference.parquet`.
  Within-arc differences (β, superelevation, Uyak−Kanektok) are datum-invariant either way; the
  per-radius value is what puts the DEM on SWOT's datum for comparison.
- Radii 3–35 km @ 0.5 km; bearing sector 248–294°; **2 m** along-arc step (native DEM res).
- Channel pick: locate P2-deepest thalweg, water surface = P2 in ±50 m; symmetric **±75 m** snap
  window both rivers (accurate field priors: boat-GPS Uyak, boat-ADCP Kanektok).
- Floodplain corridor: median terrain between channels, excluding each ±250 m notch.
- Gearon β = H_AR/H_M = (ridge crest − floodplain)/(ridge crest − bed), Kanektok only; crest = lower
  of the two P98 bank-highs within **±150 m** (~3 channel widths — set by the bankfull check that
  freeboard ≈ channel depth; the old ±350 m gave an unfillable bank and inflated β to 0.24);
  **bed = survey-stage SWOT water surface − boat-ADCP depth** (median 1.30 m). β median **0.06**,
  H_AR ≈ **+0.14 m** → no alluvial ridge. The CIVIC threshold is **β > ~0.5** (Ganti et al. 2016),
  not β = 1 — and it is **one-directional**: β < 0.5 is not a clearance (Gearon: ~60 % of avulsed
  deltas have β < 0.5, since βγ ≥ Λ and γ is not evaluated here). At β ≈ 0.06 the corridor-median
  bias (~0.10 in β units) exceeds the value, so the claim is *H_AR ≈ 0*, not a threshold pass —
  see AVULSION_ANALYSIS.md §3.
- SWOT: superelevation quoted at the **median observed stage** with a p10–p90 band; the inter-river
  difference from **pass-paired** overpasses (stage cancels). DEM vs SWOT agrees to 0.15 m.
- Migration: DEM mosaic is **2010–2021**, field centerlines **2026**; snap offsets median 38 m
  (Kanektok) / 12 m (Uyak), at the ±75 m wall on ~9 % of arcs. WSE is unaffected (0.00 m across
  windows ±75→±400 m); channel *position* is uncertain at tens of metres.
