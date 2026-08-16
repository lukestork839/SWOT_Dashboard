"""DEM tab group: terrain profile, elevation difference, slope, detrend, map, cross-sections."""
import folium
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from folium import plugins
from scipy import stats
from scipy.ndimage import gaussian_filter1d
from streamlit_folium import st_folium

from .common import (COLOR_MAP, VerticalColorbar, add_bifurcation_line,
                     add_bifurcation_marker, add_transect_overlay,
                     load_transect_overlay, load_xsec_B)
from .dem_cross_sections import render_cross_sections


def render(ctx):
    dem_points = ctx.dem_points
    dem_profile = ctx.dem_profile
    plotly_template = ctx.plotly_template
    selected_reaches = ctx.selected_reaches

    if dem_profile is None:
        st.warning("No DEM data available. If running locally, run `DEM_Pull.py` first.")
    else:
        # Cross-section artifacts are committed under DEM_Transects/data/ (so the tab shows on the
        # hosted app); still gate on presence so it degrades gracefully if they're ever missing.
        xsecB_ch, xsecB_prof = load_xsec_B()
        has_xsec = xsecB_ch is not None

        dem_tab_names = [
            "📈 Terrain Profile", "🔀 Elevation Difference",
            "📐 Terrain Slope", "🎯 Detrended Profile", "🗺️ Map View",
        ]
        if has_xsec:
            dem_tab_names.append("✂️ Cross-Sections")
        dem_tabs = st.tabs(dem_tab_names)
        dem_tab1, dem_tab2, dem_tab3, dem_tab4, dem_tab5 = dem_tabs[:5]
        dem_tab_xsec = dem_tabs[5] if has_xsec else None

        plot_order = sorted(selected_reaches, key=lambda r: r == "Uyak_Creek")

        with dem_tab1:
            st.subheader("ArcticDEM Terrain Profile")
            fig_dem = go.Figure()

            for reach in plot_order:
                line_color = COLOR_MAP.get(reach, "black")
                dem_reach = dem_profile[dem_profile["Reach_Name"] == reach].sort_values("dist_bin")
                if len(dem_reach) == 0:
                    continue

                fig_dem.add_trace(go.Scatter(
                    x=dem_reach["dist_bin"],
                    y=dem_reach["wse_median"],
                    mode="lines",
                    name=reach,
                    line=dict(color=line_color, width=3),
                    legendgroup=reach,
                    hovertemplate=(
                        f"<b>{reach}</b><br>"
                        "Distance: %{x:.1f} km<br>"
                        "Median Elevation: %{y:.1f} m<br>"
                        "<extra></extra>"
                    ),
                ))

                if len(dem_reach) >= 5:
                    slope_val, intercept_val, r_val, _, _ = stats.linregress(
                        dem_reach["dist_bin"], dem_reach["wse_median"]
                    )
                    slope_cm = abs(slope_val * 100)
                    r_sq = r_val ** 2
                    x_range = np.linspace(dem_reach["dist_bin"].min(), dem_reach["dist_bin"].max(), 100)
                    fig_dem.add_trace(go.Scatter(
                        x=x_range,
                        y=intercept_val + slope_val * x_range,
                        mode="lines",
                        name=f"{reach} Linear Trend: {slope_cm:.1f} cm/km (R\u00b2={r_sq:.3f})",
                        line=dict(color=line_color, width=3, dash="dash"),
                        legendgroup=reach,
                    ))

                    # 2nd-order polynomial fit (same curve shape as the Detrended tab baseline)
                    poly = np.polynomial.Polynomial.fit(
                        dem_reach["dist_bin"], dem_reach["wse_median"], 2
                    )
                    poly_pred = poly(dem_reach["dist_bin"].values)
                    ss_res = np.sum((dem_reach["wse_median"].values - poly_pred) ** 2)
                    ss_tot = np.sum((dem_reach["wse_median"].values - dem_reach["wse_median"].mean()) ** 2)
                    poly_r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
                    fig_dem.add_trace(go.Scatter(
                        x=x_range,
                        y=poly(x_range),
                        mode="lines",
                        name=f"{reach} Poly Trend (2nd order, R\u00b2={poly_r2:.3f})",
                        line=dict(color=line_color, width=3, dash="dot"),
                        legendgroup=reach,
                    ))

            fig_dem.update_layout(
                xaxis_title="Distance from Anchor Point (km)",
                yaxis_title="Terrain Elevation (m, EGM2008)",
                height=600, template=plotly_template,
            )
            fig_dem.update_xaxes(autorange="reversed")
            add_bifurcation_line(fig_dem)
            st.plotly_chart(fig_dem, use_container_width=True, theme=None)

            with st.expander("How to read this graph"):
                st.markdown("""
                **What this shows:** the shape of the *land* along each river \u2014 the
                elevation of the river valley floor, measured from satellite imagery
                rather than from the water.

                - **Solid lines**: the ground elevation along each river (averaged in 0.5 km steps).
                - **Dashed lines**: each river's average land slope, in cm of drop per km.
                - The **R\u00b2** number (0 to 1) says how straight the slope is. Close to 1
                  means the river drops at a steady rate; lower means it curves \u2014 usually
                  steeper near the top and gentler near the coast.

                \u2015 Technical details \u2015
                Terrain is the median ArcticDEM V4 (2 m mosaic, 10 m export) elevation within
                the river polygons, in EGM2008 orthometric heights, LiDAR-validated (RMSE 0.50 m).
                Dashed line is an OLS linear fit; lower R\u00b2 reflects profile concavity
                (Hack, 1957; Flint, 1974).
                """)

        with dem_tab2:
            st.subheader("Terrain Elevation Difference: Kanektok \u2212 Uyak")

            if "Kanektok_River" not in dem_profile["Reach_Name"].values or "Uyak_Creek" not in dem_profile["Reach_Name"].values:
                st.warning("Both rivers are required for this analysis.")
            else:
                kan_dem = dem_profile[dem_profile["Reach_Name"] == "Kanektok_River"][["dist_bin", "wse_median"]].rename(
                    columns={"wse_median": "kan_median"})
                uyak_dem = dem_profile[dem_profile["Reach_Name"] == "Uyak_Creek"][["dist_bin", "wse_median"]].rename(
                    columns={"wse_median": "uyak_median"})
                diff_dem = kan_dem.merge(uyak_dem, on="dist_bin", how="inner")
                diff_dem["diff"] = diff_dem["kan_median"] - diff_dem["uyak_median"]

                fig_diff = go.Figure()
                fig_diff.add_trace(go.Scatter(
                    x=diff_dem["dist_bin"], y=diff_dem["diff"],
                    mode="lines+markers", name="Kanektok \u2212 Uyak",
                    line=dict(color="mediumpurple", width=2), marker=dict(size=4),
                    fill="tozeroy", fillcolor="rgba(147,112,219,0.15)",
                    hovertemplate="Distance: %{x:.1f} km<br>Difference: %{y:.1f} m<br><extra></extra>",
                ))
                fig_diff.add_hline(y=0, line_dash="dot", line_color="gray")
                fig_diff.update_layout(
                    xaxis_title="Distance from Anchor Point (km)",
                    yaxis_title="Elevation Difference (m)",
                    height=500, template=plotly_template,
                )
                fig_diff.update_xaxes(autorange="reversed")
                add_bifurcation_line(fig_diff)
                st.plotly_chart(fig_diff, use_container_width=True, theme=None)

                with st.expander("How to read this graph"):
                    st.markdown("""
                    **What this shows:** how much higher one river valley sits than the
                    other at each point along their length.

                    - **Above zero**: the Kanektok valley floor is higher here.
                    - **Below zero**: the Uyak valley floor is higher here.
                    - When one river sits higher than its neighbor, gravity gives its water
                      a reason to spill over and shift toward the lower one \u2014 a key warning
                      sign for a river changing its path.

                    \u2015 Technical details \u2015
                    Difference of median terrain elevation between the two river corridors per
                    0.5 km bin. Analogous to *alluvial ridge height* (Slingerland & Smith, 1998),
                    the H_AR term in the superelevation ratio of Gearon et al. (2024, *Nature*).
                    This is a corridor-wide comparison; for the channel-by-channel version, with
                    the floodplain between them as the reference, see the ✂️ Cross-Sections tab.
                    """)

        with dem_tab3:
            st.subheader("Terrain Slope Profile")
            fig_slope = go.Figure()

            for reach in plot_order:
                dem_reach = dem_profile[dem_profile["Reach_Name"] == reach].sort_values("dist_bin")
                if len(dem_reach) < 3:
                    continue
                line_color = COLOR_MAP.get(reach, "black")
                dist_vals = dem_reach["dist_bin"].values
                elev_vals = dem_reach["wse_median"].values
                raw_slope = np.gradient(elev_vals, dist_vals) * 100
                smoothed_slope = gaussian_filter1d(raw_slope, sigma=3)

                fig_slope.add_trace(go.Scatter(
                    x=dist_vals, y=np.abs(smoothed_slope),
                    mode="lines", name=reach,
                    line=dict(color=line_color, width=2.5),
                    hovertemplate=f"<b>{reach}</b><br>Distance: %{{x:.1f}} km<br>Slope: %{{y:.1f}} cm/km<br><extra></extra>",
                ))

            fig_slope.update_layout(
                xaxis_title="Distance from Anchor Point (km)",
                yaxis_title="Terrain Slope (cm/km)",
                height=500, template=plotly_template,
            )
            fig_slope.update_xaxes(autorange="reversed")
            add_bifurcation_line(fig_slope)
            st.plotly_chart(fig_slope, use_container_width=True, theme=None)

            with st.expander("How to read this graph"):
                st.markdown("""
                **What this shows:** how steep the land is at each point along the river,
                instead of one average slope for the whole river.

                - **Higher line** = steeper ground there = faster, more forceful flow.
                - Where the two rivers differ in steepness tells you which one is more
                  likely to erode and shift its path.

                ― Technical details ―
                Local terrain gradient = numerical derivative (central differences) of the
                binned median elevation, smoothed with a Gaussian filter (1.5 km window).
                """)

        with dem_tab4:
            st.subheader("Detrended Terrain Profile")

            all_dist = dem_profile["dist_bin"].values
            all_elev = dem_profile["wse_median"].values
            poly_baseline = np.polynomial.Polynomial.fit(all_dist, all_elev, 2)

            fig_detrend = go.Figure()
            for reach in plot_order:
                dem_reach = dem_profile[dem_profile["Reach_Name"] == reach].sort_values("dist_bin")
                if len(dem_reach) == 0:
                    continue
                line_color = COLOR_MAP.get(reach, "black")
                residuals = dem_reach["wse_median"].values - poly_baseline(dem_reach["dist_bin"].values)

                fig_detrend.add_trace(go.Scatter(
                    x=dem_reach["dist_bin"], y=residuals,
                    mode="lines", name=reach,
                    line=dict(color=line_color, width=2.5),
                    hovertemplate=f"<b>{reach}</b><br>Distance: %{{x:.1f}} km<br>Residual: %{{y:.2f}} m<br><extra></extra>",
                ))

            fig_detrend.add_hline(y=0, line_dash="dot", line_color="gray")
            fig_detrend.update_layout(
                xaxis_title="Distance from Anchor Point (km)",
                yaxis_title="Detrended Elevation (m)",
                height=500, template=plotly_template,
            )
            fig_detrend.update_xaxes(autorange="reversed")
            add_bifurcation_line(fig_detrend)
            st.plotly_chart(fig_detrend, use_container_width=True, theme=None)

            with st.expander("How to read this graph"):
                st.markdown("""
                **What this shows:** the same terrain, but with the overall downhill slope
                removed \u2014 like tilting the whole picture flat so small bumps stand out.

                - The flat zero line is the expected smooth downhill shape both rivers share.
                - **Above the line**: this river's valley sits higher than expected here.
                - **Below the line**: it sits lower than expected.
                - A river that stays **above** the line is riding high on its own built-up
                  bed (a "perched" channel) \u2014 one of the main conditions that lets a river
                  jump to a new path.

                \u2015 Technical details \u2015
                Baseline is a 2nd-order polynomial fit to both rivers combined, capturing the
                expected concave-up profile (Flint, 1974). Residuals = terrain minus baseline.
                Perched channels are a known avulsion precondition (Slingerland & Smith, 1998).
                """)

        with dem_tab5:
            @st.fragment
            def render_dem_map():
                st.subheader("DEM Elevation Point Map")

                ctrl1, ctrl2, ctrl3 = st.columns([2, 2, 2])
                with ctrl1:
                    dem_color_by = st.selectbox(
                        "Color by:", options=["River Name", "Elevation (m)"],
                        key="dem_map_color_by"
                    )
                with ctrl2:
                    dem_basemap = st.selectbox(
                        "Basemap:", options=["OpenStreetMap", "Satellite (ESRI)"],
                        index=1, key="dem_basemap_style"
                    )
                with ctrl3:
                    dem_opacity = st.slider(
                        "Point Opacity:", min_value=0.1, max_value=1.0,
                        value=0.7, step=0.1, key="dem_point_opacity"
                    )

                if dem_points is None:
                    st.warning("DEM point data not available for map.")
                    return
                map_df = dem_points[dem_points["Reach_Name"].isin(selected_reaches)]

                center_lat = map_df["latitude"].mean()
                center_lon = map_df["longitude"].mean()

                basemap_tiles = {"OpenStreetMap": "OpenStreetMap", "Satellite (ESRI)": "Esri WorldImagery"}
                m = folium.Map(
                    location=[center_lat, center_lon],
                    zoom_start=10, tiles=basemap_tiles.get(dem_basemap, "Esri WorldImagery"),
                    control_scale=True
                )
                plugins.MeasureControl(
                    position="topleft",
                    primary_length_unit="kilometers", secondary_length_unit="meters",
                    primary_area_unit="sqkilometers", secondary_area_unit="acres"
                ).add_to(m)

                if dem_color_by == "River Name":
                    for reach_name, color in COLOR_MAP.items():
                        reach_data = map_df[map_df["Reach_Name"] == reach_name]
                        if len(reach_data) == 0:
                            continue

                        features = [
                            {
                                "type": "Feature",
                                "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                                "properties": {
                                    "River": reach_name,
                                    "Elevation": f"{wse:.2f} m",
                                    "Distance": f"{dist:.1f} km",
                                }
                            }
                            for lon, lat, wse, dist in zip(
                                reach_data["longitude"], reach_data["latitude"],
                                reach_data["wse"], reach_data["dist_km"]
                            )
                        ]

                        folium.GeoJson(
                            {"type": "FeatureCollection", "features": features},
                            name=reach_name,
                            marker=folium.CircleMarker(radius=3, weight=0, fill=True, fill_opacity=dem_opacity),
                            style_function=lambda x, c=color: {"fillColor": c, "color": c},
                            popup=folium.GeoJsonPopup(
                                fields=["River", "Elevation", "Distance"],
                                aliases=["River", "Elevation", "Distance"],
                            ),
                        ).add_to(m)

                else:  # Elevation (m)
                    vmin = float(map_df["wse"].min())
                    vmax = float(map_df["wse"].max())
                    colormap_fn = cm.get_cmap("viridis")
                    norm = mcolors.Normalize(vmin=vmin, vmax=vmax)

                    rgba_array = colormap_fn(norm(map_df["wse"].values))
                    hex_colors = [mcolors.rgb2hex(rgba[:3]) for rgba in rgba_array]

                    features = [
                        {
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                            "properties": {
                                "color": color, "River": reach,
                                "Elevation": f"{wse:.2f} m",
                                "Distance": f"{dist:.1f} km",
                            }
                        }
                        for lon, lat, color, reach, wse, dist in zip(
                            map_df["longitude"], map_df["latitude"], hex_colors,
                            map_df["Reach_Name"], map_df["wse"], map_df["dist_km"]
                        )
                    ]

                    folium.GeoJson(
                        {"type": "FeatureCollection", "features": features},
                        name="DEM Elevation",
                        marker=folium.CircleMarker(radius=3, weight=0, fill=True, fill_opacity=dem_opacity),
                        style_function=lambda x: {
                            "fillColor": x["properties"]["color"],
                            "color": x["properties"]["color"],
                        },
                        popup=folium.GeoJsonPopup(
                            fields=["River", "Elevation", "Distance"],
                            aliases=["River", "Elevation", "Distance"],
                        ),
                    ).add_to(m)

                    VerticalColorbar(
                        caption="Elevation (m)",
                        colors=["#440154", "#31688e", "#35b779", "#fde725"],
                        vmin=vmin, vmax=vmax,
                    ).add_to(m)

                add_bifurcation_marker(m)
                overlay = load_transect_overlay()
                if overlay is not None:
                    add_transect_overlay(m, overlay)
                folium.LayerControl().add_to(m)
                st_folium(m, width=1400, height=600, key="dem_river_map", returned_objects=[])

                with st.expander("How to read this map"):
                    st.markdown("""
                    **What this shows:** every patch of land along the rivers, placed on a
                    real map and colored by how high it is.

                    - **By river**: Kanektok (red) vs Uyak (blue).
                    - **By elevation**: purple is low ground, yellow is high ground.
                    - **Click any point** to see its exact height and distance.
                    - Use the ruler tool (top-left) to measure distances and areas.

                    **DEM-transect overlay** (toggle in the layer control, top-right) — the exact
                    geometry behind the ✂️ Cross-Sections tab:
                    - **Field centerlines** — the boat-ADCP Kanektok and boat-GPS Uyak lines that
                      drive the channel picks.
                    - **Distance-from-anchor bands** — concentric arcs every 1 km (labelled every
                      5 km); each ring is one Cross-Sections slider position. *Off by default.*
                    - **Transects** — each cross-section arc, trimmed to the Kanektok→Uyak reach and
                      dotted where it crosses each channel.

                    ― Technical details ―
                    Each point is a 10 m ArcticDEM V4 pixel within the river polygons,
                    in EGM2008 orthometric heights.
                    """)

            render_dem_map()

        if dem_tab_xsec is not None:
            with dem_tab_xsec:
                render_cross_sections(xsecB_ch, xsecB_prof, plotly_template)

        # --- DEM SUMMARY STATISTICS ---
        st.divider()
        st.subheader("DEM Summary Statistics")

        dem_summary = []
        for reach in selected_reaches:
            rp = dem_profile[dem_profile["Reach_Name"] == reach]
            slope_val = np.nan
            if len(rp) >= 5:
                slope_val, _, _, _, _ = stats.linregress(rp["dist_bin"], rp["wse_median"])
            dem_summary.append({
                "River Name": reach,
                "Avg Elevation (m)": rp["wse_median"].mean(),
                "Avg Gradient (cm/km)": abs(slope_val) * 100,
            })

        summary_df = pd.DataFrame(dem_summary)
        st.dataframe(
            summary_df.style.format({
                "Avg Elevation (m)": "{:.2f}",
                "Avg Gradient (cm/km)": "{:.2f}",
            }),
            width="stretch", hide_index=True
        )

        with st.expander("Where this data comes from"):
            st.markdown("""
            The land-elevation data is a high-detail terrain map of the Arctic built from
            satellite photos (ArcticDEM). We line its heights up with the same sea-level
            reference the SWOT water data uses, so the two can be compared directly. It has
            been checked against aircraft laser surveys and is accurate to about half a meter.

            \u2015 Technical details \u2015
            - **Source:** ArcticDEM V4 2 m mosaic (Polar Geospatial Center), exported at 10 m via Google Earth Engine.
            - **Vertical datum:** EGM2008 orthometric heights; geoid correction applied using
              spatially-interpolated undulation values (~13.2\u201313.8 m at the study site) to match the SWOT datum.
            - **Statistics:** profile stats computed from all ~2.5M pixels via DuckDB (exact bin
              medians/percentiles). Map shows a random sample of 15,000 points for performance.
              Summary stats use distance-weighted averaging (0.5 km bin medians).
            - **Validation:** independently validated against NOAA QL1 LiDAR (RMSE 0.50 m).
            """)
