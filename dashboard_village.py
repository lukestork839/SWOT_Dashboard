"""Village dashboard entrypoint (second Streamlit Cloud app, same repo/branch).

A community-facing view of the same data behind dashboard_swot.py, written for
residents of Quinhagak (Kuinerraq): plain language (~middle-school reading
level), pictures before numbers, feet and miles, Yugtun place names. It is
organized around the three avulsion warning signs from the river-science
literature rather than around our data products, and it is built for
CONTINUOUS use — every new satellite pass adds to the charts, so the village
can keep watching these signs over the years.

All science comes from swot_core via the cached loaders in
dashboard_tabs/common.py — nothing is recomputed differently here, only
presented differently. NSF Award 2527256.
"""
import folium
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from dashboard_tabs.common import (
    FINE_MIN_COVERAGE, FINE_RES_KM, FINE_WINDOW_KM, FINE_XMAX_KM,
    _fine_aggregate, _fine_window_coverage, _fine_window_slope,
    compute_finescale_pass_matrix, get_data_version, get_database_connection,
    load_reference_gradient, load_xsec_B,
)
from swot_core.config import (
    BIFURCATION_DIST_KM, BIFURCATION_LAT, BIFURCATION_LON,
    COLOR_MAP, OPEN_WATER_MONTHS,
)

st.set_page_config(page_title="Qanirtuuq River Watch", layout="centered",
                   page_icon="🛶")

# --- UNITS: everything shown to the reader is feet / miles -------------------
M_TO_FT = 3.280839895
KM_TO_MI = 0.6213712
CMKM_TO_FTMI = 0.0528       # 1 cm/km of slope = 0.0528 ft of drop per mile

# --- NAMES -------------------------------------------------------------------
KAN, UYAK = "Kanektok_River", "Uyak_Creek"
NAME = {KAN: "Qanirtuuq (Kanektok River)", UYAK: "Uyak Creek"}
SHORT = {KAN: "Qanirtuuq", UYAK: "Uyak Creek"}

# Kuinerraq (Quinhagak) village site, at the mouth of the Qanirtuuq
# (OpenStreetMap place node; visually verified against Esri imagery).
VILLAGE_LAT, VILLAGE_LON = 59.7506, -161.8972

# The village app always uses the FULL open-water record — no pass picking.
# (Winter passes are excluded: river ice fools the satellite into measuring
# the top of the ice instead of the water.)
VILLAGE_WHERE = (
    f"WHERE Reach_Name IN ('{KAN}','{UYAK}') "
    f"AND EXTRACT(MONTH FROM CAST(Pass_Date AS DATE)) IN "
    f"({','.join(str(m) for m in OPEN_WATER_MONTHS)})"
)

PLOTLY_CONFIG = {"displayModeBar": False}


def mi_from_fork(dist_km):
    """Distances shown to the reader count from the fork, in miles, headed
    downriver toward Kuinerraq and the sea. (Internally dist_km counts from
    the survey anchor ~1.5 mi upriver of the fork.)"""
    return (np.asarray(dist_km, dtype=float) - BIFURCATION_DIST_KM) * KM_TO_MI


def base_layout(fig, ytitle, height=460):
    fig.update_layout(
        template="plotly_white", height=height, font=dict(size=15),
        hovermode="x unified", yaxis_title=ytitle,
        xaxis_title="Miles downriver from the fork (toward Kuinerraq and the sea)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(l=10, r=10, t=60, b=10),
    )
    fig.add_vline(x=0, line_dash="dash", line_color="gray", line_width=1.5,
                  annotation_text="The Fork", annotation_position="top",
                  annotation_font_color="gray")
    lock_axes(fig)


def lock_axes(fig):
    """Disable zoom/pan (hover still works). The modebar is hidden on every
    chart, so a reader who drag-zoomed had no way back to the default view —
    simplest fix for this audience is to make the charts un-zoomable."""
    fig.update_xaxes(fixedrange=True)
    fig.update_yaxes(fixedrange=True)
    fig.update_layout(dragmode=False)


@st.cache_data(ttl=86400)
def load_map_points(_con, url_version):
    """A light sample of satellite measurement locations for the map."""
    try:
        return _con.execute(f"""
            SELECT latitude, longitude, Reach_Name
            FROM (SELECT latitude, longitude, Reach_Name
                  FROM river_data {VILLAGE_WHERE})
            USING SAMPLE 4000 ROWS (reservoir, 42)
        """).fetchdf()
    except Exception:
        return None


