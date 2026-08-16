"""Slope Profile tab: Gaussian-smoothed interval slope along each reach."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .common import COLOR_MAP, add_bifurcation_line, calculate_slope_profile


def render(ctx):
    con = ctx.con
    plotly_template = ctx.plotly_template
    selected_reaches = ctx.selected_reaches
    where_clause = ctx.where_clause

    st.subheader("Slope Profile")

    # Query raw data per river
    slope_query = f"""
        SELECT dist_km, wse, Reach_Name
        FROM river_data
        {where_clause}
        ORDER BY Reach_Name, dist_km
    """

    try:
        slope_raw_df = con.execute(slope_query).fetchdf()

        if len(slope_raw_df) == 0:
            st.warning("No data available for the selected filters.")
        else:
            fig_slopes = go.Figure()
            slope_stats = []

            for reach in selected_reaches:
                reach_data = slope_raw_df[slope_raw_df['Reach_Name'] == reach]
                if len(reach_data) < 10:
                    st.warning(f"Insufficient data for {reach} ({len(reach_data)} points). Need at least 10.")
                    continue

                x_eval, slope_cm_km, y_fitted = calculate_slope_profile(
                    reach_data['dist_km'].tolist(),
                    reach_data['wse'].tolist()
                )

                line_color = COLOR_MAP.get(reach, "black")
                abs_slope = np.abs(slope_cm_km)

                fig_slopes.add_trace(go.Scatter(
                    x=x_eval,
                    y=abs_slope,
                    mode='lines',
                    name=reach,
                    line=dict(color=line_color, width=3),
                    hovertemplate='<b>' + reach + '</b><br>' +
                                  'Distance: %{x:.2f} km<br>' +
                                  'Slope: %{y:.1f} cm/km<br>' +
                                  '<extra></extra>'
                ))

                # x_eval ascends from the ANCHOR (dist 0, inland anchor point)
                # to the COAST (~35 km, the mouths) — index 0 is the anchor
                # end, index -1 the coast end. nan-aware because the profile
                # now leaves coverage holes as honest NaN gaps.
                finite = np.isfinite(abs_slope)
                slope_stats.append({
                    "River": reach,
                    "Mean Slope (cm/km)": np.nanmean(abs_slope),
                    "Max Slope (cm/km)": np.nanmax(abs_slope),
                    "Min Slope (cm/km)": np.nanmin(abs_slope),
                    "Slope at Anchor (cm/km)": abs_slope[finite][0] if finite.any() else np.nan,
                    "Slope at Coast (cm/km)": abs_slope[finite][-1] if finite.any() else np.nan,
                    "Points Used": len(reach_data)
                })

            fig_slopes.update_layout(
                xaxis_title="Distance from Anchor Point (km)",
                yaxis_title="Slope (cm/km)",
                height=600,
                template=plotly_template,
                hovermode='x unified',
                showlegend=True
            )
            fig_slopes.update_xaxes(autorange="reversed")
            add_bifurcation_line(fig_slopes)

            st.plotly_chart(fig_slopes, width="stretch", theme=None)

            with st.expander("How to read this graph"):
                st.markdown("""
                **What this shows:** how the *water's* steepness changes along the river,
                instead of one average slope for the whole thing.

                - **Higher line** = steeper water surface there = faster, more forceful flow.
                - Compare the two rivers to spot where one is clearly steeper than the other.

                ― Technical details ―
                WSE binned to 100 m medians, smoothed with a 2 km Gaussian window; slope is
                the derivative of the smoothed elevation profile (cm/km).
                """)

            if slope_stats:
                st.subheader("Slope Profile Statistics")
                stats_summary = pd.DataFrame(slope_stats)
                st.dataframe(
                    stats_summary.style.format({
                        "Mean Slope (cm/km)": "{:.1f}",
                        "Max Slope (cm/km)": "{:.1f}",
                        "Min Slope (cm/km)": "{:.1f}",
                        "Slope at Coast (cm/km)": "{:.1f}",
                        "Slope at Anchor (cm/km)": "{:.1f}",
                    }),
                    width="stretch",
                    hide_index=True
                )

    except Exception as e:
        st.error(f"Error calculating slope profile: {e}")
