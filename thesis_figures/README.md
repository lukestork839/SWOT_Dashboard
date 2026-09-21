# Thesis Figures

Print-first, publication-quality figures for the Kanektok avulsion-risk thesis.

This module is **separate from the interactive dashboard** but **reuses the dashboard's
validated analysis** (via `core.py` → the shared `swot_core` package), so every figure is
provably identical to the science shown in the dashboard — the numerical regression gate
(`tools/regression_gate.py`) covers both. Only the presentation differs: full data (no
browser downsampling), fixed physical dimensions, consistent typography, and vector +
high-DPI raster export.

## Layout

| File | Role |
|------|------|
| `config.py` | Publication style (`apply_style`), colours, paths, dimensions, `savefig`. Change styling for **all** figures here. |
| `core.py` | Thin façade over **`swot_core`** (the single implementation of detrending, Theil–Sen gradient, binning, slope used by the dashboard AND the figures). No Streamlit. |
| `make_figures.py` | SWOT figure builders (`figure_00` … `figure_09`, incl. the `figure_03a/b/c` temporal set) + CLI. |
| `make_dem_figures.py` | DEM figure builders (`dem_fig01` … `dem_fig05`, incl. the `dem_fig04_M/P/S` set). |
| `make_presentation_figures.py` | Presentation (slide-format) variants, including the bifurcation virtual-gauge figure. |
| `export_final.py` | Maps the stable figure-series names to sequential thesis numbers and copies image + caption into `final/Figure_NN.*`. **The `FIGURE_MAP` inside it is the source of truth for thesis numbering.** |
| `captions/` | One caption text file per figure, alongside its series. |
| `assets/` | Static inputs (e.g. basemap imagery). |
| `output/`, `final/` | Rendered output (gitignored; regenerate with the commands below). |

## Usage

```bash
python -m thesis_figures.make_figures --list        # list SWOT figures
python -m thesis_figures.make_figures --smoke       # verify data + core (no plots)
python -m thesis_figures.make_figures --all         # build every SWOT figure
python -m thesis_figures.make_dem_figures --all     # build the DEM figures
python -m thesis_figures.export_final               # collect final/Figure_01..18 + captions
```

## Thesis figure set (18 figures, per `export_final.FIGURE_MAP`)

| # | Content | Series |
|---|---------|--------|
| 1 | Regional setting map | `figure_00` |
| 2 | Study area & spatial-normalization polygons | `figure_01` |
| 3 | Processing-pipeline flowchart | `figure_02` |
| 4 | Arc-based DEM sampling frame | `dem_fig01_D` |
| 5 | Reference hydraulic gradient, per-pass distribution | `figure_04` |
| 6 | Reach-scale interval slope profiles | `figure_08` |
| 7 | Fine-scale slope profiles + bifurcation zoom | `figure_09` |
| 8 | Valley terrain slope vs measurement scale | `dem_fig05` |
| 9 | β superelevation-ratio map | `dem_fig04_M` |
| 10 | β distance profiles (H_AR, H_M, ADCP depth) | `dem_fig04_P` |
| 11 | Valley long profile + channel water surfaces | `dem_fig02` |
| 12 | Superelevation vs floodplain, both channels, stage band | `dem_fig04_S` |
| 13 | Absolute longitudinal WSE profiles | `figure_05` |
| 14 | Kanektok−Uyak elevation difference | `figure_06` |
| 15 | Detrended relative elevation profiles | `figure_07` |
| 16 | Stage record at the 15 km virtual gauge | `figure_03a` |
| 17 | Per-pass reach gradient vs date | `figure_03b` |
| 18 | Gradient vs stage (stage-invariance test) | `figure_03c` |

## Conventions (all distance-profile figures)

- **X-axis reversed**: Bering Sea / mouth left (~35 km), anchor point right (0 km).
- Colours: Kanektok = `firebrick`, Uyak = `dodgerblue` (matches the dashboard).
- Bifurcation marked with a dashed line at 2.493 km from the anchor point.
- Open-water season only (May–October, `qc_registry.ICE_SAFE_MONTHS`); known-bad passes excluded.
- Output: vector **PDF** (embed in LaTeX/Word) + **PNG** at 400 dpi.

## Data sources

Figure builders read the full local archive (`batch_outputs/`, built by `SWOT_Pull.py`) plus
the tracked artifacts (`temporal_results/`, `DEM_Transects/data/`); paths are set in
`config.py`. Captions quote numbers that a smoke check recomputes from the same artifacts,
so caption and figure cannot drift.
