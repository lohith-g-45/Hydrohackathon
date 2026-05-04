"""Geometric GZ / KN cross-curve calculations built on heeled hull integration."""
from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from hydrostatics import compute_phase4
from Hydrohackathon.hull_geometry import find_heeled_waterplane, heeled_buoyancy_centroid, rotate_hull
from integration import compute_phase3
from stability import compute_phase5


def _as_1d_float_array(name: str, values) -> NDArray[np.float64]:
    arr = np.asarray(values, dtype=float).reshape(-1)
    if arr.size == 0:
        raise ValueError(f"{name} must not be empty.")
    if np.isnan(arr).any():
        raise ValueError(f"{name} contains NaN values.")
    return arr


def _rotate_back_to_upright(
    y_heeled: float,
    z_heeled: float,
    heel_rad: float,
) -> tuple[float, float]:
    cos_theta = float(np.cos(heel_rad))
    sin_theta = float(np.sin(heel_rad))
    y_upright = y_heeled * cos_theta + z_heeled * sin_theta
    z_upright = -y_heeled * sin_theta + z_heeled * cos_theta
    return float(y_upright), float(z_upright)


def compute_geometric_gz_curve(
    stations,
    waterlines,
    offset_table,
    draft: float,
    rho: float,
    KG: float,
    heel_angles,
) -> dict[str, np.ndarray | float]:
    """Compute geometric and simplified GZ / KN curves across heel angles."""
    stations_arr = _as_1d_float_array("stations", stations)
    waterlines_arr = _as_1d_float_array("waterlines", waterlines)
    offset_table_arr = np.asarray(offset_table, dtype=float)
    heel_angles_arr = _as_1d_float_array("heel_angles", heel_angles)

    if offset_table_arr.ndim != 2:
        raise ValueError("offset_table must be a 2D array.")
    if np.isnan(offset_table_arr).any():
        raise ValueError("offset_table contains NaN values.")

    draft_value = float(draft)
    rho_value = float(rho)
    kg_value = float(KG)
    if np.isnan(draft_value) or np.isnan(rho_value) or np.isnan(kg_value):
        raise ValueError("draft, rho, and KG must be valid numbers.")

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

    for idx, heel_deg in enumerate(heel_angles_arr):
        heeled_hull = rotate_hull(stations_arr, waterlines_arr, offset_table_arr, float(heel_deg))
        z_wl = find_heeled_waterplane(heeled_hull, upright_volume, tol=1e-4)
        y_heeled, z_heeled = heeled_buoyancy_centroid(heeled_hull, z_wl)
        y_upright, z_upright = _rotate_back_to_upright(y_heeled, z_heeled, heel_rad[idx])

        gz_geometric[idx] = -(
            y_upright * np.cos(heel_rad[idx]) + (z_upright - kg_value) * np.sin(heel_rad[idx])
        )
        kn_geometric[idx] = gz_geometric[idx] + kg_value * np.sin(heel_rad[idx])
        waterplane_elevations[idx] = z_wl
        buoyancy_y[idx] = y_upright
        buoyancy_z[idx] = z_upright

    max_gz_idx = int(np.argmax(gz_geometric))
    max_kn_idx = int(np.argmax(kn_geometric))

    return {
        "heel_deg": heel_angles_arr.astype(float),
        "heel_rad": heel_rad.astype(float),
        "GM": gm,
        "upright_volume_m3": upright_volume,
        "waterplane_elevation": waterplane_elevations,
        "buoyancy_y_upright": buoyancy_y,
        "buoyancy_z_upright": buoyancy_z,
        "gz_geometric": gz_geometric,
        "kn_geometric": kn_geometric,
        "gz_simplified": gz_simplified,
        "kn_simplified": kn_simplified,
        "max_gz_geometric": float(gz_geometric[max_gz_idx]),
        "angle_at_max_gz_geometric": float(heel_angles_arr[max_gz_idx]),
        "max_kn_geometric": float(kn_geometric[max_kn_idx]),
        "angle_at_max_kn_geometric": float(heel_angles_arr[max_kn_idx]),
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
        }
    )