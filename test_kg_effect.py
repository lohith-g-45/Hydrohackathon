#!/usr/bin/env python3
"""Test how KG affects AVS and stability parameters."""

import numpy as np
from gz_curve import estimate_angle_of_vanishing_stability, estimate_deck_immersion_angle
from geometric_gz import compute_geometric_gz_curve as _compute_geometric_gz_curve
from ship_excel_extractor import extract_ship_data

# Load data
extracted = extract_ship_data('HYDRO HACKATHON DATA.xlsx')
offset = extracted['offset_table']
stations = offset['stations']
waterlines = offset['waterlines']
offset_table = offset['offset_table_clean']
draft = extracted['draft']
rho = extracted['rho']
depth = extracted.get('depth', 40)

print('Current KG: 24.846 m')
print('\nEffect of lowering KG on Stability:\n')
print(f"{'KG (m)':<8} {'GM (m)':<8} {'Max GZ (m)':<12} {'Angle of Max GZ':<16} {'AVS (deg)':<10}")
print("-" * 65)

for kg_test in [24.846, 24.0, 23.0, 22.0, 21.0, 20.0]:
    heel_deg = np.linspace(0, 120, 121)
    
    try:
        geo = _compute_geometric_gz_curve(
            offset_table=offset_table,
            stations=stations,
            waterlines=waterlines,
            heel_angles=heel_deg,
            KG=kg_test,
            draft=draft,
            depth=depth,
            rho=rho,
        )
        gz_values = np.asarray(geo['gz_geometric'], dtype=float)
        gm = geo['GM']
        
        avs = estimate_angle_of_vanishing_stability(heel_deg, gz_values)
        max_gz_idx = np.argmax(gz_values)
        max_gz = float(gz_values[max_gz_idx])
        angle_max_gz = float(heel_deg[max_gz_idx])
        
        marker = " ← CURRENT" if kg_test == 24.846 else ""
        print(f"{kg_test:<8.2f} {gm:<8.4f} {max_gz:<12.2f} {angle_max_gz:<16.0f} {avs:<10.0f}{marker}")
    except Exception as e:
        print(f"{kg_test:<8.2f} ERROR: {str(e)[:40]}")

print("\n" + "="*65)
print("Key Insight:")
print("  • Lowering KG = Higher initial stability (bigger GM)")
print("  • But lower KG = Lower GZ at large angles = Lower AVS")
print("  • Ideal: Deck immersion angle (15.6°) should be > 25-30°")
print("  • To increase deck immersion angle, increase DEPTH (freeboard)")
print("="*65)
