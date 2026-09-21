"""
Ingest the boat-ADCP velocity/depth survey into ONE tracked parquet.

This is the only script in the repo that touches the raw ADCP archive. Everything downstream
(`build_kanektok_centerline.py`, `adcp_depth_stats.py`, and through them the Gearon beta in
`build_arc_B.py`) reads the parquet this writes, so the analysis reproduces from a clean clone
with no external folder and no hardcoded personal path.

WHAT IS INGESTED. Every `*/Shapefiles/*_velocity_depth_01_ASC.shp` under the archive — the
RiverSurveyor velocity/depth export, one shapefile per transect, ~40.8 k pings across six survey
days (Kanektok Days 02/02b/03/05/06 + Uiyak Day 04), May-Jun 2026. All attribute columns are kept
verbatim; the geometry is dropped because it duplicates LAT/LON exactly. At ~1.5 MB (zstd) this is
the whole scientific content of the depth survey, so it lives in git.

WHAT IS NOT. The archive is ~386 MB: raw instrument binaries (`.PD0`), per-transect NetCDF, the
`Law of the Wall` / `Valid_Near_Bed_Long_Format` CSV intermediates, discharge summary workbooks, and
the coworkers' notebooks. None of it feeds this analysis, and it belongs in a data repository rather
than git. It stays in the archive; this script records what it read in the manifest beside the
parquet.

ARCHIVE LOCATION. Only needed to re-run this script (the parquet is committed). Resolution order:
  1. `--adcp-dir /path/to/ADCP Data`
  2. `$SWOT_ADCP_DIR`
  3. `~/Downloads/ADCP Data`  (where the archive currently sits)

Run:  python3 DEM_Transects/ingest_adcp.py            # -> data/adcp_velocity_depth.parquet
      python3 DEM_Transects/ingest_adcp.py --check    # verify the committed parquet, write nothing
"""

from __future__ import annotations

import argparse
import glob
import json
import os

import geopandas as gpd
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
PARQUET = os.path.join(DATA, "adcp_velocity_depth.parquet")
MANIFEST = os.path.join(DATA, "adcp_velocity_depth.manifest.json")

DEFAULT_ADCP_DIR = os.path.expanduser("~/Downloads/ADCP Data")
SHP_GLOB = os.path.join("*", "Shapefiles", "*_velocity_depth_01_ASC.shp")

ANCHOR = (59.82463509, -161.33397834)   # lat, lon — shared radial origin (SWOT/DEM dist_km)
R_EARTH = 6371.0088

# Attribute columns of the RiverSurveyor velocity_depth export, kept verbatim.
#   YY/MONTH/DAY/HOUR/MINUTE/SECOND/HS  ping timestamp (HS = hundredths of a second)
#   LAT/LON/ALT                         GPS position and antenna altitude (m)
#   DEPTH                               measured river depth (m) — the beta H_M term
#   WSPEED/FDIR                         water speed (m/s) and flow direction (deg)
#   TRANSECT                            source file stem = one boat transect
COLS = ["YY", "MONTH", "DAY", "HOUR", "MINUTE", "SECOND", "HS",
        "LAT", "LON", "ALT", "DEPTH", "WSPEED", "FDIR", "TRANSECT"]
# Downcast only where it is lossless at the instrument's precision. LAT/LON stay float64 (1e-6 deg
# ~ 0.1 m matters) and so does DEPTH — it is the measurement the Gearon beta bed rests on, and the
# export carries 6 decimals, which float32 cannot hold at metre-scale values. The rest is
# float32/int16; the whole file is ~1.8 MB either way.
F32 = ["ALT", "WSPEED", "FDIR"]
I16 = ["YY", "MONTH", "DAY", "HOUR", "MINUTE", "SECOND", "HS"]


