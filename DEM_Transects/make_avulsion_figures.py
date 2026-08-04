"""
Temporary avulsion figures: per-transect beta (superelevation) and gamma (gradient
advantage), styled by value, with the Gearon avulsion threshold (beta*gamma >= Lambda ~ 2.1).

beta is computed here with Gearon's "method 2" (channel depth = ridge crest above the
water surface): beta = H_AR / (ARE - WSE), using SWOT water-surface elevations matched to
each transect by distance-from-anchor. gamma = S_AR / S_M comes from pick_features.

CAVEATS (temporary): SWOT-derived channel centerline + first-pass auto-picks (~10-15%
fail on valley walls); transect DEM uses a constant 13.46 m geoid offset vs SWOT's
spatially-varying geoid (~0.3 m). For visual exploration, not publication.

Run:  python3 DEM_Transects/make_avulsion_figures.py
"""

from __future__ import annotations

import os

import duckdb
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "outputs")
SWOT = os.path.join(ROOT, "dashboard_data.parquet")
ANCHOR_LAT, ANCHOR_LON = 59.82463509, -161.33397834  # from SWOT_Pull.py
LAMBDA = 2.1  # Gearon median avulsion threshold


def haversine_km(lat, lon, lat0=ANCHOR_LAT, lon0=ANCHOR_LON):
    R = 6371.0
    p1, p2 = np.radians(lat), np.radians(lat0)
    dphi = np.radians(lat0 - lat)
    dl = np.radians(lon0 - lon)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def channel_lonlat(samples: pd.DataFrame, picks: pd.DataFrame) -> pd.DataFrame:
    """For each transect, the lon/lat of the sample nearest the picked channel position."""
    rows = []
    for (reach, tid), g in samples.groupby(["Reach_Name", "transect_id"]):
        pk = picks[(picks.Reach_Name == reach) & (picks.transect_id == tid)]
        if pk.empty or not np.isfinite(pk.channel_x.iloc[0]):
            continue
        i = (g.cross_dist_m - pk.channel_x.iloc[0]).abs().idxmin()
        rows.append({"Reach_Name": reach, "transect_id": tid,
                     "lon": g.loc[i, "lon"], "lat": g.loc[i, "lat"]})
    return pd.DataFrame(rows)


def swot_wse_lookup(reach: str, bin_km: float = 0.2):
    """SWOT median WSE vs distance-from-anchor for a reach (interpolatable)."""
    con = duckdb.connect()
    df = con.execute(f"""
        SELECT ROUND(dist_km/{bin_km})*{bin_km} AS d, MEDIAN(wse) AS wse
        FROM read_parquet('{SWOT}')
        WHERE Reach_Name = ? AND classification IN (3,4)
        GROUP BY 1 ORDER BY 1
    """, [reach]).fetchdf()
    return df["d"].to_numpy(), df["wse"].to_numpy()


def build_table() -> pd.DataFrame:
    samples = pd.read_parquet(os.path.join(OUT, "transect_elevations.parquet"))
    picks = pd.read_parquet(os.path.join(OUT, "transect_picks.parquet"))
    cll = channel_lonlat(samples, picks)
    cll["dist_km"] = haversine_km(cll.lat.to_numpy(), cll.lon.to_numpy())
    df = picks.merge(cll, on=["Reach_Name", "transect_id"], how="left")

    df["wse"] = np.nan
    for reach in df.Reach_Name.unique():
        d, wse = swot_wse_lookup(reach)
        m = df.Reach_Name == reach
        df.loc[m, "wse"] = np.interp(df.loc[m, "dist_km"], d, wse, left=np.nan, right=np.nan)

    # beta via method 2: channel depth = ridge crest above water surface.
    depth = df["are"] - df["wse"]
    df["beta"] = df["har"] / depth.where(depth > 0)
    df["lambda_bg"] = df["beta"] * df["gamma"]
    # "clean" transects: real ridge, positive depth, sane metric ranges.
    df["clean"] = (df.har > 0.1) & (depth > 0.3) & df.beta.between(0, 10) & df.gamma.between(0, 20)
    return df