def fork_series(pdata):
    """Per-pass steepness (ft/mi) in the zone around the fork, one value per
    satellite pass that imaged enough of the zone. Returns {reach: Series}."""
    out = {}
    for reach, r in pdata.items():
        wsl = _fine_window_slope(r["mat"], r["grid"], FINE_WINDOW_KM)
        cov = _fine_window_coverage(r["mat"], r["grid"], FINE_WINDOW_KM)
        ok = (cov >= FINE_MIN_COVERAGE) & np.isfinite(wsl)
        if not ok.any():
            continue
        s = pd.Series(np.abs(wsl[ok]) * CMKM_TO_FTMI,
                      index=pd.to_datetime(r["passes"])[ok]).sort_index()
        out[reach] = s
    return out


# =============================================================================
# TAB 1 — START HERE
# =============================================================================
def render_start():
    st.markdown("""
    <div style="position: relative; width: 100%; margin-bottom: 1rem;">
        <img src="app/static/rivers_overhead.jpg" style="width: 100%; height: 190px; object-fit: cover; border-radius: 8px; filter: brightness(0.65);">
        <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); text-align: center; width: 100%;">
            <h1 style="color: white; margin: 0; text-shadow: 2px 2px 8px rgba(0,0,0,0.7); font-size: 2.2rem;">Qanirtuuq River Watch</h1>
            <p style="color: rgba(255,255,255,0.92); margin: 0.3rem 0 0 0; text-shadow: 1px 1px 4px rgba(0,0,0,0.7); font-size: 1.05rem;">Keeping an eye on the river — for Kuinerraq (Quinhagak)</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    About 20 miles upriver from Kuinerraq, the **Qanirtuuq (Kanektok River)
    splits in two**. Most of the water follows the main river past the
    village. A smaller share goes down **Uyak Creek**.

    Rivers like the Qanirtuuq can sometimes **jump** — leave their old path
    and pour down a new one. It usually starts slowly, then happens fast.
    The land here remembers this: the village's own name, *Kuinerraq*,
    means **"New River Channel."**

    #### How we watch the river from space

    A NASA satellite called **SWOT** flies over every few days and measures
    the **height of the river water**, accurate to a few inches, at
    thousands of spots along both rivers. From those heights we can measure
    each river's **steepness** — and steepness is what decides where water
    wants to go.

    #### The three warning signs

    River scientists have studied rivers that jumped, all over the world.
    Before a jump, one or more of these signs usually shows up:

    1. ⚖️ **The side path gets steeper than the main river.** Water always
       picks the steepest way downhill. *(Sign 1 tab)*
    2. 📉 **A flat spot appears.** The main river suddenly loses its
       steepness in one stretch, and water starts looking for a way out.
       *(Sign 2 tab)*
    3. 🌊 **The water sits higher than the land beside it.** A river that
       rides above its banks only needs one big flood to spill over and
       stay. *(Sign 3 tab)*

    Each sign has its own page in this tool. Look at the pictures, see
    where the rivers stand today, and check back over the months and years —
    **new satellite measurements are added as they come in**, so this is a
    tool for keeping watch, not a one-time report.
    """)

    st.info("**Start with the map** to see where the measurements are, "
            "then walk through the three signs. The last page, *Is Anything "
            "Changing?*, shows the whole record over time.")


# =============================================================================
# TAB 2 — THE RIVERS (MAP)
# =============================================================================
def render_map(con, data_version):
    st.subheader("Where the satellite measures")
    pts = load_map_points(con, data_version)
    if pts is None or len(pts) == 0:
        st.warning("The map points could not be loaded right now. "
                   "Try again in a few minutes.")
        return

    m = folium.Map(
        location=[(BIFURCATION_LAT + VILLAGE_LAT) / 2,
                  (BIFURCATION_LON + VILLAGE_LON) / 2],
        zoom_start=10,
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
              "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
    )
    for _, row in pts.iterrows():
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]], radius=2,
            color=COLOR_MAP.get(row["Reach_Name"], "black"),
            fill=True, fill_opacity=0.7, opacity=0.7, weight=0,
        ).add_to(m)
    folium.Marker(
        [BIFURCATION_LAT, BIFURCATION_LON], tooltip="The Fork — where the river splits",
        icon=folium.Icon(color="green", icon="random"),
    ).add_to(m)
    folium.Marker(
        [VILLAGE_LAT, VILLAGE_LON], tooltip="Kuinerraq (Quinhagak)",
        icon=folium.Icon(color="darkblue", icon="home"),
    ).add_to(m)
    st_folium(m, height=520, use_container_width=True, returned_objects=[])

    st.markdown(f"""
    - <span style="color:{COLOR_MAP[KAN]}">**Red dots**</span> — satellite
      water measurements on the **Qanirtuuq (Kanektok River)**, the main
      river that runs past the village.
    - <span style="color:{COLOR_MAP[UYAK]}">**Blue dots**</span> — measurements
      on **Uyak Creek**, the side path the water could switch into.
    - The **green marker** is the fork, about 20 miles upriver. The **house
      marker** is Kuinerraq.
    """, unsafe_allow_html=True)
    st.caption("Each dot is one real water-height measurement from space. "
               "This map shows a sample of them; the charts on the other "
               "pages use all of them.")


