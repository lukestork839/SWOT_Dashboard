#!/usr/bin/env python3
"""Rebuild master parquet files from existing checkpoint CSVs.

Thin wrapper around SWOT_Pull.rebuild_master_from_daily_csvs() so there is
exactly ONE implementation of the master build — QC exclusions
(KNOWN_BAD_PASSES), the May-Oct ice-season hard line, column pruning, dtype
optimization, partitioning, and the reference-gradient artifact all live
there. Faster than a full re-pull because nothing is downloaded.

(An earlier standalone implementation here had drifted from the pipeline: it
skipped the QC exclusions and the reference-gradient rebuild, and left stale
partition files behind when the dataset shrank.)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from SWOT_Pull import rebuild_master_from_daily_csvs

if __name__ == "__main__":
    rebuild_master_from_daily_csvs()
