# DEM_Transects — alluvial-ridge / avulsion analysis

DEM cross-section avulsion analysis for the Kanektok River and Uyak Creek, on the 2 m ArcticDEM.
Reproduces (and corrects) a prior ArcGIS superelevation workflow, then answers the avulsion
question with a radial side-by-side frame consistent with the SWOT dashboard.

**Read [`AVULSION_ANALYSIS.md`](AVULSION_ANALYSIS.md) for the methods, results, and caveats.**
Build status: [`STATUS.md`](STATUS.md).

## The analysis — the arc method (`build_arc_B.py`)

| What it answers | Method | Headline |
|---|---|---|
| How do the two rivers compare at matched downstream distance, and is either **perched** above the floodplain it would spill into? | Cross-sections along **arcs of constant distance-from-anchor** (fan/delta radial frame); each arc spans Kanektok→floodplain→Uyak. Channels located by snapping to the DEM low from a field-centerline prior; superelevation measured vs the inter-channel floodplain corridor. | Uyak water surface ~1.5 m *above* Kanektok on 92 % of arcs, **but** the Kanektok is **incised on 98 % of arcs** (−1.52 m), the Uyak sits ≈ at grade (−0.21 m), and the measured **Gearon β = H_AR/H_M ≈ 0.24** (boat-ADCP channel depth) is ≪ 1 on 100 % of arcs — topographic case **against** a Kanektok→Uyak avulsion |

This agrees with the SWOT/dashboard finding. The prior "Kanektok super-elevated" reading was a
**diagonal-transect artifact** (down-valley gradient leaking into oblique cross-sections) — see
`AVULSION_ANALYSIS.md` §3. Both channel picks now use accurate **field centerlines** — boat-GPS
Uyak and boat-ADCP Kanektok — behind a symmetric ±75 m snap window. *(An earlier
perpendicular-to-channel β method, "Approach A", has been retired; it lives in git history.)*

## Run

```bash
# prerequisites: batch_outputs/arcticdem_rivers_2m.tif, outputs/swot_centerlines.gpkg,
#                data/uyak_centerline_official.gpkg, data/kanektok_centerline_official.gpkg
python3 DEM_Transects/make_swot_centerline.py      # (re)build SWOT centerlines (now a reference overlay)
python3 DEM_Transects/build_uyak_centerline.py     # (re)build the Uyak field-GPS centerline DRAFT
python3 DEM_Transects/build_kanektok_centerline.py # (re)build Kanektok centerline DRAFT + thalweg-depth parquet
python3 DEM_Transects/build_arc_B.py               # the analysis -> arcB_*.png, arcB_channels/profiles.parquet
python3 DEM_Transects/map_transects.py             # satellite placement-check map -> transect_map.html
```

`arcB_profiles.parquet` holds the full elevation-vs-arc cross-sections and drives the interactive
**✂️ Cross-Sections** tab in the main dashboard (`dashboard_swot.py` → DEM Data). The tab only
appears when that local artifact is present, so it's a local-run feature.

Both channel priors are **official** field centerlines in `data/`: `uyak_centerline_official.gpkg`
(boat GPS) and `kanektok_centerline_official.gpkg` (boat ADCP thalweg). The `build_*_centerline.py`
scripts only refresh a `*_draft` copy in `outputs/` and never overwrite the official files.

## Layout

**Current pipeline**
| Path | What |
|---|---|
| `AVULSION_ANALYSIS.md` | methods, results, caveats, references (authoritative) |
| `build_arc_B.py` | the arc analysis — radial iso-distance-from-anchor cross-sections |
| `build_uyak_centerline.py` | build the field boat-GPS Uyak centerline (draft; official is hand-edited) |
| `build_kanektok_centerline.py` | build the field boat-ADCP Kanektok centerline (draft; Day-03 thalweg) + thalweg-depth parquet |
| `data/uyak_centerline_official.gpkg` | **official** Uyak centerline prior (tracked, canonical) |
| `data/kanektok_centerline_official.gpkg` | **official** Kanektok centerline prior (tracked, canonical) |
| `data/kanektok_thalweg_depth.parquet` | Kanektok boat-ADCP thalweg depth vs radius — the Gearon β bed / H_M term |
| `data/uyak_mouth_depth.parquet` | Uyak boat-ADCP depth near its mouth (radius 31–33 km) — the only Uyak depth |
| `adcp_depth_stats.py` | Kanektok depth statistics + Uyak-vs-Kanektok mouth depth comparison → `adcp_depth_comparison.png` |
| `map_transects.py` | satellite placement-check map (centerlines + arcs + anchor) |
| `make_swot_centerline.py` | build SWOT channel centerlines from water pixels → gpkg (reference overlay) |
| `centerline.py` | centerline utilities (load / SWOT-points / polygon skeleton) |
| `outputs/` | figures + parquet + `swot_centerlines.gpkg` (scratch; parquet gitignored) |

**Superseded / exploratory** (kept for provenance; not part of the final result)
`reproduce_beta.py`, `beta_floodplain.py`, `prototype_B.py`, `run_B.py`, `transects.py` — earlier
framings, incl. the retired perpendicular-transect machinery; see `STATUS.md`.

**Legacy** (Gearon β/γ/Λ port + validation harness, not used by the current reproduction)
`avulsion_metrics.py`, `build_transects.py`, `pick_features.py`, `make_avulsion_figures.py`,
`validation/`, `reference/`.

## Key parameters

- Anchor (dist origin): `59.82463509, -161.33397834` — same as the SWOT dashboard.
- Geoid offset 13.46 m (elevation differences are datum-invariant).
- Radii 3–35 km @ 0.5 km; bearing sector 248–294°; **2 m** along-arc step (native DEM res).
- Channel pick: locate P2-deepest thalweg, water surface = P2 in ±50 m; symmetric **±75 m** snap
  window both rivers (accurate field priors: boat-GPS Uyak, boat-ADCP Kanektok).
- Floodplain corridor: median terrain between channels, excluding each ±250 m notch.
- Gearon β = H_AR/H_M = (ridge crest − floodplain)/(ridge crest − bed), Kanektok only; crest = lower
  of the two P98 bank-highs within ±350 m; **bed = DEM water surface − boat-ADCP depth** (median
  1.30 m). β median 0.24 (≪ 1 threshold). Depth artifact `data/kanektok_thalweg_depth.parquet`.
