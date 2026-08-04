# Validation: our avulsion-metric port vs. Gearon et al. (2024)

**Harness:** `validate_against_gearon.py` recomputes β, γ, Λ from the raw inputs in the
authors' released `fig2_data.csv` (snapshot in `data/gearon_fig2_data.csv`, 58 avulsion
sites) using `DEM_Transects/avulsion_metrics.py`, and compares to their published
`beta` / `gamma` / `lambda` columns.

## Result — our formula port is faithful ✅

| Metric | Comparison | Result |
|---|---|---|
| **β** (superelevation) | our deterministic vs their published Monte-Carlo mean | max abs err **6.3×10⁻⁸**, 58/58 within 5% |
| **γ** (gradient advantage) | our `sar_mean/sm_mean` vs published γ | max abs err **3.8×10⁻¹²**, exact, 58/58 |
| **Λ = β·γ** | reproduced exactly when γ uses their `sar_mean` | exact |

Our β/γ/Λ implementation reproduces the published numbers to floating-point precision.
The pipeline math is verified before applying it to Kanektok/Uyak.

## Finding — apparent typo in the published γ (sar_mean)

`reproduce_figs.py:59` computes the alluvial-ridge slope mean as:

```python
df['sar_mean'] = df[['sar1', 'sar1', 'sar3']].mean(axis=1)   # sar1 twice, sar2 dropped
df['sm_mean']  = df[['sm1', 'sm2', 'sm3']].mean(axis=1)       # next line: correct (1,2,3)
```

We confirmed the published `sar_mean` equals `mean(sar1, sar1, sar3)` **exactly**
(max diff 1×10⁻¹⁶), not the intended `mean(sar1, sar2, sar3)`. Because `sm_mean` on the
following line uses 1/2/3 correctly, this looks like a copy-paste typo rather than a
deliberate exclusion of transect 2.

- **Impact:** affects **57 / 58 sites** (every site where `sar2 ≠ sar1`). Recomputing γ
  with the intended mean shifts it by a **median 12.6%** (max 126%) per site, and Λ with it.
- **β is unaffected** (it does not use the sar columns).
- This does not necessarily overturn the paper's source-to-sink *trends* (which are
  broad and log-scale), but individual published γ/Λ values carry this artifact.

### How we handle it
`avulsion_metrics.mean_slope()` uses the **intended** `mean(sar1, sar2, sar3)`. The
harness reports both:
- γ from their `sar_mean` column → exact match (proves our formula is right);
- γ from raw `sar1,sar2,sar3` → diverges (surfaces the typo, not silently absorbed).

When we publish Kanektok/Uyak γ values we will use the corrected mean and note the
difference from the published dataset. Worth raising with the authors (jhgearon@iu.edu)
if we cite their per-site γ/Λ.
