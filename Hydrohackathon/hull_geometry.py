"""Heeled hull geometry utilities for geometric KN/GZ workflows."""

from __future__ import annotations

import numpy as np
from scipy.integrate import simpson


def _as_1d(name: str, values) -> np.ndarray:
    arr = np.asarray(values, dtype=float).reshape(-1)
    if arr.size == 0:
        raise ValueError(f"{name} must not be empty.")
    if np.isnan(arr).any():
        raise ValueError(f"{name} contains NaN values.")
    if np.any(np.diff(arr) <= 0.0):
        raise ValueError(f"{name} must be strictly increasing.")
    return arr


def _as_2d(name: str, values) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 2:
        raise ValueError(f"{name} must be a 2D array.")
    if arr.size == 0:
        raise ValueError(f"{name} must not be empty.")
    if np.isnan(arr).any():
        raise ValueError(f"{name} contains NaN values.")
    return arr


def rotate_hull(stations, waterlines, offset_table, heel_deg: float) -> dict[str, np.ndarray | float]:
    """Rotate port and starboard half-breadths around x-axis by heel angle."""
    x = _as_1d("stations", stations)
    z = _as_1d("waterlines", waterlines)
    y_half = _as_2d("offset_table", offset_table)

    expected_shape = (z.size, x.size)
    if y_half.shape != expected_shape:
        raise ValueError(f"offset_table shape {y_half.shape} does not match expected {expected_shape}.")

    x_grid = np.tile(x, (z.size, 1))
    z_grid = np.tile(z[:, np.newaxis], (1, x.size))

    theta = float(np.deg2rad(float(heel_deg)))
    c = float(np.cos(theta))
    s = float(np.sin(theta))

    y_stbd = y_half * c - z_grid * s
    z_stbd = y_half * s + z_grid * c

    y_port_raw = -y_half
    y_port = y_port_raw * c - z_grid * s
    z_port = y_port_raw * s + z_grid * c

    return {
        "x": x_grid.astype(float),
        "y_stbd": y_stbd.astype(float),
        "z_stbd": z_stbd.astype(float),
        "y_port": y_port.astype(float),
        "z_port": z_port.astype(float),
        "heel_deg": float(heel_deg),
    }


