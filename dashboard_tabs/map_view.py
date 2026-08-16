"""Map View tab: folium map of the visualization sample with metric coloring."""
import folium
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import streamlit as st
from folium import plugins
from streamlit_folium import st_folium

from .common import (COLOR_MAP, MAX_MAP_POINTS, VerticalColorbar,
                     add_bifurcation_marker)


def render(ctx):
    viz_df = ctx.viz_df

    @st.fragment
    def render_map():
        st.subheader("Satellite Data Point Locations")

        # --- Map display controls (inside fragment for isolated reruns) ---
        ctrl1, ctrl2, ctrl3 = st.columns(3)
        with ctrl1:
            map_color_by = st.selectbox(
                "Color Points By:",
                options=["River Name", "Classification", "Detrended Residual (m)", "Interval Slope (cm/km)"],
                index=0, key="map_color_by"
            )
        with ctrl2:
            basemap_style = st.selectbox(
                "Basemap Style:",
                options=["OpenStreetMap", "Satellite (ESRI)"],
                index=1, key="basemap_style"
            )
        with ctrl3:
            point_opacity = st.slider(
                "Point Opacity:", min_value=0.1, max_value=1.0,
                value=0.7, step=0.1, key="point_opacity"
            )

        # Sample data if too large. Seed the sample so the plotted points stay put
        # across the fragment's reruns (opacity/basemap/color-by changes) instead of
        # jittering to a new random subset each interaction.
        if len(viz_df) > MAX_MAP_POINTS:
            map_df = viz_df.sample(MAX_MAP_POINTS, random_state=42)
            st.info(f"📍 Showing {MAX_MAP_POINTS:,} sampled points (out of {len(viz_df):,}) for map performance.")
        else:
            map_df = viz_df

        center_lat = map_df['latitude'].mean()
        center_lon = map_df['longitude'].mean()

        basemap_tiles = {"OpenStreetMap": "OpenStreetMap", "Satellite (ESRI)": "Esri WorldImagery"}
        selected_tiles = basemap_tiles.get(basemap_style, "Esri WorldImagery")

        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=10, tiles=selected_tiles, control_scale=True
        )

        plugins.MeasureControl(
            position='topleft',
            primary_length_unit='kilometers', secondary_length_unit='meters',
            primary_area_unit='sqkilometers', secondary_area_unit='acres'
        ).add_to(m)

        # Configure coloring based on user selection
        if map_color_by == "River Name":
            for reach_name, color in COLOR_MAP.items():
                reach_data = map_df[map_df['Reach_Name'] == reach_name]
                if len(reach_data) == 0:
                    continue

                features = [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                        "properties": {
                            "River": reach_name, "WSE": f"{wse:.2f} m",
                            "Date": str(date), "Class": int(cls),
                        }
                    }
                    for lon, lat, wse, date, cls in zip(
                        reach_data['longitude'], reach_data['latitude'],
                        reach_data['wse'], reach_data['Pass_Date'],
                        reach_data['classification']
                    )
                ]

                folium.GeoJson(
                    {"type": "FeatureCollection", "features": features},
                    name=reach_name,
                    marker=folium.CircleMarker(radius=3, weight=0, fill=True, fill_opacity=point_opacity),
                    style_function=lambda x, c=color: {'fillColor': c, 'color': c},
                    popup=folium.GeoJsonPopup(
                        fields=['River', 'WSE', 'Date', 'Class'],
                        aliases=['River', 'WSE', 'Date', 'Class'],
                    ),
                ).add_to(m)

        elif map_color_by == "Classification":
            # Only classes 3-4 survive ingestion (DEFAULT_CLASSES in
            # SWOT_Pull.py), so the legend provisions exactly those two.
            class_colors = {
                3: "#FFA500", 4: "#00CED1"
            }

            for class_val, color in class_colors.items():
                class_data = map_df[map_df['classification'] == class_val]
                if len(class_data) == 0:
                    continue

                features = [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                        "properties": {
                            "River": reach, "WSE": f"{wse:.2f} m",
                            "Date": str(date), "Class": int(class_val),
                        }
                    }
                    for lon, lat, reach, wse, date in zip(
                        class_data['longitude'], class_data['latitude'],
                        class_data['Reach_Name'], class_data['wse'],
                        class_data['Pass_Date']
                    )
                ]

                folium.GeoJson(
                    {"type": "FeatureCollection", "features": features},
                    name=f"Class {class_val}",
                    marker=folium.CircleMarker(radius=3, weight=0, fill=True, fill_opacity=point_opacity),
                    style_function=lambda x, c=color: {'fillColor': c, 'color': c},
                    popup=folium.GeoJsonPopup(
                        fields=['River', 'WSE', 'Date', 'Class'],
                        aliases=['River', 'WSE', 'Date', 'Class'],
                    ),
                ).add_to(m)

        elif map_color_by == "Detrended Residual (m)":
            # Fixed scale: -3 to 3m, positive=blue (above baseline), negative=red (below)
            res_bound = 3.0
            colormap_fn = cm.get_cmap('RdBu')
            norm = mcolors.Normalize(vmin=-res_bound, vmax=res_bound, clip=True)

            # Vectorized color computation
            rgba_array = colormap_fn(norm(map_df['detrended_residual'].values))
            hex_colors = [mcolors.rgb2hex(rgba[:3]) for rgba in rgba_array]

            features = [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                    "properties": {
                        "color": color, "River": reach,
                        "Residual": f"{res:+.3f} m", "WSE": f"{wse:.2f} m",
                        "Date": str(date),
                    }
                }
                for lon, lat, color, reach, res, wse, date in zip(
                    map_df['longitude'], map_df['latitude'], hex_colors,
                    map_df['Reach_Name'], map_df['detrended_residual'],
                    map_df['wse'], map_df['Pass_Date']
                )
            ]

            folium.GeoJson(
                {"type": "FeatureCollection", "features": features},
                name="Detrended Residual",
                marker=folium.CircleMarker(radius=3, weight=0, fill=True, fill_opacity=point_opacity),
                style_function=lambda x: {
                    'fillColor': x['properties']['color'],
                    'color': x['properties']['color'],
                },
                popup=folium.GeoJsonPopup(
                    fields=['River', 'Residual', 'WSE', 'Date'],
                    aliases=['River', 'Residual', 'WSE', 'Date'],
                ),
            ).add_to(m)

            VerticalColorbar(
                caption='Residual (m, colors capped at ±3)',
                colors=['#b2182b', '#f4a582', '#f7f7f7', '#92c5de', '#2166ac'],
                vmin=-res_bound,
                vmax=res_bound,
            ).add_to(m)

        elif map_color_by == "Interval Slope (cm/km)":
            slope_min = float(map_df['interval_slope'].abs().min())
            slope_max = float(map_df['interval_slope'].abs().max())
            colormap_fn = cm.get_cmap('YlOrRd')
            norm = mcolors.Normalize(vmin=slope_min, vmax=slope_max)

            # Vectorized color computation
            abs_slopes = map_df['interval_slope'].abs().values
            rgba_array = colormap_fn(norm(abs_slopes))
            hex_colors = [mcolors.rgb2hex(rgba[:3]) for rgba in rgba_array]

            features = [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                    "properties": {
                        "color": color, "River": reach,
                        "Slope": f"{slope:.2f} cm/km", "WSE": f"{wse:.2f} m",
                        "Date": str(date),
                    }
                }
                for lon, lat, color, reach, slope, wse, date in zip(
                    map_df['longitude'], map_df['latitude'], hex_colors,
                    map_df['Reach_Name'], abs_slopes,
                    map_df['wse'], map_df['Pass_Date']
                )
            ]

            folium.GeoJson(
                {"type": "FeatureCollection", "features": features},
                name="Interval Slope",
                marker=folium.CircleMarker(radius=3, weight=0, fill=True, fill_opacity=point_opacity),
                style_function=lambda x: {
                    'fillColor': x['properties']['color'],
                    'color': x['properties']['color'],
                },
                popup=folium.GeoJsonPopup(
                    fields=['River', 'Slope', 'WSE', 'Date'],
                    aliases=['River', 'Slope', 'WSE', 'Date'],
                ),
            ).add_to(m)

            VerticalColorbar(
                caption='Slope (cm/km)',
                colors=['#ffffb2', '#fd8d3c', '#bd0026'],
                vmin=slope_min,
                vmax=slope_max,
            ).add_to(m)

        # --- Highlight points box-selected on a profile tab (Gradient/Detrended) ---
        # Union of both charts' selections so either (or both) can drive the highlight.
        highlight_pts = (st.session_state.get("sel_grad", [])
                         + st.session_state.get("sel_detr", []))
        if highlight_pts:
            hl_group = folium.FeatureGroup(name="🔦 Selected from profile", show=True)
            for pt in highlight_pts:
                label = " · ".join(x for x in (pt.get("reach", "").replace("_", " "),
                                               pt.get("date", "")) if x)
                reach_color = COLOR_MAP.get(pt.get("reach", ""), "gray")
                folium.CircleMarker(
                    location=[pt["lat"], pt["lon"]],
                    radius=7,
                    color="yellow", weight=3, opacity=0.6,   # yellow outline at 60%
                    fill=True, fill_color=reach_color, fill_opacity=1.0,  # keep original river color inside
                    popup=folium.Popup(f"Selected point<br>{label}", max_width=250),
                    tooltip="Selected from profile",
                ).add_to(hl_group)
            hl_group.add_to(m)
            # zoom to the highlighted points so the user lands on that stretch of river
            lats = [p["lat"] for p in highlight_pts]
            lons = [p["lon"] for p in highlight_pts]
            lat_min, lat_max = min(lats), max(lats)
            lon_min, lon_max = min(lons), max(lons)
            # pad a degenerate (single-point / tight-cluster) box so fit_bounds doesn't over-zoom
            if lat_max - lat_min < 1e-3:
                lat_min -= 1e-3; lat_max += 1e-3
            if lon_max - lon_min < 1e-3:
                lon_min -= 1e-3; lon_max += 1e-3
            m.fit_bounds([[lat_min, lon_min], [lat_max, lon_max]], padding=(40, 40))

        # Add layer control (toggle layers on/off)
        add_bifurcation_marker(m)
        folium.LayerControl().add_to(m)

        if highlight_pts:
            c_msg, c_btn = st.columns([3, 1])
            c_msg.success(f"🔦 **{len(highlight_pts)} point(s) highlighted** from your profile "
                          "selection (yellow outlines). The map has zoomed to them.")
            if c_btn.button("Clear highlight", use_container_width=True, key="clear_highlight"):
                st.session_state["sel_ver"] = st.session_state.get("sel_ver", 0) + 1
                st.session_state["sel_grad"] = []
                st.session_state["sel_detr"] = []
                st.rerun()

        st_folium(
            m, width=1400, height=600,
            key="river_map", returned_objects=[]
        )

        # Interpretation guides
        if map_color_by == "Detrended Residual (m)":
            st.info("""
            **Color Interpretation - Detrended Residual (2nd Order Polynomial):**
            - **Blue**: Points ABOVE the baseline trend (higher than expected elevation)
            - **Red**: Points BELOW the baseline trend (lower than expected elevation)
            - **White**: Points exactly on the baseline

            **What this shows:**
            - Spatial patterns of elevation deviations from the overall river profile
            - Blue clusters = river sits higher than expected at that distance
            - Red clusters = river sits lower than expected at that distance
            """)
        elif map_color_by == "Interval Slope (cm/km)":
            st.info("""
            **Color Interpretation - Interval Slope:**
            - **Yellow**: Gentle slopes (low gradient)
            - **Orange**: Moderate slopes
            - **Red**: Steep slopes (high gradient)

            **What this shows:**
            - Segment-by-segment steepness (100m intervals)
            - Red areas = higher energy, faster flow potential
            - Yellow areas = lower energy, slower flow
            """)

    render_map()
