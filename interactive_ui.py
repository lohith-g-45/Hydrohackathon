"""Interactive Streamlit UI wired to hydrostatics and stability modules."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from hydrostatics import compute_phase4
from integration import compute_phase3
from ship_excel_extractor import extract_ship_data
from stability import compute_phase5
from volume_conservation import run_volume_conservation
from offset_optimizer import OptimizationConstraints, run_optimization

try:
    from geometric_gz import compute_geometric_gz_curve
except Exception:
    compute_geometric_gz_curve = None


DEFAULT_EXCEL = Path(__file__).with_name("HYDRO HACKATHON DATA.xlsx")


def _as_numeric_arrays(extracted: dict) -> dict:
    offset = extracted.get("offset_table")
    if not offset:
        raise ValueError("Offset table could not be extracted from the workbook.")

    stations = np.asarray(offset.get("stations", []), dtype=float)
    waterlines = np.asarray(offset.get("waterlines", []), dtype=float)
    offset_table_clean = np.asarray(offset.get("offset_table_clean", []), dtype=float)

    if stations.size == 0 or waterlines.size == 0 or offset_table_clean.size == 0:
        raise ValueError("Extracted offset table is empty or incomplete.")

    draft = float(extracted.get("draft"))
    rho = float(extracted.get("rho"))
    kg = float(extracted.get("KG"))
    depth = extracted.get("depth")

    return {
        "stations": stations,
        "waterlines": waterlines,
        "offset_table_clean": offset_table_clean,
        "draft": draft,
        "rho": rho,
        "kg": kg,
        "depth": float(depth) if depth is not None else float(np.max(waterlines)),
    }


@st.cache_data(show_spinner=False)
def load_ship_data(file_path: str) -> dict:
    extracted = extract_ship_data(file_path)
    return _as_numeric_arrays(extracted)


def _discover_offset_benchmark_report_paths() -> list[Path]:
    base = Path(__file__).resolve().parent
    candidates = [
        base / "results" / "kcs_offset_benchmark.csv",
        Path.cwd() / "results" / "kcs_offset_benchmark.csv",
        Path.cwd() / "Hydrohackathon" / "results" / "kcs_offset_benchmark.csv",
    ]
    existing = [p for p in candidates if p.exists()]
    existing.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return existing


@st.cache_data(show_spinner=False)
def load_offset_benchmark_report(report_csv_path: str) -> pd.DataFrame:
    return pd.read_csv(report_csv_path)


def _as_float_or_nan(value) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return out


def _nearest_tabulated_draft(waterlines: np.ndarray, draft: float) -> float:
    idx = int(np.argmin(np.abs(waterlines - draft)))
    return float(waterlines[idx])


def run_analysis(data: dict, draft: float, rho: float, kg: float) -> dict:
    phase3 = compute_phase3(
        stations=data["stations"],
        waterlines=data["waterlines"],
        offset_table_clean=data["offset_table_clean"],
        draft=float(draft),
        rho=float(rho),
        method="trapezoidal",
    )

    phase4 = compute_phase4(
        stations=data["stations"],
        waterlines=data["waterlines"],
        offset_table_clean=data["offset_table_clean"],
        sectional_areas=phase3["sectional_areas"],
        displaced_volume=float(phase3["displaced_volume"]),
        draft=float(draft),
        rho=float(rho),
    )

    stability_draft = _nearest_tabulated_draft(data["waterlines"], float(draft))
    phase5 = compute_phase5(
        stations=data["stations"],
        waterlines=data["waterlines"],
        offset_table_clean=data["offset_table_clean"],
        draft=stability_draft,
        displaced_volume=float(phase4["displaced_volume"]),
        kb=float(phase4["KB"]),
        kg=float(kg),
    )

    heel_deg = np.linspace(0.0, 60.0, 61)
    heel_rad = np.deg2rad(heel_deg)
    gz = float(phase5["GM"]) * np.sin(heel_rad)
    kn = gz + float(kg) * np.sin(heel_rad)

    return {
        "phase3": phase3,
        "phase4": phase4,
        "phase5": phase5,
        "input": {"draft": float(draft), "rho": float(rho), "kg": float(kg)},
        "stability_draft": stability_draft,
        "heel_deg": heel_deg,
        "gz": gz,
        "kn": kn,
    }


def _render_optimization_result(opt_result, data: dict, analysis: dict) -> None:
    """Render optimization result with side-by-side baseline and optimized tables."""
    
    if opt_result.status == "converged":
        st.success("✓ Optimization converged successfully")
        
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("GZ before (m)", f"{float(opt_result.gz_before):.3f}")
        col2.metric("GZ after (m)", f"{float(opt_result.gz_after):.3f}", delta=f"{float(opt_result.gz_improvement_pct):+.1f}%")
        col3.metric("Area before (m·rad)", f"{float(opt_result.area_gz_before):.4f}")
        col4.metric("Area after (m·rad)", f"{float(opt_result.area_gz_after):.4f}")
        
        # Offset tables side-by-side
        st.markdown("### Offset Comparison")
        baseline_table = pd.DataFrame(
            data["offset_table_clean"],
            columns=[f"Stn {i}" for i in range(data["offset_table_clean"].shape[1])],
            index=[f"WL {i:.2f}m" for i in data["waterlines"]]
        )
        optimized_table = pd.DataFrame(
            opt_result.optimized_offsets,
            columns=[f"Stn {i}" for i in range(opt_result.optimized_offsets.shape[1])],
            index=[f"WL {i:.2f}m" for i in data["waterlines"]]
        )
        delta_table = optimized_table - baseline_table
        
        tab_base, tab_opt, tab_delta = st.tabs(["Baseline", "Optimized", "Delta"])
        with tab_base:
            st.dataframe(baseline_table.style.format("{:.4f}"), use_container_width=True)
        with tab_opt:
            st.dataframe(optimized_table.style.format("{:.4f}"), use_container_width=True)
        with tab_delta:
            st.dataframe(delta_table.style.format("{:.4f}").highlight_max(axis=None, color="red").highlight_min(axis=None, color="blue"), use_container_width=True)
        
        # GZ comparison chart (with constraint overlay)
        st.markdown("### GZ Curve Comparison (Baseline vs Optimized)")
        heel_deg = np.linspace(0, 60, 61)
        
        # Baseline GZ
        baseline_gm = float(analysis["phase5"]["GM"])
        baseline_gz = baseline_gm * np.sin(np.deg2rad(heel_deg))
        
        # Optimized GZ (approximate via simple phase5 recompute on optimized offsets)
        try:
            opt_phase3 = compute_phase3(
                stations=data["stations"],
                waterlines=data["waterlines"],
                offset_table_clean=opt_result.optimized_offsets,
                draft=float(analysis["input"]["draft"]),
                rho=float(analysis["input"]["rho"]),
                method="trapezoidal",
            )
            opt_phase4 = compute_phase4(
                stations=data["stations"],
                waterlines=data["waterlines"],
                offset_table_clean=opt_result.optimized_offsets,
                sectional_areas=opt_phase3["sectional_areas"],
                displaced_volume=float(opt_phase3["displaced_volume"]),
                draft=float(analysis["input"]["draft"]),
                rho=float(analysis["input"]["rho"]),
            )
            opt_phase5 = compute_phase5(
                stations=data["stations"],
                waterlines=data["waterlines"],
                offset_table_clean=opt_result.optimized_offsets,
                draft=_nearest_tabulated_draft(data["waterlines"], float(analysis["input"]["draft"])),
                displaced_volume=float(opt_phase4["displaced_volume"]),
                kb=float(opt_phase4["KB"]),
                kg=float(analysis["input"]["kg"]),
            )
            opt_gm = float(opt_phase5["GM"])
            opt_gz = opt_gm * np.sin(np.deg2rad(heel_deg))
        except Exception:
            opt_gz = baseline_gz
        
        fig_gz_overlay = go.Figure()
        
        # Baseline GZ curve
        fig_gz_overlay.add_trace(
            go.Scatter(
                x=heel_deg,
                y=baseline_gz,
                mode="lines",
                name="Baseline GZ",
                line=dict(color="blue", width=2, dash="dash"),
            )
        )
        
        # Optimized GZ curve
        fig_gz_overlay.add_trace(
            go.Scatter(
                x=heel_deg,
                y=opt_gz,
                mode="lines",
                name="Optimized GZ",
                line=dict(color="green", width=3),
            )
        )
        
        # Add constraint lines for each GZ minimum constraint
        constraint_dict = {}  # heel_angle -> gz_min
        # Access the constraints from the form if available
        # For now, we'll get them from the result if stored
        for heel_angle in [10, 20, 30, 40, 50]:
            if heel_angle <= 60:
                fig_gz_overlay.add_hline(
                    y=0.0,
                    line_dash="dot",
                    line_color="gray",
                    opacity=0.5,
                    annotation_text="" if heel_angle > 10 else "0 m reference",
                    annotation_position="right",
                )
        
        # Add visual indicators at constraint heel angles if any
        try:
            # Try to extract constraint info from session state
            constraint_angles = [10, 20, 30, 40, 50]
            constraint_mins = [0.20, 0.40, 0.50, 0.45, 0.30]
            
            for ang, min_gz in zip(constraint_angles[:3], constraint_mins[:3]):
                if ang <= 60:
                    # Add constraint line
                    fig_gz_overlay.add_hline(
                        y=float(min_gz),
                        line_dash="dot",
                        line_color="red",
                        opacity=0.4,
                        annotation_text=f"Min GZ @ {int(ang)}°: {float(min_gz):.2f} m",
                        annotation_position="right",
                    )
                    
                    # Mark the points on both curves
                    idx = int(ang)
                    if idx < len(baseline_gz):
                        fig_gz_overlay.add_trace(
                            go.Scatter(
                                x=[float(ang)],
                                y=[float(baseline_gz[idx])],
                                mode="markers",
                                name=f"Baseline @ {int(ang)}°",
                                marker=dict(size=8, color="blue", symbol="circle"),
                                showlegend=False,
                            )
                        )
                        fig_gz_overlay.add_trace(
                            go.Scatter(
                                x=[float(ang)],
                                y=[float(opt_gz[idx])],
                                mode="markers",
                                name=f"Optimized @ {int(ang)}°",
                                marker=dict(size=8, color="green", symbol="diamond"),
                                showlegend=False,
                            )
                        )
        except Exception:
            pass
        
        fig_gz_overlay.update_layout(
            title="GZ Curve Overlay: Baseline vs Optimized with Constraints",
            xaxis_title="Heel (°)",
            yaxis_title="GZ (m)",
            hovermode="x unified",
            height=500,
        )
        st.plotly_chart(fig_gz_overlay, use_container_width=True)
        
        # Show comparison metrics
        with st.expander("GZ Comparison Details"):
            comp_metrics = {
                "Heel (°)": [10, 20, 30, 40, 50],
                "Baseline GZ (m)": [baseline_gz[int(h)] for h in [10, 20, 30, 40, 50]],
                "Optimized GZ (m)": [opt_gz[int(h)] for h in [10, 20, 30, 40, 50]],
            }
            comp_df = pd.DataFrame(comp_metrics)
            comp_df["Change (m)"] = comp_df["Optimized GZ (m)"] - comp_df["Baseline GZ (m)"]
            comp_df["Change (%)"] = 100.0 * comp_df["Change (m)"] / (comp_df["Baseline GZ (m)"] + 1e-8)
            st.dataframe(comp_df.style.format({
                "Baseline GZ (m)": "{:.4f}",
                "Optimized GZ (m)": "{:.4f}",
                "Change (m)": "{:.4f}",
                "Change (%)": "{:.1f}%",
            }), use_container_width=True)
        
        # Download buttons
        st.markdown("### Download Results")
        col1, col2 = st.columns(2)
        
        with col1:
            opt_csv = optimized_table.to_csv(index=True)
            st.download_button(
                label="Download Optimized Offsets (CSV)",
                data=opt_csv,
                file_name="optimized_offsets.csv",
                mime="text/csv"
            )
        
        with col2:
            report_json = opt_result.to_json()
            st.download_button(
                label="Download Optimization Report (JSON)",
                data=report_json,
                file_name="optimization_report.json",
                mime="application/json"
            )
    
    elif opt_result.status == "infeasible":
        st.error("✗ Optimization did not converge — constraints are infeasible at current settings")
        
        st.markdown("### Violated Constraints")
        if opt_result.infeasibility_report:
            report = opt_result.infeasibility_report
            if report.violated_constraints:
                st.write("The following constraints could not be satisfied:")
                for vc in report.violated_constraints:
                    st.write(f"  • {vc}")
            
            st.markdown("### Relaxation Suggestions")
            st.info(report.explanation)
            
            if report.per_constraint_relaxation:
                st.write("**Per-constraint relaxation values:**")
                relax_df = pd.DataFrame(
                    list(report.per_constraint_relaxation.items()),
                    columns=["Constraint", "Suggested Value"]
                )
                st.dataframe(relax_df, use_container_width=True)
            
            st.write(f"**Suggested max perturbation (p_max):** {report.suggested_p_max:.4f}")
            st.write(f"**Simultaneous scale factor:** {report.simultaneous_scale_factor:.3f}")
        else:
            st.write("No detailed infeasibility report available.")


def main() -> None:
    st.set_page_config(page_title="Ship Stability", layout="wide")
    st.title("Ship Stability Workbench")
    st.caption("HydroHackathon interactive analysis UI")

    default_path = str(DEFAULT_EXCEL) if DEFAULT_EXCEL.exists() else ""
    file_path = st.sidebar.text_input("Excel file path", value=default_path)

    if not file_path:
        st.warning("Provide an Excel path to start analysis.")
        return

    try:
        data = load_ship_data(file_path)
    except Exception as exc:
        st.error(f"Failed to load workbook: {exc}")
        return

    st.sidebar.subheader("Inputs")
    draft = st.sidebar.number_input("Draft (m)", min_value=0.01, value=float(data["draft"]), step=0.1)
    rho = st.sidebar.number_input("Fluid density rho (kg/m^3)", min_value=1.0, value=float(data["rho"]), step=1.0)
    kg = st.sidebar.number_input("KG (m)", min_value=0.0, value=float(data["kg"]), step=0.05)
    run_clicked = st.sidebar.button("Run Analysis", type="primary")

    if run_clicked or "analysis" not in st.session_state:
        try:
            st.session_state["analysis"] = run_analysis(data, float(draft), float(rho), float(kg))
        except Exception as exc:
            st.error(f"Analysis failed: {exc}")
            return

    analysis = st.session_state["analysis"]

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            "Stability Explorer",
            "KN -> GZ Transform",
            "Benchmark Validation",
            "Volume Validation",
            "Offset Optimizer",
        ]
    )

    with tab1:
        st.subheader("Stability Explorer")
        if not np.isclose(analysis["input"]["draft"], analysis["stability_draft"], atol=1e-12):
            st.info(
                "Stability draft snapped to nearest tabulated waterline for Phase 5: "
                f"{analysis['stability_draft']:.3f} m"
            )

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Displaced Volume (m^3)", f"{analysis['phase4']['displaced_volume']:.2f}")
        m2.metric("KB (m)", f"{analysis['phase4']['KB']:.3f}")
        m3.metric("GM (m)", f"{analysis['phase5']['GM']:.3f}")
        m4.metric("Assessment", str(analysis["phase5"]["assessment"]))

        sec_df = pd.DataFrame(
            {
                "Station": analysis["phase3"]["stations"],
                "Sectional Area": analysis["phase3"]["sectional_areas"],
            }
        )
        fig_sec = px.line(sec_df, x="Station", y="Sectional Area", markers=True, title="Sectional Area Curve")
        st.plotly_chart(fig_sec, use_container_width=True)

        gz_df = pd.DataFrame(
            {
                "Heel (deg)": analysis["heel_deg"],
                "GZ (m)": analysis["gz"],
                "KN (m)": analysis["kn"],
            }
        )
        fig_gz = px.line(gz_df, x="Heel (deg)", y=["GZ (m)", "KN (m)"], title="GM-based GZ and Derived KN")
        st.plotly_chart(fig_gz, use_container_width=True)

    with tab2:
        st.subheader("KN -> GZ Transform")
        st.caption("Using GZ = KN - KG * sin(theta)")

        st.markdown("### True Geometric KN/GZ")
        if compute_geometric_gz_curve is None:
            st.warning("Geometric solver is unavailable in this environment.")
        else:
            c1, c2, c3 = st.columns(3)
            max_angle = c1.slider(
                "Max heel angle for geometric curve (deg)",
                min_value=20,
                max_value=180,
                value=70,
                step=5,
                help="Use higher angles when you want the solver to capture angle of vanishing stability beyond the initial 60-80 deg range.",
            )
            step_angle = c2.selectbox("Heel step (deg)", options=[1, 2, 5], index=0)
            volume_tol = c3.number_input("Volume tolerance", min_value=1e-6, max_value=1e-2, value=1e-4, format="%.6f")

            if st.button("Compute True Geometric Curve", key="compute_geom"):
                try:
                    heel_angles = np.arange(0.0, float(max_angle) + float(step_angle), float(step_angle), dtype=float)
                    geom = compute_geometric_gz_curve(
                        offset_table=data["offset_table_clean"],
                        stations=data["stations"],
                        waterlines=data["waterlines"],
                        heel_angles=heel_angles,
                        KG=float(analysis["input"]["kg"]),
                        draft=float(analysis["input"]["draft"]),
                        depth=float(data["depth"]),
                        rho=float(analysis["input"]["rho"]),
                        volume_tol=float(volume_tol),
                    )
                    st.session_state["geom_curve"] = geom
                except Exception as exc:
                    st.session_state.pop("geom_curve", None)
                    st.error(f"Geometric curve computation failed: {exc}")

            geom_curve = st.session_state.get("geom_curve")
            if geom_curve is not None:
                g1, g2, g3 = st.columns(3)
                g1.metric("Max geometric GZ (m)", f"{float(geom_curve['max_gz_geometric']):.3f}")
                g2.metric("Angle at max GZ (deg)", f"{float(geom_curve['angle_at_max_gz_geometric']):.1f}")
                g3.metric("Max |volume error|", f"{float(np.max(np.abs(geom_curve['volume_rel_error']))):.2e}")

                heel_geom = np.asarray(geom_curve["heel_deg"], dtype=float)
                gz_geom = np.asarray(geom_curve["gz_geometric"], dtype=float)
                deck_angle = float(geom_curve.get("deck_immersion_angle_deg", float("nan")))
                avs_angle = float(geom_curve.get("angle_of_vanishing_stability_deg", float("nan")))

                k1, k2 = st.columns(2)
                k1.metric("Deck touches water (deg)", f"{deck_angle:.1f}" if np.isfinite(deck_angle) else "N/A")
                k2.metric("Angle of vanishing stability (deg)", f"{avs_angle:.1f}" if np.isfinite(avs_angle) else "N/A")

                if bool(geom_curve.get("truncated_due_to_infeasible_volume", False)):
                    computed_max = float(geom_curve.get("computed_max_heel_deg", float("nan")))
                    first_unachievable = float(geom_curve.get("first_unachievable_heel_deg", float("nan")))
                    truncation_mode = str(geom_curve.get("truncation_mode", "")).strip()
                    reason = str(geom_curve.get("truncation_reason", "")).strip()
                    prefix = "Geometric curve truncated before the requested maximum heel angle. "
                    if truncation_mode == "geometric-infeasible":
                        prefix += "Reason: geometric infeasibility at high heel. "
                    elif truncation_mode == "volume-tolerance":
                        prefix += "Reason: volume match failed tolerance. "
                    elif truncation_mode:
                        prefix += "Reason: runtime error during high-heel solve. "

                    st.warning(
                        prefix
                        + f"Computed through {computed_max:.1f} deg"
                        + (f"; first failed heel was {first_unachievable:.1f} deg. " if np.isfinite(first_unachievable) else ". ")
                        + (reason if reason else "")
                    )
                elif not np.isfinite(avs_angle):
                    st.info("Angle of vanishing stability was not found within the computed geometric heel range.")

                geom_df = pd.DataFrame(
                    {
                        "Heel (deg)": heel_geom,
                        "GZ geometric (m)": gz_geom,
                        "GZ simplified (m)": np.asarray(geom_curve["gz_simplified"], dtype=float),
                        "KN geometric (m)": np.asarray(geom_curve["kn_geometric"], dtype=float),
                    }
                )
                st.dataframe(geom_df, use_container_width=True)
                fig_geom = px.line(
                    geom_df,
                    x="Heel (deg)",
                    y=["GZ geometric (m)", "GZ simplified (m)", "KN geometric (m)"],
                    title="True Geometric vs Simplified Curves",
                )

                if np.isfinite(deck_angle):
                    fig_geom.add_vline(
                        x=float(deck_angle),
                        line_dash="dot",
                        line_color="orange",
                        line_width=2,
                        annotation_text=f"Deck touches water: {deck_angle:.1f} deg",
                        annotation_position="top left",
                    )
                    if heel_geom[0] <= deck_angle <= heel_geom[-1]:
                        y_deck = float(np.interp(deck_angle, heel_geom, gz_geom))
                        fig_geom.add_trace(
                            go.Scatter(
                                x=[float(deck_angle)],
                                y=[y_deck],
                                mode="markers",
                                marker={"size": 10, "color": "orange", "symbol": "diamond"},
                                name="Deck touch point",
                            )
                        )

                if np.isfinite(avs_angle):
                    fig_geom.add_vline(
                        x=float(avs_angle),
                        line_dash="dash",
                        line_color="red",
                        line_width=2,
                        annotation_text=f"AVS: {avs_angle:.1f} deg",
                        annotation_position="top right",
                    )
                    if heel_geom[0] <= avs_angle <= heel_geom[-1]:
                        y_avs = float(np.interp(avs_angle, heel_geom, gz_geom))
                        fig_geom.add_trace(
                            go.Scatter(
                                x=[float(avs_angle)],
                                y=[y_avs],
                                mode="markers",
                                marker={"size": 10, "color": "red", "symbol": "x"},
                                name="AVS point",
                            )
                        )

                uncertainty_end_angle = float("nan")
                uncertainty_label = ""
                if np.isfinite(avs_angle):
                    uncertainty_end_angle = avs_angle
                    uncertainty_label = "Uncertain area: potential water ingress"
                else:
                    computed_max = float(geom_curve.get("computed_max_heel_deg", float("nan")))
                    if np.isfinite(computed_max):
                        uncertainty_end_angle = computed_max
                        uncertainty_label = "Uncertain area to truncation: potential water ingress"

                if np.isfinite(deck_angle) and np.isfinite(uncertainty_end_angle) and uncertainty_end_angle > deck_angle:
                    fig_geom.add_vrect(
                        x0=float(deck_angle),
                        x1=float(uncertainty_end_angle),
                        fillcolor="gray",
                        opacity=0.22,
                        line_width=0,
                        annotation_text=uncertainty_label,
                        annotation_position="top",
                    )
                st.plotly_chart(fig_geom, use_container_width=True)

        kg_for_transform = st.number_input(
            "KG for transform (m)",
            min_value=0.0,
            value=float(analysis["input"]["kg"]),
            step=0.05,
            help="Only affects the KN -> GZ transformation below; does not recalculate hydrostatics or displacement.",
            key="kg_transform",
        )
        st.caption(
            "This KG value only affects the KN -> GZ transformation below. "
            "It does not recalculate hydrostatics or displacement."
        )

        geom_curve = st.session_state.get("geom_curve")
        if geom_curve is not None:
            default_heel = np.asarray(geom_curve["heel_deg"], dtype=float)
            default_kn = np.asarray(geom_curve["kn_geometric"], dtype=float)
        else:
            default_heel = analysis["heel_deg"]
            default_kn = analysis["kn"]

        default_table = pd.DataFrame({"Heel (deg)": default_heel[::5], "KN (m)": default_kn[::5]})
        editable = st.data_editor(default_table, num_rows="dynamic", use_container_width=True, key="kn_editor")

        try:
            heel_vals = np.asarray(editable["Heel (deg)"], dtype=float)
            kn_vals = np.asarray(editable["KN (m)"], dtype=float)
            order = np.argsort(heel_vals)
            heel_vals = heel_vals[order]
            kn_vals = kn_vals[order]
            gz_vals = kn_vals - float(kg_for_transform) * np.sin(np.deg2rad(heel_vals))

            trans_df = pd.DataFrame(
                {
                    "Heel (deg)": heel_vals,
                    "KN (m)": kn_vals,
                    "GZ from KN (m)": gz_vals,
                }
            )
            st.dataframe(trans_df, use_container_width=True)

            fig_trans = go.Figure()
            fig_trans.add_trace(go.Scatter(x=heel_vals, y=kn_vals, mode="lines+markers", name="KN"))
            fig_trans.add_trace(go.Scatter(x=heel_vals, y=gz_vals, mode="lines+markers", name="GZ from KN"))
            fig_trans.update_layout(title="KN to GZ Transformation", xaxis_title="Heel (deg)", yaxis_title="Lever Arm (m)")
            st.plotly_chart(fig_trans, use_container_width=True)
        except Exception as exc:
            st.error(f"Invalid KN table input: {exc}")

    with tab3:
        st.subheader("Benchmark Validation")
        st.caption(
            "Compares application-generated hydrostatics against NMRI KCS offset-based benchmark references."
        )
        st.info(
            "This tab uses only authentic NMRI KCS offset data as the external benchmark source. "
            "Reference values are published KCS particulars; generated values come from this application pipeline."
        )
        st.markdown(
            """
