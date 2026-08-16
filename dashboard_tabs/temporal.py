"""Temporal Results tab: pre-computed seasonal/interannual/typhoon conclusions."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from .common import COLOR_MAP, add_bifurcation_line, load_temporal_results


def render(ctx):
    plotly_template = ctx.plotly_template

    st.subheader("⏳ Is the River Changing Over Time?")
    temporal = load_temporal_results()
    if temporal is None:
        st.info(
            "Temporal-analysis results not found. Generate them with "
            "`python3 temporal_analysis.py` (writes to `temporal_results/`)."
        )
    else:
        results = temporal["results"]
        metrics = temporal["metrics"]
        q3_curve = temporal["q3_curve"]
        method = results["method"]
        record = results["record"]

        DISP = {"Kanektok_River": "Kanektok River", "Uyak_Creek": "Uyak Creek"}
        REACH_ORDER = ["Kanektok_River", "Uyak_Creek"]

        def _fmt_p(p, p_adj=None):
            # Star on the Holm-adjusted p when the JSON carries it (one family
            # across all the page's Mann-Whitney tests); raw-p fallback keeps
            # older JSONs rendering until they are regenerated.
            if p is None or (isinstance(p, float) and np.isnan(p)):
                return "n/a (n<3)"
            starred = (p_adj if p_adj is not None else p) < 0.05
            return f"{p:.3f}" + (" *" if starred else "")

        q1_slope = {r["reach"]: r for r in results["Q1_seasonal"]
                    if r["question"] == "Q1_slope_pooled"}
        q3p = {r["reach"]: r for r in results["Q3_profile"]}

        st.markdown(
            "This page asks a simple question: **are these two rivers changing over "
            "time?** We look three ways — from spring to late summer, from one year to the "
            "next, and before vs. after Typhoon Halong. The answers were worked out once, "
            "off-line, using the same fair method as the river-steepness page: it measures "
            "the whole river evenly, so a satellite pass that only caught part of the river "
            "can't tip the results. Nothing here is re-calculated on the fly."
        )
        st.success(
            "**Bottom line — both rivers are holding steady.** How steeply the river drops "
            "has barely changed from spring to late summer, from year to year, or across "
            "Typhoon Halong. The water level moves around a little, but only as much as it "
            "normally does from one year to the next — and **we see no sign of the typhoon "
            "changing the river upstream** (the storm check is still preliminary — see the "
            "note on the last chart)."
        )
        st.markdown(
            f"- **Spring vs. late summer:** the river's steepness barely moves "
            f"(a change of {q1_slope['Kanektok_River']['dslope_cm_km']:+.1f} cm/km on "
            f"Kanektok and {q1_slope['Uyak_Creek']['dslope_cm_km']:+.1f} on Uyak, against "
            f"an overall drop of about 195 cm/km — too small to matter). The water level "
            f"rises and falls only about 0.2–0.5 m, and which season is higher flips from "
            f"year to year.\n"
            f"- **Year to year (summer 2024 vs. 2025):** both rivers steady — the steepness "
            f"change is tiny, and the water level shifts only about 0.2 m (Kanektok) to "
            f"0.5 m (Uyak).\n"
            f"- **Typhoon Halong (preliminary):** upriver, the water level changed only "
            f"{q3p['Kanektok_River']['median_dwse_m']:+.2f} m (Kanektok) and "
            f"{q3p['Uyak_Creek']['median_dwse_m']:+.2f} m (Uyak) — within the normal "
            f"year-to-year range. The storm's damage was along the coast, not up the river."
        )
        st.caption(
            "Two terms to know: the river's **steepness** (how far the water surface drops "
            "for every kilometer downstream — about 195 cm, roughly 6 feet, per km on these "
            "rivers) is labeled **Hydraulic Gradient** on the charts; the **water level** is "
            "labeled **Water Surface Elevation**. "
            "Full write-up, method checks, and limitations: "
            "`TEMPORAL_ANALYSIS.md` · `SCIENTIFIC_METHODOLOGY.md`."
        )
        st.divider()

        # ---------- FIGURE 3: control chart (time series with event markers) ----------
        st.markdown("#### Chart 1 — The whole record, with the big events marked")
        st.caption(
            "Each dot is one satellite pass from 2023 to 2026. The top shows how high the "
            "water sat; the bottom shows how steeply the river dropped. If the typhoon had "
            "reshaped the river, you'd see the dots jump up or down at the dashed line and "
            "stay there. They don't — after the storm the river just goes back to its usual "
            "pattern."
        )
        fig_ts = make_subplots(
            rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.09,
            subplot_titles=("Water Surface Elevation at 15 km (m)",
                            "Hydraulic Gradient (cm/km)"),
        )
        for reach in REACH_ORDER:
            d = metrics[metrics["reach"] == reach].sort_values("date")
            color = COLOR_MAP.get(reach, "black")
            fig_ts.add_trace(go.Scatter(
                x=d["date"], y=d["wse_ref_m"], mode="markers", name=DISP[reach],
                legendgroup=reach, marker=dict(color=color, size=6, opacity=0.8),
                hovertemplate="%{x|%b %d, %Y}<br>WSE " + "%{y:.2f} m<extra></extra>",
            ), row=1, col=1)
            fig_ts.add_trace(go.Scatter(
                x=d["date"], y=d["slope_cm_km"], mode="markers", name=DISP[reach],
                legendgroup=reach, showlegend=False,
                marker=dict(color=color, size=6, opacity=0.8),
                hovertemplate="%{x|%b %d, %Y}<br>slope " + "%{y:.0f} cm/km<extra></extra>",
            ), row=2, col=1)
        # winter ice bands (no open-water data in the gated set) — explains the gaps
        for x0, x1 in [("2023-12-01", "2024-03-31"), ("2024-12-01", "2025-03-31"),
                       ("2025-12-01", "2026-03-31")]:
            fig_ts.add_vrect(x0=x0, x1=x1, fillcolor="lightsteelblue", opacity=0.25,
                             line_width=0, row="all")
        # typhoon landfall
        fig_ts.add_vline(x=method["typhoon_date"], line_dash="dash", line_color="black",
                         line_width=1.5, row="all")
        fig_ts.add_annotation(x=method["typhoon_date"], yref="paper", y=1.0,
                              text="Typhoon Halong", showarrow=False, xanchor="left",
                              font=dict(size=11, color="black"))
        fig_ts.update_layout(height=620, template=plotly_template,
                             legend=dict(orientation="h", yanchor="bottom", y=1.06))
        fig_ts.update_xaxes(title_text="Date", row=2, col=1)
        st.plotly_chart(fig_ts, width="stretch", theme=None)
        st.caption("The pale blue stripes are winter (Dec–Mar), when the rivers freeze and "
                   "the satellite can't get a clean water reading — so there are no dots "
                   "there. That's expected, not missing data.")
        st.divider()

        # ---------- FIGURE 1: stage-invariance scatter ----------
        st.markdown("#### Chart 2 — Steepness stays the same whether the water is high or low")
        st.caption(
            "Each dot is one satellite pass. On a lot of rivers the steepness changes a lot "
            "when the water rises or drops. Here the dots form a flat band — this river "
            "drops just as steeply at high water as at low water. That's why it's fair to "
            "combine passes from different seasons and years when we talk about steepness."
        )
        fig_si = go.Figure()
        corr_txt = []
        for reach in REACH_ORDER:
            d = metrics[metrics["reach"] == reach]
            color = COLOR_MAP.get(reach, "black")
            fig_si.add_trace(go.Scatter(
                x=d["wse_ref_m"], y=d["slope_cm_km"], mode="markers", name=DISP[reach],
                marker=dict(color=color, size=8, opacity=0.55),
                customdata=d["date"].dt.strftime("%b %d, %Y"),
                hovertemplate=(f"<b>{DISP[reach]}</b><br>Pass: %{{customdata}}<br>"
                               "WSE %{x:.2f} m<br>slope %{y:.0f} cm/km<extra></extra>"),
            ))
            med = float(d["slope_cm_km"].median())
            fig_si.add_hline(y=med, line_dash="dot", line_color=color, opacity=0.7)
            corr_txt.append(f"{DISP[reach]}: usually about {med:.0f} cm/km")
        fig_si.update_layout(
            height=460, template=plotly_template,
            xaxis_title="Water Surface Elevation at 15 km (m)",
            yaxis_title="Hydraulic Gradient (cm/km)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_si, width="stretch", theme=None)
        st.caption("The dotted line is each river's usual steepness.  " +
                   "  ·  ".join(corr_txt) +
                   ".  Because the bands are flat, the water level has almost no effect on "
                   "how steeply the river drops.")
        st.divider()

        # ---------- FIGURE 4: distribution swarms ----------
        st.markdown("#### Chart 3 — Why we say \"no real change\": the groups overlap")
        st.caption(
            "Each box shows the range of the individual passes, and the dots are the passes "
            "themselves. When two boxes cover the same ground, there's no real difference "
            "between them. This is the plain-language version of the \"no real change\" "
            "notes in the tables further down."
        )
        colA, colB = st.columns(2)
        with colA:
            mA = metrics[metrics["month"].isin([5, 7, 8])].copy()
            mA["season"] = np.where(mA["month"] == 5, "Spring (May)", "Late summer (Jul–Aug)")
            fig_sa = go.Figure()
            for reach in REACH_ORDER:
                d = mA[mA["reach"] == reach]
                fig_sa.add_trace(go.Box(
                    x=d["season"], y=d["slope_cm_km"], name=DISP[reach],
                    marker_color=COLOR_MAP.get(reach, "black"),
                    boxpoints="all", jitter=0.5, pointpos=0,
                ))
            fig_sa.update_layout(
                height=430, template=plotly_template, boxmode="group",
                title="Hydraulic Gradient: spring vs. late summer",
                yaxis_title="Hydraulic Gradient (cm/km)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            fig_sa.update_xaxes(categoryorder="array",
                                categoryarray=["Spring (May)", "Late summer (Jul–Aug)"])
            st.plotly_chart(fig_sa, width="stretch", theme=None)
        with colB:
            mB = metrics[(metrics["month"].isin([7, 8])) &
                         (metrics["year"].isin([2024, 2025]))].copy()
            mB["yr"] = mB["year"].astype(str)
            fig_sb = go.Figure()
            for reach in REACH_ORDER:
                d = mB[mB["reach"] == reach]
                fig_sb.add_trace(go.Box(
                    x=d["yr"], y=d["wse_ref_m"], name=DISP[reach],
                    marker_color=COLOR_MAP.get(reach, "black"),
                    boxpoints="all", jitter=0.5, pointpos=0, showlegend=False,
                ))
            fig_sb.update_layout(
                height=430, template=plotly_template, boxmode="group",
                title="Water Surface Elevation: 2024 vs. 2025 (late summer)",
                yaxis_title="Water Surface Elevation at 15 km (m)", xaxis_title="Year",
            )
            st.plotly_chart(fig_sb, width="stretch", theme=None)
        st.divider()

        # ---------- FIGURE 2: spatial delta (typhoon, interim) ----------
        st.markdown("#### Chart 4 — Did the typhoon change any spot along the river? (preliminary)")
        st.warning(
            "**Still preliminary.** This compares June 2025 with June 2026, and we only "
            "have 2–3 clean passes per river for those months. Treat it as a strong hint, "
            "not a final answer — we'll know for sure once the summer 2026 data comes in."
        )
        st.caption(
            "This line shows how much the water level changed at each point along the river "
            "(June 2026 compared with June 2025). If the storm had scoured out the riverbed "
            "or dumped a pile of gravel somewhere, you'd see a sharp spike or dip at that "
            "spot. The line mostly stays near zero; a few points reach about ±0.7 m, but "
            "that is within the year-to-year wiggle we see between storm-free summers too — "
            "nothing here stands out as a storm scar."
        )
        if len(q3_curve):
            fig_d = go.Figure()
            for reach in REACH_ORDER:
                d = q3_curve[q3_curve["reach"] == reach].sort_values("dist_km")
                if not len(d):
                    continue
                color = COLOR_MAP.get(reach, "black")
                fig_d.add_trace(go.Scatter(
                    x=d["dist_km"], y=d["dwse"], mode="lines+markers", name=DISP[reach],
                    marker=dict(color=color, size=5),
                    line=dict(color=color, width=1.5),
                    hovertemplate="%{x:.1f} km<br>ΔWSE %{y:+.2f} m<extra></extra>",
                ))
            fig_d.add_hline(y=0, line_color="black", line_width=1)
            add_bifurcation_line(fig_d, axis="x")
            fig_d.update_layout(
                height=440, template=plotly_template,
                xaxis_title="Distance from Anchor Point (km)",
                yaxis_title="Change in Water Surface Elevation, Jun 2026 − Jun 2025 (m)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            # Same convention as every other distance-axis figure:
            # coast (36 km) on the left, anchor (0 km) on the right.
            fig_d.update_xaxes(autorange="reversed")
            st.plotly_chart(fig_d, width="stretch", theme=None)
        else:
            st.info("Not enough matching June passes to draw this chart yet.")
        st.divider()

        # ---------- TABLES (secondary, in expanders) ----------
        st.markdown("#### The numbers behind the charts")
        st.caption("Open any section for the exact figures. Click a header to expand it.")

        with st.expander("Spring vs. late summer (May high water vs. Jul–Aug low water)"):
            rows = [{
                "River": DISP[r["reach"]], "Passes May": r["n_high"],
                "Passes Jul–Aug": r["n_low"],
                "Steepness May (cm/km)": round(r["slope_high"], 1),
                "Steepness Jul–Aug (cm/km)": round(r["slope_low"], 1),
                "Change (cm/km)": r["dslope_cm_km"],
                "p-value": _fmt_p(r["p_slope"], r.get("p_slope_holm")),
            } for r in results["Q1_seasonal"] if r["question"] == "Q1_slope_pooled"]
            st.markdown("**Steepness (all years combined — it doesn't change with season):**")
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            rows = [{
                "River": DISP[r["reach"]], "Year": r["year"],
                "Water level May (m)": round(r["wse_high"], 2),
                "Water level Jul–Aug (m)": round(r["wse_low"], 2),
                "Change (m)": r["dwse_m"],
                "p-value": _fmt_p(r["p_wse"], r.get("p_wse_holm")),
            } for r in results["Q1_seasonal"] if r["question"] == "Q1_wse_seasonal"]
            st.markdown("**Water level (shown per year — this is what rises and falls with flow):**")
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            st.caption("The water level goes up and down a little, and which season is "
                       "higher flips from year to year — that's ordinary flow variation, not "
                       "the river steadily changing. (A * marks a difference that is probably "
                       "not just chance. Because this page runs many comparisons at once, the "
                       "star is awarded only if the result stays convincing after a "
                       "Holm correction for multiple testing — the raw p-value is shown "
                       "either way.)")

        with st.expander("Year to year (summer 2024 vs. 2025 — the normal yardstick)"):
            rows = [{
                "River": DISP[r["reach"]],
                "Steepness 2024 (cm/km)": round(r["slope_2024"], 1),
                "Steepness 2025 (cm/km)": round(r["slope_2025"], 1),
                "Change (cm/km)": r["dslope_cm_km"],
                "p-value (steepness)": _fmt_p(r["p_slope"], r.get("p_slope_holm")),
                "Water level 2024 (m)": round(r["wse_2024"], 2),
                "Water level 2025 (m)": round(r["wse_2025"], 2),
                "Change (m)": r["dwse_m"],
                "p-value (level)": _fmt_p(r["p_wse"], r.get("p_wse_holm")),
            } for r in results["Q2_interannual"]]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            st.caption("Steepness is measured over the whole ice-free year; water level is "
                       "compared in the same season (late summer). Kanektok's water-level "
                       "change shows up as \"significant\" only because its readings are so "
                       "consistent — the change itself (about 0.2 m, roughly 8 inches) is far "
                       "too small to notice on the ground. A result can be statistically "
                       "\"significant\" and still be too tiny to matter.")

        with st.expander("Typhoon Halong (June 2025 vs. June 2026 — preliminary)"):
            rows = [{
                "River": DISP[r["reach"]], "Passes 2025": r["n_2025"],
                "Passes 2026": r["n_2026"],
                "Water level 2025 (m)": round(r["wse_2025"], 2),
                "Water level 2026 (m)": round(r["wse_2026"], 2),
                "Change (m)": r["dwse_m"], "Normal year-to-year change (m)": r["baseline_dwse_m"],
                "Within normal?": {"within": "yes", "exceeds": "exceeds",
                                   "indistinguishable": "too close to call"}.get(
                                      r["wse_vs_baseline"], r["wse_vs_baseline"]),
                "Steepness change (cm/km)": r["dslope_cm_km"],
                "p-value (level)": _fmt_p(r["p_wse"], r.get("p_wse_holm")),
            } for r in results["Q3_typhoon"]]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            rows = [{
                "River": DISP[r["reach"]], "Points compared": r["n_bins"],
                "Typical change (m)": r["median_dwse_m"],
                "Upper river (≤18 km)": r["upstream_dwse_m"],
                "Lower river (>18 km)": r["downstream_dwse_m"],
            } for r in results["Q3_profile"]]
            st.markdown("**Change at each point along the river:**")
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            st.caption("The change around the storm is no larger than an ordinary "
                       "year-to-year swing — with only a handful of matching passes the "
                       "comparison is honestly \"too close to call\" rather than a proven "
                       "\"no change,\" but nothing stands out, and the change is flat all "
                       "along the river — no upstream storm scar. Preliminary until the "
                       "summer 2026 (Jul–Aug) data comes in.")

        st.caption(
            f"**Where the numbers come from.** Satellite record {record['date_min']} – "
            f"{record['date_max']}; {record['n_passes_fit']} passes measured, and the "
            f"{record['n_full_coverage_open_water']} that caught the whole river in the "
            f"ice-free season were used here. Technical detail — steepness: "
            f"{method['slope_estimator']}; water level: {method['level_metric']}; "
            f"a pass qualifies with ≥{method['min_nodes']} points, spanning "
            f"≥{method['min_span_km']:.0f} km and starting within "
            f"{method['max_start_km']:.0f} km of the mouth, in months "
            f"{method['open_water_months']}. Generated by temporal_analysis.py."
        )

# --- SUMMARY STATS & DATA INFO (inside SWOT tab) ---
