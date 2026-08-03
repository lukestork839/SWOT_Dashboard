"""
Validation harness: prove our avulsion_metrics port reproduces Gearon et al. (2024)'s
published beta / gamma / Lambda from their own input data.

We read the authors' released fig2_data.csv (snapshotted in validation/data/), recompute
beta, gamma, and Lambda from the raw per-transect inputs (are/fpe/wse, sar/sm, xgb_depth,
method_used) using DEM_Transects/avulsion_metrics.py, and compare against the published
beta/gamma/lambda columns. If our port is faithful, the differences are ~0 (gamma exactly;
beta within Monte-Carlo noise since their published beta is a stochastic mean).

Run:  python3 DEM_Transects/validation/validate_against_gearon.py
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import avulsion_metrics as am  # noqa: E402

GROUND_TRUTH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "gearon_fig2_data.csv")


def _row_dicts(row):
    """Pull per-transect inputs from a fig2_data row into {transect: value} dicts."""
    are = {i: row.get(f"are{i}_m", np.nan) for i in (1, 2, 3)}
    fpe = {i: row.get(f"fpe{i}_m", np.nan) for i in (1, 2, 3)}
    wse = {i: row.get(f"wse{i}_m", np.nan) for i in (1, 2, 3)}
    return are, fpe, wse


def recompute(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for _, row in df.iterrows():
        are, fpe, wse = _row_dicts(row)
        method = int(row["method_used"])
        xgb = row.get("xgb_depth", np.nan)

        beta = am.site_superelevation(are, fpe, method, wse, xgb)
        # gamma from the raw per-transect slopes (intended sar1,sar2,sar3 mean).
        sar = am.mean_slope([row.get("sar1"), row.get("sar2"), row.get("sar3")])
        sm = am.mean_slope([row.get("sm1"), row.get("sm2"), row.get("sm3")])
        gamma = am.gradient_advantage(sar, sm)
        # gamma exactly as published: their sar_mean / sm_mean columns.
        gamma_published_inputs = am.gradient_advantage(row.get("sar_mean"), row.get("sm_mean"))

        out.append({
            "name": row.get("Avulsion Name"),
            "method": method,
            "beta_ours": beta, "beta_pub": row.get("beta"),
            "gamma_ours": gamma, "gamma_pub": row.get("gamma"),
            "gamma_from_pub_means": gamma_published_inputs,
            "lambda_ours": am.avulsion_lambda(beta, gamma),
            "lambda_pub": row.get("lambda"),
        })
    return pd.DataFrame(out)


def _report(label, ours, pub, rtol):
    mask = np.isfinite(ours) & np.isfinite(pub)
    o, p = ours[mask], pub[mask]
    abs_err = np.abs(o - p)
    rel_err = abs_err / np.where(np.abs(p) > 1e-9, np.abs(p), np.nan)
    within = np.nansum(rel_err <= rtol)
    print(f"\n{label}: {len(o)} comparable sites")
    print(f"  max abs err = {np.nanmax(abs_err):.4g} | "
          f"median rel err = {np.nanmedian(rel_err):.3%} | "
          f"within {rtol:.0%}: {within}/{len(o)}")
    worst = np.argsort(-rel_err)[:3]
    for w in worst:
        print(f"    worst: rel={rel_err[w]:.2%}  ours={o.iloc[w]:.4g}  pub={p.iloc[w]:.4g}")
    return within == len(o)


def main():
    if not os.path.exists(GROUND_TRUTH):
        sys.exit(f"Ground-truth not found: {GROUND_TRUTH}")
    df = pd.read_csv(GROUND_TRUTH)
    print(f"Loaded {len(df)} published avulsion sites from {os.path.basename(GROUND_TRUTH)}")
    res = recompute(df)

    # gamma should match the published value essentially exactly when computed from
    # their own sar_mean/sm_mean columns (deterministic, no sampling).
    ok_gamma_exact = _report("gamma (from published sar_mean/sm_mean)",
                             res["gamma_from_pub_means"], res["gamma_pub"], rtol=0.001)
    # gamma from raw sar1/sar2/sar3 surfaces the sar2-vs-sar1 averaging discrepancy.
    _report("gamma (from raw sar1,sar2,sar3 — intended mean)",
            res["gamma_ours"], res["gamma_pub"], rtol=0.05)
    # beta is a Monte-Carlo mean in their code; our deterministic value is its expectation.
    ok_beta = _report("beta (deterministic vs published MC mean)",
                      res["beta_ours"], res["beta_pub"], rtol=0.05)
    _report("Lambda = beta*gamma", res["lambda_ours"], res["lambda_pub"], rtol=0.05)

    print("\n" + "=" * 60)
    print(f"gamma exact match (<=0.1%): {'PASS' if ok_gamma_exact else 'CHECK'}")
    print(f"beta within MC noise (<=5%): {'PASS' if ok_beta else 'CHECK'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
