import argparse
from typing import Dict

import numpy as np

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


def _interpolate_breadths_at_draft(
    waterlines: np.ndarray,
    offset_table_clean: np.ndarray,
    draft: float,
) -> np.ndarray:
    """Return half-breadths at draft, with interpolation if draft is not a tabulated waterline."""
    tol = 1e-12
    idx_exact = np.where(np.isclose(waterlines, draft, atol=tol, rtol=0.0))[0]
    if idx_exact.size:
        return offset_table_clean[idx_exact[0], :]

    if draft < waterlines[0] or draft > waterlines[-1]:
        raise ValueError("draft is outside the range of waterlines.")

    i_upper = int(np.searchsorted(waterlines, draft, side="right"))
    i_lower = i_upper - 1

    z0, z1 = waterlines[i_lower], waterlines[i_upper]
    b0, b1 = offset_table_clean[i_lower, :], offset_table_clean[i_upper, :]

    t = (draft - z0) / (z1 - z0)
    return b0 + t * (b1 - b0)


def _prepare_underwater_waterplane_areas(
    stations: np.ndarray,
    waterlines: np.ndarray,
    offset_table_clean: np.ndarray,
    draft: float,
) -> Dict[str, np.ndarray]:
    """Build underwater z grid and corresponding waterplane areas up to draft.

    Uses actual stations and actual waterline elevations. If draft is not exactly
    tabulated in waterlines, an interpolated row at draft is added.
    """
    mask = waterlines <= (draft + 1e-12)
    if np.count_nonzero(mask) < 2:
        raise ValueError("Need at least two waterlines at or below draft.")

    wl_used = waterlines[mask]
    offsets_used = offset_table_clean[mask, :]

    if not np.isclose(wl_used[-1], draft, atol=1e-12, rtol=0.0):
        draft_row = _interpolate_breadths_at_draft(waterlines, offset_table_clean, draft)
        wl_used = np.concatenate([wl_used, [draft]])
        offsets_used = np.vstack([offsets_used, draft_row])

    waterplane_areas = np.zeros(wl_used.size, dtype=float)
    for i, _z in enumerate(wl_used):
        half_breadths = offsets_used[i, :]
        full_breadths = 2.0 * half_breadths
        waterplane_areas[i] = trapezoidal_rule(stations, full_breadths)

    return {
        "waterlines_used": wl_used,
        "waterplane_areas": waterplane_areas,
    }


def compute_lcb(stations, sectional_areas) -> float:
    """LCB = integral(x * A(x) dx) / integral(A(x) dx)."""
    x = _as_1d_float_array("stations", stations)
    a = _as_1d_float_array("sectional_areas", sectional_areas)

    if x.size != a.size:
        raise ValueError("stations and sectional_areas must have the same length.")
    _validate_increasing("stations", x)

    volume = trapezoidal_rule(x, a)
    if abs(volume) < 1e-12:
        raise ValueError("Displaced volume is zero; cannot compute LCB.")

    moment_x = trapezoidal_rule(x, x * a)
    return float(moment_x / volume)


def compute_waterplane_area(stations, draft_breadths) -> float:
    """Compute waterplane area at draft from half-breadths along stations.

    full breadth B(x) = 2 * half-breadth, then Awp = integral(B(x) dx).
    """
    x = _as_1d_float_array("stations", stations)
    hb = _as_1d_float_array("draft_breadths", draft_breadths)

    if x.size != hb.size:
        raise ValueError("stations and draft_breadths must have the same length.")
    _validate_increasing("stations", x)

    full_breadths = 2.0 * hb
    return float(trapezoidal_rule(x, full_breadths))


def compute_lcf(stations, draft_breadths) -> float:
    """LCF = integral(x * B(x) dx) / integral(B(x) dx), where B(x) is full breadth."""
    x = _as_1d_float_array("stations", stations)
    hb = _as_1d_float_array("draft_breadths", draft_breadths)

    if x.size != hb.size:
        raise ValueError("stations and draft_breadths must have the same length.")
    _validate_increasing("stations", x)

    full_breadths = 2.0 * hb
    awp = trapezoidal_rule(x, full_breadths)
    if abs(awp) < 1e-12:
        raise ValueError("Waterplane area is zero; cannot compute LCF.")

    moment_x = trapezoidal_rule(x, x * full_breadths)
    return float(moment_x / awp)


