"""Shared analysis core for thesis figures — now a thin façade over `swot_core`.

Historically this module carried hand-synced copies of the dashboard's science,
"ported verbatim" — and the copies drifted (the 2026-08 gap-honest slope-profile
rewrite and the polynomial coefficient-domain fix reached only the dashboard).
The dashboard split (PR A) collapsed both copies into the `swot_core` package:
figures and dashboards now compute from literally the same implementation, and
`tools/regression_gate.py` guards that equivalence numerically.

Everything the figure builders import from `core` re-exports below, so
`make_figures.py` / `make_dem_figures.py` call sites are unchanged. The default
data source stays the FULL local archive via `connect()` (thesis convention;
see thesis_figures/config.py).
"""

from __future__ import annotations

from typing import Optional

import duckdb

from swot_core.config import OPEN_WATER_MONTHS  # noqa: F401  (Apr–Nov, shared)
from swot_core.data import (  # noqa: F401
    exclusion_condition as _exclusion_condition,
    drop_excluded as _drop_excluded,
    load_swot,
    load_reference_gradient,
    load_temporal_metrics,
    load_temporal_results,
)
from swot_core.stats import (  # noqa: F401
    calculate_detrending,
    flag_residual_outliers,
    calculate_slope_profile,
    finescale_slope_profile,
    elevation_difference,
    fine_slope_theilsen as _fine_slope_theilsen,
    fine_regular_grid as _fine_regular_grid,
    FINE_BASE_BIN_KM,
    FINE_MIN_PIX_BIN,
    FINE_FILL_GAP_KM,
)

from . import config


def connect(data_path: Optional[str] = None) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection with `river_data` bound to the SWOT parquet.

    Defaults to the thesis data source (`config.DATA_PATH` = the full local
    archive, NOT the deployment subset — figures must match the thesis text).
    Delegates to swot_core.data.connect for the actual binding.
    """
    from swot_core.data import connect as _connect
    return _connect(data_path or config.DATA_PATH)
