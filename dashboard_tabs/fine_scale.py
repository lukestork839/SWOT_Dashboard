"""Fine-Scale Slope tab: per-pass fine-resolution slope matrix and window stats."""
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from .common import (COLOR_MAP, FINE_GROUP_MODES, FINE_MAX_PERIOD_LINES,
                     FINE_MIN_COVERAGE, FINE_RES_KM, FINE_WINDOW_KM, FINE_XMAX_KM,
                     REMOTE_PARQUET_URL, _fine_aggregate, _fine_group_passes,
                     _fine_window_coverage, _fine_window_slope,
                     add_bifurcation_line, compute_finescale_pass_matrix)


def render(ctx):
    con = ctx.con
    plotly_template = ctx.plotly_template
    selected_reaches = ctx.selected_reaches
    where_clause = ctx.where_clause

    st.subheader("🔬 Fine-Scale Slope Profile")
    st.markdown(
        "The steepness of the water surface at **backwater scale**, instead of one "
        "smoothed average. Slope is computed *within each satellite pass* (so river "
        "stage is held constant), then the **median across passes** is shown with a "
        "shaded pass-to-pass band. This resolves ~0.5 km structure near the "
        "bifurcation that the standard Slope Profile tab blurs away."
    )
    st.caption(f"Fixed at **{FINE_RES_KM} km** resolution (the backwater length scale) "
               f"over the first **{FINE_XMAX_KM:.0f} km** (tidal mouth trimmed) — the same "
               "settings as thesis Figure 9.")

    @st.fragment
    def render_finescale():
        res_km, xmax = FINE_RES_KM, FINE_XMAX_KM

        view = st.radio(
            "View", ["Aggregate profile", "Compare periods", "Slope over time"],
            horizontal=True, key="fine_view",
            help="**Aggregate** pools every selected pass into one profile. "
                 "**Compare periods** draws one profile per year / season / month, so you "
                 "can see whether the fine-scale shape itself moves. **Slope over time** "
                 "condenses a chosen reach window to one number per pass and plots it "
                 "against date.")

        with st.spinner("Computing per-pass slopes…"):
            pdata = compute_finescale_pass_matrix(
                con, st.session_state.get("data_version", REMOTE_PARQUET_URL),
                where_clause, float(res_km), float(xmax))

        if not pdata:
            st.warning("No data available for the selected filters.")
            return
        data = {reach: dict(grid=r["grid"], n_passes=r["n_passes"],
                            **dict(zip(("med", "lo", "hi", "n"),
                                       _fine_aggregate(r["mat"]))))
                for reach, r in pdata.items()}

        # Guard: this per-pass-then-aggregate method needs many overlapping passes.
        # With only a handful (e.g. the welcome-page quick-start, which loads just the
        # most-recent passes), the n>=3 display gate starves -- the profile degrades
        # into straight-line interpolation across dropped bins. That is a SELECTION
        # artifact, not real slope structure.
        MIN_PASSES_RELIABLE = 10
        pass_counts = {r: data[r]["n_passes"] for r in selected_reaches if r in data}
        if pass_counts and min(pass_counts.values()) < MIN_PASSES_RELIABLE:
            worst = ", ".join(f"{r.replace('_', ' ')}: {n} pass{'es' if n != 1 else ''}"
                              for r, n in pass_counts.items())
            st.warning(
                f"⚠️ **Too few passes for a reliable fine-scale slope** ({worst}). "
                "This method aggregates a slope computed *within each pass*, so it needs "
                "many overlapping passes; with only a handful the profile breaks into "
                "interpolated straight segments — a selection artifact, not real "
                "structure. Return to the homepage and select the **full pass record** "
                "(not the quick-start subset) for a trustworthy result."
            )

        reaches = [r for r in selected_reaches if r in pdata]
        if not reaches:
            st.warning("No data available for the selected rivers.")
            return

        # ================= VIEW 1: aggregate profile (all passes pooled) =====
        if view == "Aggregate profile":
            zoom = st.checkbox("Zoom to the bifurcation region (0–8 km)", value=False,
                               key="fine_zoom")
            fig_fine = go.Figure()
            near_rows = []
            for reach in reaches:
                r = data[reach]
                grid, med, lo, hi, n = r["grid"], r["med"], r["lo"], r["hi"], r["n"]
                core = n >= 3  # only trust bins imaged by >= 3 passes
                if not core.any():
                    continue
                color = COLOR_MAP.get(reach, "black")
                rr, gg, bb, _ = mcolors.to_rgba(color)
                fill = f"rgba({int(rr*255)},{int(gg*255)},{int(bb*255)},0.15)"

                # IQR band (across passes)
                fig_fine.add_trace(go.Scatter(
                    x=np.concatenate([grid[core], grid[core][::-1]]),
                    y=np.concatenate([hi[core], lo[core][::-1]]),
                    fill="toself", fillcolor=fill, line=dict(width=0),
                    name=f"{reach} IQR", showlegend=False, hoverinfo="skip"))
                # median line
                fig_fine.add_trace(go.Scatter(
                    x=grid[core], y=med[core], mode="lines",
                    line=dict(color=color, width=3),
                    name=f"{reach} ({r['n_passes']} passes)",
                    hovertemplate="<b>" + reach + "</b><br>Distance: %{x:.2f} km<br>"
                                  "Slope: %{y:.1f} cm/km<extra></extra>"))

                nb = core & (grid >= 1.0) & (grid <= 5.0)
                near_rows.append({
                    "River": reach,
                    "Near-bifurcation slope (1–5 km)": float(np.nanmedian(med[nb])) if nb.any() else np.nan,
                    "Passes": int(r["n_passes"]),
                })

            add_bifurcation_line(fig_fine)
            fig_fine.update_layout(
                xaxis_title="Distance from Anchor Point (km)",
                yaxis_title="Interval Slope (cm/km)",
                height=600, template=plotly_template, hovermode="x unified",
                showlegend=True)
            fig_fine.update_xaxes(autorange="reversed")
            if zoom:
                fig_fine.update_xaxes(range=[8, 0])  # reversed axis: [max, min]

            st.plotly_chart(fig_fine, width="stretch", theme=None)

            # Near-bifurcation contrast (the headline of the re-analysis)
            if len(near_rows) == 2 and all(np.isfinite(x["Near-bifurcation slope (1–5 km)"]) for x in near_rows):
                k = next((x for x in near_rows if x["River"] == "Kanektok_River"), None)
                u = next((x for x in near_rows if x["River"] == "Uyak_Creek"), None)
                if k and u:
                    adv = k["Near-bifurcation slope (1–5 km)"] - u["Near-bifurcation slope (1–5 km)"]
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Kanektok @ bifurcation (1–5 km)",
                              f"{k['Near-bifurcation slope (1–5 km)']:.0f} cm/km")
                    m2.metric("Uyak @ bifurcation (1–5 km)",
                              f"{u['Near-bifurcation slope (1–5 km)']:.0f} cm/km")
                    m3.metric("Kanektok advantage here", f"{adv:+.0f} cm/km",
                              help="Reach-averaged, the two gradients differ by only ~3.6 cm/km; "
                                   "near the bifurcation the local advantage is far larger.")

        # ================= VIEWS 2 & 3: temporal ============================
        # The window and the coverage gate are fixed (see FINE_WINDOW_KM /
        # FINE_MIN_COVERAGE); grouping is the only thing left to choose, because it
        # is the actual question -- year vs season vs month.
        else:
            window, min_cov = FINE_WINDOW_KM, FINE_MIN_COVERAGE
            group_mode = st.selectbox(
                "Group by", FINE_GROUP_MODES, index=0, key="fine_group",
                help="How passes are bundled into periods. Seasons are the flow regimes "
                     "used in the repo's temporal analysis (freshet = May, baseflow = "
                     "Jul–Aug, shoulder = Apr/Jun/Sep–Nov).")

            # --- pass-quality gate ---
            gate, kept_note = {}, []
            for reach in reaches:
                r = pdata[reach]
                cov = _fine_window_coverage(r["mat"], r["grid"], window)
                gate[reach] = cov >= min_cov
                kept_note.append(f"{reach.replace('_', ' ')}: "
                                 f"**{int(gate[reach].sum())}** of {len(cov)}")
            st.caption(f"Slope measured over **{window[0]:.0f}–{window[1]:.0f} km** "
                       f"(the bifurcation zone), using passes that imaged ≥ {min_cov:.0%} "
                       f"of it — " + " · ".join(kept_note))
            if not any(gate[r].any() for r in reaches):
                st.warning("No selected pass covers enough of the bifurcation zone to give "
                           "a fine-scale slope. Return to the homepage and select more "
                           "passes.")
                return

            # ---------- VIEW 2: one profile per period ----------
            if view == "Compare periods":
                zoom_cmp = st.checkbox("Zoom to the bifurcation region (0–8 km)",
                                       value=False, key="fine_zoom_cmp")
                fig_cmp = make_subplots(
                    rows=len(reaches), cols=1, shared_xaxes=True, vertical_spacing=0.09,
                    subplot_titles=[r.replace("_", " ") for r in reaches])
                summary, period_order, capped = [], [], False
                for row, reach in enumerate(reaches, start=1):
                    r = pdata[reach]
                    grid, keep = r["grid"], gate[reach]
                    groups = [(lab, idx[keep[idx]])
                              for lab, idx in _fine_group_passes(r["passes"], group_mode)]
                    groups = [(lab, idx) for lab, idx in groups if len(idx)]
                    if len(groups) > FINE_MAX_PERIOD_LINES:
                        groups, capped = groups[-FINE_MAX_PERIOD_LINES:], True
                    wsl = _fine_window_slope(r["mat"], grid, window)
                    for gi, (lab, idx) in enumerate(groups):
                        if lab not in period_order:
                            period_order.append(lab)
                        shade = gi / max(len(groups) - 1, 1)
                        cr, cg, cb, _ = cm.viridis(0.12 + 0.76 * shade)
                        # Hold each period to the same >=3-pass support as the aggregate
                        # view, except where the period simply cannot supply three.
                        med, _, _, _ = _fine_aggregate(r["mat"], idx,
                                                       min_passes=min(3, len(idx)))
                        ok = np.isfinite(med)
                        if not ok.any():
                            continue
                        fig_cmp.add_trace(go.Scatter(
                            x=grid[ok], y=med[ok], mode="lines",
                            line=dict(color=f"rgb({int(cr*255)},{int(cg*255)},{int(cb*255)})",
                                      width=2),
                            legendgroup=lab, name=f"{lab} ({len(idx)})",
                            showlegend=(row == 1),
                            hovertemplate=f"<b>{lab}</b><br>Distance: %{{x:.2f}} km<br>"
                                          "Slope: %{y:.1f} cm/km<extra></extra>"),
                            row=row, col=1)
                        summary.append({
                            "Period": lab, "River": reach.split("_")[0],
                            "slope": float(np.nanmedian(wsl[idx])), "n": int(len(idx))})
                if capped:
                    st.info(f"Showing the most recent {FINE_MAX_PERIOD_LINES} periods — "
                            "choose a coarser *Group by* to see the whole record.")
                add_bifurcation_line(fig_cmp)
                fig_cmp.update_layout(height=330 * len(reaches), template=plotly_template,
                                      hovermode="x unified", legend_title_text=group_mode)
                fig_cmp.update_xaxes(autorange="reversed")
                if zoom_cmp:
                    fig_cmp.update_xaxes(range=[8, 0])
                fig_cmp.update_xaxes(title_text="Distance from Anchor Point (km)",
                                     row=len(reaches), col=1)
                fig_cmp.update_yaxes(title_text="Interval Slope (cm/km)")
                st.plotly_chart(fig_cmp, width="stretch", theme=None)

                if summary:
                    sdf = pd.DataFrame(summary)
                    rows_out = []
                    for lab in period_order:
                        out = {"Period": lab}
                        sub = sdf[sdf["Period"] == lab].set_index("River")
                        for river in sdf["River"].unique():
                            out[f"{river} (cm/km)"] = (round(sub.loc[river, "slope"], 1)
                                                       if river in sub.index else np.nan)
                            out[f"{river} n"] = (int(sub.loc[river, "n"])
                                                 if river in sub.index else 0)
                        if {"Kanektok", "Uyak"} <= set(sub.index):
                            out["Advantage (cm/km)"] = round(
                                sub.loc["Kanektok", "slope"] - sub.loc["Uyak", "slope"], 1)
                        rows_out.append(out)
                    st.markdown(f"**Median slope in the {window[0]:.0f}–{window[1]:.0f} km "
                                f"bifurcation zone, by {group_mode.lower()}**")
                    st.dataframe(pd.DataFrame(rows_out), width="stretch", hide_index=True)

            # ---------- VIEW 3: window slope as a time series ----------
            else:
                fig_ts = make_subplots(
                    rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.11,
                    subplot_titles=(
                        f"Slope in the {window[0]:.0f}–{window[1]:.0f} km bifurcation "
                        "zone, per pass",
                        "Kanektok − Uyak advantage (paired within date)"))
                series = {}
                for reach in reaches:
                    r = pdata[reach]
                    wsl = _fine_window_slope(r["mat"], r["grid"], window)
                    ok = gate[reach] & np.isfinite(wsl)
                    if not ok.any():
                        continue
                    s = pd.Series(wsl[ok],
                                  index=pd.to_datetime(r["passes"])[ok]).sort_index()
                    series[reach] = s
                    label = reach.replace("_", " ")
                    fig_ts.add_trace(go.Scatter(
                        x=s.index, y=s.values, mode="markers+lines", marker=dict(size=5),
                        line=dict(color=COLOR_MAP.get(reach, "black"), width=1),
                        name=f"{label} ({len(s)} passes)",
                        hovertemplate=f"<b>{label}</b><br>%{{x|%Y-%m-%d}}<br>"
                                      "Slope: %{y:.0f} cm/km<extra></extra>"),
                        row=1, col=1)

                # Pairing within date is what removes stage: a single overpass images
                # both channels at the same instant, so the difference is geometry.
                adv = None
                if "Kanektok_River" in series and "Uyak_Creek" in series:
                    adv = (series["Kanektok_River"] - series["Uyak_Creek"]).dropna()
                if adv is not None and len(adv):
                    fig_ts.add_trace(go.Scatter(
                        x=adv.index, y=adv.values, mode="markers+lines",
                        marker=dict(size=5), line=dict(color="darkgreen", width=1),
                        name="Kanektok − Uyak", showlegend=False,
                        hovertemplate="%{x|%Y-%m-%d}<br>Advantage: %{y:+.0f} cm/km"
                                      "<extra></extra>"),
                        row=2, col=1)
                    fig_ts.add_hline(y=0, line_color="gray", line_width=1, row=2, col=1)
                    fig_ts.add_hline(
                        y=float(adv.median()), line_dash="dot", line_color="darkgreen",
                        line_width=1.5, row=2, col=1,
                        annotation_text=f"median {adv.median():+.0f} cm/km",
                        annotation_position="top left", annotation_font_size=10,
                        annotation_font_color="darkgreen")
                fig_ts.update_layout(height=700, template=plotly_template,
                                     hovermode="x unified")
                fig_ts.update_yaxes(title_text="Interval Slope (cm/km)", row=1, col=1)
                fig_ts.update_yaxes(title_text="Δ Slope (cm/km)", row=2, col=1)
                fig_ts.update_xaxes(title_text="Pass date", row=2, col=1)
                st.plotly_chart(fig_ts, width="stretch", theme=None)

                if adv is not None and len(adv):
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Median advantage", f"{adv.median():+.0f} cm/km",
                              help="Kanektok minus Uyak, median over paired passes.")
                    m2.metric("Passes with Kanektok steeper",
                              f"{int((adv > 0).sum())} / {len(adv)}")
                    m3.metric("Pass-to-pass spread (IQR)",
                              f"{adv.quantile(0.75) - adv.quantile(0.25):.0f} cm/km",
                              help="How much the advantage swings between passes. If this "
                                   "dwarfs the median, the advantage is a tendency rather "
                                   "than a persistent separation.")

                # Period summary: does the window slope move with season or year?
                if series:
                    all_dates = np.concatenate([s.index.to_numpy() for s in series.values()])
                    order = [lab for lab, _ in _fine_group_passes(all_dates, group_mode)]
                    grp = {reach: dict(_fine_group_passes(s.index.to_numpy(), group_mode))
                           for reach, s in series.items()}
                    adv_grp = (dict(_fine_group_passes(adv.index.to_numpy(), group_mode))
                               if adv is not None and len(adv) else {})
                    rows_out = []
                    for lab in order:
                        out = {"Period": lab}
                        for reach, s in series.items():
                            idx = grp[reach].get(lab)
                            river = reach.split("_")[0]
                            out[f"{river} (cm/km)"] = (round(float(np.median(s.values[idx])), 1)
                                                       if idx is not None and len(idx) else np.nan)
                            out[f"{river} n"] = int(len(idx)) if idx is not None else 0
                        if lab in adv_grp:
                            out["Advantage (cm/km)"] = round(
                                float(np.median(adv.values[adv_grp[lab]])), 1)
                        rows_out.append(out)
                    st.markdown(f"**Median bifurcation-zone slope by "
                                f"{group_mode.lower()}**")
                    st.dataframe(pd.DataFrame(rows_out), width="stretch", hide_index=True)

        # ---------------- shared explainer ----------------
        with st.expander("How to read this graph"):
            st.markdown("""
            **What this shows:** the water-surface steepness *along* the river at fine
            resolution — the higher the line, the steeper the water there.

            - Each satellite pass is fit to its own local slope (stage held constant),
              then we plot the **median across passes** (solid line) and the
              **25–75% pass-to-pass band** (shading).
            - The dashed line marks the **bifurcation** (2.5 km). The whole point of the
              re-analysis is to see the slope *right there*, which the standard Slope
              Profile tab's 2 km smoothing (≈ 4.7 km effective resolution) blurs out.

            **The three views**
            - *Aggregate profile* — every selected pass pooled into one profile.
            - *Compare periods* — the same profile drawn once per year / season / month,
              so you can see whether the fine-scale **shape** shifts over time.
            - *Slope over time* — the **1–5 km bifurcation zone** condensed to one slope
              per pass and plotted against date, with the Kanektok−Uyak advantage paired
              within each date (one overpass images both channels at once, so pairing
              cancels stage).

            **Why some passes are excluded.** A pass only yields a fine-scale slope where
            it actually imaged the river. A pass that clipped the edge of the zone would
            otherwise contribute a slope fit to a sliver of it, which reads as wild
            scatter in the time series. So passes imaging less than **80 %** of the
            1–5 km zone are dropped — this is the fine-scale analogue of the reference
            gradient's span/start gate, and it excludes far more Uyak passes than
            Kanektok ones. The counts above the chart show exactly how many survived.
            Seasons are the flow regimes used in the repo's temporal analysis
            (freshet = May, baseflow = Jul–Aug).

            ― Technical details ―
            WSE binned to 100 m medians per pass (≥ 30 pixels/bin); slope via a robust
            sliding **Theil–Sen** fit over a **0.5 km** window — the backwater length
            scale, and the same resolution as thesis Figure 9; median + IQR aggregated
            across passes; bins with < 3 passes hidden. A pass's *window slope* is the
            median of its local slopes inside the window, so the time series and the
            profile always agree. The reach is cut at **34 km** to drop the tidal mouth,
            which sits far downstream of the bifurcation.
            """)

    render_finescale()
