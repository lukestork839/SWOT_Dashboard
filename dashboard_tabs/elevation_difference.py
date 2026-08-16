"""Elevation Difference tab: per-pass paired Kanektok-minus-Uyak WSE difference."""
import plotly.graph_objects as go
import streamlit as st

from .common import add_bifurcation_line


def render(ctx):
    con = ctx.con
    plotly_template = ctx.plotly_template
    selected_reaches = ctx.selected_reaches
    where_clause = ctx.where_clause

    st.subheader("Elevation Difference: Kanektok - Uyak")

    # Data-integrity guard, not a UI check: selected_reaches always mirrors
    # available_reaches (the dashboard no longer offers river selection), so
    # this fires only if the dataset itself is missing a river.
    if len(selected_reaches) != 2:
        st.warning("⚠️ This analysis requires both rivers in the dataset; only one was found.")
    else:
        # Per-pass within-pass difference, then median across passes.
        # Each SWOT pass images both channels near-simultaneously, so
        # differencing WITHIN a pass cancels the shared water stage (a paired
        # comparison); the per-(pass, bin) MEDIAN is robust to contaminated
        # pixels. We keep only bins where BOTH rivers were imaged in that pass,
        # difference Kanektok - Uyak, then report the median difference across
        # passes per bin. (Replaces the older pooled-AVG difference, which mixed
        # passes unpaired and used an outlier-sensitive mean.)
        diff_query = f"""
            WITH per_pass_bin AS (
                SELECT
                    CAST(Pass_Date AS DATE) AS pass,
                    ROUND(dist_km / 0.1) * 0.1 AS dist_bin,
                    Reach_Name,
                    median(wse) AS med_wse
                FROM river_data
                {where_clause}
                GROUP BY pass, dist_bin, Reach_Name
            ),
            paired AS (
                SELECT
                    k.dist_bin,
                    k.med_wse - u.med_wse AS diff
                FROM (SELECT * FROM per_pass_bin
                      WHERE Reach_Name = 'Kanektok_River') k
                INNER JOIN (SELECT * FROM per_pass_bin
                            WHERE Reach_Name = 'Uyak_Creek') u
                  ON k.pass = u.pass AND k.dist_bin = u.dist_bin
            )
            SELECT
                dist_bin,
                median(diff) AS elevation_diff,
                COUNT(*) AS n_passes
            FROM paired
            GROUP BY dist_bin
            ORDER BY dist_bin
        """

        try:
            diff_df = con.execute(diff_query).fetchdf()

            if len(diff_df) == 0:
                st.warning("No overlapping distance bins found between the two rivers.")
            else:
                # Create the elevation difference plot
                fig_diff = go.Figure()

                # Add the elevation difference line
                fig_diff.add_trace(go.Scatter(
                    x=diff_df['dist_bin'],
                    y=diff_df['elevation_diff'],
                    mode='lines+markers',
                    name='Kanektok - Uyak',
                    line=dict(color='darkgreen', width=3),
                    marker=dict(size=5),
                    hovertemplate='<b>Distance</b>: %{x:.2f} km<br>' +
                                  '<b>Elevation Diff</b>: %{y:.3f} m<br>' +
                                  '<extra></extra>'
                ))

                # Add zero reference line
                fig_diff.add_hline(
                    y=0,
                    line_dash="dash",
                    line_color="gray",
                    annotation_text="Equal Elevation",
                    annotation_position="right"
                )

                # Update layout
                fig_diff.update_layout(
                    xaxis_title="Distance from Anchor Point (km)",
                    yaxis_title="Elevation Difference (m)",
                    height=600,
                    template=plotly_template,
                    hovermode='x unified'
                )

                # Reverse x-axis to match other plots (Coast on left, Anchor on right)
                fig_diff.update_xaxes(autorange="reversed")
                add_bifurcation_line(fig_diff)

                st.plotly_chart(fig_diff, width="stretch", theme=None)

                # Add interpretation guide
                with st.expander("How to read this graph"):
                    st.markdown("""
                    **What this shows:** which river's *water* sits higher at each point
                    along the way.

                    - **Above zero**: Kanektok's water is higher here.
                    - **Below zero**: Uyak's water is higher here.
                    - **On the zero line**: the two are at the same height.

                    ― Technical details ―
                    Within each satellite pass, water heights are taken as the
                    median per 100 m bin and differenced (Kanektok − Uyak) where
                    both rivers were imaged; the line is the median of those
                    per-pass differences across all passes.
                    """)

                # Show summary statistics
                max_abs_idx = diff_df['elevation_diff'].abs().idxmax()
                max_abs_diff = diff_df.loc[max_abs_idx, 'elevation_diff']
                max_kanektok = diff_df['elevation_diff'].max()  # Most positive = Kanektok highest above Uyak
                max_uyak = diff_df['elevation_diff'].min()      # Most negative = Uyak highest above Kanektok

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Average Difference", f"{diff_df['elevation_diff'].mean():.3f} m")
                col2.metric("Max |Difference|", f"{max_abs_diff:.3f} m",
                            help="Largest absolute elevation difference (positive = Kanektok higher, negative = Uyak higher)")
                col3.metric("Kanektok Max Above", f"+{max_kanektok:.3f} m",
                            help="Greatest elevation where Kanektok is above Uyak")
                col4.metric("Uyak Max Above", f"{max_uyak:.3f} m",
                            help="Greatest elevation where Uyak is above Kanektok")

        except Exception as e:
            st.error(f"Error calculating elevation difference: {e}")
