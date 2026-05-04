import argparse
from typing import Dict

import numpy as np

from gz_curve import run_phase6, generate_kn_curve
from hydrostatics import compute_phase4
from integration import compute_phase3
from ship_excel_extractor import extract_ship_data
from stability import compute_phase5


def interpret_gm(gm: float) -> str:
    """Generate human-readable GM interpretation."""
    if gm < 0:
        return "UNSTABLE - The vessel cannot maintain upright equilibrium."
    if gm < 1.0:
        return "VERY TENDER - The vessel has poor stability with minimal resistance to tilting. Gentle rolling motion."
    if gm < 5.0:
        return "STABLE - The vessel exhibits adequate stability with moderate heeling resistance. Normal rolling behavior."
    return "STIFF - The vessel has excellent stability with strong resistance to heeling. Rapid, harsh rolling motion."


def interpret_stiffness(gm: float) -> str:
    """Explain stiffness implications for rolling behavior."""
    if gm < 1.0:
        return (
            "A tender vessel (low GM) experiences gentle, slow rolling motions. Crew comfort is good, "
            "but the ship responds sluggishly to waves. This design is typical for cargo vessels prioritizing "
            "cargo stability over ship motion.\n"
        )
    if gm < 5.0:
        return (
            "A stable vessel (moderate GM) exhibits balanced rolling behavior. The ship responds appropriately "
            "to wave excitation with moderate period oscillations. This provides good balance between crew comfort "
            "and ship handling.\n"
        )
    return (
        "A stiff vessel (high GM) exhibits rapid, energetic rolling motions. Crew comfort may suffer due to harsh "
        "accelerations, but the ship maintains excellent resistance to capsizing. Naval vessels and offshore support "
        "ships often use this design for safety in extreme seas.\n"
    )


def interpret_hydrostatics(lcb: float, lcf: float, kb: float, draft: float, volume: float) -> str:
    """Generate hydrostatic parameter interpretation."""
    kb_to_draft_ratio = (kb / draft) * 100.0
    return (
        f"Longitudinal Center of Buoyancy (LCB): {lcb:.2f} m\n"
        f"  The LCB is the geometric center of the immersed hull volume. It indicates where the resultant "
        f"buoyant force acts vertically upward. Position at {lcb:.2f} m from the forward reference.\n\n"
        f"Longitudinal Center of Flotation (LCF): {lcf:.2f} m\n"
        f"  The LCF is the geometric center of the waterplane area (floating surface). It marks the pivot point "
        f"for longitudinal trim changes. Position at {lcf:.2f} m from the forward reference.\n\n"
        f"Vertical Center of Buoyancy (KB): {kb:.2f} m\n"
        f"  KB represents the height of the buoyancy center above the keel. At draft {draft:.2f} m, "
        f"KB is {kb_to_draft_ratio:.1f}% of the draft, showing how deeply the weighted volume extends vertically.\n"
    )