# =============================================================================
# TAB 3 — SIGN 1: THE STEEPER PATH
# =============================================================================
def render_sign_steeper(con, data_version):
    st.subheader("Sign 1 — Is the side path the steeper way down?")
    st.markdown("""
    Water always follows the **steepest path downhill**. Today the main
    river is steeper, so the water stays with it. If Uyak Creek ever became
    clearly steeper — especially **right at the fork**, where the water
    makes its choice — more and more water would switch over.
    """)

    with st.spinner("Measuring the rivers' steepness from the satellite record…"):
        pdata = compute_finescale_pass_matrix(
            con, data_version, VILLAGE_WHERE, FINE_RES_KM, FINE_XMAX_KM)
        ref = load_reference_gradient(con, data_version)
    series = fork_series(pdata) if pdata else {}

    if KAN not in series or UYAK not in series:
        st.warning("Not enough satellite passes are loaded to measure the "
                   "fork right now. Try again later.")
        return

    fork_kan = float(series[KAN].median())
    fork_uyak = float(series[UYAK].median())
    adv = fork_kan - fork_uyak

    # The picture first: two bars, side by side, at the fork.
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[SHORT[KAN], SHORT[UYAK]], y=[fork_kan, fork_uyak],
        marker_color=[COLOR_MAP[KAN], COLOR_MAP[UYAK]],
        text=[f"{fork_kan:.1f} ft/mi", f"{fork_uyak:.1f} ft/mi"],
        textposition="outside", width=0.5,
        hovertemplate="%{x}: drops %{y:.1f} feet per mile<extra></extra>",
    ))
    fig.update_layout(
        template="plotly_white", height=420, font=dict(size=15),
        yaxis_title="Feet of drop per mile, near the fork",
        title="Steepness at the fork — which path drops faster?",
        margin=dict(l=10, r=10, t=60, b=10), showlegend=False,
        # Headroom above the taller bar so the outside text labels
        # ("13.5 ft/mi") don't get clipped by the plot's top edge.
        yaxis_range=[0, max(fork_kan, fork_uyak) * 1.18],
    )
    lock_axes(fig)
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, theme=None)
    st.caption("Measured over the stretch about a mile each side of the "
               "fork, from every satellite pass that imaged it "
               f"({len(series[KAN])} passes on the Qanirtuuq, "
               f"{len(series[UYAK])} on Uyak Creek). Taller bar = steeper "
               "path = where the water wants to go.")

    if adv > 0:
        st.success(f"✅ **Right now: the main river is the steeper path.** "
                   f"At the fork, the Qanirtuuq drops about "
                   f"**{adv:.1f} feet per mile more** than Uyak Creek, so "
                   "the water has no reason to switch. The sign to watch "
                   "for is these bars trading places.")
    else:
        st.warning(f"⚠️ **Watch this:** at the fork, Uyak Creek is currently "
                   f"measuring **{-adv:.1f} feet per mile steeper** than the "
                   "main river. This is one of the warning signs — it is "
                   "worth checking the *Is Anything Changing?* page and "
                   "contacting the research team.")

    # Whole-river numbers as quiet context.
    if ref is not None and len(ref):
        ow = ref[(ref["open_water"]) & (ref["gated"])]
        whole = {r: float(g["theilsen_cm_km"].abs().median()) * CMKM_TO_FTMI
                 for r, g in ow.groupby("Reach_Name")}
        if KAN in whole and UYAK in whole:
            st.markdown(f"Over their **whole length** the two are nearly "
                        f"twins — the Qanirtuuq drops about "
                        f"**{whole[KAN]:.1f}** feet per mile and Uyak Creek "
                        f"about **{whole[UYAK]:.1f}**. That is exactly why "
                        "the fork is the place to watch: small differences "
                        "there decide where the water goes.")

    with st.expander("How is steepness measured from space?"):
        st.markdown("""
        Every satellite pass measures the water height along each river.
        Going downriver, the water gets lower — the drop per mile is the
        **steepness**. We measure it inside each single flyover (so the
        river's water level that day doesn't confuse the answer), then take
        the middle value across all flyovers. Passes that only caught a
        sliver of the fork area are left out, so bad angles can't skew the
        answer.
        """)