def compute_kb(stations, waterlines, offset_table_clean, draft) -> float:
    """KB = integral(z * Awp(z) dz) / integral(Awp(z) dz), using z <= draft only."""
    x = _as_1d_float_array("stations", stations)
    z = _as_1d_float_array("waterlines", waterlines)
    hb_table = _as_2d_float_array("offset_table_clean", offset_table_clean)
    d = float(draft)

    if np.isnan(d):
        raise ValueError("draft contains NaN value.")

    _validate_increasing("stations", x)
    _validate_increasing("waterlines", z)

    expected_shape = (z.size, x.size)
    if hb_table.shape != expected_shape:
        raise ValueError(
            f"offset_table_clean shape {hb_table.shape} does not match expected {expected_shape}."
        )

    underwater = _prepare_underwater_waterplane_areas(x, z, hb_table, d)
    z_used = underwater["waterlines_used"]
    awp = underwater["waterplane_areas"]

    vol = trapezoidal_rule(z_used, awp)
    if abs(vol) < 1e-12:
        raise ValueError("Underwater volume is zero; cannot compute KB.")

    moment_z = trapezoidal_rule(z_used, z_used * awp)
    return float(moment_z / vol)


def compute_phase4(
    stations,
    waterlines,
    offset_table_clean,
    sectional_areas,
    displaced_volume: float,
    draft: float,
    rho: float,
) -> Dict[str, float | int]:
    x = _as_1d_float_array("stations", stations)
    z = _as_1d_float_array("waterlines", waterlines)
    hb_table = _as_2d_float_array("offset_table_clean", offset_table_clean)
    a_sec = _as_1d_float_array("sectional_areas", sectional_areas)

    if x.size != a_sec.size:
        raise ValueError("sectional_areas length must match stations length.")

    expected_shape = (z.size, x.size)
    if hb_table.shape != expected_shape:
        raise ValueError(
            f"offset_table_clean shape {hb_table.shape} does not match expected {expected_shape}."
        )

    _validate_increasing("stations", x)
    _validate_increasing("waterlines", z)

    d = float(draft)
    rho_val = float(rho)
    vol = float(displaced_volume)

    if np.isnan(d) or np.isnan(rho_val) or np.isnan(vol):
        raise ValueError("draft, rho, and displaced_volume must be valid numbers.")

    if vol <= 0.0:
        raise ValueError("displaced_volume must be positive.")

    # Draft waterplane breadths from the half-breadth table.
    draft_half_breadths = _interpolate_breadths_at_draft(z, hb_table, d)

    lcb = compute_lcb(x, a_sec)
    awp_draft = compute_waterplane_area(x, draft_half_breadths)
    lcf = compute_lcf(x, draft_half_breadths)
    kb = compute_kb(x, z, hb_table, d)

    underwater = _prepare_underwater_waterplane_areas(x, z, hb_table, d)
    z_used = underwater["waterlines_used"]

    return {
        "draft": d,
        "waterlines_used_count": int(z_used.size),
        "nan_check_passed": 1,
        "displaced_volume": vol,
        "displacement_mass": vol * rho_val,
        "waterplane_area_draft": awp_draft,
        "LCB": lcb,
        "LCF": lcf,
        "KB": kb,
    }


def print_phase4_results(results: Dict[str, float | int]) -> None:
    print("\n=== PHASE 4: HYDROSTATICS RESULTS ===")
    print(f"Draft used                  : {results['draft']:.4f} m")
    print(f"Number of waterlines used   : {results['waterlines_used_count']} (z <= draft)")
    print(f"No NaN values check         : {'PASSED' if results['nan_check_passed'] == 1 else 'FAILED'}")

    print("\nPrimary hydrostatics:")
    print(f"Displaced volume            : {results['displaced_volume']:.4f} m^3")
    print(f"Displacement mass           : {results['displacement_mass']:.4f} kg")
    print(f"Waterplane area at draft    : {results['waterplane_area_draft']:.4f} m^2")
    print(f"LCB                         : {results['LCB']:.4f} m")
    print(f"LCF                         : {results['LCF']:.4f} m")
    print(f"KB                          : {results['KB']:.4f} m")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 4 hydrostatics computation engine.")
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

    if stations is None or waterlines is None or offset_table_clean is None:
        raise ValueError("stations/waterlines/offset_table_clean are missing.")
    if draft is None:
        raise ValueError("draft is missing.")
    if rho is None:
        raise ValueError("rho is missing.")

    phase3 = compute_phase3(
        stations=stations,
        waterlines=waterlines,
        offset_table_clean=offset_table_clean,
        draft=float(draft),
        rho=float(rho),
        method="trapezoidal",
    )

    sectional_areas = phase3["sectional_areas"]
    displaced_volume = float(phase3["displaced_volume"])

    results = compute_phase4(
        stations=stations,
        waterlines=waterlines,
        offset_table_clean=offset_table_clean,
        sectional_areas=sectional_areas,
        displaced_volume=displaced_volume,
        draft=float(draft),
        rho=float(rho),
    )
    print_phase4_results(results)


if __name__ == "__main__":
    main()
