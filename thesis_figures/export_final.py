"""Export built figures and captions to thesis_figures/final/ under their
final thesis numbers.

The generator scripts keep their stable file-series names (figure_00..09,
dem_fig01..05); this script is the single place that maps those names to the
sequential figure numbers used in the thesis document. Re-run it after any
figure regeneration; assembly should pull images and captions from final/
only.

Usage:
    python -m thesis_figures.export_final
"""

from __future__ import annotations

import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "output"
CAPTIONS = HERE / "captions"
FINAL = HERE / "final"

# thesis number -> (series subdir, output file stem, caption file name)
FIGURE_MAP = {
    1: ("SWOT_Figures", "figure_00", "figure_00_caption.txt"),
    2: ("SWOT_Figures", "figure_01", "figure_01_caption.txt"),
    3: ("SWOT_Figures", "figure_02", "figure_02_caption.txt"),
    4: ("DEM_Figures", "dem_fig01_D", "dem_fig01_caption.txt"),
    5: ("SWOT_Figures", "figure_04", "figure_04_caption.txt"),
    6: ("SWOT_Figures", "figure_08", "figure_08_caption.txt"),
    7: ("SWOT_Figures", "figure_09", "figure_09_caption.txt"),
    8: ("DEM_Figures", "dem_fig05", "dem_fig05_caption.txt"),
    9: ("DEM_Figures", "dem_fig04_M", "dem_fig04_M_caption.txt"),
    10: ("DEM_Figures", "dem_fig04_P", "dem_fig04_P_caption.txt"),
    11: ("DEM_Figures", "dem_fig02", "dem_fig02_caption.txt"),
    12: ("DEM_Figures", "dem_fig04_S", "dem_fig04_S_caption.txt"),
    13: ("SWOT_Figures", "figure_05", "figure_05_caption.txt"),
    14: ("SWOT_Figures", "figure_06", "figure_06_caption.txt"),
    15: ("SWOT_Figures", "figure_07", "figure_07_caption.txt"),
    # The temporal-stability record is exported as three standalone figures
    # (stage vs date, gradient vs date, gradient vs stage) so each can be
    # placed beside the Results text that discusses it.
    16: ("SWOT_Figures", "figure_03a", "figure_03a_caption.txt"),
    17: ("SWOT_Figures", "figure_03b", "figure_03b_caption.txt"),
    18: ("SWOT_Figures", "figure_03c", "figure_03c_caption.txt"),
}

# Supplementary text files that ride along with a figure.
EXTRA_TEXT = {
    3: ("SWOT_Figures", "figure_02_detailed.txt", "Figure_03_detailed.txt"),
}


def main() -> None:
    FINAL.mkdir(exist_ok=True)
    for stale in FINAL.glob("Figure_*"):
        stale.unlink()

    missing = []
    for n, (series, stem, caption) in sorted(FIGURE_MAP.items()):
        copied = []
        for ext in (".png", ".pdf"):
            src = OUTPUT / series / f"{stem}{ext}"
            if src.exists():
                shutil.copy2(src, FINAL / f"Figure_{n:02d}{ext}")
                copied.append(ext)
            else:
                missing.append(str(src.relative_to(HERE)))
        cap = CAPTIONS / series / caption
        if cap.exists():
            shutil.copy2(cap, FINAL / f"Figure_{n:02d}_caption.txt")
            copied.append("caption")
        else:
            missing.append(str(cap.relative_to(HERE)))
        print(f"Figure {n:02d}  <-  {series}/{stem}  [{', '.join(copied)}]")

    for n, (series, name, out_name) in EXTRA_TEXT.items():
        src = CAPTIONS / series / name
        if src.exists():
            shutil.copy2(src, FINAL / out_name)
            print(f"Figure {n:02d}  <-  {series}/{name}  [extra text]")
        else:
            missing.append(str(src.relative_to(HERE)))

    if missing:
        print("\nMISSING sources (regenerate and re-run):")
        for m in missing:
            print(f"  - {m}")
        raise SystemExit(1)
    print(f"\nExported {len(FIGURE_MAP)} figures to {FINAL.relative_to(HERE.parent)}/")


if __name__ == "__main__":
    main()
