"""Detrended Profile tab: polynomial baseline removal and residual outlier flags."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .common import (COLOR_MAP, MAX_BASELINE_POINTS, MAX_PLOT_POINTS,
                     RESIDUAL_MAD_THRESHOLD, add_bifurcation_line,
                     extract_selection, flag_residual_outliers, load_detrend_frame)


def render(ctx):
    con = ctx.con
    detrend_method = ctx.detrend_method
    plotly_template = ctx.plotly_template
    selected_reaches = ctx.selected_reaches
    where_clause = ctx.where_clause

    st.subheader("Detrended Elevation Profile")

    try:
        # Fetch + detrend ONCE per (passes, method); cached so the figure is stable
        # across reruns and the chart's box-selection survives (see load_detrend_frame).
        baseline_df, method_name, total_count, _coeffs = load_detrend_frame(
            con, ctx.data_version, where_clause, detrend_method)
        if total_count > MAX_BASELINE_POINTS:
            st.info(f"📊 Baseline fit on ~{MAX_BASELINE_POINTS:,} systematically sampled "
                    f"points (of {total_count:,} total) for performance.")

        if len(baseline_df) < 3 or method_name is None:
            st.warning("Not enough data for detrending analysis (need at least 3 points).")
        else:
            # Flag residual-domain outliers (per-reach), matching the ingestion
            # Modified Z-Score method but applied to residuals rather than raw WSE.
            # These are localized contamination (e.g. spring-ice blobs) that the
            # raw-WSE ingestion MAD cannot catch; flagging (not deleting) them keeps
            # the stats table and plot readable without discarding data silently.
            baseline_df = baseline_df.copy()
            baseline_df['residual_outlier'] = False
            for _reach in baseline_df['Reach_Name'].unique():
                _mask = baseline_df['Reach_Name'] == _reach
                _flags = flag_residual_outliers(baseline_df.loc[_mask, 'residual'].values)
                baseline_df.loc[_mask, 'residual_outlier'] = _flags
            n_flagged = int(baseline_df['residual_outlier'].sum())
            pct_flagged = 100 * n_flagged / len(baseline_df)

            # Fit-quality metrics use the CLEAN (non-flagged) residuals so a handful
            # of contaminated points can't dominate the mean/spread shown to the user.
            clean_df = baseline_df[~baseline_df['residual_outlier']]

            # Check detrending quality (robust to flagged outliers)
            overall_mean_residual = clean_df['residual'].mean()
            overall_std_residual = clean_df['residual'].std()

            # Warning if only one river selected (detrending works best with both)
            num_rivers = baseline_df['Reach_Name'].nunique()
            if num_rivers == 1:
                st.warning("⚠️ **Only one river in this selection's data**: the chosen passes imaged a single river, so the baseline is fit to it alone. Cross-river comparison is unavailable and residuals may retain systematic structure.")

            # Sample for visualization if needed
            if len(baseline_df) > MAX_PLOT_POINTS:
                step_size = int(len(baseline_df) / MAX_PLOT_POINTS)
                plot_df = baseline_df.iloc[::step_size].copy()
                st.info(f"📉 Showing 1 out of every {step_size} points for visualization.")
            else:
                plot_df = baseline_df

            # Create detrended plot
            fig_detrend = go.Figure()

            # Plot residuals for each river (Uyak on top). Flagged residual
            # outliers are omitted from the traces so the y-axis auto-scales to the
            # real signal instead of being stretched by a few contaminated points;
            # they remain in baseline_df and the Raw Data tab (nothing is deleted).
            for reach in sorted(selected_reaches, key=lambda r: r == "Uyak_Creek"):
                reach_data = plot_df[(plot_df['Reach_Name'] == reach)
                                     & (~plot_df['residual_outlier'])]
                if len(reach_data) == 0:
                    continue

                line_color = COLOR_MAP.get(reach, "black")

                # Solid legend marker
                fig_detrend.add_trace(go.Scatter(
                    x=[None], y=[None],
                    mode='markers',
                    name=reach,
                    marker=dict(color=line_color, size=8, opacity=1.0),
                    legendgroup=reach,
                ))
                # Translucent data points (hidden from legend).
                # customdata = [lat, lon, date, reach] so a box-selection here can be
                # highlighted on the Map View tab (same mechanism as the Gradient Profile).
                cd = np.column_stack([
                    reach_data['latitude'].to_numpy(),
                    reach_data['longitude'].to_numpy(),
                    reach_data['Pass_Date'].astype(str).to_numpy(),
                    np.full(len(reach_data), reach),
                ])
                fig_detrend.add_trace(go.Scatter(
                    x=reach_data['dist_km'],
                    y=reach_data['residual'],
                    mode='markers',
                    marker=dict(color=line_color, size=3, opacity=0.4),
                    legendgroup=reach,
                    showlegend=False,
                    customdata=cd,
                    hovertemplate='<b>' + reach + '</b><br>' +
                                  'Distance: %{x:.2f} km<br>' +
                                  'Residual: %{y:.3f} m<br>' +
                                  'Pass: %{customdata[2]}<br>' +
                                  '<extra></extra>'
                ))

            # Add zero reference line
            fig_detrend.add_hline(
                y=0,
                line_dash="dash",
                line_color="gray",
                line_width=2,
                annotation_text="Baseline Trend",
                annotation_position="right"
            )

            # Update layout
            fig_detrend.update_layout(
                xaxis_title="Distance from Anchor Point (km)",
                yaxis_title=f"Residual Elevation (m) - Detrended using {method_name}",
                height=600,
                template=plotly_template,
                hovermode='closest',
                showlegend=True
            )

            # Reverse x-axis to match other plots
            fig_detrend.update_xaxes(autorange="reversed")
            fig_detrend.update_layout(dragmode="select")
            add_bifurcation_line(fig_detrend)

            st.caption("🔦 **Link to map:** drag a box around points here — they'll be "
                       "highlighted (yellow outline) on the **🗺️ Map View** tab. Switch back "
                       "to zoom/pan with the toolbar at the top-right of the chart.")
            if n_flagged > 0:
                st.caption(f"⚠️ **{n_flagged:,} point(s) ({pct_flagged:.3f}%)** flagged as "
                           f"residual outliers (Modified Z-Score > {RESIDUAL_MAD_THRESHOLD}, "
                           "per river) and omitted from this view so the axis reflects the "
                           "real signal. These are localized contamination (e.g. spring ice) "
                           "that the raw-WSE ingestion filter cannot catch. They are **not "
                           "deleted** — they remain in the data and the Raw Data tab.")
            detr_event = st.plotly_chart(
                fig_detrend, width="stretch", theme=None,
                on_select="rerun", selection_mode=("points", "box"),
                key=f"detrend_select_{st.session_state.get('sel_ver', 0)}",
            )
            st.session_state["sel_detr"] = extract_selection(detr_event)

            # Show fit quality metrics
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Overall Mean Residual", f"{overall_mean_residual:.4f} m",
                         help="Mean of non-flagged residuals; should be close to 0.000 for a good fit")
            with col2:
                st.metric("Residual Std Dev", f"{overall_std_residual:.3f} m",
                         help="Spread of non-flagged residuals around baseline (flagged outliers excluded)")
            with col3:
                st.metric("Rivers in Baseline Fit", num_rivers,
                         help="Detrending works best when both rivers are included")

            # Diagnostic warning if residuals show systematic bias
            if abs(overall_mean_residual) > 0.5:
                st.error(f"""
                🔴 **Poor Fit Detected**: Overall mean residual is {overall_mean_residual:.2f}m (should be ~0).

                **Possible causes:**
                - Selected passes imaged only one river (the shared baseline needs both)
                - Data has extreme outliers (check the flagged-points count above)
                - The quadratic baseline doesn't suit this selection's profile shape
                """)

            # Add interpretation guide
            with st.expander("How to read this graph"):
                st.markdown(f"""
                **What this shows:** the water profile with its overall downhill slope
                removed — like flattening the picture so small ups and downs stand out.

                - The flat zero line is the river's expected smooth trend.
                - **Above the line**: the water is higher than expected here.
                - **Below the line**: it's lower than expected.
                - This makes subtle differences between the two rivers easy to see.

                **What to look for:**
                - A steady gap between the two rivers means one consistently sits higher than the other.
                - A river that stays above the line is steeper than average; below the line, gentler.

                **Is it working?** The dots should scatter evenly around zero with no
                leftover tilt. A remaining up- or down-slope means the smooth baseline
                doesn't fully describe this selection — read local features with care.

                ― Technical details ―
                Baseline = {method_name} fit through all points of the selected river(s);
                the plot shows the residuals (data minus baseline). Mean residual ≈ 0 when the fit is appropriate.
                """)

            # Guidance for the (single, hardcoded) baseline method
            st.success("""
                **Using 2nd Order Polynomial Baseline:**
                - Captures the gentle downstream curvature both rivers share
                - Residuals show deviations from this smooth curve
                - Best for highlighting systematic differences between rivers
                """)

            # Show statistics per river
            st.subheader("Detrended Elevation Statistics")

            # Robust statistics. Min/Max/Range are non-robust by construction (a
            # single contaminated pixel sets them), so they are replaced by robust
            # dispersion measures computed over ALL residuals: the median, a
            # MAD-based robust standard deviation (1.4826 * MAD, the normal-
            # consistent estimator), and the 1st/99th percentiles. Mean and Std Dev
            # are retained for continuity but computed on the non-flagged residuals
            # so they are not distorted by flagged outliers. "N Flagged" reports how
            # many points exceeded the residual Modified Z-Score threshold.
            stats_data = []
            for reach in selected_reaches:
                reach_all = baseline_df[baseline_df['Reach_Name'] == reach]
                if len(reach_all) == 0:
                    continue
                residuals_clean = reach_all.loc[~reach_all['residual_outlier'], 'residual']
                med = residuals_clean.median()
                robust_sd = 1.4826 * (residuals_clean - med).abs().median()
                stats_data.append({
                    "River": reach,
                    "Median (m)": med,
                    "Robust SD (m)": robust_sd,
                    "P1 (m)": residuals_clean.quantile(0.01),
                    "P99 (m)": residuals_clean.quantile(0.99),
                    "Mean (m)": residuals_clean.mean(),
                    "Std Dev (m)": residuals_clean.std(),
                    "N Flagged": int(reach_all['residual_outlier'].sum()),
                })

            if stats_data:
                stats_summary = pd.DataFrame(stats_data)
                st.dataframe(
                    stats_summary.style.format({
                        "Median (m)": "{:.3f}",
                        "Robust SD (m)": "{:.3f}",
                        "P1 (m)": "{:.3f}",
                        "P99 (m)": "{:.3f}",
                        "Mean (m)": "{:.3f}",
                        "Std Dev (m)": "{:.3f}",
                        "N Flagged": "{:,d}",
                    }),
                    width="stretch",
                    hide_index=True
                )
                st.caption(
                    "All statistics are computed over the same residual set, with points "
                    f"flagged by the residual Modified Z-Score (> {RESIDUAL_MAD_THRESHOLD}) "
                    "excluded, so the extreme percentiles reflect structural deviation rather "
                    "than contamination. **Median / Robust SD (1.4826·MAD) / P1 / P99** are "
                    "outlier-resistant measures of centre and spread. **N Flagged** counts the "
                    "excluded points, which are retained in the data but omitted here and from "
                    "the plot. Min/Max/Range were removed: a single contaminated pixel sets "
                    "them, so they misrepresented the detrended spread."
                )

            # Optional: Show baseline trend curve
            with st.expander("📊 Show Baseline Trend Curve"):
                # Sample the baseline for plotting
                baseline_plot_df = baseline_df.sort_values('dist_km')
                if len(baseline_plot_df) > 1000:
                    baseline_plot_df = baseline_plot_df.iloc[::len(baseline_plot_df)//1000]

                fig_baseline = go.Figure()

                # Add all original data points
                for reach in selected_reaches:
                    reach_data = plot_df[plot_df['Reach_Name'] == reach]
                    line_color = COLOR_MAP.get(reach, "black")
                    fig_baseline.add_trace(go.Scatter(
                        x=reach_data['dist_km'],
                        y=reach_data['wse'],
                        mode='markers',
                        name=reach,
                        marker=dict(color=line_color, size=3, opacity=0.3)
                    ))

                # Add baseline curve
                fig_baseline.add_trace(go.Scatter(
                    x=baseline_plot_df['dist_km'],
                    y=baseline_plot_df['baseline'],
                    mode='lines',
                    name='Baseline Trend',
                    line=dict(color='black', width=3, dash='dash')
                ))

                fig_baseline.update_layout(
                    xaxis_title="Distance from Anchor Point (km)",
                    yaxis_title="Water Surface Elevation (m)",
                    height=500,
                    template=plotly_template,
                    title=f"Original Data with {method_name} Baseline"
                )

                fig_baseline.update_xaxes(autorange="reversed")
                add_bifurcation_line(fig_baseline)
                st.plotly_chart(fig_baseline, width="stretch", theme=None)

    except Exception as e:
        st.error(f"Error calculating detrended profile: {e}")
        import traceback
        st.code(traceback.format_exc())