# =============================================================================
# TAB 4 — SIGN 2: A FLAT SPOT
# =============================================================================
def render_sign_flattening(con, data_version):
    st.subheader("Sign 2 — Has a flat spot appeared in the river?")
    st.markdown("""
    Before rivers jump, they often **suddenly flatten out in one stretch** —
    studies of rivers around the world found the steepness dropping to half
    or a third of normal right where the river later broke out. This chart
    is the river's steepness at every point along the way, so a new flat
    spot has nowhere to hide.
    """)

    with st.spinner("Building the steepness profile from every satellite pass…"):
        pdata = compute_finescale_pass_matrix(
            con, data_version, VILLAGE_WHERE, FINE_RES_KM, FINE_XMAX_KM)
    if not pdata:
        st.warning("The steepness profile could not be built right now. "
                   "Try again later.")
        return

    fig = go.Figure()
    for reach in (KAN, UYAK):
        if reach not in pdata:
            continue
        r = pdata[reach]
        med, lo, hi, n = _fine_aggregate(r["mat"])
        core = n >= 3          # only show stretches imaged by 3+ passes
        if not core.any():
            continue
        x = mi_from_fork(r["grid"][core])
        y = np.abs(med[core]) * CMKM_TO_FTMI
        b1, b2 = np.abs(lo[core]) * CMKM_TO_FTMI, np.abs(hi[core]) * CMKM_TO_FTMI
        band_lo, band_hi = np.minimum(b1, b2), np.maximum(b1, b2)
        color = COLOR_MAP[reach]
        rgb = {"firebrick": "178,34,34", "dodgerblue": "30,144,255"}.get(color, "0,0,0")
        fig.add_trace(go.Scatter(
            x=np.concatenate([x, x[::-1]]),
            y=np.concatenate([band_hi, band_lo[::-1]]),
            fill="toself", fillcolor=f"rgba({rgb},0.15)", line=dict(width=0),
            showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(
            x=x, y=y, mode="lines", line=dict(color=color, width=3),
            name=SHORT[reach],
            hovertemplate=f"<b>{SHORT[reach]}</b><br>%{{x:.1f}} mi from the "
                          "fork<br>drops %{y:.1f} feet per mile<extra></extra>"))
    base_layout(fig, "Feet of drop per mile", height=480)
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, theme=None)
    st.caption("The line is the typical steepness at each spot (middle value "
               "across all satellite passes); the shading shows how much it "
               "varies from pass to pass. Stretches seen by fewer than 3 "
               "passes are left blank instead of guessed.")

    st.success("✅ **Right now: this is the normal, healthy shape.** Both "
               "rivers are steep up near the fork and grow gentler toward "
               "the sea — rivers are supposed to look like this. The warning "
               "sign would be a **new dip** in this line where the river "
               "used to be steep, showing up and staying across many passes.")

    with st.expander("How to read this chart"):
        st.markdown("""
        - **Left edge** = up at the fork. **Right edge** = down near
          Kuinerraq and the sea.
        - **Higher line = steeper water = faster-moving river** at that spot.
        - The two rivers can be compared directly: where the red line is
          above the blue line, the main river is steeper than Uyak Creek.
        - Uyak Creek is narrower, so the satellite catches it cleanly less
          often — that is why its shaded band is wider.
        """)


