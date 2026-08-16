"""Gradient Profile tab: binned-median river profile with reference gradients."""
import numpy as np
import plotly.graph_objects as go
import streamlit as st

from .common import (COLOR_MAP, PROFILE_BAND, PROFILE_NODE_KM,
                     add_bifurcation_line, extract_selection, load_reference_gradient)


def render(ctx):
    con = ctx.con
    plotly_template = ctx.plotly_template
    selected_reaches = ctx.selected_reaches
    viz_df = ctx.viz_df

    st.subheader("River Profile")

    # B2: surface each river's robust reference gradient on the landing tab.
    # This is the SAME value as the Hydraulic Gradient tab -- the median of
    # per-pass Theil-Sen slopes over the full open-water record -- NOT the slope
    # of the profile line below (which follows the current pass selection).
    _refg = load_reference_gradient(con)
    if _refg is not None and len(_refg) > 0:
        _ow = _refg[(_refg["open_water"]) & (_refg["gated"])]
        _parts = []
        for _r in sorted(selected_reaches, key=lambda r: r == "Uyak_Creek"):
            _d = _ow[_ow["Reach_Name"] == _r]
            if len(_d) > 0:
                _parts.append(f"**{_r.replace('_', ' ')}** {_d['theilsen_cm_km'].abs().median():.1f} cm/km")
        if _parts:
            st.markdown(
                "**Reference gradient (robust Theil–Sen, full open-water record):** "
                + " · ".join(_parts)
                + " — each river's characteristic slope (details on the **Hydraulic "
                "Gradient** tab). This is *not* the slope of the profile line below, "
                "which follows your current pass selection."
            )

    fig = go.Figure()

    # Draw Kanektok first so Uyak layers on top
    plot_order = sorted(selected_reaches, key=lambda r: r == "Uyak_Creek")
    for reach in plot_order:
        reach_data = viz_df[viz_df['Reach_Name'] == reach]
        if len(reach_data) == 0:
            continue
        line_color = COLOR_MAP.get(reach, "black")

        # Solid legend marker (invisible data, shown in legend)
        fig.add_trace(go.Scatter(
            x=[None], y=[None],
            mode='markers',
            name=reach,
            marker=dict(color=line_color, size=8, opacity=1.0),
            legendgroup=reach,
        ))
        # Scatter points (translucent data, hidden from legend).
        # customdata carries [lat, lon, date, reach] so a lasso/box selection here
        # can be highlighted on the Map View tab (see extract_selection / tab5).
        cd = np.column_stack([
            reach_data['latitude'].to_numpy(),
            reach_data['longitude'].to_numpy(),
            reach_data['Pass_Date'].astype(str).to_numpy(),
            np.full(len(reach_data), reach),
        ])
        fig.add_trace(go.Scatter(
            x=reach_data['dist_km'],
            y=reach_data['wse'],
            mode='markers',
            marker=dict(color=line_color, size=5, opacity=0.3),
            legendgroup=reach,
            showlegend=False,
            customdata=cd,
            hovertemplate='<b>' + reach + '</b><br>'
                          'Distance: %{x:.2f} km<br>'
                          'WSE: %{y:.2f} m<br>'
                          'Pass: %{customdata[2]}<br>'
                          '<extra></extra>'
        ))

        # Density-de-biased profile line: bin distance to PROFILE_NODE_KM nodes
        # and take the MEDIAN WSE per node, so every along-stream location
        # contributes equally regardless of point density. This replaces the old
        # OLS linear trend, whose cm/km slope was density-biased (see the
        # Hydraulic Gradient tab). Same median-per-bin idiom as the Slope Profile
        # and Elevation Difference tabs. A shaded percentile band shows the spread
        # of passes around the median. The single characteristic slope is NOT
        # drawn here -- it is the robust Theil-Sen value shown above the chart.
        if len(reach_data) >= 5:
            node = (reach_data['dist_km'] / PROFILE_NODE_KM).round() * PROFILE_NODE_KM
            g = reach_data.assign(_node=node).groupby('_node')['wse']
            med = g.median().sort_index()
            lo = g.quantile(PROFILE_BAND[0] / 100).sort_index()
            hi = g.quantile(PROFILE_BAND[1] / 100).sort_index()
            xb = np.asarray(med.index, dtype=float)

            # percentile band (drawn under the line)
            fig.add_trace(go.Scatter(
                x=np.concatenate([xb, xb[::-1]]),
                y=np.concatenate([hi.to_numpy(), lo.to_numpy()[::-1]]),
                fill='toself', fillcolor=line_color, opacity=0.15,
                mode='lines', line=dict(width=0),
                name=f"{reach} {PROFILE_BAND[0]}–{PROFILE_BAND[1]}% of passes",
                legendgroup=reach, showlegend=False, hoverinfo='skip',
            ))
            # binned-median profile line
            fig.add_trace(go.Scatter(
                x=xb, y=med.to_numpy(), mode='lines',
                name=f"{reach} median profile ({PROFILE_NODE_KM:g} km bins)",
                line=dict(color=line_color, width=3),
                legendgroup=reach,
                hovertemplate='<b>' + reach + '</b><br>'
                              'Distance: %{x:.2f} km<br>'
                              'Median WSE: %{y:.2f} m<extra></extra>',
            ))

    fig.update_layout(
        xaxis_title="Distance from Anchor Point (km)",
        yaxis_title="Water Surface Elevation (m)",
    )

    # 🔄 REVERSE THE X-AXIS HERE
    fig.update_xaxes(autorange="reversed")

    fig.update_layout(height=600, template=plotly_template, dragmode="select")
    add_bifurcation_line(fig)
    st.caption("🔦 **Link to map:** drag a box around points here — they'll be highlighted "
               "(yellow outline) on the **🗺️ Map View** tab so you can see where they are on "
               "the river. Switch back to zoom/pan with the toolbar at the top-right of the chart.")
    grad_event = st.plotly_chart(
        fig, width="stretch", theme=None,
        on_select="rerun", selection_mode=("points", "box"),
        key=f"grad_profile_select_{st.session_state.get('sel_ver', 0)}",
    )
    st.session_state["sel_grad"] = extract_selection(grad_event)

    # Add interpretation guide
    with st.expander("How to read this graph"):
        st.markdown("""
        **What this shows:** the height of the water surface along each river — from
        the coast on the left, back toward the anchor point on the right.

        - **Left–right**: how far up the river you are, in kilometers. The coast/river
          mouth is on the left (~36 km); the anchor point is on the right (0 km).
        - **Up–down**: how high the water sits above sea level, in meters.
        - **Dots**: individual measurements from the satellite.
        - **Solid line**: the river's typical water-surface profile — the median height
          at each point along the river.
        - **Shaded band**: the middle range (5th–95th percentile) of measurements around
          that median — how much the passes vary at each point.

        **What to look for:**
        - A **steeper drop** along the line means the water loses height faster there.
        - If one river sits **higher** than the other along the same stretch, it has more
          potential to spill over and shift its path toward the lower one.
        - A **wider band** means more variation between satellite passes and water levels.

        **Tip:** the other tabs go deeper —
        - *Hydraulic Gradient* gives each river's single best average slope.
        - *Elevation Difference* shows which river is higher at each point.
        - *Detrended Profile* removes the overall downhill slope to reveal subtle differences.
        - *Slope Profile* shows how the steepness changes along the river.

        ― Technical details ―
        Heights are orthometric, relative to the EGM2008 geoid. The solid line is the
        **median water-surface elevation in 0.5 km distance bins** (median-per-bin removes
        along-stream point-density bias); the band spans the 5th–95th percentiles within
        each bin. For each river's single characteristic slope (robust Theil–Sen), see the
        Hydraulic Gradient tab.
        """)
