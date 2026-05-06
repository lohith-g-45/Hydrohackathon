"""KG sensitivity analysis for GM/GZ trends."""

from __future__ import annotations

import numpy as np
import pandas as pd

from hydrostatics import compute_phase4
from integration import compute_phase3


def _range_of_stability_deg(gm: float) -> float:
	if gm <= 0.0:
		return 0.0
	return 180.0


def run_kg_sensitivity(
	stations,
	waterlines,
	offset_table,
	draft: float,
	rho: float,
	kg_values,
	heel_angles,
) -> pd.DataFrame:
	stations_arr = np.asarray(stations, dtype=float)
	waterlines_arr = np.asarray(waterlines, dtype=float)
	offsets_arr = np.asarray(offset_table, dtype=float)
	heels = np.asarray(heel_angles, dtype=float)

	phase3 = compute_phase3(
		stations=stations_arr,
		waterlines=waterlines_arr,
		offset_table_clean=offsets_arr,
		draft=float(draft),
		rho=float(rho),
		method="trapezoidal",
	)
	phase4 = compute_phase4(
		stations=stations_arr,
		waterlines=waterlines_arr,
		offset_table_clean=offsets_arr,
		sectional_areas=phase3["sectional_areas"],
		displaced_volume=float(phase3["displaced_volume"]),
		draft=float(draft),
		rho=float(rho),
	)

	kb = float(phase4["KB"])
	bm_proxy = float(phase4["waterplane_area_draft"]) / max(float(phase4["displaced_volume"]), 1e-12)

	rows = []
	for kg in np.asarray(kg_values, dtype=float):
		gm = kb + bm_proxy - float(kg)
		gz = gm * np.sin(np.deg2rad(heels))

		max_idx = int(np.argmax(gz))
		area_0_30 = 0.0
		mask_30 = heels <= 30.0
		if np.any(mask_30):
			area_0_30 = float(np.trapz(np.maximum(gz[mask_30], 0.0), np.deg2rad(heels[mask_30])))

		rows.append(
			{
				"kg_m": float(kg),
				"gm_m": float(gm),
				"max_gz_m": float(gz[max_idx]),
				"angle_max_gz_deg": float(heels[max_idx]),
				"range_stability_deg": float(_range_of_stability_deg(gm)),
				"area_0_30": float(area_0_30),
			}
		)

	return pd.DataFrame(
		rows,
		columns=[
			"kg_m",
			"gm_m",
			"max_gz_m",
			"angle_max_gz_deg",
			"range_stability_deg",
			"area_0_30",
		],
	)


__all__ = ["run_kg_sensitivity"]
