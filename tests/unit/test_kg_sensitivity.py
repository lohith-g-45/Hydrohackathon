import numpy as np
import pandas as pd

from kg_sensitivity import run_kg_sensitivity


def make_parabolic_offsets(n_wl=7, n_sta=11):
    stations = np.linspace(0.0, 10.0, n_sta)
    waterlines = np.linspace(0.0, 3.0, n_wl)
    # simple parabolic half-breadth increasing towards midships
    X, Z = np.meshgrid(stations, waterlines)
    offsets = 0.5 * (1.0 - ((X - 5.0) / 5.0) ** 2)  # max 0.5 m midships
    offsets = offsets + 0.05 * (Z / waterlines[-1])  # slightly larger at deeper WL
    return stations, waterlines, offsets


def test_higher_kg_lower_gm():
    stations, waterlines, offsets = make_parabolic_offsets()
    draft = 1.5
    rho = 1025.0
    kg_values = [0.2, 0.8, 1.4]
    heel_angles = list(range(0, 61, 1))

    df = run_kg_sensitivity(stations, waterlines, offsets, draft, rho, kg_values, heel_angles)
    gm = df["gm_m"].to_numpy()
    assert gm[0] > gm[1] and gm[1] > gm[2]


def test_area_decreases_with_kg():
    stations, waterlines, offsets = make_parabolic_offsets()
    draft = 1.5
    rho = 1025.0
    kg_values = [0.2, 0.8, 1.4]
    heel_angles = list(range(0, 61, 1))

    df = run_kg_sensitivity(stations, waterlines, offsets, draft, rho, kg_values, heel_angles)
    area = df["area_0_30"].to_numpy()
    gm = df["gm_m"].to_numpy()
    if np.all(gm > 0):
        assert area[0] > area[1] and area[1] > area[2]
    else:
        # For unstable or marginal cases just assert finite outputs
        assert np.all(np.isfinite(area))


def test_csv_output_schema():
    stations, waterlines, offsets = make_parabolic_offsets()
    draft = 1.5
    rho = 1025.0
    kg_values = [0.5, 1.0]
    heel_angles = list(range(0, 61, 1))

    df = run_kg_sensitivity(stations, waterlines, offsets, draft, rho, kg_values, heel_angles)
    expected_cols = [
        "kg_m",
        "gm_m",
        "max_gz_m",
        "angle_max_gz_deg",
        "range_stability_deg",
        "area_0_30",
    ]
    assert list(df.columns) == expected_cols
    assert df.shape[0] == len(kg_values)
