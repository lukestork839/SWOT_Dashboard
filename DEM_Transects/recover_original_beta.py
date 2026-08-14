"""
Recover the original ArcGIS two-zone beta table from the project geodatabase.

The prior ArcGIS workflow (`V6. adding beta calculation values for each line.ipynb`)
errored before saving beta back to `Avulsion_Lines_2`, leaving those attribute columns
empty — but the elevation POINT layers it had already built are intact in the gdb.
This script re-reduces them, per transect (ORIG_SEQ_1):

    P98, P2  from `River_Elevation_2`          (near-channel clip zone)
    median   from `Total_Elevation_2_Clipped`  (broad floodplain clip zone)
    H_AR = P98 - median,  Hm = P98 - P2,  beta = H_AR / Hm

Verified output: beta median 0.96, H_AR median 4.30 m, 30% of transects perched
(beta > 1) — the "recovered original" quoted in AVULSION_ANALYSIS.md §2.

The gdb itself is too large to commit (~283 MB zipped). It is archived at
    ~/Downloads/clean_and_complete.gdb.zip
Recover it with:
    mkdir /tmp/clean_and_complete.gdb
    unzip ~/Downloads/clean_and_complete.gdb.zip -d /tmp/clean_and_complete.gdb
(the zip holds the gdb's internal files with no directory wrapper), or set
AVULSION_GDB to an existing extracted copy. The 199-row result is committed at
reference/original_beta.parquet, so this script only needs re-running if that
file is ever lost or questioned.

Run:  python3 DEM_Transects/recover_original_beta.py
"""

from __future__ import annotations

import os

import geopandas as gpd
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
GDB = os.environ.get("AVULSION_GDB", "/tmp/clean_and_complete.gdb")
OUT = os.path.join(HERE, "reference", "original_beta.parquet")


def main():
    if not os.path.exists(GDB):
        raise SystemExit(
            f"gdb not found: {GDB}\n"
            "Recover it:  mkdir /tmp/clean_and_complete.gdb && "
            "unzip ~/Downloads/clean_and_complete.gdb.zip -d /tmp/clean_and_complete.gdb\n"
            "or point AVULSION_GDB at an extracted copy."
        )

    riv = gpd.read_file(GDB, layer="River_Elevation_2").dropna(subset=["Z"])
    tot = gpd.read_file(GDB, layer="Total_Elevation_2_Clipped").dropna(subset=["Z"])
    print(f"River_Elevation_2: {len(riv)} pts | Total_Elevation_2_Clipped: {len(tot)} pts")

    near = riv.groupby("ORIG_SEQ_1")["Z"].agg(
        p98=lambda z: np.percentile(z, 98),
        p2=lambda z: np.percentile(z, 2),
    )
    o = near.join(tot.groupby("ORIG_SEQ_1")["Z"].median().rename("median"), how="inner")
    o["har"] = o["p98"] - o["median"]
    o["hm"] = o["p98"] - o["p2"]
    o["beta"] = o["har"] / o["hm"]

    o.to_parquet(OUT)
    print(f"{len(o)} transects -> {OUT}")
    print(f"beta median {o['beta'].median():.2f}, H_AR median {o['har'].median():.2f} m, "
          f"perched (beta>1) {(o['beta'] > 1).mean() * 100:.0f}%")


if __name__ == "__main__":
    main()
