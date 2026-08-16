"""swot_core — the single shared implementation of the project's science.

One package, three consumers:

  * `dashboard_swot.py` (researcher app) — wraps these functions in
    `st.cache_data` at the app layer,
  * `dashboard_village.py` (village app) — same wrappers, subset of tabs,
  * `thesis_figures/` — imports them headless for the publication figures.

Design rule: NOTHING in this package imports streamlit. Caching, widgets and
presentation belong to the apps; swot_core is pure numpy/pandas/scipy/duckdb so
the thesis pipeline and any future batch analysis can import it without side
effects. If a computation here changes, every consumer changes with it — that is
the point (no more hand-synced copies drifting apart).

Modules:
  config — shared scientific constants, data paths/URLs, QC registry re-exports
  data   — DuckDB connection + headless loaders (SWOT points, reference
           gradient, temporal artifacts) with QC exclusion applied
  stats  — the computations: detrending, MAD outlier flag, slope profiles
           (pooled + fine-scale per-pass), elevation difference
"""

from . import config, data, stats  # noqa: F401