def fig_scatter(df, path):
    """Gearon Fig.3-style beta-gamma scatter with avulsion-threshold contours."""
    c = df[df.clean]
    fig, ax = plt.subplots(figsize=(7.5, 6.5))
    for lam, ls in [(1, ":"), (2.1, "-"), (5, "--")]:
        g = np.linspace(0.05, 20, 200)
        ax.plot(g, lam / g, ls, color="0.4", lw=1, label=f"Λ={lam}")
    colors = {"Kanektok_River": "firebrick", "Uyak_Creek": "dodgerblue"}
    for reach, sub in c.groupby("Reach_Name"):
        ax.scatter(sub.gamma, sub.beta, s=28, alpha=0.7, edgecolor="k", lw=0.3,
                   color=colors.get(reach, "gray"), label=reach.replace("_", " "))
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("γ  (gradient advantage = S_AR / S_M)")
    ax.set_ylabel("β  (superelevation = H_AR / H_M)")
    ax.set_title("Per-transect avulsion metrics\nupper-right of Λ lines = more avulsion-prone")
    ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def fig_maps(df, path):
    """Channel-point maps coloured by β, γ, and Λ=βγ (avulsion-prone highlighted)."""
    c = df[df.clean]
    fig, axes = plt.subplots(1, 3, figsize=(17, 6))
    specs = [("beta", "β superelevation", "viridis", None),
             ("gamma", "γ gradient advantage", "viridis", None),
             ("lambda_bg", "Λ = β·γ  (≥2.1 avulsion-prone)", "RdYlGn_r", LAMBDA)]
    for ax, (col, title, cmap, thr) in zip(axes, specs):
        vmax = np.nanpercentile(c[col], 95)
        sc = ax.scatter(c.lon, c.lat, c=c[col], cmap=cmap, s=30, vmin=0, vmax=vmax,
                        edgecolor="k", lw=0.2)
        if thr is not None:
            hot = c[c[col] >= thr]
            ax.scatter(hot.lon, hot.lat, facecolor="none", edgecolor="k", s=70, lw=1.0)
        fig.colorbar(sc, ax=ax, shrink=0.7)
        ax.set_title(title); ax.set_xlabel("lon"); ax.set_ylabel("lat")
    fig.suptitle("Transect avulsion metrics in map view (circled = above threshold)")
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def fig_profiles(df, path):
    """β, γ, Λ along each river vs distance from anchor."""
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    colors = {"Kanektok_River": "firebrick", "Uyak_Creek": "dodgerblue"}
    for col, ax, lbl in [("beta", axes[0], "β"), ("gamma", axes[1], "γ"),
                         ("lambda_bg", axes[2], "Λ = β·γ")]:
        for reach, sub in df[df.clean].groupby("Reach_Name"):
            sub = sub.sort_values("dist_km")
            ax.plot(sub.dist_km, sub[col], lw=1, marker="o", ms=2.5,
                    color=colors.get(reach), label=reach.replace("_", " "), alpha=0.8)
        ax.set_ylabel(lbl)
        ax.grid(alpha=0.3)
    axes[2].axhline(LAMBDA, color="k", ls="--", lw=1, label=f"Λ threshold = {LAMBDA}")
    axes[0].legend(fontsize=8); axes[2].legend(fontsize=8)
    axes[2].set_xlabel("distance from anchor (km)  —  0=confluence, →coast")
    fig.suptitle("Avulsion metrics along each river (clean transects)")
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def main():
    df = build_table()
    df.to_parquet(os.path.join(OUT, "transect_avulsion_metrics.parquet"), index=False)
    n = df.clean.sum()
    print(f"{len(df)} transects, {n} clean")
    for reach, g in df[df.clean].groupby("Reach_Name"):
        print(f"  {reach}: β median {g.beta.median():.2f}, γ median {g.gamma.median():.2f}, "
              f"Λ median {g.lambda_bg.median():.2f}, "
              f"% above Λ≥{LAMBDA}: {(g.lambda_bg >= LAMBDA).mean():.0%}")
    fig_scatter(df, os.path.join(OUT, "fig_beta_gamma_scatter.png"))
    fig_maps(df, os.path.join(OUT, "fig_avulsion_maps.png"))
    fig_profiles(df, os.path.join(OUT, "fig_avulsion_profiles.png"))
    print("wrote fig_beta_gamma_scatter.png, fig_avulsion_maps.png, fig_avulsion_profiles.png")


if __name__ == "__main__":
    main()