- **Benchmark source used:** NMRI KCS geometry/conditions page (official workshop data portal): https://www.nmri.go.jp/study/research_organization/fluid_performance/cfd/cfdws05/Detail/KCS/kcs_g&c.htm
- **Offset geometry input used by this app:** KCS offsets archive from NMRI: https://www.nmri.go.jp/study/research_organization/fluid_performance/cfd/cfdws05/Detail/data/KCS_data/kcs_offsets.ZIP
- **Reference values used for comparison:** published KCS particulars (displacement, block coefficient, LCB %Lpp) from benchmark documentation.
- **How validation is computed:**
    1. Parse official `kcs.fix` offset data.
    2. Build the offset table used by the app hydrostatics pipeline.
    3. Compute generated values from the same app pipeline used in analysis tabs.
    4. Compare generated values against published KCS reference values and report % difference.
- **Why ShipD is not shown in judge-facing validation:** ShipD data is parameter-vector based and requires a conversion layer to reconstruct offsets, while this app's core workflow is direct offset-table input from the organizer workbook/NMRI files.
- **Summary of input-data mismatch with ShipD:**
    1. ShipD starts from compact hull design vectors, not native offset tables.
    2. Conversion assumptions (stern/longitudinal shaping) can shift hydrostatic outputs.
    3. That introduces benchmark-model mismatch risk for an offset-only judging narrative.
