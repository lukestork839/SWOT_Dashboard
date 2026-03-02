#!/usr/bin/env python3
"""
Quick rebuild of master parquet files from existing daily CSVs.
This is faster than re-running the full SWOT_Pull.py pipeline.
"""

import pandas as pd
from pathlib import Path
from tqdm import tqdm

# Import settings from SWOT_Pull.py
import sys
sys.path.insert(0, str(Path(__file__).parent))
from SWOT_Pull import KEEP_COLUMNS, ROWS_PER_CHUNK

DATA_DIR = Path("batch_outputs/data")
OUTPUT_DIR = Path("batch_outputs")

def rebuild_master_files():
    """Rebuild master files from all daily CSVs with updated column list."""

    print("🔍 Finding daily CSV files...")
    csv_files = sorted(DATA_DIR.glob("*_data.csv"))

    if not csv_files:
        print("❌ No daily CSV files found in batch_outputs/data/")
        return

    print(f"✅ Found {len(csv_files)} daily CSV files")
    print("📊 Reading and combining CSVs...")

    # Read all CSVs
    dfs = []
    for csv_file in tqdm(csv_files, desc="Loading CSVs"):
        df = pd.read_csv(csv_file)
        dfs.append(df)

    # Combine
    print("🔗 Combining all data...")
    final_df = pd.concat(dfs, ignore_index=True)

    # Save master CSV
    print("💾 Saving master CSV...")
    master_csv = OUTPUT_DIR / "master_all_data.csv"
    final_df.to_csv(master_csv, index=False)
    print(f"✅ Saved: {master_csv}")

    # Save master Parquet (unoptimized)
    print("💾 Saving master Parquet...")
    master_parquet = OUTPUT_DIR / "master_all_data.parquet"
    final_df.to_parquet(master_parquet, engine='pyarrow', compression='snappy')
    print(f"✅ Saved: {master_parquet}")

    # === OPTIMIZATION ===
    print("\n🚀 Optimizing for dashboard...")

    # Keep only necessary columns
    existing_cols = [c for c in KEEP_COLUMNS if c in final_df.columns]
    opt_df = final_df[existing_cols].copy()

    # Data type optimization
    print("⚙️  Optimizing data types...")
    for col in opt_df.columns:
        if opt_df[col].dtype == 'float64':
            opt_df[col] = opt_df[col].astype('float32')

    # Categorical encoding
    if 'Reach_Name' in opt_df.columns:
        opt_df['Reach_Name'] = opt_df['Reach_Name'].astype('category')

    # Convert Pass_Date to datetime
    if 'Pass_Date' in opt_df.columns:
        opt_df['Pass_Date'] = pd.to_datetime(opt_df['Pass_Date'])

    print(f"📦 Columns kept: {list(opt_df.columns)}")

    # Create partitioned parquet files
    print(f"✂️  Creating partitions ({ROWS_PER_CHUNK:,} rows per chunk)...")

    total_rows = len(opt_df)
    num_partitions = (total_rows + ROWS_PER_CHUNK - 1) // ROWS_PER_CHUNK

    for i in tqdm(range(num_partitions), desc="Writing partitions"):
        start_idx = i * ROWS_PER_CHUNK
        end_idx = min((i + 1) * ROWS_PER_CHUNK, total_rows)
        chunk = opt_df.iloc[start_idx:end_idx]

        output_file = OUTPUT_DIR / f"master_all_data_part_{i}.parquet"
        chunk.to_parquet(
            output_file,
            engine='pyarrow',
            compression='zstd',
            compression_level=9,
            index=False
        )

    print(f"\n✅ Rebuild complete!")
    print(f"   Total rows: {total_rows:,}")
    print(f"   Partitions: {num_partitions}")
    print(f"   Columns: {len(opt_df.columns)}")

if __name__ == "__main__":
    rebuild_master_files()