def _station_submerged_profiles(heeled_hull: dict, station_idx: int, z_wl: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    y_stbd = np.asarray(heeled_hull["y_stbd"], dtype=float)[:, station_idx]
    z_stbd = np.asarray(heeled_hull["z_stbd"], dtype=float)[:, station_idx]
    y_port = np.asarray(heeled_hull["y_port"], dtype=float)[:, station_idx]
    z_port = np.asarray(heeled_hull["z_port"], dtype=float)[:, station_idx]

    order_stbd = np.argsort(z_stbd)
    order_port = np.argsort(z_port)
    z_stbd_s = z_stbd[order_stbd]
    y_stbd_s = y_stbd[order_stbd]
    z_port_s = z_port[order_port]
    y_port_s = y_port[order_port]

    z_min = max(float(min(z_stbd_s[0], z_port_s[0])), -1e9)
    z_top = float(z_wl)
    if z_top <= z_min:
        return np.array([], dtype=float), np.array([], dtype=float), np.array([], dtype=float)

    z_candidates = np.concatenate(
        [
            z_stbd_s[(z_stbd_s >= z_min) & (z_stbd_s <= z_top)],
            z_port_s[(z_port_s >= z_min) & (z_port_s <= z_top)],
            np.array([z_min, z_top], dtype=float),
        ]
    )
    z_eval = np.unique(z_candidates)
    if z_eval.size < 2:
        return np.array([], dtype=float), np.array([], dtype=float), np.array([], dtype=float)

    y_right = np.interp(z_eval, z_stbd_s, y_stbd_s, left=y_stbd_s[0], right=y_stbd_s[-1])
    y_left = np.interp(z_eval, z_port_s, y_port_s, left=y_port_s[0], right=y_port_s[-1])
    return z_eval, y_left, y_right


def _clip_polygon_below_waterline(points_yz: np.ndarray, z_wl: float) -> np.ndarray:
    """Clip a closed polygon in (y, z) coordinates to the half-plane z <= z_wl."""
    if points_yz.shape[0] < 3:
        return np.empty((0, 2), dtype=float)

    clipped: list[np.ndarray] = []
    n = points_yz.shape[0]
    eps = 1e-12

    def inside(p: np.ndarray) -> bool:
        return bool(p[1] <= float(z_wl) + eps)

    def intersect(p1: np.ndarray, p2: np.ndarray) -> np.ndarray:
        z1 = float(p1[1])
        z2 = float(p2[1])
        if abs(z2 - z1) <= eps:
            return np.array([float(p2[0]), float(z_wl)], dtype=float)
        t = (float(z_wl) - z1) / (z2 - z1)
        y = float(p1[0]) + t * (float(p2[0]) - float(p1[0]))
        return np.array([y, float(z_wl)], dtype=float)

    for i in range(n):
        curr = points_yz[i]
        prev = points_yz[i - 1]
        curr_in = inside(curr)
        prev_in = inside(prev)

        if curr_in:
            if not prev_in:
                clipped.append(intersect(prev, curr))
            clipped.append(curr.astype(float))
        elif prev_in:
            clipped.append(intersect(prev, curr))

    if len(clipped) < 3:
        return np.empty((0, 2), dtype=float)

    clipped_arr = np.asarray(clipped, dtype=float)
    if not np.allclose(clipped_arr[0], clipped_arr[-1], atol=1e-12):
        clipped_arr = np.vstack([clipped_arr, clipped_arr[0]])
    return clipped_arr


def _polygon_area(points_yz: np.ndarray) -> float:
    """Return absolute area of a closed polygon in (y, z)."""
    if points_yz.shape[0] < 4:
        return 0.0
    y = points_yz[:, 0]
    z = points_yz[:, 1]
    return float(0.5 * abs(np.sum(y[:-1] * z[1:] - y[1:] * z[:-1])))


def _station_submerged_polygon_area(heeled_hull: dict, station_idx: int, z_wl: float) -> float:
    """Compute submerged cross-sectional area at one station using polygon clipping only."""
    y_stbd = np.asarray(heeled_hull["y_stbd"], dtype=float)[:, station_idx]
    z_stbd = np.asarray(heeled_hull["z_stbd"], dtype=float)[:, station_idx]
    y_port = np.asarray(heeled_hull["y_port"], dtype=float)[:, station_idx]
    z_port = np.asarray(heeled_hull["z_port"], dtype=float)[:, station_idx]

    order_port = np.argsort(z_port)
    order_stbd = np.argsort(z_stbd)

    port_curve = np.column_stack([y_port[order_port], z_port[order_port]])
    stbd_curve = np.column_stack([y_stbd[order_stbd][::-1], z_stbd[order_stbd][::-1]])

    section_polygon = np.vstack([port_curve, stbd_curve])
    if not np.allclose(section_polygon[0], section_polygon[-1], atol=1e-12):
        section_polygon = np.vstack([section_polygon, section_polygon[0]])

    clipped = _clip_polygon_below_waterline(section_polygon, z_wl=float(z_wl))
    return _polygon_area(clipped)


def integrate_heeled_volume_true_polygon(heeled_hull: dict, z_wl: float) -> float:
    """Integrate displaced volume from clipped station polygons using section-to-section slabs."""
    x_grid = np.asarray(heeled_hull["x"], dtype=float)
    x = x_grid[0, :]
    if x.size < 2:
        return 0.0

    sectional_areas = np.zeros_like(x, dtype=float)
    for j in range(x.size):
        sectional_areas[j] = _station_submerged_polygon_area(heeled_hull, j, float(z_wl))

    volume = 0.0
    for j in range(x.size - 1):
        dx = float(x[j + 1] - x[j])
        volume += 0.5 * float(sectional_areas[j] + sectional_areas[j + 1]) * dx
    return max(float(volume), 0.0)


def integrate_heeled_volume_true_polygon_simpson(heeled_hull: dict, z_wl: float) -> float:
    """Integrate displaced volume from clipped station polygons using Simpson along stations."""
    x_grid = np.asarray(heeled_hull["x"], dtype=float)
    x = x_grid[0, :]
    if x.size < 2:
        return 0.0

    sectional_areas = np.zeros_like(x, dtype=float)
    for j in range(x.size):
        sectional_areas[j] = _station_submerged_polygon_area(heeled_hull, j, float(z_wl))

    if x.size >= 3:
        volume = float(simpson(sectional_areas, x=x))
    else:
        volume = float(np.trapz(sectional_areas, x))
    return max(volume, 0.0)


def integrate_heeled_volume(heeled_hull: dict, z_wl: float) -> float:
    """Integrate submerged volume below a horizontal waterplane in rotated coordinates."""
    x_grid = np.asarray(heeled_hull["x"], dtype=float)
    x = x_grid[0, :]

    sectional_areas = np.zeros_like(x, dtype=float)
    for j in range(x.size):
        z_eval, y_left, y_right = _station_submerged_profiles(heeled_hull, j, float(z_wl))
        if z_eval.size < 2:
            sectional_areas[j] = 0.0
            continue
        breadth = np.maximum(y_right - y_left, 0.0)
        sectional_areas[j] = float(np.trapz(breadth, z_eval))

    volume = float(np.trapz(sectional_areas, x))
    return max(volume, 0.0)


def integrate_heeled_volume_simpson(heeled_hull: dict, z_wl: float) -> float:
    """Integrate submerged volume using Simpson's rule where possible."""
    x_grid = np.asarray(heeled_hull["x"], dtype=float)
    x = x_grid[0, :]

    sectional_areas = np.zeros_like(x, dtype=float)
    for j in range(x.size):
        z_eval, y_left, y_right = _station_submerged_profiles(heeled_hull, j, float(z_wl))
        if z_eval.size < 2:
            sectional_areas[j] = 0.0
            continue

        breadth = np.maximum(y_right - y_left, 0.0)
        if z_eval.size >= 3:
            sectional_areas[j] = float(simpson(breadth, x=z_eval))
        else:
            sectional_areas[j] = float(np.trapz(breadth, z_eval))

    if x.size >= 3:
        volume = float(simpson(sectional_areas, x=x))
    else:
        volume = float(np.trapz(sectional_areas, x))
    return max(volume, 0.0)


def find_heeled_waterplane(
    heeled_hull: dict,
    target_volume: float,
    tol: float = 1e-4,
    max_iter: int = 80,
) -> float:
    """Find waterplane elevation using bisection so displaced volume matches target."""
    z_all = np.concatenate(
        [
            np.asarray(heeled_hull["z_stbd"], dtype=float).reshape(-1),
            np.asarray(heeled_hull["z_port"], dtype=float).reshape(-1),
        ]
    )
    z_low = float(np.min(z_all))
    z_high = float(np.max(z_all))

    v_low = integrate_heeled_volume(heeled_hull, z_low)
    v_high = integrate_heeled_volume(heeled_hull, z_high)

    target = float(target_volume)
    if target < v_low - tol or target > v_high + tol:
        raise RuntimeError(
            "Geometric infeasibility: no horizontal waterplane can match the target displaced volume "
            "for this hull orientation."
        )

    for _ in range(max_iter):
        z_mid = 0.5 * (z_low + z_high)
        v_mid = integrate_heeled_volume(heeled_hull, z_mid)
        if abs(v_mid - target) <= tol:
            return float(z_mid)
        if v_mid < target:
            z_low = z_mid
        else:
            z_high = z_mid

    return float(0.5 * (z_low + z_high))


def heeled_buoyancy_centroid(heeled_hull: dict, z_wl: float) -> tuple[float, float]:
    """Compute submerged buoyancy centroid (y_B, z_B) in rotated frame."""
    x_grid = np.asarray(heeled_hull["x"], dtype=float)
    x = x_grid[0, :]

    area_x = np.zeros_like(x, dtype=float)
    my_x = np.zeros_like(x, dtype=float)
    mz_x = np.zeros_like(x, dtype=float)

    for j in range(x.size):
        z_eval, y_left, y_right = _station_submerged_profiles(heeled_hull, j, float(z_wl))
        if z_eval.size < 2:
            continue

        breadth = np.maximum(y_right - y_left, 0.0)
        area_x[j] = float(np.trapz(breadth, z_eval))

        # First moment in transverse direction: integral_z [ 0.5 * (y_r^2 - y_l^2) ] dz
        my_integrand = 0.5 * (y_right**2 - y_left**2)
        my_x[j] = float(np.trapz(my_integrand, z_eval))

        # First moment in vertical direction: integral_z [ z * breadth ] dz
        mz_x[j] = float(np.trapz(z_eval * breadth, z_eval))

    volume = float(np.trapz(area_x, x))
    if volume <= 0.0:
        raise RuntimeError("Submerged volume is zero; cannot compute buoyancy centroid.")

    my = float(np.trapz(my_x, x))
    mz = float(np.trapz(mz_x, x))

    return float(my / volume), float(mz / volume)