# =============================================================================
# TAB 5 — SIGN 3: WATER ABOVE THE LAND
# =============================================================================
def render_sign_high_water():
    st.subheader("Sign 3 — Does the water sit higher than the land beside it?")
    st.markdown("""
    Over many years, a river slowly builds its own bed upward. A river in
    danger of jumping is one that has built itself up so high that its
    **water rides above the land next to it** — held in only by its banks.
    Then one big flood can spill over and never come back. This chart
    compares the Qanirtuuq's water height to the height of the land beside
    it, mile by mile.
    """)

    channels, _profiles = load_xsec_B()
    if channels is None or "kan_superelev_m" not in channels:
        st.warning("The land-height measurements are not loaded right now.")
        return

    ch = channels.dropna(subset=["kan_superelev_m"]).sort_values("R_km")
    x = mi_from_fork(ch["R_km"])
    y = ch["kan_superelev_m"].to_numpy() * M_TO_FT
    lo = ch["kan_superelev_p10_m"].to_numpy() * M_TO_FT
    hi = ch["kan_superelev_p90_m"].to_numpy() * M_TO_FT

    fig = go.Figure()
    # Green = the safe zone: water below the level of the nearby land.
    ymin = float(min(np.nanmin(lo), np.nanmin(y))) - 1.5
    fig.add_hrect(y0=ymin, y1=0, fillcolor="green", opacity=0.06, line_width=0)
    fig.add_trace(go.Scatter(
        x=np.concatenate([x, x[::-1]]), y=np.concatenate([hi, lo[::-1]]),
        fill="toself", fillcolor="rgba(178,34,34,0.15)", line=dict(width=0),
        showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=x, y=y, mode="lines+markers", line=dict(color=COLOR_MAP[KAN], width=3),
        marker=dict(size=5), name=SHORT[KAN],
        hovertemplate="%{x:.1f} mi from the fork<br>water is %{y:.1f} ft "
                      "vs. the nearby land<extra></extra>"))
    fig.add_hline(y=0, line_color="black", line_width=2,
                  annotation_text="Level of the nearby land",
                  annotation_position="top left")
    base_layout(fig, "Water height compared to the nearby land (feet)", height=480)
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, theme=None)
    st.caption("Below the black line = the water sits **below** the land "
               "beside the river (the green zone is good). The shading shows "
               "the range as the river rises and falls between seasons.")

    below = float((ch["kan_superelev_m"] < 0).mean()) * 100
    typical_ft = -float(ch["kan_superelev_m"].median()) * M_TO_FT
    st.success(f"✅ **Right now: the water sits below the land almost "
               f"everywhere.** Along {below:.0f}% of the measured river, the "
               f"Qanirtuuq's water is **below** the land beside it — "
               f"typically about **{typical_ft:.0f} feet below**. The warning "
               "sign would be this line climbing up toward the black line "
               "over the years.")
    st.caption("⚠️ *An early look:* the land heights here come from aerial "
               "elevation mapping collected 2010–2021, and the research "
               "team's detailed check of these numbers is still being "
               "finished. The water heights are current satellite "
               "measurements.")

    with st.expander("Why does a river build itself up?"):
        st.markdown("""
        Rivers carry sand and mud. When a river floods, the water slows down
        at the edges and drops that sand, building natural ridges (levees)
        and slowly raising the river's own bed. Give it enough years and the
        river can end up perched above its floodplain — like water in a
        raised gutter. That is when a jump becomes possible.
        """)


