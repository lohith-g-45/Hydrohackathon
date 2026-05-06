"""Geometric GZ / KN cross-curve calculations built on heeled hull integration."""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from hydrostatics import compute_phase4
from Hydrohackathon.hull_geometry import (
    find_heeled_waterplane,
    heeled_buoyancy_centroid,
    integrate_heeled_volume,
    rotate_hull,
)
from integration import compute_phase3
from stability import compute_phase5

logger = logging.getLogger(__name__)


def _rotate_back_to_upright(y_heeled: float, z_heeled: float, heel_rad: float) -> tuple[float, float]:
    cos_theta = float(np.cos(heel_rad))
    sin_theta = float(np.sin(heel_rad))
    y_upright = y_heeled * cos_theta + z_heeled * sin_theta
    z_upright = -y_heeled * sin_theta + z_heeled * cos_theta
    return float(y_upright), float(z_upright)


def _as_1d_float_array(name: str, values) -> NDArray[np.float64]:
    arr = np.asarray(values, dtype=float).reshape(-1)
    if arr.size == 0:
        raise ValueError(f"{name} must not be empty.")
    if np.isnan(arr).any():
        raise ValueError(f"{name} contains NaN values.")
    return arr


def _estimate_angle_of_vanishing_stability(heel_deg: NDArray[np.float64], gz: NDArray[np.float64]) -> float:
    peak_idx = int(np.argmax(gz))
    post_peak_heel = heel_deg[peak_idx:]
    post_peak_gz = gz[peak_idx:]

    for idx in range(1, post_peak_heel.size):
        left_gz = float(post_peak_gz[idx - 1])
        right_gz = float(post_peak_gz[idx])
        if left_gz >= 0.0 and right_gz <= 0.0:
            return float(
                np.interp(
                    0.0,
                    [left_gz, right_gz],
                    [float(post_peak_heel[idx - 1]), float(post_peak_heel[idx])],
                )
            )

    return float("nan")


def _estimate_deck_immersion_angle(
    waterlines: NDArray[np.float64],
    draft: float,
    offset_table: NDArray[np.float64],
) -> float:
    depth = float(np.max(waterlines))
    freeboard = max(depth - float(draft), 0.0)
    if freeboard <= 0.0:
        return 0.0

    half_breadth = float(np.max(offset_table))
    if not np.isfinite(half_breadth) or half_breadth <= 0.0:
        return float("nan")

    return float(np.degrees(np.arctan2(freeboard, half_breadth)))