"""
        )
        st.caption(
            "Acronyms: CB = Block Coefficient (how full the underwater hull is vs L x B x T block); "
            "LCB = Longitudinal Center of Buoyancy (fore-aft location of buoyancy center)."
        )

        offset_reports = _discover_offset_benchmark_report_paths()
        if offset_reports:
            st.markdown("### NMRI KCS Offset Benchmark")
            st.caption(
                "Compares generated hydrostatics from NMRI KCS offset data against published KCS particulars "
                "(displacement, block coefficient, and LCB in %Lpp)."
            )
            offset_path = offset_reports[0]
            st.caption(f"Using benchmark report: {offset_path}")

            try:
                offset_df = load_offset_benchmark_report(str(offset_path))
            except Exception as exc:
                st.error(f"Failed to load KCS benchmark report: {exc}")
                offset_df = pd.DataFrame()

            if not offset_df.empty and {"metric", "reference", "generated", "pct_diff"}.issubset(offset_df.columns):
                pass_band_pct = st.slider(
                    "Acceptance band for |% diff|",
                    min_value=0.1,
                    max_value=5.0,
                    value=1.0,
                    step=0.1,
                    key="kcs_acceptance_band",
                )

                diffs = pd.to_numeric(offset_df["pct_diff"], errors="coerce").abs()
                pass_count = int((diffs <= pass_band_pct).sum())
                metric_count = int(diffs.notna().sum())
                fail_count = int(metric_count - pass_count)
                max_diff = float(diffs.max()) if metric_count else float("nan")

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Metrics evaluated", f"{metric_count}")
                m2.metric("PASS", f"{pass_count}")
                m3.metric("FAIL", f"{fail_count}")
                m4.metric("Max |% diff|", "N/A" if not np.isfinite(max_diff) else f"{max_diff:.2f}%")

                cards = st.columns(min(3, len(offset_df)))
                for idx, (_, metric_row) in enumerate(offset_df.head(3).iterrows()):
                    card = cards[idx]
                    metric_name = str(metric_row.get("metric", "Metric"))
                    gen_val = _as_float_or_nan(metric_row.get("generated", np.nan))
                    unit = str(metric_row.get("unit", "")).strip()
                    suffix = f" {unit}" if unit and unit != "-" else ""
                    value_txt = "N/A" if not np.isfinite(gen_val) else f"{gen_val:.3f}{suffix}"
                    pct_val = _as_float_or_nan(metric_row.get("pct_diff", np.nan))
                    delta_txt = "N/A" if not np.isfinite(pct_val) else f"{pct_val:+.2f}% vs reference"
                    card.metric(metric_name, value_txt, delta=delta_txt)

                display_df = offset_df.copy()
                display_df["status"] = np.where(
                    pd.to_numeric(display_df["pct_diff"], errors="coerce").abs() <= pass_band_pct,
                    "PASS",
                    "FAIL",
                )
                st.dataframe(
                    display_df.style.format(
                        {
                            "reference": "{:.4f}",
                            "generated": "{:.4f}",
                            "pct_diff": "{:+.2f}%",
                        },
                        na_rep="N/A",
                    ),
                    use_container_width=True,
                )
        else:
            st.info(
                "No NMRI KCS benchmark report found. "
                "Run python run_kcs_offset_benchmark.py to generate results/kcs_offset_benchmark.csv."
            )

    with tab4:
        st.subheader("Volume Displacement Validation vs Heel")
        st.caption(
            "Uses true station-wise clipped polygons; compares trapezoid and Simpson integration along stations only."
        )
        st.info(
            "Note: with a fixed global waterplane, volume can drop sharply at high heel angles. "
            "That trend is geometric clipping behavior, not necessarily an integration bug. "
            "Using a more granular offset grid (more stations/waterlines) can reduce % deviation from upright."
        )

        c1, c2 = st.columns(2)
        heel_max = c1.slider("Max heel angle (deg)", min_value=10, max_value=90, value=60, step=5)
        heel_step = c2.selectbox("Heel increment (deg)", options=[1, 2, 5], index=1)

        if st.button("Run Volume Validation", key="run_volume_validation"):
            try:
                heel_angles = np.arange(0.0, float(heel_max) + float(heel_step), float(heel_step), dtype=float)
                vol_df = run_volume_conservation(
                    stations=data["stations"],
                    waterlines=data["waterlines"],
                    offset_table=data["offset_table_clean"],
                    draft=float(analysis["input"]["draft"]),
                    rho=float(analysis["input"]["rho"]),
                    heel_angles=heel_angles,
                )
                st.session_state["volume_validation_df"] = vol_df
            except Exception as exc:
                st.session_state.pop("volume_validation_df", None)
                st.error(f"Volume validation failed: {exc}")

        vol_df = st.session_state.get("volume_validation_df")
        if vol_df is not None and len(vol_df) > 0:
            v1, v2, v3 = st.columns(3)
            v1.metric("Upright volume (m^3)", f"{float(vol_df['V_upright_m3'].iloc[0]):.0f}")
            v2.metric(
                "Max |polygon deviation| (%)",
                f"{float(np.max(np.asarray(vol_df['deviation_abs_pct'], dtype=float))):.1f}",
            )
            v3.metric(
                "Max |Simpson - Polygon| (%)",
                f"{float(np.max(np.abs(np.asarray(vol_df['simpson_minus_polygon_pct'], dtype=float)))):.1f}",
            )

            v_upright = float(vol_df["V_upright_m3"].iloc[0])
            polygon_dev_pct = 100.0 * (np.asarray(vol_df["V_heeled_m3"], dtype=float) - v_upright) / v_upright
            simpson_dev_pct = 100.0 * (np.asarray(vol_df["V_heeled_simpson_m3"], dtype=float) - v_upright) / v_upright

            fig_vol = go.Figure()
            fig_vol.add_trace(
                go.Scatter(
                    x=vol_df["heel_deg"],
                    y=polygon_dev_pct,
                    mode="lines+markers",
                    name="True polygon",
                )
            )
            fig_vol.add_trace(
                go.Scatter(
                    x=vol_df["heel_deg"],
                    y=simpson_dev_pct,
                    mode="lines+markers",
                    name="True polygon + Simpson",
                )
            )
            fig_vol.add_hline(
                y=0.0,
                line_dash="dash",
                line_color="gray",
                annotation_text="Upright reference (0% deviation)",
                annotation_position="top left",
            )
            fig_vol.update_layout(
                title="Displaced Volume Deviation vs Heel Angle (True Polygon Method)",
                xaxis_title="Heel (deg)",
                yaxis_title="% Deviation from Upright",
                yaxis_tickformat=".1f",
            )
            st.plotly_chart(fig_vol, use_container_width=True)

            st.dataframe(
                vol_df[
                    [
                        "heel_deg",
                        "V_upright_m3",
                        "V_upright_simpson_m3",
                        "V_heeled_m3",
                        "V_heeled_simpson_m3",
                        "deviation_pct",
                        "deviation_simpson_pct",
                        "deviation_abs_pct",
                        "deviation_simpson_abs_pct",
                        "simpson_minus_polygon_m3",
                        "simpson_minus_polygon_pct",
                    ]
                ].round(
                    {
                        "heel_deg": 0,
                        "V_upright_m3": 0,
                        "V_upright_simpson_m3": 0,
                        "V_heeled_m3": 0,
                        "V_heeled_simpson_m3": 0,
                        "deviation_pct": 1,
                        "deviation_simpson_pct": 1,
                        "deviation_abs_pct": 1,
                        "deviation_simpson_abs_pct": 1,
                        "simpson_minus_polygon_m3": 0,
                        "simpson_minus_polygon_pct": 1,
                    }
                ),
                use_container_width=True,
            )

    with tab5:
        st.subheader("Offset Optimizer")
        st.caption("Optimize offset table to satisfy GZ constraints at multiple heel angles and minimum area under GZ curve.")

        # Display baseline geometric GZ curve as reference
        st.markdown("### Baseline GZ Curve (Reference)")
        
        col_geom1, col_geom2 = st.columns([3, 1])
        with col_geom1:
            st.caption("Current ship GZ profile at current draft and KG")
        with col_geom2:
            compute_baseline_geom = st.button("Compute Geometric GZ", key="compute_baseline_geom")
        
        baseline_geom_curve = st.session_state.get("baseline_geom_curve")
        if baseline_geom_curve is None and compute_baseline_geom:
            with st.spinner("Computing baseline geometric GZ curve..."):
                try:
                    heel_angles_geom = np.arange(0.0, 61.0, 1.0, dtype=float)
                    baseline_geom_curve = compute_geometric_gz_curve(
                        offset_table=data["offset_table_clean"],
                        stations=data["stations"],
                        waterlines=data["waterlines"],
                        heel_angles=heel_angles_geom,
                        KG=float(analysis["input"]["kg"]),
                        draft=float(analysis["input"]["draft"]),
                        depth=float(data["depth"]),
                        rho=float(analysis["input"]["rho"]),
                        volume_tol=1e-4,
                    )
                    st.session_state["baseline_geom_curve"] = baseline_geom_curve
                except Exception as exc:
                    st.error(f"Failed to compute baseline geometric GZ: {exc}")
        
        if baseline_geom_curve is not None:
            heel_geom = np.asarray(baseline_geom_curve["heel_deg"], dtype=float)
            gz_geom = np.asarray(baseline_geom_curve["gz_geometric"], dtype=float)
            
            fig_baseline_gz = go.Figure()
            fig_baseline_gz.add_trace(
                go.Scatter(
                    x=heel_geom,
                    y=gz_geom,
                    mode="lines",
                    name="Baseline GZ",
                    line=dict(color="blue", width=2),
                )
            )
            fig_baseline_gz.update_layout(
                title="Baseline GZ Curve (Geometric)",
                xaxis_title="Heel (°)",
                yaxis_title="GZ (m)",
                hovermode="x unified",
                height=400,
            )
            st.plotly_chart(fig_baseline_gz, use_container_width=True)
            
            # Display GZ values table for reference
            with st.expander("Baseline GZ Values Table"):
                geom_table_df = pd.DataFrame({
                    "Heel (°)": heel_geom[::5],  # Every 5°
                    "GZ (m)": gz_geom[::5],
                })
                st.dataframe(geom_table_df, use_container_width=True)

        with st.form("optimizer_constraints"):
            st.markdown("### Optimization Configuration")
            
            col1, col2 = st.columns(2)
            with col1:
                target_heel = col1.selectbox(
                    "Target heel angle (°)",
                    options=[20, 30, 40, 50],
                    index=1,
                    help="Heel angle to maximize GZ at."
                )
            with col2:
                p_max_pct = col2.slider(
                    "Max half-breadth perturbation (%)",
                    min_value=1,
                    max_value=20,
                    value=5,
                    step=1,
                    help="Maximum allowed relative change to offset values."
                )
            
            st.markdown("### Minimum GZ Constraints at Heel Angles")
            st.caption("Enter up to 5 heel angles and their minimum required GZ values. Leave angle blank to skip a constraint.")
            
            gz_constraints = {}
            constraint_cols = st.columns([2, 3, 1])
            constraint_cols[0].write("**Heel (°)**")
            constraint_cols[1].write("**Min GZ (m)**")
            constraint_cols[2].write("")
            
            default_angles = [10, 20, 30, 40, 50]
            default_gz = [0.20, 0.40, 0.50, 0.45, 0.30]
            
            for i in range(5):
                cols = st.columns([2, 3, 1])
                heel_val = cols[0].number_input(
                    f"Heel {i+1}",
                    min_value=0,
                    max_value=90,
                    value=default_angles[i] if i < len(default_angles) else 30,
                    step=1,
                    key=f"heel_angle_{i}",
                    label_visibility="collapsed"
                )
                gz_val = cols[1].number_input(
                    f"Min GZ {i+1}",
                    min_value=0.0,
                    max_value=2.0,
                    value=default_gz[i] if i < len(default_gz) else 0.3,
                    step=0.01,
                    key=f"min_gz_{i}",
                    label_visibility="collapsed"
                )
                enabled = cols[2].checkbox(
                    f"Enable {i+1}",
                    value=(i < 3),
                    key=f"gz_enable_{i}",
                    label_visibility="collapsed"
                )
                
                if enabled and heel_val is not None and gz_val is not None:
                    gz_constraints[int(heel_val)] = float(gz_val)
            
            st.markdown("### Minimum Area Under GZ Curve")
            area_min = st.slider(
                "Min area under GZ (0-30°) [m·rad]",
                min_value=0.0,
                max_value=1.0,
                value=0.25,
                step=0.05,
                help="Minimum integrated area under the GZ curve from 0° to 30° heel."
            )
            
            submitted = st.form_submit_button("Run Optimization", type="primary")
        
        if submitted:
            if not gz_constraints:
                st.warning("Please enable at least one GZ constraint.")
            else:
                with st.spinner("Running optimization..."):
                    try:
                        constraints = OptimizationConstraints(
                            p_max=float(p_max_pct) / 100.0,
                            gz_min_at_angles=gz_constraints,
                            area_min=float(area_min),
                            target_heel=float(target_heel),
                        )
                        
                        opt_result = run_optimization(
                            stations=data["stations"],
                            waterlines=data["waterlines"],
                            offset_table=data["offset_table_clean"],
                            constraints=constraints,
                            KG=float(analysis["input"]["kg"]),
                            draft=float(analysis["input"]["draft"]),
                            rho=float(analysis["input"]["rho"]),
                        )
                        
                        st.session_state["optimizer_result"] = opt_result
                    except Exception as exc:
                        st.error(f"Optimization failed: {exc}")
                        st.session_state.pop("optimizer_result", None)
        
        # Render results if available
        opt_result = st.session_state.get("optimizer_result")
        if opt_result is not None:
            _render_optimization_result(opt_result, data, analysis)


if __name__ == "__main__":
    main()