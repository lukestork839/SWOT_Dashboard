"""Hydraulic Gradient tab: per-pass Theil-Sen reference gradient and decomposition."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .common import COLOR_MAP, load_reference_gradient, load_refgrad_decomposition


def render(ctx):
    con = ctx.con
    plotly_template = ctx.plotly_template
    selected_reaches = ctx.selected_reaches

    st.subheader("Reference Hydraulic Gradient")
    ref_df = load_reference_gradient(con, ctx.data_version)

    if ref_df is None or len(ref_df) == 0:
        st.info(
            "Reference gradient data not available. If running locally, run `SWOT_Pull.py` "
            "(it writes `reference_gradient_per_pass.parquet` automatically at the end of a pull)."
        )
    else:
        ow = ref_df[(ref_df["open_water"]) & (ref_df["gated"])].copy()
        ow["abs_slope"] = ow["theilsen_cm_km"].abs()

        st.markdown(
            "**Median of per-pass robust (Theil–Sen) slopes over the full open-water record (Apr–Nov).** "
            "This is a characteristic property of each river: it is computed from *all* qualifying open-water "
            "passes and does **not** change with the pass selection above — nor is it the slope of any single "
            "line drawn on the Gradient Profile chart."
        )

        grad_order = sorted(selected_reaches, key=lambda r: r == "Uyak_Creek")

        # --- Headline metrics (one per river) ---
        mcols = st.columns(len(grad_order))
        for i, reach in enumerate(grad_order):
            d = ow[ow["Reach_Name"] == reach]
            if len(d) == 0:
                mcols[i].metric(reach.replace("_", " "), "—")
                continue
            mcols[i].metric(
                reach.replace("_", " "),
                f"{d['abs_slope'].median():.1f} cm/km",
                help=(f"Median of {len(d)} full-coverage open-water passes · "
                      f"IQR {d['abs_slope'].quantile(0.25):.1f}–{d['abs_slope'].quantile(0.75):.1f} cm/km"),
            )

        # --- Per-pass distribution: every pass as a jittered dot, with a bold
        #     median line and a shaded middle-50% (IQR) band. Clearer than a box
        #     plot here — Kanektok's IQR is so small a box collapses to a line. ---
        fig_g = go.Figure()
        rng = np.random.default_rng(42)  # fixed seed -> jitter is stable across reruns
        xpos = {}
        for xi, reach in enumerate(grad_order):
            d = ow[ow["Reach_Name"] == reach]
            if len(d) == 0:
                continue
            xpos[reach] = xi
            color = COLOR_MAP.get(reach, "black")
            vals = d["abs_slope"].to_numpy()
            q25, med, q75 = np.percentile(vals, [25, 50, 75])

            # shaded middle-50% (IQR) band
            fig_g.add_shape(type="rect", x0=xi - 0.30, x1=xi + 0.30, y0=q25, y1=q75,
                            fillcolor=color, opacity=0.12, line_width=0, layer="below")
            # bold median line = the headline value
            fig_g.add_shape(type="line", x0=xi - 0.36, x1=xi + 0.36, y0=med, y1=med,
                            line=dict(color=color, width=3))
            # every pass as a jittered dot
            jitter = rng.uniform(-0.16, 0.16, size=len(vals))
            fig_g.add_trace(go.Scatter(
                x=xi + jitter, y=vals, mode="markers",
                marker=dict(color=color, size=5, opacity=0.45),
                name=reach.replace("_", " "),
                hovertemplate="%{y:.1f} cm/km<extra></extra>",
            ))
        fig_g.update_layout(
            yaxis_title="Per-pass gradient (cm/km)",
            height=520, template=plotly_template, showlegend=False,
            title="Distribution of per-pass robust slopes (each dot = one satellite pass)",
            xaxis=dict(tickmode="array", tickvals=list(xpos.values()),
                       ticktext=[r.replace("_", " ") for r in xpos],
                       range=[-0.6, len(xpos) - 0.4]),
        )
        st.plotly_chart(fig_g, use_container_width=True, theme=None)
        st.caption("Each dot is one satellite pass. The **line** marks the typical value (median); "
                   "the **shaded band** covers the middle 50% of passes. A tighter band means a more "
                   "consistent river.")

        # --- Methodology ---
        with st.expander("How this number is calculated"):
            st.markdown("""
            For **each satellite pass**:
            1. Water-surface elevations are aggregated to **1 km nodes** (median WSE per node).
               This removes along-stream point-density bias before fitting.
            2. A single reach slope is fit with the **Theil–Sen estimator** (median of all
               pairwise slopes) — robust to outliers, unlike ordinary least squares.

            We keep only passes that image the **full river** — at least **8 nodes**, a span of
            **≥ 30 km**, and a start within **3 km of the anchor point**. This matters because both
            rivers are steep near the anchor point and gentle toward the mouth, so a pass that only
            catches part of the river reports a misleadingly different slope. Only the
            **open-water season (Apr–Nov)** is used — winter ice inflates WSE by 0.5–2+ m.

            The headline value is the **median of those per-pass slopes** across all qualifying
            passes. See `SCIENTIFIC_METHODOLOGY.md` → *Reference Gradient (Per-Pass Robust
            Regression)* for the full verification.
            """)

        # --- Optional decomposition: why this differs from the visual trendline ---
        with st.expander("Why this differs from the Gradient Profile trendline"):
            decomp = load_refgrad_decomposition(con, ctx.data_version)
            if decomp is None:
                st.caption("Decomposition unavailable for the current data source.")
            else:
                rows = []
                for reach in grad_order:
                    d = ow[ow["Reach_Name"] == reach]
                    dd = decomp[decomp["Reach_Name"] == reach]
                    if len(d) == 0 or len(dd) == 0:
                        continue
                    rows.append({
                        "River": reach.replace("_", " "),
                        "[A] pooled OLS, raw pixels": dd["pooled_raw"].iloc[0],
                        "[B] pooled OLS, 1km nodes": dd["pooled_nodes"].iloc[0],
                        "[C] per-pass OLS, mean": d["ols_cm_km"].abs().mean(),
                        "[D] per-pass Theil–Sen, mean": d["abs_slope"].mean(),
                        "[D′] Theil–Sen, median (reference)": d["abs_slope"].median(),
                    })
                if rows:
                    st.dataframe(
                        pd.DataFrame(rows).style.format({c: "{:.1f}" for c in rows[0] if c != "River"}),
                        width="stretch", hide_index=True,
                    )
                st.caption(
                    "[A] is the old Gradient Profile trendline (density-biased — dense downstream "
                    "pixels flatten it). [A]→[B] removing that bias is the dominant correction; "
                    "per-pass averaging and the robust estimator are smaller refinements."
                )