def dist_km(lat, lon):
    """Great-circle distance (km) from the anchor — the arc-frame downstream coordinate."""
    la1, lo1 = np.radians(ANCHOR[0]), np.radians(ANCHOR[1])
    la2, lo2 = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    a = (np.sin((la2 - la1) / 2) ** 2
         + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R_EARTH * np.arcsin(np.sqrt(a))


def resolve_adcp_dir(cli_dir: str | None) -> str:
    for cand in (cli_dir, os.environ.get("SWOT_ADCP_DIR"), DEFAULT_ADCP_DIR):
        if cand and os.path.isdir(os.path.expanduser(cand)):
            return os.path.expanduser(cand)
    raise SystemExit(
        "ADCP archive not found. The committed parquet is what the analysis reads, so you only\n"
        "need the archive to re-ingest. Point at it with one of:\n"
        "  python3 DEM_Transects/ingest_adcp.py --adcp-dir '/path/to/ADCP Data'\n"
        "  SWOT_ADCP_DIR='/path/to/ADCP Data' python3 DEM_Transects/ingest_adcp.py\n"
        f"  or place it at {DEFAULT_ADCP_DIR}"
    )


def ingest(adcp_dir: str) -> tuple[pd.DataFrame, list[str]]:
    """Read every velocity_depth shapefile into one frame, preserving archive row order.

    `ping_seq` is the ping's original 0-based row index within its shapefile. The export writes
    pings in acquisition order but timestamps only to the second (several pings share a second), so
    a sort on the timestamp alone cannot restore that order. Keeping the index makes downstream
    ordering exact and deterministic instead of tie-broken by the sort algorithm.
    """
    files = sorted(glob.glob(os.path.join(adcp_dir, SHP_GLOB)))
    if not files:
        raise SystemExit(f"No velocity_depth shapefiles under {adcp_dir}/{SHP_GLOB}")
    frames = []
    for f in files:
        g = gpd.read_file(f)
        missing = [c for c in COLS if c not in g.columns]
        if missing:
            raise SystemExit(f"{f}: missing expected columns {missing}")
        df = pd.DataFrame({c: g[c].to_numpy() for c in COLS})
        # Survey day = the archive folder holding the Shapefiles dir (Kanektok_Day_03, Uiyak_Day_04…)
        df["survey_day"] = os.path.basename(os.path.dirname(os.path.dirname(f)))
        df["ping_seq"] = np.arange(len(df), dtype="int32")
        frames.append(df)

    a = pd.concat(frames, ignore_index=True)
    a["radius_km"] = dist_km(a["LAT"], a["LON"])
    # River is a property of the survey day: Days 02/02b/03/05/06 are Kanektok, Day 04 the Uyak.
    # ("Uiyak" is the archive's spelling; the repo uses "Uyak" throughout.)
    a["river"] = np.where(a["survey_day"].str.startswith("Uiyak"), "Uyak_Creek", "Kanektok_River")
    for c in I16:
        a[c] = a[c].astype("int16")
    for c in F32:
        a[c] = a[c].astype("float32")
    a["radius_km"] = a["radius_km"].astype("float32")
    for c in ("TRANSECT", "survey_day", "river"):
        a[c] = a[c].astype("category")
    rel = [os.path.relpath(f, adcp_dir) for f in files]
    return a, rel


def summarize(a: pd.DataFrame) -> None:
    print(f"\n{len(a):,} pings, {a['TRANSECT'].nunique()} transects, "
          f"radius {a['radius_km'].min():.2f}-{a['radius_km'].max():.2f} km")
    g = (a.groupby("survey_day", observed=True)
          .agg(pings=("DEPTH", "size"), transects=("TRANSECT", "nunique"),
               valid_depth=("DEPTH", lambda s: int((s > 0).sum())),
               depth_med=("DEPTH", "median"),
               r_min=("radius_km", "min"), r_max=("radius_km", "max")))
    for day, r in g.iterrows():
        print(f"  {day:24s} {int(r.pings):6,d} pings  {int(r.transects):3d} transects  "
              f"depth med {r.depth_med:.2f} m  radius {r.r_min:5.2f}-{r.r_max:5.2f} km")


def check() -> None:
    """Report the committed parquet without touching the archive (clean-clone smoke test)."""
    if not os.path.exists(PARQUET):
        raise SystemExit(f"missing {os.path.relpath(PARQUET, HERE)} — run without --check to build it")
    a = pd.read_parquet(PARQUET)
    print(f"read {os.path.relpath(PARQUET, HERE)} "
          f"({os.path.getsize(PARQUET) / 1e6:.1f} MB)")
    summarize(a)
    if os.path.exists(MANIFEST):
        with open(MANIFEST) as fh:
            m = json.load(fh)
        print(f"\nmanifest: {m['n_source_files']} source shapefiles from "
              f"{m['source_archive']} ({m['survey_window']})")


def main():
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[1])
    ap.add_argument("--adcp-dir", default=None,
                    help="path to the raw 'ADCP Data' archive (else $SWOT_ADCP_DIR, else ~/Downloads)")
    ap.add_argument("--check", action="store_true",
                    help="summarize the committed parquet and exit; needs no archive")
    args = ap.parse_args()

    if args.check:
        check()
        return

    adcp_dir = resolve_adcp_dir(args.adcp_dir)
    print(f"ingesting from {adcp_dir}")
    a, rel = ingest(adcp_dir)
    summarize(a)

    os.makedirs(DATA, exist_ok=True)
    a.to_parquet(PARQUET, index=False, compression="zstd")
    dates = pd.to_datetime(pd.DataFrame({"year": 2000 + a["YY"].astype(int),
                                         "month": a["MONTH"].astype(int),
                                         "day": a["DAY"].astype(int)}))
    manifest = {
        "product": "RiverSurveyor velocity_depth export (*_velocity_depth_01_ASC.shp)",
        # Written home-relative: the manifest is tracked in a public repo, so it records WHERE the
        # archive sat without pinning a username into git history.
        "source_archive": adcp_dir.replace(os.path.expanduser("~"), "~", 1),
        "n_source_files": len(rel),
        "n_pings": int(len(a)),
        "survey_window": f"{dates.min().date()} .. {dates.max().date()}",
        "surveys": {str(k): int(v) for k, v in
                    a.groupby("survey_day", observed=True).size().items()},
        "columns_kept": COLS + ["survey_day", "ping_seq", "radius_km", "river"],
        "anchor_lat_lon": list(ANCHOR),
        "not_ingested": ("raw .PD0 instrument binaries, per-transect NetCDF, Law-of-the-Wall and "
                         "Valid_Near_Bed_Long_Format CSV intermediates, discharge summary "
                         "workbooks, coworker notebooks (~386 MB total, none used by this analysis)"),
        "source_files": rel,
    }
    with open(MANIFEST, "w") as fh:
        json.dump(manifest, fh, indent=1)
    print(f"\nwrote {os.path.relpath(PARQUET, HERE)} ({os.path.getsize(PARQUET) / 1e6:.1f} MB)")
    print(f"wrote {os.path.relpath(MANIFEST, HERE)} ({len(rel)} source files listed)")


if __name__ == "__main__":
    main()