def compute_geometric_gz_curve(
    offset_table,
    stations,
    waterlines,
    heel_angles,
    KG: float,
    draft: float | None = None,
    depth: float | None = None,
    rho: float = 1025.0,
    volume_tol: float = 1e-4,
) -> dict[str, np.ndarray | float]:
    """Compute true geometric GZ from submerged heeled geometry."""
    stations_arr = _as_1d_float_array("stations", stations)
    waterlines_arr = _as_1d_float_array("waterlines", waterlines)
    offset_table_arr = np.asarray(offset_table, dtype=float)
    heel_angles_arr = _as_1d_float_array("heel_angles", heel_angles)

    if offset_table_arr.ndim != 2:
        raise ValueError("offset_table must be a 2D array.")
    if np.isnan(offset_table_arr).any():
        raise ValueError("offset_table contains NaN values.")

    if offset_table_arr.shape != (waterlines_arr.size, stations_arr.size):
        raise ValueError(
            "offset_table shape must match (len(waterlines), len(stations)). "
            f"Got {offset_table_arr.shape}, expected {(waterlines_arr.size, stations_arr.size)}."
        )

    draft_value = float(waterlines_arr[-1] if draft is None else draft)
    rho_value = float(rho)
    kg_value = float(KG)
    if np.isnan(draft_value) or np.isnan(rho_value) or np.isnan(kg_value) or np.isnan(volume_tol):
        raise ValueError("draft, rho, KG, and volume_tol must be valid numbers.")
    if volume_tol <= 0.0:
        raise ValueError("volume_tol must be positive.")

    phase3 = compute_phase3(
        stations=stations_arr,
        waterlines=waterlines_arr,
        offset_table_clean=offset_table_arr,
        draft=draft_value,
        rho=rho_value,
        method="trapezoidal",
    )
    phase4 = compute_phase4(
        stations=stations_arr,
        waterlines=waterlines_arr,
        offset_table_clean=offset_table_arr,
        sectional_areas=phase3["sectional_areas"],
        displaced_volume=float(phase3["displaced_volume"]),
        draft=draft_value,
        rho=rho_value,
    )
    phase5 = compute_phase5(
        stations=stations_arr,
        waterlines=waterlines_arr,
        offset_table_clean=offset_table_arr,
        draft=draft_value,
        displaced_volume=float(phase4["displaced_volume"]),
        kb=float(phase4["KB"]),
        kg=kg_value,
    )

    upright_volume = float(phase3["displaced_volume"])
    gm = float(phase5["GM"])

    heel_rad = np.deg2rad(heel_angles_arr)
    gz_geometric = np.zeros_like(heel_rad, dtype=float)
    kn_geometric = np.zeros_like(heel_rad, dtype=float)
    gz_simplified = gm * np.sin(heel_rad)
    kn_simplified = gz_simplified + kg_value * np.sin(heel_rad)
    waterplane_elevations = np.zeros_like(heel_rad, dtype=float)
    buoyancy_y = np.zeros_like(heel_rad, dtype=float)
    buoyancy_z = np.zeros_like(heel_rad, dtype=float)
    buoyancy_transverse_arm = np.zeros_like(heel_rad, dtype=float)
    heeled_volume = np.zeros_like(heel_rad, dtype=float)
    volume_rel_error = np.zeros_like(heel_rad, dtype=float)

    computed_count = 0
    truncation_reason = ""
    truncation_mode = ""
    first_unachievable_heel_deg = float("nan")

    for idx, heel_deg in enumerate(heel_angles_arr):
        try:
            heeled_hull = rotate_hull(stations_arr, waterlines_arr, offset_table_arr, float(heel_deg))
            z_wl = find_heeled_waterplane(heeled_hull, upright_volume, tol=1e-4)
            v_heeled = integrate_heeled_volume(heeled_hull, z_wl)
            rel_error = abs(v_heeled - upright_volume) / max(abs(upright_volume), 1e-12)
            if rel_error > volume_tol:
                raise RuntimeError(
                    f"Volume conservation failed at {heel_deg:.2f} deg: "
                    f"relative error {rel_error:.3e} > tolerance {volume_tol:.3e}."
                )

            y_heeled, z_heeled = heeled_buoyancy_centroid(heeled_hull, z_wl)
            y_upright, z_upright = _rotate_back_to_upright(y_heeled, z_heeled, heel_rad[idx])

            gz_geometric[idx] = -(
                y_upright * np.cos(heel_rad[idx])
                + (z_upright - kg_value) * np.sin(heel_rad[idx])
            )
            kn_geometric[idx] = gz_geometric[idx] + kg_value * np.sin(heel_rad[idx])
            by_arm = kn_geometric[idx]
            waterplane_elevations[idx] = z_wl
            buoyancy_y[idx] = y_upright
            buoyancy_z[idx] = z_upright
            buoyancy_transverse_arm[idx] = by_arm
            heeled_volume[idx] = v_heeled
            volume_rel_error[idx] = rel_error
            computed_count = idx + 1
        except RuntimeError as exc:
            if idx == 0:
                raise RuntimeError(f"Geometric GZ failed at {heel_deg:.2f} deg: {exc}") from exc
            truncation_reason = str(exc)
            if "Geometric infeasibility:" in truncation_reason:
                truncation_mode = "geometric-infeasible"
            elif "Volume conservation failed" in truncation_reason:
                truncation_mode = "volume-tolerance"
            else:
                truncation_mode = "runtime-error"
            first_unachievable_heel_deg = float(heel_deg)
            break

    heel_angles_used = heel_angles_arr[:computed_count]
    heel_rad_used = heel_rad[:computed_count]
    gz_geometric = gz_geometric[:computed_count]
    kn_geometric = kn_geometric[:computed_count]
    gz_simplified = gz_simplified[:computed_count]
    kn_simplified = kn_simplified[:computed_count]
    waterplane_elevations = waterplane_elevations[:computed_count]
    buoyancy_y = buoyancy_y[:computed_count]
    buoyancy_z = buoyancy_z[:computed_count]
    buoyancy_transverse_arm = buoyancy_transverse_arm[:computed_count]
    heeled_volume = heeled_volume[:computed_count]
    volume_rel_error = volume_rel_error[:computed_count]

    zero_idx = np.where(np.isclose(heel_angles_used, 0.0, atol=1e-12))[0]
    if zero_idx.size > 0:
        gz_zero = float(gz_geometric[int(zero_idx[0])])
        if abs(gz_zero) > 1e-3:
            raise RuntimeError(
                f"Geometric GZ sanity check failed at 0 deg: GZ(0)={gz_zero:.6f} m"
            )

    max_gz_idx = int(np.argmax(gz_geometric))
    max_kn_idx = int(np.argmax(kn_geometric))
    deck_reference_levels = waterlines_arr
    if depth is not None and np.isfinite(float(depth)):
        deck_reference_levels = np.append(waterlines_arr, float(depth))

    deck_immersion_angle_deg = _estimate_deck_immersion_angle(
        waterlines=np.asarray(deck_reference_levels, dtype=float),
        draft=draft_value,
        offset_table=offset_table_arr,
    )
    angle_of_vanishing_stability_deg = _estimate_angle_of_vanishing_stability(
        heel_deg=heel_angles_used,
        gz=gz_geometric,
    )

    logger.info(
        "Computed geometric GZ for %d heel angles. max|volume_rel_error|=%.3e",
        heel_angles_used.size,
        float(np.max(volume_rel_error)),
    )

    return {
        "heel_deg": heel_angles_used.astype(float),
        "heel_rad": heel_rad_used.astype(float),
        "GM": gm,
        "upright_volume_m3": upright_volume,
        "heeled_volume_m3": heeled_volume,
        "volume_rel_error": volume_rel_error,
        "waterplane_elevation": waterplane_elevations,
        "buoyancy_y": buoyancy_y,
        "buoyancy_z": buoyancy_z,
        "buoyancy_transverse_arm": buoyancy_transverse_arm,
        "gz_geometric": gz_geometric,
        "kn_geometric": kn_geometric,
        "gz_simplified": gz_simplified,
        "kn_simplified": kn_simplified,
        "max_gz_geometric": float(gz_geometric[max_gz_idx]),
        "angle_at_max_gz_geometric": float(heel_angles_used[max_gz_idx]),
        "max_kn_geometric": float(kn_geometric[max_kn_idx]),
        "angle_at_max_kn_geometric": float(heel_angles_used[max_kn_idx]),
        "deck_immersion_angle_deg": float(deck_immersion_angle_deg),
        "angle_of_vanishing_stability_deg": float(angle_of_vanishing_stability_deg),
        "requested_max_heel_deg": float(heel_angles_arr[-1]),
        "computed_max_heel_deg": float(heel_angles_used[-1]),
        "first_unachievable_heel_deg": float(first_unachievable_heel_deg),
        "truncated_due_to_infeasible_volume": bool(bool(truncation_reason)),
        "truncation_mode": truncation_mode,
        "truncation_reason": truncation_reason,
    }


def geometric_gz_to_frame(df: dict[str, np.ndarray | float]) -> pd.DataFrame:
    """Convert a geometric GZ result dictionary into a tabular DataFrame."""
    return pd.DataFrame(
        {
            "heel_deg": df["heel_deg"],
            "gz_geometric": df["gz_geometric"],
            "gz_simplified": df["gz_simplified"],
            "kn_geometric": df["kn_geometric"],
            "kn_simplified": df["kn_simplified"],
            "buoyancy_y": df["buoyancy_y"],
            "buoyancy_z": df["buoyancy_z"],
            "buoyancy_transverse_arm": df["buoyancy_transverse_arm"],
            "volume_rel_error": df["volume_rel_error"],
        }
    )