"""Single source of truth for dataset-level QC exclusions.

Imported by BOTH the ingestion pipeline (SWOT_Pull.py) and the thesis-figure
module (thesis_figures/config.py) so the exclusion registry can never drift
between producers and consumers. Keep this module dependency-free (stdlib
only) so lightweight consumers don't inherit the ingestion stack.

Both mechanisms are QC FLAGS, not raw-data edits: per-granule checkpoint CSVs
in batch_outputs/data/ are kept intact for provenance; the exclusions are
applied once when the master analysis products are rebuilt
(SWOT_Pull.rebuild_master_from_daily_csvs), so the master parquet, dashboard
data, reference gradient, temporal analysis, and thesis figures all inherit
them from a single filter point. (Since 2026-08-14 ice-season granules are
also skipped at DOWNLOAD time to save ~146 GB — the rebuild-time hard line
still enforces the cutoff for anything already on disk.)
"""

# --- ICE-SEASON HARD LINE (data-usage cutoff) --------------------------------
# Archive audit (2026-08-14) of per-date basin-median WSE anomaly vs the Jun-Aug
# node baseline plus per-pass Theil-Sen slopes, 2023-07..2026-07:
#   * April carries breakup-ice interference in EVERY observed year (2024-04-07;
#     2025-04-17 [registry below] and 2025-04-19; 2026-04-07/08/18/28 -- WSE up
#     to +0.9 m with synchronous both-river slope spikes).
#   * October is clean in all observed years: anomalies negative (baseflow
#     recession), slopes at the summer baseline.
#   * First freeze-up interference appears mid-November (2025-11-12).
#   * Dec-Mar WSE rides the ice surface (median +0.30 m, up to +1.34 m).
# Late-May/June positive WSE anomalies are the snowmelt freshet (real water,
# real flow) and are deliberately kept.
ICE_SAFE_MONTHS = {5, 6, 7, 8, 9, 10}

# --- KNOWN-BAD PASSES (documented exclusion registry) ------------------------
# Each entry: 'YYYY-MM-DD': 'reason (evidence)'.
# NOTE: the 2025-04-17 breakup event is now also covered wholesale by
# ICE_SAFE_MONTHS (April excluded); the entry is kept as documentation and as
# defense-in-depth for consumers that read checkpoint CSVs directly.
KNOWN_BAD_PASSES = {
    "2025-04-17": (
        "Spring-breakup ice contamination: reach gradient anomalously steep on BOTH "
        "channels simultaneously (Uyak 236, Kanektok 224 cm/km vs medians 192/196) -- "
        "a synchronous basin-wide spike is an ice-event signature, not a real gradient."
    ),
}
