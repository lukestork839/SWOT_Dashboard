"""
Rough figures reproducing the prior avulsion analysis, for BOTH rivers.

Reads reproduce_beta.py outputs (transect_beta.parquet, transect_profiles.parquet) and
makes, per reach:
  1. Long profile — Alluvial Ridge (P98) / Floodplain (median) / River Depth (P2) vs
     distance upstream   (cf. prior "Comparing_Elevation")
  2. H_AR & Hm vs distance upstream                        (cf. prior "Har and Hm")
  3. beta vs distance upstream
  4. a few example transect side-profiles                  (cf. prior "Transect_XX")

Plus a Kanektok-vs-Uyak H_AR / beta comparison. Figures are quick sanity plots
(numbers-first), not final styled thesis figures.

Run:  python3 DEM_Transects/make_beta_figures.py
"""

from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "outputs")

RIDGE = "#9ecae1"      # light blue  (P98, alluvial ridge)
RIVER = "#08519c"      # dark blue   (P2, river depth)
FLOOD = "#a1d99b"      # green       (median, floodplain)


def long_profile_ax(ax, b: pd.DataFrame, title: str):
    x = b["station_m"] / 1000.0
    ax.plot(x, b["are_p98"], color=RIDGE, lw=1.5, label="Alluvial Ridge (P98)")
    ax.plot(x, b["floodplain_median"], color=FLOOD, lw=1.5, label="Floodplain (median)")
    ax.plot(x, b["channel_p2"], color=RIVER, lw=1.5, label="River Depth (P2)")
    ax.set_xlabel("Distance upstream (km)")
    ax.set_ylabel("Elevation (m)")
    ax.set_title(title)
    ax.legend(fontsize=8, loc="upper left")


def har_hm_ax(ax, b: pd.DataFrame, title: str):
    x = b["station_m"] / 1000.0
    ax.plot(x, b["hm"], color=RIVER, lw=1.0, label="Hm = P98 - P2")
    ax.plot(x, b["har"], color=RIDGE, lw=1.0, label="H_AR = P98 - median")
    ax.set_xlabel("Distance upstream (km)")
    ax.set_ylabel("Height (m)")
    ax.set_title(title)
    ax.legend(fontsize=8)


def beta_ax(ax, b: pd.DataFrame, title: str):
    x = b["station_m"] / 1000.0
    ax.plot(x, b["beta"], color="#d94801", lw=1.0)
    ax.axhline(b["beta"].median(), color="k", ls="--", lw=0.8,
               label=f"median {b['beta'].median():.2f}")
    ax.set_xlabel("Distance upstream (km)")
    ax.set_ylabel("beta = H_AR / Hm")
    ax.set_ylim(0, 1)
    ax.set_title(title)
    ax.legend(fontsize=8)


def example_profiles_ax(ax, prof: pd.DataFrame, b: pd.DataFrame, title: str, n: int = 3):
    """Plot n example transect side-profiles spread along the reach."""
    tids = b["transect_id"].to_numpy()
    picks = tids[np.linspace(0, len(tids) - 1, n).astype(int)]
    for tid in picks:
        g = prof[prof["transect_id"] == tid].sort_values("cross_dist_m")
        st = float(b.loc[b["transect_id"] == tid, "station_m"].iloc[0]) / 1000.0
        ax.plot(g["cross_dist_m"], g["elevation_m"], lw=0.8,
                label=f"#{tid} @ {st:.1f} km")
    ax.set_xlabel("Cross-transect distance (m)")
    ax.set_ylabel("Elevation (m)")
    ax.set_title(title)
    ax.legend(fontsize=8)


def main():
    beta = pd.read_parquet(os.path.join(OUT, "transect_beta.parquet"))
    prof = pd.read_parquet(os.path.join(OUT, "transect_profiles.parquet"))

    for reach, b in beta.groupby("Reach_Name"):
        b = b.sort_values("station_m")
        p = prof[prof["Reach_Name"] == reach]
        fig, axes = plt.subplots(2, 2, figsize=(14, 9))
        long_profile_ax(axes[0, 0], b, f"{reach} — long profile")
        har_hm_ax(axes[0, 1], b, f"{reach} — H_AR & Hm")
        beta_ax(axes[1, 0], b, f"{reach} — superelevation beta")
        example_profiles_ax(axes[1, 1], p, b, f"{reach} — example transects")
        fig.tight_layout()
        dst = os.path.join(OUT, f"beta_summary_{reach}.png")
        fig.savefig(dst, dpi=130)
        plt.close(fig)
        print(f"wrote {dst}")

    # Cross-river comparison.
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for reach, b in beta.groupby("Reach_Name"):
        b = b.sort_values("station_m")
        axes[0].plot(b["station_m"] / 1000.0, b["har"], lw=1.0, label=reach)
        axes[1].plot(b["station_m"] / 1000.0,
                     b["beta"].rolling(11, center=True, min_periods=1).median(),
                     lw=1.2, label=reach)
    axes[0].set(xlabel="Distance upstream (km)", ylabel="H_AR (m)",
                title="Ridge height H_AR — Kanektok vs Uyak")
    axes[1].set(xlabel="Distance upstream (km)", ylabel="beta (11-transect median)",
                title="Superelevation beta — Kanektok vs Uyak", ylim=(0, 1))
    for ax in axes:
        ax.legend(fontsize=9)
    fig.tight_layout()
    dst = os.path.join(OUT, "beta_comparison.png")
    fig.savefig(dst, dpi=130)
    plt.close(fig)
    print(f"wrote {dst}")

    # Compact numeric summary.
    print("\n=== summary ===")
    for reach, b in beta.groupby("Reach_Name"):
        print(f"{reach}: n={len(b)}, H_AR median {b['har'].median():.2f} m, "
              f"Hm median {b['hm'].median():.2f} m, beta median {b['beta'].median():.2f}")


if __name__ == "__main__":
    main()
