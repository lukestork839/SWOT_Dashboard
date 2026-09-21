# Architecture

How the code is organized after the August 2026 refactor, which split the original
monolithic dashboard into a shared analysis core and thin presentation layers.

## Data flow

```
NASA Earthdata (SWOT L2 HR PIXC)          PGC / Google Earth Engine (ArcticDEM)
        │                                          │
   SWOT_Pull.py                          DEM_Pull.py · DEM_2m_Pull.py
        │  granule CSV checkpoints                 │
        ▼                                          ▼
 batch_outputs/master_all_data_part_*.parquet   batch_outputs/dem_river_elevations.parquet
        │                                          │
        ├──────────────► swot_core/  ◄─────────────┤
        │              (the one implementation     │
        │               of all the math)           │
        ▼                                          ▼
 dashboard_swot.py (Streamlit)            thesis_figures/ (matplotlib)
 temporal_analysis.py → temporal_results/ DEM_Transects/ (β / arc analysis)
```

On Streamlit Cloud there is no local `batch_outputs/`; `swot_core/data.py` reads the
deployment parquets from GitHub Release `v2.0-data` over DuckDB `httpfs` (stable URLs in
`swot_core/config.py`), so data can be refreshed by swapping release assets without a code
change.

## Layers

| Layer | Contents | Rule |
|---|---|---|
| `qc_registry.py` | Ice-safe months (May–Oct) and known-bad passes | Single source of truth for exclusions; imported by ingestion, core, and analyses |
| `swot_core/` | `config.py` (constants, URLs, anchor), `data.py` (headless DuckDB loaders), `stats.py` (detrending, Theil–Sen reference gradient, fine-scale slope, binning) | The **only** implementation of the science. No Streamlit imports |
| `dashboard_tabs/` | One renderer per dashboard tab + `common.py` (`@st.cache_data` wrappers over `swot_core`, presentation constants) | Presentation only — math lives in `swot_core` |
| `dashboard_swot.py` | Entry point: welcome page, pass selection, tab layout | `streamlit run dashboard_swot.py` |
| `thesis_figures/` | Print-quality figure builders reusing `swot_core` via `core.py`; `export_final.py` maps the stable figure series to thesis numbering | `python -m thesis_figures.make_figures --all` |
| `DEM_Transects/` | The β / superelevation arc analysis, ADCP ingest, centerlines | See `DEM_Transects/README.md` |
| `tools/` | `regression_gate.py` + `regression_baseline.json` | See below |

## The regression gate

`tools/regression_baseline.json` stores 515 numerical outputs of the reference metrics. Any
code change that alters a single one of these values fails
`python tools/regression_gate.py`; intentional methodological changes require explicitly
regenerating the snapshot. This is what guarantees that the dashboard, the thesis figures,
and the documented methodology all execute the same math.

## Data artifacts tracked in git

Small analysis products that downstream code reads directly: `temporal_results/` (the
one-time temporal analysis the Temporal Results tab displays), `DEM_Transects/data/`
(arc profiles, ADCP ingest, official centerlines), `tools/regression_baseline.json`.
Everything bulky (`batch_outputs/`, rasters, rendered figures) is gitignored and
reproducible from the pull scripts.