def run_phase9(excel_file: str, output_file: str = "insights.txt") -> Dict[str, str]:
    """Generate stability insights report from all computed data."""
    extracted = extract_ship_data(excel_file)
    offset = extracted.get("offset_table")
    if not offset:
        raise ValueError("Offset table is missing.")

    stations = offset.get("stations")
    waterlines = offset.get("waterlines")
    offset_table_clean = offset.get("offset_table_clean")

    draft = extracted.get("draft")
    rho = extracted.get("rho")
    kg = extracted.get("KG")

    if stations is None or waterlines is None or offset_table_clean is None:
        raise ValueError("stations/waterlines/offset_table_clean are missing.")
    if draft is None or rho is None or kg is None:
        raise ValueError("draft, rho, or KG is missing.")

    # Run all phases to gather data.
    phase3 = compute_phase3(
        stations=stations,
        waterlines=waterlines,
        offset_table_clean=offset_table_clean,
        draft=float(draft),
        rho=float(rho),
        method="trapezoidal",
    )

    phase4 = compute_phase4(
        stations=stations,
        waterlines=waterlines,
        offset_table_clean=offset_table_clean,
        sectional_areas=phase3["sectional_areas"],
        displaced_volume=float(phase3["displaced_volume"]),
        draft=float(draft),
        rho=float(rho),
    )

    phase5 = compute_phase5(
        stations=stations,
        waterlines=waterlines,
        offset_table_clean=offset_table_clean,
        draft=float(draft),
        displaced_volume=float(phase4["displaced_volume"]),
        kb=float(phase4["KB"]),
        kg=float(kg),
    )

    phase6 = run_phase6(
        excel_file=excel_file,
        step_deg=1.0,
        max_angle_deg=60.0,
    )

    # Build report sections.
    vol = float(phase3["displaced_volume"])
    mass = float(phase4["displacement_mass"])
    awp = float(phase4["waterplane_area_draft"])
    lcb = float(phase4["LCB"])
    lcf = float(phase4["LCF"])
    kb = float(phase4["KB"])
    bm = float(phase5["BM"])
    gm = float(phase5["GM"])
    max_gz = float(phase6["max_gz"])
    angle_max_gz = float(phase6["angle_at_max_gz"])
    heel_deg = phase6["heel_deg"]
    gz = phase6["gz"]
    assert hasattr(heel_deg, "shape")
    assert hasattr(gz, "shape")

    kn = generate_kn_curve(heel_deg=heel_deg, gz=gz, KG=float(kg))
    max_kn_idx = int(np.argmax(kn))
    max_kn = float(kn[max_kn_idx])
    angle_max_kn = float(heel_deg[max_kn_idx])

    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("SHIP HYDROSTATICS AND STABILITY ANALYSIS REPORT")
    report_lines.append("Phase 9: Insight Engine")
    report_lines.append("=" * 80)

    report_lines.append("\n" + "=" * 80)
    report_lines.append("1. STABILITY SUMMARY")
    report_lines.append("=" * 80)

    report_lines.append(f"\nMetacentric Height (GM): {gm:.4f} m")
    report_lines.append(f"Classification: {interpret_gm(gm)}\n")
    report_lines.append(interpret_stiffness(gm))

    report_lines.append(
        "A positive GM indicates the ship will return to upright after a disturbance. "
        "The larger the GM, the greater the restoring moment and the faster the ship will right itself. "
        "However, extremely high GM values lead to harsh rolling motions that reduce crew comfort.\n"
    )

    report_lines.append("\n" + "=" * 80)
    report_lines.append("2. HYDROSTATIC SUMMARY")
    report_lines.append("=" * 80 + "\n")

    report_lines.append(f"Draft: {float(draft):.4f} m")
    report_lines.append(f"Displaced Volume: {vol:.4f} m³")
    report_lines.append(f"Displacement Mass: {mass:.2f} kg ({mass / 1e6:.2f} thousand tonnes)\n")
    report_lines.append(f"Waterplane Area (at draft): {awp:.4f} m²\n")

    report_lines.append(interpret_hydrostatics(lcb, lcf, kb, float(draft), vol))

    report_lines.append("Design Insight:")
    report_lines.append(
        "The waterplane area of {:.0f} m² establishes the ship's floating footprint. "
        "Larger waterplane areas provide greater reserve buoyancy and improved trim stability. "
        "The calculated LCB and LCF positions indicate longitudinal load distribution and trim response.\n".format(awp)
    )

    report_lines.append("\n" + "=" * 80)
    report_lines.append("3. GZ CURVE AND RIGHTING MOMENT INTERPRETATION")
    report_lines.append("=" * 80 + "\n")

    report_lines.append(
        "The GZ curve represents the righting arm—the perpendicular distance between the lines of action "
        "of weight and buoyancy. As a vessel heels, GZ increases initially, then peaks, and eventually decreases.\n"
    )

    report_lines.append(f"Maximum GZ (within 0–60°): {max_gz:.4f} m at heel angle {angle_max_gz:.1f}°\n")

    report_lines.append(
        "This peak represents the maximum restoring moment available. A higher peak GZ indicates greater "
        "righting capacity at large heel angles.\n"
    )

    report_lines.append(
        "Derived KN curve relation used in this project: KN(θ) = GZ(θ) + KG × sin(θ).\n"
    )

    report_lines.append(
        f"Maximum derived KN (within 0–60°): {max_kn:.4f} m at heel angle {angle_max_kn:.1f}°\n"
    )

    report_lines.append(
        "This KN curve is an approximation derived from the GM-based GZ model. "
        "True KN cross-curves require recomputing the buoyancy center for each heel angle "
        "from the heeled hull geometry.\n"
    )

    report_lines.append(
        "Note: The GZ curve shown uses a simplified model based on GM: GZ(θ) = GM × sin(θ). "
        "This approximation is valid for initial stability (θ < 30°). For larger angles up to 60°, "
        "more accurate GZ requires accounting for the shifting buoyancy center as hull geometry changes. "
        "The Plotly 3D visualization above shows the actual immersed hull geometry at the operating draft.\n"
    )

    report_lines.append("\n" + "=" * 80)
    report_lines.append("4. ASSUMPTIONS AND LIMITATIONS")
    report_lines.append("=" * 80 + "\n")

    report_lines.append("Key Assumptions Used in This Analysis:\n")

    report_lines.append(
        f"• Fluid Density (ρ): {float(rho):.1f} kg/m³\n"
        f"  Standard seawater density assumed. If operating in fresh water (ρ ≈ 1000 kg/m³) or "
        f"salt water with different salinity, GM and displacement will shift.\n"
    )

    report_lines.append(
        f"• Vertical Center of Gravity (KG): {float(kg):.4f} m\n"
        f"  Estimated as 0.5 × Draft (0.5 × {float(draft):.2f} = {float(kg):.2f} m).\n"
        f"  Since actual loading data was not available, this approximation represents a representative "
        f"cargo distribution. Real KG depends on specific cargo loading, ballast, and consumables.\n"
    )

    report_lines.append(
        f"• Integration Method: Trapezoidal rule with actual (non-uniform) station and waterline spacing.\n"
        f"  This numerical method integrates over the real geometric data from the ship's lines plan.\n"
    )

    report_lines.append(
        f"• GZ Curve Simplification: GZ(θ) = GM × sin(θ) for heel angles 0–60°.\n"
        f"  This small-angle approximation provides quick initial stability insight but overestimates GZ "
        f"at large heel angles. A detailed cross-curve calculation accounting for shifting buoyancy centers "
        f"would be required for damage stability and regulatory compliance.\n"
    )

    report_lines.append(
        f"• KN Curve Simplification: KN(θ) = GZ(θ) + KG × sin(θ) (derived approximation).\n"
        f"  This is not a direct geometric KN cross-curve solution. Accurate KN needs buoyancy center "
        f"recalculation at each heel increment using the heeled waterplane and immersed volume.\n"
    )

    report_lines.append("\nLimitations:\n")

    report_lines.append(
        "• Free surface effects: No fluid slack tanks or cargo shift modeled.\n"
        "• Dynamic effects: Wave-induced rolling and pitching not included.\n"
        "• Nonlinear hydrostatics: GZ curve uses GM approximation; real GZ is nonlinear above ~20° heel.\n"
        "• Uncrewed ship assumption: No human factors in stability margin choices.\n"
    )

    report_lines.append("\n" + "=" * 80)
    report_lines.append("END OF REPORT")
    report_lines.append("=" * 80 + "\n")

    report_text = "\n".join(report_lines)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(report_text)

    return {
        "report_text": report_text,
        "output_file": output_file,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 9: Stability Insight Engine - generates human-readable report.")
    parser.add_argument("excel_file", help="Path to workbook")
    parser.add_argument("--output", type=str, default="insights.txt", help="Output report file path")
    args = parser.parse_args()

    results = run_phase9(excel_file=args.excel_file, output_file=args.output)
    output_file = results["output_file"]

    print("\n=== PHASE 9: STABILITY INSIGHT ENGINE ===")
    print(f"Report generated: {output_file}")
    print(f"\nReport preview (first 1000 chars):\n")
    print(results["report_text"][:1000] + "...\n")


if __name__ == "__main__":
    main()
