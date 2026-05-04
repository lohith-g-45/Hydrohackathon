import argparse
from pathlib import Path
from typing import Dict, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from hydrostatics import compute_phase4
from integration import compute_phase3
from geometric_gz import compute_geometric_gz_curve as _compute_geometric_gz_curve
from ship_excel_extractor import extract_ship_data
from stability import compute_phase5


def generate_heel_angles(max_angle_deg: float = 60.0, step_deg: float = 1.0) -> np.ndarray:
    """Generate heel angles in degrees from 0 to max_angle_deg (inclusive)."""
    if max_angle_deg <= 0:
        raise ValueError("max_angle_deg must be positive.")
    if step_deg <= 0:
        raise ValueError("step_deg must be positive.")

    count = int(round(max_angle_deg / step_deg))
    angles = np.linspace(0.0, max_angle_deg, count + 1)
    return angles


def compute_gz_curve(gm: float, heel_deg: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Compute GZ using simplified initial stability approximation.

    GZ(theta) = GM * sin(theta)

    Note:
    - This method is acceptable for hackathon-level initial stability estimation.
    - Accurate GZ for larger heel requires full buoyancy center shift from hull geometry.
    """
    gm_val = float(gm)
    if np.isnan(gm_val):
        raise ValueError("GM must be a valid number.")

    heel_deg_arr = np.asarray(heel_deg, dtype=float)
    if heel_deg_arr.ndim != 1 or heel_deg_arr.size == 0:
        raise ValueError("heel_deg must be a non-empty 1D array.")
    if np.isnan(heel_deg_arr).any():
        raise ValueError("heel_deg contains NaN values.")

    heel_rad = np.deg2rad(heel_deg_arr)
    gz = gm_val * np.sin(heel_rad)
    return heel_rad, gz


def generate_kn_curve(heel_deg: np.ndarray, gz: np.ndarray, KG: float) -> np.ndarray:
    """Compute a derived KN curve from heel angle and GZ values.

    KN(theta) = GZ(theta) + KG * sin(theta)

    This is a derived KN approximation (not full geometric computation).
    """
    heel_deg_arr = np.asarray(heel_deg, dtype=float)
    gz_arr = np.asarray(gz, dtype=float)
    kg_val = float(KG)

    if heel_deg_arr.ndim != 1 or heel_deg_arr.size == 0:
        raise ValueError("heel_deg must be a non-empty 1D array.")
    if gz_arr.ndim != 1 or gz_arr.size == 0:
        raise ValueError("gz must be a non-empty 1D array.")
    if heel_deg_arr.shape != gz_arr.shape:
        raise ValueError("heel_deg and gz must have the same shape.")
    if np.isnan(heel_deg_arr).any() or np.isnan(gz_arr).any() or np.isnan(kg_val):
        raise ValueError("heel_deg, gz, and KG must not contain NaN values.")

    heel_rad = np.deg2rad(heel_deg_arr)
    kn = gz_arr + kg_val * np.sin(heel_rad)
    return kn


def compute_geometric_gz_curve(
    stations,
    waterlines,
    offset_table,
    draft: float,
    rho: float,
    KG: float,
    heel_angles,
) -> dict[str, np.ndarray | float]:
    return _compute_geometric_gz_curve(
        stations=stations,
        waterlines=waterlines,
        offset_table=offset_table,
        draft=draft,
        rho=rho,
        KG=KG,
        heel_angles=heel_angles,
    )


def analyze_gz_curve(heel_deg: np.ndarray, gz: np.ndarray) -> Dict[str, float]:
    """Return key points: max GZ and angle of maximum GZ."""
    heel_deg_arr = np.asarray(heel_deg, dtype=float)
    gz_arr = np.asarray(gz, dtype=float)

    if heel_deg_arr.shape != gz_arr.shape:
        raise ValueError("heel_deg and gz must have the same shape.")

    i_max = int(np.argmax(gz_arr))
    return {
        "max_gz": float(gz_arr[i_max]),
        "angle_at_max_gz": float(heel_deg_arr[i_max]),
    }


def estimate_range_of_stability(gm: float, search_step_deg: float = 0.1) -> float:
    """Estimate angle where simplified GZ returns near zero after positive values.

    For GZ = GM * sin(theta), the next zero after 0 deg is near 180 deg.
    """
    if search_step_deg <= 0:
        raise ValueError("search_step_deg must be positive.")

    theta_deg = np.arange(0.0, 180.0 + search_step_deg, search_step_deg)
    gz = float(gm) * np.sin(np.deg2rad(theta_deg))

    tol = max(1e-5, abs(float(gm)) * 1e-5)
    candidates = np.where((theta_deg > 0.0) & (np.abs(gz) <= tol))[0]
    if candidates.size == 0:
        return float("nan")
    return float(theta_deg[candidates[0]])


def validate_gz_behavior(heel_deg: np.ndarray, gz: np.ndarray) -> Dict[str, bool]:
    """Basic checks for smoothness and physically expected initial trend."""
    heel_deg_arr = np.asarray(heel_deg, dtype=float)
    gz_arr = np.asarray(gz, dtype=float)

    starts_at_zero = np.isclose(gz_arr[0], 0.0, atol=1e-9)

    diffs = np.diff(gz_arr)
    smooth = not np.isnan(diffs).any() and np.all(np.abs(np.diff(diffs)) < max(1e-6, np.max(np.abs(gz_arr)) * 0.2))

    increasing_initial = np.all(diffs[: min(5, diffs.size)] >= -1e-12)

    # Within 0 to 60 deg for sin(theta), the curve is monotonic increasing.
    has_drop_in_range = np.any(diffs < -1e-12)

    return {
        "starts_at_zero": bool(starts_at_zero),
        "smooth": bool(smooth),
        "increasing_initial": bool(increasing_initial),
        "has_drop_in_selected_range": bool(has_drop_in_range),
        "monotonic_in_selected_range_expected": True,
    }


def plot_gz_curve(heel_deg: np.ndarray, gz: np.ndarray, png_out: str | None = None, show_plot: bool = True) -> None:
    plt.figure(figsize=(9, 5))
    plt.plot(heel_deg, gz, linewidth=2)
    plt.xlabel("Heel angle (deg)")
    plt.ylabel("GZ (m)")
    plt.title("GZ Curve")
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.tight_layout()

    if png_out:
        plt.savefig(png_out, dpi=200)

    if show_plot:
        plt.show()
    else:
        plt.close()


def plot_kn_curve(heel_deg: np.ndarray, kn: np.ndarray, output_file: str = "kn_curve.png") -> None:
    """Plot derived KN curve and save as PNG."""
    heel_deg_arr = np.asarray(heel_deg, dtype=float)
    kn_arr = np.asarray(kn, dtype=float)

    if heel_deg_arr.shape != kn_arr.shape:
        raise ValueError("heel_deg and kn must have the same shape.")
    if heel_deg_arr.ndim != 1 or heel_deg_arr.size == 0:
        raise ValueError("heel_deg and kn must be non-empty 1D arrays.")
    if np.isnan(heel_deg_arr).any() or np.isnan(kn_arr).any():
        raise ValueError("heel_deg and kn must not contain NaN values.")

    i_max = int(np.argmax(kn_arr))
    max_kn = float(kn_arr[i_max])
    angle_max_kn = float(heel_deg_arr[i_max])

    plt.figure(figsize=(9, 5))
    plt.plot(heel_deg_arr, kn_arr, linewidth=2)
    plt.xlabel("Heel Angle (degrees)")
    plt.ylabel("KN (m)")
    plt.title("Derived KN Curve (Approximate)")
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.annotate(
        "KN derived from GM-based GZ approximation",
        xy=(0.02, 0.95),
        xycoords="axes fraction",
        ha="left",
        va="top",
        fontsize=9,
        bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "0.7", "alpha": 0.9},
    )
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Maximum KN                  : {max_kn:.4f} m")
    print(f"Angle at maximum KN         : {angle_max_kn:.1f} deg")


def export_gz_csv(
    csv_out: str,
    heel_deg: np.ndarray,
    gz: np.ndarray,
    gz_simplified: np.ndarray | None = None,
    kn: np.ndarray | None = None,
    kn_simplified: np.ndarray | None = None,
) -> None:
    frame = pd.DataFrame({"heel_angle_deg": np.asarray(heel_deg, dtype=float), "gz_m": np.asarray(gz, dtype=float)})
    if gz_simplified is not None:
        frame["gz_simplified_m"] = np.asarray(gz_simplified, dtype=float)
    if kn is not None:
        frame["kn_m"] = np.asarray(kn, dtype=float)
    if kn_simplified is not None:
        frame["kn_simplified_m"] = np.asarray(kn_simplified, dtype=float)
    frame.to_csv(csv_out, index=False)


def run_phase6(excel_file: str, step_deg: float, max_angle_deg: float) -> Dict[str, np.ndarray | float | Dict[str, bool]]:
    extracted = extract_ship_data(excel_file)
    offset = extracted.get("offset_table")
    if not offset:
        raise ValueError("Offset table is missing in extracted data.")

    stations = offset.get("stations")
    waterlines = offset.get("waterlines")
    offset_table_clean = offset.get("offset_table_clean")

    draft = extracted.get("draft")
    rho = extracted.get("rho")
    kg = extracted.get("KG")

    if stations is None or waterlines is None or offset_table_clean is None:
        raise ValueError("stations/waterlines/offset_table_clean are missing.")
    if draft is None:
        raise ValueError("draft is missing.")
    if rho is None:
        raise ValueError("rho is missing.")
    if kg is None:
        raise ValueError("KG is missing.")

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

    heel_deg = generate_heel_angles(max_angle_deg=max_angle_deg, step_deg=step_deg)
    geometric = compute_geometric_gz_curve(
        stations=stations,
        waterlines=waterlines,
        offset_table=offset_table_clean,
        draft=float(draft),
        rho=float(rho),
        KG=float(kg),
        heel_angles=heel_deg,
    )

    gz = np.asarray(geometric["gz_geometric"], dtype=float)
    gz_simplified = np.asarray(geometric["gz_simplified"], dtype=float)
    kn = np.asarray(geometric["kn_geometric"], dtype=float)
    kn_simplified = np.asarray(geometric["kn_simplified"], dtype=float)
    gm = float(geometric["GM"])

    key_points = analyze_gz_curve(heel_deg, gz)
    stability_range_deg = estimate_range_of_stability(gm)
    checks = validate_gz_behavior(heel_deg, gz)

    return {
        "heel_deg": heel_deg,
        "gz": gz,
        "gz_simplified": gz_simplified,
        "kn": kn,
        "kn_simplified": kn_simplified,
        "GM": gm,
        "max_gz": key_points["max_gz"],
        "angle_at_max_gz": key_points["angle_at_max_gz"],
        "range_of_stability_deg": stability_range_deg,
        "checks": checks,
    }


def print_phase6_results(results: Dict[str, np.ndarray | float | Dict[str, bool]]) -> None:
    heel_deg = results["heel_deg"]
    gz = results["gz"]
    checks = results["checks"]

    assert isinstance(heel_deg, np.ndarray)
    assert isinstance(gz, np.ndarray)
    assert isinstance(checks, dict)

    print("\n=== PHASE 6: GZ CURVE (SIMPLIFIED) ===")
    print(f"GM used                    : {float(results['GM']):.4f} m")
    print(f"Heel angle range           : {float(heel_deg[0]):.1f} to {float(heel_deg[-1]):.1f} deg")
    if heel_deg.size > 1:
        print(f"Heel angle step            : {float(heel_deg[1] - heel_deg[0]):.1f} deg")

    print("\nSample GZ values:")
    sample_idx = [0, min(10, heel_deg.size - 1), min(20, heel_deg.size - 1), heel_deg.size - 1]
    printed = set()
    for i in sample_idx:
        if i in printed:
            continue
        printed.add(i)
        print(f"Angle {float(heel_deg[i]):5.1f} deg -> GZ {float(gz[i]):8.4f} m")

    print("\nKey points:")
    print(f"Maximum GZ                 : {float(results['max_gz']):.4f} m")
    print(f"Angle at maximum GZ        : {float(results['angle_at_max_gz']):.1f} deg")
    print(f"Estimated range stability  : ~{float(results['range_of_stability_deg']):.1f} deg (simplified model)")

    print("\nValidation checks:")
    print(f"GZ starts at zero          : {'PASS' if checks['starts_at_zero'] else 'FAIL'}")
    print(f"GZ smooth trend            : {'PASS' if checks['smooth'] else 'FAIL'}")
    print(f"GZ initial increase        : {'PASS' if checks['increasing_initial'] else 'FAIL'}")
    if checks["has_drop_in_selected_range"]:
        print("GZ peak-and-drop in range  : PASS")
    else:
        print("GZ peak-and-drop in range  : NOT OBSERVED (expected for 0-60 deg with GM*sin(theta))")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 6 GZ curve using simplified GM*sin(theta) model.")
    parser.add_argument("excel_file", help="Path to workbook")
    parser.add_argument("--step", type=float, default=1.0, help="Heel angle step in degrees (default: 1)")
    parser.add_argument("--max-angle", type=float, default=60.0, help="Maximum heel angle in degrees (default: 60)")
    parser.add_argument("--no-plot", action="store_true", help="Disable matplotlib plot")
    parser.add_argument("--csv-out", type=str, default="", help="Optional CSV file path for angle-GZ export")
    parser.add_argument("--png-out", type=str, default="", help="Optional PNG file path for plot export")
    args = parser.parse_args()

    excel_stem = Path(args.excel_file).stem
    csv_out = args.csv_out if args.csv_out else f"{excel_stem}_gz_curve.csv"
    png_out = args.png_out if args.png_out else f"{excel_stem}_gz_curve.png"

    results = run_phase6(
        excel_file=args.excel_file,
        step_deg=args.step,
        max_angle_deg=args.max_angle,
    )

    heel_deg = results["heel_deg"]
    gz = results["gz"]
    assert isinstance(heel_deg, np.ndarray)
    assert isinstance(gz, np.ndarray)

    export_gz_csv(csv_out, heel_deg, gz)
    plot_gz_curve(heel_deg, gz, png_out=png_out, show_plot=not args.no_plot)

    print_phase6_results(results)
    print("\nArtifacts:")
    print(f"GZ CSV saved               : {csv_out}")
    print(f"GZ plot PNG saved          : {png_out}")


if __name__ == "__main__":
    main()
