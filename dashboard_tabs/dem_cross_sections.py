"""Cross-Sections DEM sub-tab: pre-built arc-B transect figures."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .common import COLOR_MAP

def render_cross_sections(chB, profB, plotly_template):
    """Interactive DEM cross-section viewer — Approach B iso-distance-from-anchor arcs
    (Kanektok vs Uyak water surfaces at a matched downstream position).
    See DEM_Transects/AVULSION_ANALYSIS.md."""
    st.subheader("DEM Cross-Sections")
    st.caption(
        "Scrub through the individual DEM cross-sections behind the avulsion analysis. Each cut "
        "follows an **arc of constant distance-from-anchor**, spanning Kanektok → floodplain → Uyak, "
        "so the two rivers are compared at a matched downstream position."
    )
    if chB is None or profB is None:
        st.warning("Cross-section artifacts not found. Run the DEM_Transects scripts locally.")
        return

    radii = chB["R_km"].tolist()
    default_R = min(radii, key=lambda r: abs(r - 16.0))
    R = st.select_slider(
        "Distance from anchor (km, ≈ downstream)", options=radii, value=default_R,
        key="xsecB_R")
    crow = chB[chB["R_km"] == R].iloc[0]
    g = profB[profB["R_km"] == R].sort_values("arc_m")

    # Re-center the cross-valley axis on the Kanektok channel (x = 0), increasing toward the Uyak,
    # so every arc reads "stand in the Kanektok, walk the spill path toward the Uyak" and the β
    # anatomy (bed / crest / floodplain) hangs directly off the would-be avulsing channel at x = 0.
    kcm, ucm = crow["kan_arc_m"], crow["uyak_arc_m"]
    recentered = np.isfinite(kcm) and np.isfinite(ucm)
    sgn = float(np.sign(ucm - kcm)) if recentered else 1.0
    if sgn == 0:
        sgn = 1.0
    origin = kcm if np.isfinite(kcm) else 0.0

    def _x(arc_m):  # metres on the along-arc axis -> km on the Kanektok-centered axis
        return (np.asarray(arc_m, float) - origin) * sgn / 1000.0

    KAN, UYAK = COLOR_MAP["Kanektok_River"], COLOR_MAP["Uyak_Creek"]
    x_kan = _x(kcm) if np.isfinite(kcm) else None      # 0.0 when the Kanektok is located
    x_uyak = _x(ucm) if np.isfinite(ucm) else None     # > 0 (Uyak direction)
    bed, crest, fp = crow.get("kan_bed_m", np.nan), crow.get("kan_crest_m", np.nan), crow.get("fp_ref_m", np.nan)

    # Trim the view to the Kanektok→Uyak span plus a little context. The outward arc sweep runs
    # well past the Uyak (increasingly so at large radius) over terrain outside the two-river
    # system, which is nothing we're reading here — so cut the section a fixed distance past each
    # channel. Filtering the terrain (not just the axis range) also lets the y-axis fit the reach.
    PAD_KM = 0.75
    xr_all = _x(g["arc_m"])
    left = (x_kan if x_kan is not None else float(np.min(xr_all))) - PAD_KM
    right = (x_uyak if x_uyak is not None else float(np.max(xr_all))) + PAD_KM
    win = (xr_all >= left) & (xr_all <= right)
    gx, gy = xr_all[win], g["elevation_m"].to_numpy()[win]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=gx, y=gy, mode="lines",
        line=dict(color="#555", width=1.3), name="terrain",
        hovertemplate="from Kanektok: %{x:+.2f} km<br>elevation: %{y:.2f} m<extra></extra>"))
    if x_kan is not None:
        fig.add_vline(x=x_kan, line_color=KAN, line_width=2,
                      annotation_text="Kanektok", annotation_position="top",
                      annotation_font_color=KAN)
    if x_uyak is not None:
        fig.add_vline(x=x_uyak, line_color=UYAK, line_width=2,
                      annotation_text="Uyak", annotation_position="top",
                      annotation_font_color=UYAK)
    # Inter-channel floodplain corridor (the avulsion pathway) + its reference elevation.
    CH_WIN_M = 250.0  # matches build_arc_B.py
    if np.isfinite(fp) and x_kan is not None and x_uyak is not None:
        lo, hi = sorted([x_kan, x_uyak])
        fig.add_vrect(x0=lo + CH_WIN_M / 1000.0, x1=hi - CH_WIN_M / 1000.0,
                      fillcolor="#31a354", opacity=0.08, line_width=0,
                      annotation_text="floodplain corridor", annotation_position="top left",
                      annotation_font_size=10, annotation_font_color="#31a354")
        fig.add_hline(y=fp, line_dash="dash", line_color="#31a354", line_width=1.5,
                      annotation_text=f"floodplain ref ({fp:.1f} m)",
                      annotation_position="right", annotation_font_size=10,
                      annotation_font_color="#31a354")
    # Kanektok ADCP bed ▼ + ridge crest ▲ at x = 0 (the β geometry — H_M = crest→bed, H_AR =
    # crest→floodplain — but the actual β / H_M / H_AR values live in the metrics below, not on-plot).
    if x_kan is not None and np.isfinite(bed):
        fig.add_trace(go.Scatter(
            x=[x_kan], y=[bed], mode="markers", name="Kanektok bed (ADCP)",
            marker=dict(symbol="triangle-down", size=12, color=KAN),
            hovertemplate=f"Kanektok bed: %{{y:.2f}} m<br>ADCP depth: {crow.get('kan_depth_m', np.nan):.2f} m<extra></extra>"))
    if x_kan is not None and np.isfinite(crest):
        fig.add_trace(go.Scatter(
            x=[x_kan], y=[crest], mode="markers", name="Kanektok ridge crest",
            marker=dict(symbol="triangle-up", size=12, color=KAN),
            hovertemplate="Kanektok ridge crest: %{y:.2f} m<extra></extra>"))
    # Independent SWOT water surface at each channel, with the p10–p90 range across overpasses as the
    # error bar. The DEM images one arbitrary stage from a 2010–2021 mosaic blend; SWOT shows both
    # where the water actually sits and how far it moves, so the reader can see the DEM marker land
    # inside the observed range rather than take the single DEM value on faith.
    for tag, xc, col, name in (("kan", x_kan, KAN, "Kanektok"), ("uyak", x_uyak, UYAK, "Uyak")):
        med = crow.get(f"swot_{tag}_wse_med_m", np.nan)
        p10, p90 = crow.get(f"swot_{tag}_wse_p10_m", np.nan), crow.get(f"swot_{tag}_wse_p90_m", np.nan)
        if xc is None or not np.isfinite(med):
            continue
        err = dict(type="data", symmetric=False, array=[p90 - med], arrayminus=[med - p10],
                   color=col, thickness=1.5, width=6) if np.isfinite(p10) and np.isfinite(p90) else None
        fig.add_trace(go.Scatter(
            x=[xc], y=[med], mode="markers", name=f"{name} SWOT water (p10–p90)",
            marker=dict(symbol="circle-open", size=13, color=col, line=dict(width=2.5)),
            error_y=err,
            hovertemplate=f"{name} SWOT median stage: %{{y:.2f}} m<br>"
                          f"range p10–p90: {p10:.2f} – {p90:.2f} m<extra></extra>"))
    fig.update_layout(
        title=f"Arc at {R:.1f} km from anchor  (Kanektok → floodplain → Uyak)",
        xaxis=dict(title="Distance from Kanektok toward Uyak (km)", range=[left, right]),
        yaxis_title="Elevation (m, EGM2008)",
        height=460, template=plotly_template, showlegend=True, margin=dict(r=150),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, use_container_width=True, theme=None)

    # Two aligned rows of 3: water surfaces on top, superelevation (the avulsion metric) below.
    def _se(v):
        return f"{v:+.2f} m" if pd.notna(v) else "n/a"

    # The inter-river difference is quoted from SWOT PASS-PAIRED data, not from the DEM. Both rivers
    # are measured in the same overpass, so stage cancels exactly. The DEM version is contaminated:
    # the ArcticDEM mosaic is a multi-date blend that caught the Kanektok near the 29th percentile of
    # observed stages and the Uyak near the 76th, worth ~0.27 m of spurious "Uyak higher"
    # (per-arc median of DEM-diff minus SWOT-paired-diff, n=64 arcs, arcB_channels.parquet).
    swot_diff = crow.get("swot_diff_uyak_minus_kan", np.nan)
    dem_diff = crow["diff_uyak_minus_kan"]
    r1c1, r1c2, r1c3 = st.columns(3)
    r1c1.metric("Kanektok water surface", f"{crow['kan_wse_m']:.2f} m",
                help="From the 2 m ArcticDEM along this arc (EGM2008). The open circle on the plot "
                     "is the independent SWOT water surface, with its p10–p90 range across overpasses.")
    r1c2.metric("Uyak water surface", f"{crow['uyak_wse_m']:.2f} m",
                help="As for the Kanektok.")
    r1c3.metric("Uyak − Kanektok (SWOT)",
                f"{swot_diff:+.2f} m" if pd.notna(swot_diff) else _se(dem_diff),
                help="Positive → Uyak sits higher at this radius. Taken from SWOT overpasses that "
                     "measured BOTH rivers at the same moment, so river stage cancels out. "
                     f"The DEM-only value here is {dem_diff:+.2f} m; it reads high because the "
                     "multi-date DEM mosaic imaged the two rivers at different stages.")

    # Superelevation is inherently stage-dependent, so it is quoted at the SWOT MEDIAN stage with the
    # p10–p90 band in the help text rather than at the DEM's single arbitrary blend stage.
    def _band(tag):
        p10, p90 = crow.get(f"{tag}_superelev_p10_m", np.nan), crow.get(f"{tag}_superelev_p90_m", np.nan)
        return (f" Across the observed stage range this runs {p10:+.2f} m (low water) to "
                f"{p90:+.2f} m (high water)." if pd.notna(p10) and pd.notna(p90) else "")

    r2c1, r2c2, r2c3 = st.columns(3)
    r2c1.metric("Kanektok superelevation", _se(crow.get("kan_superelev_m", np.nan)),
                help="Channel water surface minus the inter-channel floodplain corridor, at the "
                     "median observed stage. Negative = incised below the floodplain (not perched); "
                     "positive = perched above the corridor (avulsion-prone)." + _band("kan"))
    r2c2.metric("Uyak superelevation", _se(crow.get("uyak_superelev_m", np.nan)),
                help="As for the Kanektok, relative to the same corridor." + _band("uyak"))
    r2c3.metric("Floodplain corridor elev",
                f"{crow['fp_ref_m']:.2f} m" if pd.notna(crow.get("fp_ref_m", np.nan)) else "n/a",
                help="Median terrain of the corridor between the channels — the baseline "
                     "each superelevation is measured against.")

    # Kanektok Gearon β = H_AR/H_M, using the measured ADCP channel depth for the bed.
    st.markdown("**Kanektok superelevation ratio** — Gearon β = H_AR / H_M "
                "(alluvial-ridge height ÷ channel depth)")
    b = crow.get("kan_beta", np.nan)
    r3c1, r3c2, r3c3 = st.columns(3)
    r3c1.metric("Kanektok β", f"{b:.2f}" if pd.notna(b) else "n/a",
                help="H_AR/H_M, with the bed from the boat-ADCP depth at the SWOT-matched survey "
                     "stage. β near 0 means H_AR ≈ 0 — there is no alluvial ridge standing above the "
                     "floodplain to superelevate. Note β = 1 is NOT the operative avulsion threshold: "
                     "Gearon's criterion is β×γ ≥ Λ, and this analysis does not evaluate the gradient "
                     "term γ. See the how-to-read note below.")
    r3c2.metric("H_AR (ridge height)", _se(crow.get("kan_HAR_m", np.nan)),
                help="Alluvial-ridge crest minus floodplain. Across all arcs the median is ≈ +0.1 m, "
                     "i.e. effectively no ridge — consistent with the channel being incised.")
    r3c3.metric("H_M (channel depth)",
                f"{crow['kan_HM_m']:.2f} m" if pd.notna(crow.get("kan_HM_m", np.nan)) else "n/a",
                help=f"Crest minus bed = freeboard + measured ADCP depth "
                     f"({crow.get('kan_depth_m', np.nan):.2f} m at this arc).")

    # Water-surface long-profiles vs radius with the current arc marked.
    prof_fig = go.Figure()
    for tag, col, name in (("kan", COLOR_MAP["Kanektok_River"], "Kanektok"),
                           ("uyak", COLOR_MAP["Uyak_Creek"], "Uyak")):
        p10, p90 = chB.get(f"swot_{tag}_wse_p10_m"), chB.get(f"swot_{tag}_wse_p90_m")
        if p10 is not None and p10.notna().any():
            # Trace-level opacity rather than an rgba fillcolor, so COLOR_MAP can hold CSS colour
            # names (it does — "firebrick"/"dodgerblue") without needing a name→rgb conversion.
            band = pd.concat([p90, p10[::-1]]).to_numpy(dtype=float)
            prof_fig.add_trace(go.Scatter(
                x=np.concatenate([chB["R_km"].to_numpy(), chB["R_km"].to_numpy()[::-1]]),
                y=band, fill="toself", fillcolor=col, opacity=0.18, line=dict(width=0),
                name=f"{name} SWOT stage p10–p90", hoverinfo="skip"))
        prof_fig.add_trace(go.Scatter(x=chB["R_km"], y=chB[f"{tag}_wse_m"], mode="lines",
                                      name=f"{name} (DEM)", line=dict(color=col, width=2)))
    prof_fig.add_vline(x=R, line_color="gray", line_dash="dot", line_width=1.5)
    prof_fig.update_layout(
        title="Channel water-surface long profiles at matched radius",
        xaxis_title="Distance from anchor (km, ≈ downstream)",
        yaxis_title="Channel water-surface elevation (m)", height=340, template=plotly_template)
    st.plotly_chart(prof_fig, use_container_width=True, theme=None)

    sv = chB.dropna(subset=["swot_diff_uyak_minus_kan"])
    fpv = chB.dropna(subset=["fp_ref_m"])
    kan_perched = (fpv["kan_superelev_m"] > 0).mean() * 100 if len(fpv) else float("nan")
    st.markdown(
        f"**Across all arcs:** the Uyak water surface sits a median "
        f"**{sv['swot_diff_uyak_minus_kan'].median():+.2f} m** above the Kanektok, measured from SWOT "
        f"overpasses that caught **both rivers at the same moment** so that stage cancels. (The "
        f"DEM-only value, {chB['diff_uyak_minus_kan'].median():+.2f} m, reads high because the "
        f"multi-date DEM mosaic imaged the two rivers at different stages.)\n\n"
        f"**Superelevation vs the floodplain corridor, at the median observed stage:** the Kanektok "
        f"is **incised** (median **{fpv['kan_superelev_m'].median():+.2f} m**, perched on "
        f"{kan_perched:.0f}% of arcs) while the Uyak sits closer to grade (median "
        f"**{fpv['uyak_superelev_m'].median():+.2f} m**). A channel must be *perched above* the "
        "corridor to avulse into it — the Kanektok is not, so this is direct topographic evidence "
        "**against** a Kanektok → Uyak avulsion."
    )
    bv = chB.dropna(subset=["kan_beta"])
    if len(bv):
        st.markdown(
            f"**Superelevation ratio (Gearon β = H_AR/H_M):** median **β = {bv['kan_beta'].median():.2f}**, "
            f"with **H_AR ≈ {bv['kan_HAR_m'].median():+.2f} m** — the Kanektok has essentially **no "
            f"alluvial ridge** standing above the floodplain, and on "
            f"**{(bv['kan_beta']<=0).mean()*100:.0f}%** of arcs the near-channel high ground sits "
            "*below* the floodplain reference outright. That is the same story the incision figure "
            "tells, in dimensionless form: there is no levee here to perch a channel on top of. "
            "β is reported as a reproduction of the original ArcGIS metric — **β = 1 is not the "
            "operative avulsion threshold** (see the note below)."
        )
    with st.expander("How to read this arc cross-section (and its caveat)"):
        st.markdown("""
            Each cut follows an **arc of constant straight-line distance from the shared anchor**,
            so every point is at the same downstream coordinate the rest of the dashboard uses
            (the fan/delta radial-distance convention). One arc spans **Kanektok → floodplain →
            Uyak**, letting the two water surfaces be compared at a matched downstream position.

            - The **x-axis is re-centered on the Kanektok (x = 0), increasing toward the Uyak**, so
              the plot reads *"stand in the Kanektok, walk the spill path toward the Uyak."* The
              Uyak line therefore sits at the channel separation (~3 km) on the right. The view is
              **trimmed a short distance past the Uyak** — the outward arc sweep runs on over terrain
              outside the two-river system, which isn't part of the avulsion question.
            - The two **vertical lines** mark each channel; the **green band** is the inter-channel
              floodplain corridor (the pathway a Kanektok → Uyak avulsion would drain across),
              excluding each channel's ±250 m notch; the **green dashed line** is its median elevation.
            - **Superelevation** = channel water surface − corridor elevation. *Negative* means the
              channel is incised below the floodplain (the safe, usual case); *positive* means it is
              perched above the corridor and could spill toward the other river.
            - **Water surface, and why SWOT is here.** The grey terrain line is the 2 m ArcticDEM.
              The **open circles** are the independent **SWOT** water surface at each channel, and
              their **error bars are the p10–p90 range across overpasses** — a river has no single
              water surface, and at a fixed radius the stage moves ~0.7 m. The DEM is a *mosaic
              blended from 2010–2021 imagery*, so it captured one arbitrary (and per-river different)
              stage. It holds up well — the DEM channel water surface lands within ~0.15 m of the
              SWOT median on both rivers — but because the mosaic caught the Kanektok low in its
              stage range and the Uyak high, the **Uyak − Kanektok difference is quoted from
              pass-paired SWOT**, where both rivers are measured in the same overpass and stage
              cancels exactly. Superelevation is likewise quoted **at the median observed stage**,
              with the low/high-water range given in each metric's tooltip.
            - **Gearon β = H_AR / H_M** — on the Kanektok at x = 0, ▲ marks the ridge crest and ▼ the
              bed; H_M = crest − bed (channel depth) and H_AR = crest − floodplain (ridge height), and
              the **β / H_AR / H_M values are listed in the metrics below the plot**. Note that all
              three are *topographic* surfaces: the water surface is not a term in β — it only serves
              to place the bed under the **boat-ADCP depth sounding**, and it is taken from the SWOT
              pass that flew **during the 2026 survey**, so depth and water surface share one stage.
              The crest is read within **±150 m** of the channel (~3 channel widths, the scale Gearon
              works at); a wider window climbs onto regional high ground rather than a bank, and
              yields a "bank" standing far higher above the water than the river is deep — one the
              river could never fill. **β = 1 is not the operative avulsion threshold.** Gearon's
              criterion is **β × γ ≥ Λ** (Λ median ≈ 2.1), where γ is a gradient-advantage term this
              analysis does not evaluate; in their data most avulsed *deltas* sit at β < 0.5. Here β
              lands near 0 because **H_AR ≈ 0 — there is no alluvial ridge to superelevate.**
              (Kanektok only — the Uyak has ADCP depth near its mouth only.)
            - Each channel is located by **snapping to the actual DEM channel** from a centerline
              prior. Both priors are **official field-surveyed centerlines** accurate to ~20–50 m —
              the Uyak from a hunter's boat GPS, the Kanektok from a coworker boat-ADCP thalweg run —
              so both use the same tight ±75 m search that can't stray onto nearby sloughs. The channels are narrow
              (~30–50 m), so both the thalweg and the water surface use the **2nd percentile**
              (deepest sliver of terrain = the water) in a tight ±50 m window, sampled at the DEM's
              native 2 m resolution so the narrow channel is genuinely resolved (~15–25 samples).
              ArcticDEM images the water surface, not the true bed, so this is
              directly comparable to the SWOT water surface.

            **Channel-migration caveat:** the field centerlines were surveyed in **2026**, but the
            ArcticDEM mosaic is built from **2010–2021** imagery, so the river has had years to
            shift. The DEM channel sits a median ~38 m (Kanektok) and ~12 m (Uyak) from the boat
            line, and on ~9% of arcs the snap runs into the edge of its ±75 m search window, meaning
            the DEM channel may lie further out still. This does **not** move the water-surface
            values — widening the search leaves them unchanged to 0.00 m, because the floodplain low
            is broad and flat — but it does leave the channel *position*, and the crest window
            anchored on it, uncertain at the few-tens-of-metres level.

            **Validity caveat (Merwade et al. 2006):** straight-line radius equals along-channel
            flow distance only where a channel runs straight from the anchor. Here each channel's
            bearing drifts ~20° over its length, but *both* drift consistently and keep a steady
            separation, so the Kanektok-vs-Uyak comparison stays robust — and it agrees with SWOT.
            """)
