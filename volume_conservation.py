"""Volume conservation checks across heel angles."""

from __future__ import annotations

import numpy as np
import pandas as pd

from Hydrohackathon.hull_geometry import (
    rotate_hull,
    integrate_heeled_volume_true_polygon,
    integrate_heeled_volume_true_polygon_simpson,
)


def run_volume_conservation(
    stations,
    waterlines,
    offset_table,
    draft: float,
    rho: float,
    heel_angles,
) -> pd.DataFrame:
    """Compute displaced-volume deviation using true clipped polygons at each station."""
    _ = rho
    upright_hull = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)
    v_upright = float(integrate_heeled_volume_true_polygon(upright_hull, z_wl=float(draft)))
    v_upright_simpson = float(integrate_heeled_volume_true_polygon_simpson(upright_hull, z_wl=float(draft)))

    rows = []
    for heel in heel_angles:
        heeled = rotate_hull(stations, waterlines, offset_table, heel_deg=float(heel))
        v_heeled = float(integrate_heeled_volume_true_polygon(heeled, z_wl=float(draft)))
        v_heeled_simpson = float(integrate_heeled_volume_true_polygon_simpson(heeled, z_wl=float(draft)))
        dev_pct = (v_heeled - v_upright) / max(v_upright, 1e-12) * 100.0
        dev_simpson_pct = (v_heeled_simpson - v_upright) / max(v_upright, 1e-12) * 100.0
        simpson_delta = v_heeled_simpson - v_heeled
        simpson_delta_pct = simpson_delta / max(v_heeled, 1e-12) * 100.0
        rows.append(
            {
                "heel_deg": float(heel),
                "V_upright_m3": float(v_upright),
                "V_upright_simpson_m3": float(v_upright_simpson),
                "V_heeled_m3": float(v_heeled),
                "V_heeled_simpson_m3": float(v_heeled_simpson),
                "deviation_pct": float(dev_pct),
                "deviation_abs_pct": float(abs(dev_pct)),
                "deviation_simpson_pct": float(dev_simpson_pct),
                "deviation_simpson_abs_pct": float(abs(dev_simpson_pct)),
                "simpson_minus_polygon_m3": float(simpson_delta),
                "simpson_minus_polygon_pct": float(simpson_delta_pct),
            }
        )

    return pd.DataFrame(rows)
