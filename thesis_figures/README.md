# Thesis Figures

Print-first, publication-quality figures for the Kanektok avulsion-risk thesis.

This module is **separate from the interactive dashboard** but **reuses the
dashboard's validated analysis** (ported into `core.py`) so every figure is
provably identical to the science shown in `dashboard_swot.py`. Only the
presentation differs: full data (no browser downsampling), fixed physical
dimensions, consistent typography, and vector + high-DPI raster export.

## Layout

| File | Role |
|------|------|
| `config.py` | Publication style (`apply_style`), colours, paths, dimensions, `savefig`. Change styling for **all** figures here. |
| `core.py` | Thin façade over the shared **`swot_core`** package (the single implementation of detrending, Theil–Sen gradient, binning, slope, elevation difference used by the dashboards AND the figures). No Streamlit. Formerly a hand-synced verbatim port; unified in the dashboard-split PR A. |
| `make_figures.py` | One `build_figN()` per figure + CLI. Renders to `output/`. |
| `output/` | Generated `figure_NN.pdf` / `.png` (created on first run). |

## Usage

```bash
python -m thesis_figures.make_figures --list        # list all figures
python -m thesis_figures.make_figures --smoke        # verify data + core (no plots)
python -m thesis_figures.make_figures 5              # build Figure 5
python -m thesis_figures.make_figures 5 6 7          # build several
python -m thesis_figures.make_figures --all          # build every implemented figure
```

## Conventions (all distance-profile figures)

- **X-axis reversed**: coast left (~70 km), confluence right (0 km).
- Colours: Kanektok = `firebrick`, Uyak = `dodgerblue` (matches dashboard).
- Bifurcation marked with a dashed line at 2.493 km.
- Open-water season (Apr–Nov) only by default; ice season (Dec–Mar) excluded.
- Output: vector **PDF** (embed in LaTeX/Word) + **PNG** at 400 dpi.

## Figure list & status

| # | Figure | Source | Status |
|---|--------|--------|--------|
| 1 | Study Area & Spatial Normalization Map | Map View / static basemap | stub |
| 2 | Custom Python Pipeline Flowchart | **external** (diagramming tool) | n/a |
| 3 | Temporal Stability & Stage-Invariance | `temporal_results/` | stub |
| 4 | Reference Hydraulic Gradient Distribution | `reference_gradient_per_pass.parquet` | stub |
| 5 | Absolute Spatial Gradient Profile | Gradient Profile tab | stub |
| 6 | Localized Elevation Difference | Elevation Difference tab | stub |
| 7 | Detrended Relative Elevation Profile | Detrended Profile tab | stub |
| 8 | Interval Slope Profile | Slope Profile tab | stub |

Figures are implemented **one at a time** as each spec is finalised.

## Data sources

Defaults (in `config.py`) mirror the deployed dashboard so figures match the
published dataset. `DATA_PATH` → `dashboard_data.parquet`; `REF_GRADIENT_PATH`
→ `batch_outputs/reference_gradient_per_pass.parquet`. Switch a builder to
`FULL_DATA_PATH` if it needs the complete local archive.
