"""
Isolated Aug 11-31, 2026 top-up pull for the DEFINITIVE Q3 (ex-Typhoon Halong)
comparison.

The master archive was frozen at 2026-08-10 for the thesis (all headline
numbers derive from it). The definitive Q3 comparison needs the rest of the
Jul-Aug 2026 low-flow window, so the missing late-August granules are pulled
and processed here into an ISOLATED directory:

    batch_outputs/q3_topup_20260831/data/   per-granule checkpoint CSVs
    batch_outputs/q3_topup_20260831/q3_topup.parquet   combined, master-schema subset

Nothing is written to batch_outputs/data/ or the master parquets — the frozen
archive is untouched, and no headline value recomputes. temporal_analysis.py
reads the combined parquet as a Q3-ONLY supplement (Q1/Q2 stay on the frozen
master by construction).

Processing is IDENTICAL to the master pipeline: this script imports SWOT_Pull
and calls its process_granule() (same polygons, filters, WSE corrections,
MAD screen), only redirecting the output/temp directories. Resumable the same
way (per-granule checkpoints).

Run: python3 q3_topup_pull.py
"""

import glob
import os

import pandas as pd

import SWOT_Pull as sp
from qc_registry import ICE_SAFE_MONTHS, KNOWN_BAD_PASSES

ISO_DIR = os.path.join("batch_outputs", "q3_topup_20260831")
TOPUP_START = "2026-08-11"   # day after the frozen archive's last pass
TOPUP_END = "2026-08-31"
OUT_PARQUET = os.path.join(ISO_DIR, "q3_topup.parquet")

# Master-parquet column subset the temporal analysis actually reads.
TOPUP_COLUMNS = ["Reach_Name", "Pass_Date", "dist_km", "wse"]


def main():
    # Redirect every write inside SWOT_Pull to the isolated directory.
    sp.OUTPUT_BASE = ISO_DIR
    sp.TEMP_DIR = os.path.join(ISO_DIR, "tmp")
    os.makedirs(os.path.join(ISO_DIR, "data"), exist_ok=True)
    os.makedirs(sp.TEMP_DIR, exist_ok=True)

    gdf_poly = sp.load_polygons()

    import earthaccess
    earthaccess.login()
    results = earthaccess.search_data(
        short_name="SWOT_L2_HR_PIXC_D",
        bounding_box=tuple(gdf_poly.total_bounds),
        temporal=(TOPUP_START, TOPUP_END),
    )
    print(f"Found {len(results)} granules in {TOPUP_START}..{TOPUP_END}")

    for granule in results:
        date, cycle, pass_num, tile = sp.extract_granule_ids(granule)
        if date is None:
            print(f"  skipping unparseable granule: {sp.get_granule_name(granule)}")
            continue
        stem = sp.granule_csv_stem(date, cycle, pass_num, tile)
        if sp.is_granule_already_processed(stem):
            print(f"  {stem}: checkpoint exists, skipping")
            continue
        print(f"  processing {stem} ...")
        sp.process_granule(granule, gdf_poly)

    # Combine checkpoints into one parquet, applying the same rebuild-time QC
    # gates as the master (ice-safe months; documented bad-pass registry).
    csvs = sorted(glob.glob(os.path.join(ISO_DIR, "data", "*_data.csv")))
    if not csvs:
        print("No checkpoint CSVs produced — nothing to combine.")
        return
    frames = [pd.read_csv(c, usecols=TOPUP_COLUMNS) for c in csvs]
    df = pd.concat(frames, ignore_index=True)
    d = pd.to_datetime(df["Pass_Date"])
    df = df[d.dt.month.isin(ICE_SAFE_MONTHS)]
    df = df[~df["Pass_Date"].isin(KNOWN_BAD_PASSES)]
    df.to_parquet(OUT_PARQUET, index=False)
    print(f"Wrote {OUT_PARQUET}: {len(df):,} rows, "
          f"{df['Pass_Date'].nunique()} pass dates: {sorted(df['Pass_Date'].unique())}")


if __name__ == "__main__":
    main()
