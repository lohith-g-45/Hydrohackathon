import argparse
from typing import Dict

import numpy as np

from hydrostatics import compute_phase4
from integration import compute_phase3, trapezoidal_rule
from ship_excel_extractor import extract_ship_data


def _as_1d_float_array(name: str, values) -> np.ndarray:
    arr = np.asarray(values, dtype=float).reshape(-1)
    if arr.size == 0:
        raise ValueError(f"{name} must not be empty.")
    if np.isnan(arr).any():
        raise ValueError(f"{name} contains NaN values.")
    return arr


def _as_2d_float_array(name: str, values) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 2:
        raise ValueError(f"{name} must be a 2D array.")
    if arr.size == 0:
        raise ValueError(f"{name} must not be empty.")
    if np.isnan(arr).any():
        raise ValueError(f"{name} contains NaN values.")
    return arr


def _validate_increasing(name: str, x: np.ndarray) -> None:
    if np.any(np.diff(x) <= 0.0):
        raise ValueError(f"{name} must be strictly increasing.")


def extract_draft_breadths(stations, waterlines, offset_table_clean, draft: float) -> np.ndarray:
    """Extract full breadths B(x) exactly at draft waterline.

    Requirement: draft waterline must exist in waterlines array (no extrapolation above/below).
    """
    x = _as_1d_float_array("stations", stations)
    z = _as_1d_float_array("waterlines", waterlines)
    hb_table = _as_2d_float_array("offset_table_clean", offset_table_clean)

    _validate_increasing("stations", x)
    _validate_increasing("waterlines", z)

    expected_shape = (z.size, x.size)
    if hb_table.shape != expected_shape:
        raise ValueError(
            f"offset_table_clean shape {hb_table.shape} does not match expected {expected_shape}."
        )

    d = float(draft)
    if np.isnan(d):
        raise ValueError("draft contains NaN value.")

    idx = np.where(np.isclose(z, d, atol=1e-12, rtol=0.0))[0]
    if idx.size == 0:
        raise ValueError(
            f"Draft waterline {d} m does not exist in waterlines array. "
            "Please provide a draft that matches one tabulated waterline."
        )

    half_breadths = hb_table[int(idx[0]), :]
    if np.isnan(half_breadths).any():
        raise ValueError("Draft half-breadths contain NaN values.")

    # Full breadth B(x) = port + starboard = 2 * half-breadth.
    full_breadths = 2.0 * half_breadths
    return full_breadths


def compute_IT(stations, breadths) -> float:
    """Compute transverse second moment of waterplane area about centerline.

    I_T = integral( (1/12) * B(x)^3 dx )
    where B(x) is full breadth at each station.
    """
    x = _as_1d_float_array("stations", stations)
    b = _as_1d_float_array("breadths", breadths)

    if x.size != b.size:
        raise ValueError("stations and breadths must have same length.")
    _validate_increasing("stations", x)

    integrand = (1.0 / 12.0) * (b**3)
    return float(trapezoidal_rule(x, integrand))


def compute_BM(i_t: float, volume: float) -> float:
    """BM = I_T / displaced_volume."""
    it_val = float(i_t)
    vol = float(volume)
    if np.isnan(it_val) or np.isnan(vol):
        raise ValueError("I_T and displaced_volume must be valid numbers.")
    if vol <= 0.0:
        raise ValueError("displaced_volume must be positive.")
    return float(it_val / vol)


def compute_GM(kb: float, bm: float, kg: float) -> float:
    """GM = KB + BM - KG."""
    kb_val = float(kb)
    bm_val = float(bm)
    kg_val = float(kg)
    if np.isnan(kb_val) or np.isnan(bm_val) or np.isnan(kg_val):
        raise ValueError("KB, BM, and KG must be valid numbers.")
    return float(kb_val + bm_val - kg_val)


def assess_stability(gm: float) -> str:
    """Interpret GM with practical naval architecture thresholds.

    - GM <= 0: unstable
    - 0 < GM <= 1 m: stable but tender
    - GM >= 2 m: stable and stiff
    - otherwise: stable (moderate)
    """
    gm_val = float(gm)
    if gm_val <= 0.0:
        return "Ship is unstable (GM <= 0)."
    if gm_val <= 1.0:
        return "Ship is stable but tender (small positive GM)."
    if gm_val >= 2.0:
        return "Ship is stable and stiff (large GM)."
    return "Ship is stable (moderate GM)."


def compute_phase5(
    stations,
    waterlines,
    offset_table_clean,
    draft: float,
    displaced_volume: float,
    kb: float,
    kg: float,
) -> Dict[str, float | str]:
    full_breadths = extract_draft_breadths(stations, waterlines, offset_table_clean, draft)

    i_t = compute_IT(stations, full_breadths)
    bm = compute_BM(i_t, displaced_volume)
    gm = compute_GM(kb, bm, kg)

    return {
        "I_T": i_t,
        "BM": bm,
        "GM": gm,
        "assessment": assess_stability(gm),
    }


def print_phase5_results(results: Dict[str, float | str]) -> None:
    print("\n=== PHASE 5: STABILITY RESULTS ===")
    print(f"Transverse moment of inertia (I_T): {float(results['I_T']):.4f} m^4")
    print(f"BM: {float(results['BM']):.4f} m")
    print(f"GM: {float(results['GM']):.4f} m")
    print("\nStability assessment:")
    print(str(results["assessment"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 5 stability calculations.")
    parser.add_argument("excel_file", help="Path to workbook")
    args = parser.parse_args()

    extracted = extract_ship_data(args.excel_file)
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

    # Reuse Phase 3 and Phase 4 to keep displaced volume/KB consistent with
    # underwater-only integration up to draft.
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

    results = compute_phase5(
        stations=stations,
        waterlines=waterlines,
        offset_table_clean=offset_table_clean,
        draft=float(draft),
        displaced_volume=float(phase4["displaced_volume"]),
        kb=float(phase4["KB"]),
        kg=float(kg),
    )
    print_phase5_results(results)


if __name__ == "__main__":
    main()