# =============================================================================
# TAB 6 — IS ANYTHING CHANGING?
# =============================================================================
def render_changes(con, data_version):
    st.subheader("Is anything changing?")
    st.markdown("""
    A river jump doesn't come from one bad day — it comes from the signs
    above **drifting in the wrong direction over the years**. This page is
    the long record, and it grows automatically: every new satellite pass
    adds a dot.
    """)

    ref = load_reference_gradient(con, data_version)
    with st.spinner("Loading the full record…"):
        pdata = compute_finescale_pass_matrix(
            con, data_version, VILLAGE_WHERE, FINE_RES_KM, FINE_XMAX_KM)

    first_year = last_year = None
    if ref is not None and len(ref):
        ow = ref[(ref["open_water"]) & (ref["gated"])].copy()
        ow["date"] = pd.to_datetime(ow["Pass_Date"])
        ow["ftmi"] = ow["theilsen_cm_km"].abs() * CMKM_TO_FTMI
        first_year, last_year = ow["date"].dt.year.min(), ow["date"].dt.year.max()

        fig = go.Figure()
        for reach in (KAN, UYAK):
            d = ow[ow["Reach_Name"] == reach].sort_values("date")
            if not len(d):
                continue
            fig.add_trace(go.Scatter(
                x=d["date"], y=d["ftmi"], mode="markers",
                marker=dict(size=6, color=COLOR_MAP[reach], opacity=0.55),
                name=SHORT[reach],
                hovertemplate=f"<b>{SHORT[reach]}</b><br>%{{x|%b %d, %Y}}<br>"
                              "drops %{y:.1f} feet per mile<extra></extra>"))
            fig.add_hline(y=float(d["ftmi"].median()), line_dash="dot",
                          line_color=COLOR_MAP[reach], line_width=1.5)
        fig.update_layout(
            template="plotly_white", height=430, font=dict(size=15),
            title="Each river's steepness, one dot per satellite pass",
            yaxis_title="Feet of drop per mile (whole river)",
            xaxis_title="Date of satellite pass", hovermode="closest",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
            margin=dict(l=10, r=10, t=60, b=10))
        lock_axes(fig)
        st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG,
                        theme=None)
        st.caption("The dotted lines mark each river's typical value. Dots "
                   "scatter around them naturally — the water level changes "
                   "with the seasons. The warning sign is the **dots walking "
                   "away from the line and staying away**.")

    # The fork gap over time — the single most important tracking chart.
    series = fork_series(pdata) if pdata else {}
    if KAN in series and UYAK in series:
        gap = (series[KAN] - series[UYAK]).dropna()
        if len(gap):
            fig2 = go.Figure()
            fig2.add_hrect(y0=0, y1=float(max(gap.max(), 1)) + 0.5,
                           fillcolor="green", opacity=0.06, line_width=0)
            fig2.add_trace(go.Scatter(
                x=gap.index, y=gap.values, mode="markers+lines",
                marker=dict(size=6, color="darkgreen"),
                line=dict(color="darkgreen", width=1), name="Fork gap",
                hovertemplate="%{x|%b %d, %Y}<br>main river steeper by "
                              "%{y:.1f} ft/mi<extra></extra>"))
            fig2.add_hline(y=0, line_color="black", line_width=2,
                           annotation_text="Even — below this line, Uyak "
                                           "Creek is the steeper path",
                           annotation_position="bottom left")
            fig2.update_layout(
                template="plotly_white", height=420, font=dict(size=15),
                title="At the fork: how much steeper is the main river?",
                yaxis_title="Qanirtuuq minus Uyak Creek (ft per mile)",
                xaxis_title="Date of satellite pass",
                margin=dict(l=10, r=10, t=60, b=10), showlegend=False)
            lock_axes(fig2)
            st.plotly_chart(fig2, width="stretch",
                            config=PLOTLY_CONFIG, theme=None)
            st.caption("Each dot compares the two paths **on the same day**, "
                       "using one satellite pass that saw both. Above the "
                       "black line, the main river is winning. If these dots "
                       "sank below the line and stayed there, the shortcut "
                       "would have become the steeper path — the clearest "
                       "early warning this tool can give.")

            share_kan = float((gap > 0).mean()) * 100
            years = (f"{first_year}–{last_year}" if first_year and
                     first_year != last_year else f"{last_year or ''}")
            st.info(f"**The bottom line, as of the newest data here:** none "
                    f"of the three warning signs is showing. The main river "
                    f"has been the steeper path at the fork in "
                    f"**{share_kan:.0f}%** of paired satellite passes, both "
                    f"rivers' steepness has held steady over **{years}**, "
                    "and the water sits below the land beside it. Rivers can "
                    "change — that is exactly why this tool keeps watching, "
                    "pass after pass, year after year.")


# =============================================================================
def main():
    data_version = get_data_version()
    con = get_database_connection(data_version)
    if not con:
        st.error("The river data could not be loaded right now. "
                 "Please try again in a few minutes.")
        st.stop()

    tabs = st.tabs([
        "🏠 Start Here", "🗺️ The Rivers", "⚖️ Sign 1: The Steeper Path",
        "📉 Sign 2: A Flat Spot", "🌊 Sign 3: Water Above the Land",
        "📅 Is Anything Changing?",
    ])
    with tabs[0]:
        render_start()
    with tabs[1]:
        render_map(con, data_version)
    with tabs[2]:
        render_sign_steeper(con, data_version)
    with tabs[3]:
        render_sign_flattening(con, data_version)
    with tabs[4]:
        render_sign_high_water()
    with tabs[5]:
        render_changes(con, data_version)

    st.divider()
    st.caption(
        "Built for the people of Kuinerraq (Quinhagak) as part of National "
        "Science Foundation Award 2527256, *Dynamic Modeling of River "
        "Ecosystem Stability*. Water heights: NASA/CNES SWOT mission. Land "
        "heights: ArcticDEM (Polar Geospatial Center). Questions or "
        "something you're seeing on the land that this tool should know "
        "about? Contact the research team — local knowledge of these rivers "
        "goes back further than any satellite."
    )


if __name__ == "__main__":
    main()
