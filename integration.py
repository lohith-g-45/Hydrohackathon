import argparse
from typing import Dict, Literal

import numpy as np

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
    dx = np.diff(x)
    if np.any(dx <= 0.0):
        raise ValueError(f"{name} must be strictly increasing.")


def trapezoidal_rule(x, y) -> float:
    """Numerical integration using trapezoidal rule for non-uniform x spacing."""
    x_arr = _as_1d_float_array("x", x)
    y_arr = _as_1d_float_array("y", y)

    if x_arr.size != y_arr.size:
        raise ValueError("x and y must have the same length.")
    if x_arr.size < 2:
        raise ValueError("At least two points are required for trapezoidal integration.")

    _validate_increasing("x", x_arr)
    return float(np.sum(0.5 * (y_arr[:-1] + y_arr[1:]) * np.diff(x_arr)))


def _quad_segment_integral(x0: float, x1: float, x2: float, y0: float, y1: float, y2: float) -> float:
    """Integrate a quadratic through three points over [x0, x2] for non-uniform spacing."""
    coeffs = np.polyfit([x0, x1, x2], [y0, y1, y2], 2)
    a, b, c = coeffs
    return float((a / 3.0) * (x2**3 - x0**3) + (b / 2.0) * (x2**2 - x0**2) + c * (x2 - x0))


def simpsons_rule(x, y) -> float:
    """Composite Simpson-style integration for non-uniform x spacing.

    Uses quadratic interpolation over each 3-point block. If one interval remains,
    it is integrated with trapezoidal rule.
    """
    x_arr = _as_1d_float_array("x", x)
    y_arr = _as_1d_float_array("y", y)

    if x_arr.size != y_arr.size:
        raise ValueError("x and y must have the same length.")
    if x_arr.size < 3:
        raise ValueError("At least three points are required for Simpson integration.")

    _validate_increasing("x", x_arr)

    n = x_arr.size
    total = 0.0
    i = 0
    while i + 2 < n:
        total += _quad_segment_integral(
            x_arr[i],
            x_arr[i + 1],
            x_arr[i + 2],
            y_arr[i],
            y_arr[i + 1],
            y_arr[i + 2],
        )
        i += 2

    if i + 1 < n:
        total += trapezoidal_rule(x_arr[i : i + 2], y_arr[i : i + 2])

    return float(total)


def compute_phase3(
    stations,
    waterlines,
    offset_table_clean,
    draft: float,
    rho: float,
    method: Literal["trapezoidal", "simpson"] = "trapezoidal",
) -> Dict[str, np.ndarray | float]:
    stations_arr = _as_1d_float_array("stations", stations)
    waterlines_arr = _as_1d_float_array("waterlines", waterlines)
    offsets_arr = _as_2d_float_array("offset_table_clean", offset_table_clean)

    # Use actual station and waterline coordinates from the dataset (non-uniform)
    # instead of spacing labels so integration reflects true geometry.
    _validate_increasing("stations", stations_arr)
    _validate_increasing("waterlines", waterlines_arr)

    expected_shape = (waterlines_arr.size, stations_arr.size)
    if offsets_arr.shape != expected_shape:
        raise ValueError(
            f"offset_table_clean shape {offsets_arr.shape} does not match expected {expected_shape}."
        )

    draft_value = float(draft)
    if np.isnan(draft_value):
        raise ValueError("draft contains NaN value.")

    # Integrate only up to draft: use rows where z <= draft.
    # This avoids counting geometry above the current floating waterline.
    z_mask = waterlines_arr <= (draft_value + 1e-12)
    if np.count_nonzero(z_mask) < 2:
        raise ValueError(
            "Need at least two waterline points at or below draft for vertical integration."
        )

    waterlines_sub = waterlines_arr[z_mask]
    offsets_sub = offsets_arr[z_mask, :]

    if method not in {"trapezoidal", "simpson"}:
        raise ValueError("method must be either 'trapezoidal' or 'simpson'.")

    integrate = trapezoidal_rule if method == "trapezoidal" else simpsons_rule

    # Sectional area at each station: integrate half-breadth over waterline z,
    # then multiply by 2 to recover full breadth area (port + starboard).
    sectional_areas = np.zeros(stations_arr.size, dtype=float)
    for j in range(stations_arr.size):
        half_breadths = offsets_sub[:, j]
        area_half = integrate(waterlines_sub, half_breadths)
        sectional_areas[j] = 2.0 * area_half

    # Volume: integrate sectional areas along longitudinal x stations.
    displaced_volume = integrate(stations_arr, sectional_areas)
    displacement_mass = displaced_volume * float(rho)

    max_idx = int(np.argmax(sectional_areas))

    return {
        "stations": stations_arr,
        "waterlines": waterlines_sub,
        "draft": draft_value,
        "sectional_areas": sectional_areas,
        "max_sectional_area": float(sectional_areas[max_idx]),
        "max_section_station": float(stations_arr[max_idx]),
        "displaced_volume": float(displaced_volume),
        "displacement_mass": float(displacement_mass),
    }


def print_phase3_results(results: Dict[str, np.ndarray | float], rho: float, method: str) -> None:
    sections = results["sectional_areas"]
    used_wl = results["waterlines"]
    assert isinstance(sections, np.ndarray)
    assert isinstance(used_wl, np.ndarray)

    print("\n=== PHASE 3: NUMERICAL INTEGRATION RESULTS ===")
    print(f"Integration method: {method}")
    print(f"Fluid density (rho): {rho} kg/m^3")
    print(f"Draft used for integration: {results['draft']} m")
    print(
        "Waterline range used: "
        f"{float(used_wl[0])} to {float(used_wl[-1])} m "
        f"({used_wl.size} points, z <= draft)"
    )

    print("\nSectional areas by station (m^2):")
    for x, area in zip(results["stations"], sections):
        print(f"Station {float(x):9.4f} m -> Area {float(area):10.4f} m^2")

    print("\nValidation summary:")
    print(f"Max sectional area : {results['max_sectional_area']:.4f} m^2")
    print(f"At station         : {results['max_section_station']:.4f} m")
    print(f"Displaced volume   : {results['displaced_volume']:.4f} m^3")
    print(f"Displacement mass  : {results['displacement_mass']:.4f} kg")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 3 numerical integration using cleaned ship geometry arrays."
    )
    parser.add_argument("excel_file", help="Path to workbook used for extraction")
    parser.add_argument(
        "--method",
        choices=["trapezoidal", "simpson"],
        default="trapezoidal",
        help="Integration method (default: trapezoidal)",
    )
    args = parser.parse_args()

    extracted = extract_ship_data(args.excel_file)
    offset = extracted.get("offset_table")
    if not offset:
        raise ValueError("Offset table was not extracted from the workbook.")

    stations = offset.get("stations")
    waterlines = offset.get("waterlines")
    offset_table_clean = offset.get("offset_table_clean")
    draft = extracted.get("draft")
    rho = extracted.get("rho")

    if stations is None or waterlines is None or offset_table_clean is None:
        raise ValueError("Cleaned offset data is incomplete (stations/waterlines/offset_table_clean missing).")
    if draft is None:
        raise ValueError("draft is missing. Provide draft before running phase 3 integration.")
    if rho is None:
        raise ValueError("rho is missing. Provide rho before running phase 3 integration.")

    results = compute_phase3(
        stations=stations,
        waterlines=waterlines,
        offset_table_clean=offset_table_clean,
        draft=float(draft),
        rho=float(rho),
        method=args.method,
    )
    print_phase3_results(results, rho=float(rho), method=args.method)


if __name__ == "__main__":
    main()
