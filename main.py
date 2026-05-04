#!/usr/bin/env python3
"""
Naval Architecture Hydrostatics and Stability Analysis Pipeline
Complete end-to-end orchestration of all phases (1-10)

Usage:
    python main.py "HYDRO HACKATHON DATA.xlsx"
    python main.py "HYDRO HACKATHON DATA.xlsx" --output-dir ./results
"""

import sys
import argparse
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime

# Import all phase modules
from ship_excel_extractor import extract_ship_data
from integration import compute_phase3
from hydrostatics import compute_phase4
from stability import compute_phase5
from geometric_gz import compute_geometric_gz_curve
from gz_curve import (
    export_gz_csv,
    plot_gz_curve,
    generate_heel_angles,
    analyze_gz_curve,
    estimate_angle_of_vanishing_stability,
    estimate_deck_immersion_angle,
    plot_kn_curve,
)
from visualization_3d import plot_3d_hull_with_waterline
from insights import run_phase9


def validate_ship_data(ship_data, phase_name):
    """Validate ship_data dict for required keys and NaN values."""
    required_keys = ['offset_table', 'stations', 'waterlines', 'draft', 'rho', 'KG']
    for key in required_keys:
        if key not in ship_data:
            raise ValueError(f"{phase_name}: Missing required key '{key}' in ship_data")
    
    if np.isnan(ship_data['offset_table']).any():
        nan_count = np.isnan(ship_data['offset_table']).sum()
        raise ValueError(f"{phase_name}: {nan_count} NaN values in offset_table")
    
    print(f"  [OK] Data validation passed")

def _zero_crossing_after_peak(heel_deg: np.ndarray, gz_values: np.ndarray) -> float:
    """Return the first heel angle after the GZ peak where GZ crosses zero."""
    heel_arr = np.asarray(heel_deg, dtype=float)
    gz_arr = np.asarray(gz_values, dtype=float)
    if heel_arr.size == 0 or gz_arr.size == 0:
        return float("nan")
    if heel_arr.shape != gz_arr.shape:
        raise ValueError("heel_deg and gz_values must have the same shape")

    peak_idx = int(np.argmax(gz_arr))
    post_peak_heel = heel_arr[peak_idx:]
    post_peak_gz = gz_arr[peak_idx:]

    for idx in range(1, post_peak_heel.size):
        if post_peak_gz[idx - 1] >= 0.0 and post_peak_gz[idx] <= 0.0:
            return float(
                np.interp(
                    0.0,
                    [post_peak_gz[idx - 1], post_peak_gz[idx]],
                    [post_peak_heel[idx - 1], post_peak_heel[idx]],
                )
            )

    return float("nan")


def main():
    """
    Main orchestration function that runs all phases sequentially.
    """
    parser = argparse.ArgumentParser(
        description="Naval Architecture Pipeline: Complete Hydrostatics & Stability Analysis"
    )
    parser.add_argument("excel_file", help="Path to ship data Excel file")
    parser.add_argument("--output-dir", default=".", help="Output directory for results")
    
    try:
        args = parser.parse_args()
    except SystemExit:
        return None
    
    excel_file = Path(args.excel_file)
    output_dir = Path(args.output_dir)
    
    # Validate input file exists
    if not excel_file.exists():
        raise FileNotFoundError(f"Excel file not found: {excel_file}")
    
    # Create output directory if needed
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("\n" + "="*80)
    print("NAVAL ARCHITECTURE HYDROSTATICS AND STABILITY ANALYSIS PIPELINE")
    print("="*80)
    print(f"Input file: {excel_file}")
    print(f"Output directory: {output_dir}")
    print("="*80 + "\n")
    
    # ========================================================================
    # PHASE 1: Data Extraction
    # ========================================================================
    print("PHASE 1: Loading and extracting data from Excel...")
    try:
        extracted = extract_ship_data(str(excel_file))
        
        # Extract offset table and derived arrays
        offset_data = extracted['offset_table']
        if offset_data is None:
            raise ValueError("No offset table found in Excel file")
        
        # Convert lists to numpy arrays
        offset_table = np.array(offset_data['offset_table_clean'], dtype=float)
        stations = np.array(offset_data['stations'], dtype=float)
        waterlines = np.array(offset_data['waterlines'], dtype=float)
        
        # Extract scalars
        draft = extracted['draft']
        depth = extracted.get('depth')
        rho = extracted['rho']
        KG = extracted['KG']

        if depth is None:
            depth = float(np.max(waterlines))
        
        # Package for downstream phases
        ship_data = {
            'offset_table': offset_table,
            'stations': stations,
            'waterlines': waterlines,
            'draft': draft,
            'depth': depth,
            'rho': rho,
            'KG': KG,
            'spacing_type': extracted.get('spacing_type', 'unknown'),
        }
        
        validate_ship_data(ship_data, "Phase 1")
        
        print(f"  [OK] Offset table dimensions: {offset_table.shape}")
        print(f"  [OK] Stations: {len(stations)} points")
        print(f"  [OK] Waterlines: {len(waterlines)} points")
        print(f"  [OK] Draft: {draft:.4f} m, rho: {rho:.1f} kg/m3, KG: {KG:.4f} m")
        print("[OK] Phase 1 COMPLETED\n")
    except Exception as e:
        raise RuntimeError(f"Phase 1 failed: {str(e)}")
    
    # ========================================================================
    # PHASE 2: Geometry Validation
    # ========================================================================
    print("PHASE 2: Validating 3D geometric structure...")
    try:
        # Validate geometry dimensions
        n_waterlines, n_stations = offset_table.shape
        assert len(waterlines) == n_waterlines, \
            f"Waterlines length {len(waterlines)} != offset table rows {n_waterlines}"
        assert len(stations) == n_stations, \
            f"Stations length {len(stations)} != offset table cols {n_stations}"
        
        print(f"  [OK] Dimensions consistent: {n_waterlines} waterlines x {n_stations} stations")
        print(f"  [OK] Waterline range: {waterlines[0]:.4f} to {waterlines[-1]:.4f} m")
        print(f"  [OK] Station range: {stations[0]:.4f} to {stations[-1]:.4f} m")
        print("[OK] Phase 2 COMPLETED\n")
    except Exception as e:
        raise RuntimeError(f"Phase 2 failed: {str(e)}")
    
    # ========================================================================
    # PHASE 3: Numerical Integration (Sectional Areas & Volume)
    # ========================================================================
    print("PHASE 3: Computing sectional areas and displaced volume...")
    try:
        phase3_results = compute_phase3(
            stations=stations,
            waterlines=waterlines,
            offset_table_clean=offset_table,
            draft=draft,
            rho=rho
        )
        
        sectional_areas = phase3_results['sectional_areas']
        displaced_volume = phase3_results['displaced_volume']
        
        # Validate results
        assert not np.isnan(sectional_areas).any(), "NaN in sectional areas"
        assert not np.isnan(displaced_volume), "NaN in displaced volume"
        assert displaced_volume > 0, "Invalid displaced volume (non-positive)"
        
        print(f"  [OK] Sectional areas: {len(sectional_areas)} values")
        print(f"  [OK] Mean sectional area: {np.mean(sectional_areas):.2f} m2")
        print(f"  [OK] Max sectional area: {np.max(sectional_areas):.2f} m2")
        print(f"  [OK] Displaced volume: {displaced_volume:,.2f} m3")
        print("[OK] Phase 3 COMPLETED\n")
    except Exception as e:
        raise RuntimeError(f"Phase 3 failed: {str(e)}")
    
    # ========================================================================
    # PHASE 4: Hydrostatic Properties
    # ========================================================================
    print("PHASE 4: Computing hydrostatic properties...")
    try:
        phase4_results = compute_phase4(
            stations=stations,
            waterlines=waterlines,
            offset_table_clean=offset_table,
            sectional_areas=sectional_areas,
            displaced_volume=displaced_volume,
            draft=draft,
            rho=rho
        )
        
        LCB = phase4_results['LCB']
        LCF = phase4_results['LCF']
        KB = phase4_results['KB']
        Awp = phase4_results['waterplane_area_draft']
        
        # Validate results
        assert not any(np.isnan([LCB, LCF, KB, Awp])), "NaN in hydrostatic properties"
        assert KB > 0, "Invalid KB (non-positive)"
        assert Awp > 0, "Invalid waterplane area (non-positive)"
        
        print(f"  [OK] Vertical Center of Buoyancy (KB): {KB:.4f} m")
        print(f"  [OK] Longitudinal Center of Buoyancy (LCB): {LCB:.4f} m")
        print(f"  [OK] Longitudinal Center of Flotation (LCF): {LCF:.4f} m")
        print(f"  [OK] Waterplane Area (Awp): {Awp:,.2f} m2")
        print("[OK] Phase 4 COMPLETED\n")
    except Exception as e:
        raise RuntimeError(f"Phase 4 failed: {str(e)}")
    
    # ========================================================================
    # PHASE 5: Stability Metrics
    # ========================================================================
    print("PHASE 5: Computing stability metrics...")
    try:
        phase5_results = compute_phase5(
            stations=stations,
            waterlines=waterlines,
            offset_table_clean=offset_table,
            draft=draft,
            displaced_volume=displaced_volume,
            kb=KB,
            kg=KG
        )
        
        I_T = phase5_results['I_T']
        BM = phase5_results['BM']
        GM = phase5_results['GM']
        
        # Validate results
        assert not any(np.isnan([I_T, BM, GM])), "NaN in stability metrics"
        assert I_T > 0, "Invalid transverse second moment (non-positive)"
        assert BM > 0, "Invalid metacentric radius (non-positive)"
        
        # Stability classification
        if GM < 0:
            stability_class = "UNSTABLE"
        elif 0 <= GM < 1:
            stability_class = "TENDER"
        elif 1 <= GM <= 5:
            stability_class = "STABLE"
        else:  # GM > 5
            stability_class = "STIFF"
        
        print(f"  [OK] Transverse Second Moment (I_T): {I_T:,.2f} m4")
        print(f"  [OK] Metacentric Radius (BM): {BM:.4f} m")
        print(f"  [OK] Metacentric Height (GM): {GM:.4f} m")
        print(f"  [OK] Stability Classification: {stability_class}")
        print("[OK] Phase 5 COMPLETED\n")
    except Exception as e:
        raise RuntimeError(f"Phase 5 failed: {str(e)}")
    
    # ========================================================================
    # PHASE 6: GZ Curve (Righting Moment)
    # ========================================================================
    print("PHASE 6: Generating GZ righting curve (0–60°)...")
    try:
        # Generate heel angles (0 to 60 degrees in 1-degree steps)
        heel_deg = generate_heel_angles(max_angle_deg=60.0, step_deg=1.0)
        
        # Also compute extended heel angles (0 to 120°) for finding AVS
        heel_deg_extended = generate_heel_angles(max_angle_deg=120.0, step_deg=1.0)
        
        geometric = compute_geometric_gz_curve(
            stations=stations,
            waterlines=waterlines,
            offset_table=offset_table,
            draft=draft,
            rho=rho,
            KG=KG,
            heel_angles=heel_deg,
        )
        gz_values = np.asarray(geometric['gz_geometric'], dtype=float)
        gz_simplified = np.asarray(geometric['gz_simplified'], dtype=float)
        kn_values = np.asarray(geometric['kn_geometric'], dtype=float)
        
        # Compute extended GZ for finding vanishing stability angle
        geometric_extended = compute_geometric_gz_curve(
            stations=stations,
            waterlines=waterlines,
            offset_table=offset_table,
            draft=draft,
            rho=rho,
            KG=KG,
            heel_angles=heel_deg_extended,
        )
        gz_values_extended = np.asarray(geometric_extended['gz_geometric'], dtype=float)
        
        # Validate results
        assert len(heel_deg) > 0, "No heel angles generated"
        assert len(gz_values) > 0, "No GZ values generated"
        assert len(heel_deg) == len(gz_values), "Heel angles and GZ mismatch"
        assert not np.isnan(gz_values).any(), "NaN in GZ values"
        
        # Analyze GZ curve
        key_points = analyze_gz_curve(heel_deg, gz_values)
        max_gz = key_points['max_gz']
        max_gz_angle = key_points['angle_at_max_gz']

        assert not np.isnan(kn_values).any(), "NaN in KN values"
        assert np.isclose(kn_values[0], 0.0, atol=1e-9), "KN does not start at 0"
        volume_rel_error = np.asarray(geometric["volume_rel_error"], dtype=float)
        if np.max(volume_rel_error) > 1e-4:
            raise AssertionError(
                f"Volume conservation exceeded tolerance: max rel error {np.max(volume_rel_error):.3e}"
            )
        if len(kn_values) > 1 and np.min(np.diff(kn_values)) < -1e-6:
            print("  [INFO] KN is non-monotonic at large heel angles (geometric behavior)")

        max_kn_idx = int(np.argmax(kn_values))
        max_kn = float(kn_values[max_kn_idx])
        angle_max_kn = float(heel_deg[max_kn_idx])
        geo_gz_at_30 = float(gz_values[30]) if gz_values.size > 30 else float("nan")
        range_of_stability_deg = _zero_crossing_after_peak(heel_deg, gz_values)
        deck_immersion_deg = estimate_deck_immersion_angle(depth, draft, offset_table)
        # Use extended heel angles to find vanishing stability angle
        vanishing_stability_deg = estimate_angle_of_vanishing_stability(heel_deg_extended, gz_values_extended)
        max_volume_rel_error = float(np.max(volume_rel_error))
        
        # Package results for export
        gz_results = {
            'heel_angles': heel_deg,
            'gz_values': gz_values,
            'gz_simplified_values': gz_simplified,
            'kn_values': kn_values,
            'GM': GM,
            'max_gz': max_gz,
            'angle_at_max_gz': max_gz_angle,
            'max_kn': max_kn,
            'angle_at_max_kn': angle_max_kn,
        }
        
        # Export GZ curve to CSV
        gz_csv_path = output_dir / "gz_curve.csv"
        export_gz_csv(str(gz_csv_path), heel_deg, gz_values, gz_simplified=gz_simplified, kn=kn_values)
        
        # Export GZ curve plot to PNG
        gz_png_path = output_dir / "gz_curve.png"
        plot_gz_curve(
            heel_deg,
            gz_values,
            gz_simplified=gz_simplified,
            deck_immersion_angle_deg=deck_immersion_deg,
            vanishing_stability_angle_deg=vanishing_stability_deg,
            png_out=str(gz_png_path),
            show_plot=False,
        )

        kn_png_path = output_dir / "kn_curve.png"
        plot_kn_curve(heel_deg, kn_values, output_file=str(kn_png_path))
        
        print(f"  [OK] GZ curve heel range: 0 to {heel_deg[-1]:.1f} degrees")
        print(f"  [OK] GZ points: {len(gz_values)}")
        print(f"  [OK] Maximum GZ: {max_gz:.4f} m @ {max_gz_angle:.1f} degrees")
        if np.isfinite(deck_immersion_deg):
            print(f"  [OK] Deck reaches water: {deck_immersion_deg:.1f} degrees")
        if np.isfinite(vanishing_stability_deg):
            print(f"  [OK] Angle of vanishing stability: {vanishing_stability_deg:.1f} degrees")
        print(f"  [OK] Maximum KN: {max_kn:.4f} m @ {angle_max_kn:.1f} degrees")
        print(f"  [OK] CSV exported: {gz_csv_path.name}")
        print(f"  [OK] PNG exported: {gz_png_path.name}")
        print(f"  [OK] PNG exported: {kn_png_path.name}")
        print("[OK] Phase 6 COMPLETED\n")
    except Exception as e:
        raise RuntimeError(f"Phase 6 failed: {str(e)}")
    
    # ========================================================================
    # PHASE 8: 3D Hull Visualization
    # ========================================================================
    print("PHASE 8: Generating 3D hull visualization...")
    try:
        # Generate Plotly 3D visualization with waterline overlay
        html_path = output_dir / "hull_3d.html"
        plot_3d_hull_with_waterline(
            stations=stations,
            waterlines=waterlines,
            offset_table_clean=offset_table,
            draft=draft,
            output_file=str(html_path)
        )
        
        print(f"  [OK] Hull grid dimensions: {offset_table.shape[0]} x {offset_table.shape[1] * 2}")
        print(f"  [OK] Waterline plane created at z = {draft:.2f} m")
        print(f"  [OK] Interactive HTML exported: {html_path.name}")
        print("[OK] Phase 8 COMPLETED\n")
    except Exception as e:
        raise RuntimeError(f"Phase 8 failed: {str(e)}")
    
    # ========================================================================
    # PHASE 9: Insight Engine (Human-Readable Report)
    # ========================================================================
    print("PHASE 9: Generating insight engine report...")
    try:
        insights_txt_path = output_dir / "insights.txt"
        insights_results = run_phase9(
            excel_file=str(excel_file),
            output_file=str(insights_txt_path)
        )
        
        print(f"  [OK] Insight report generated: {insights_txt_path.name}")
        print("[OK] Phase 9 COMPLETED\n")
    except Exception as e:
        raise RuntimeError(f"Phase 9 failed: {str(e)}")
    
    # ========================================================================
    # PHASE 10: Results Summary and Aggregation
    # ========================================================================
    print("PHASE 10: Generating results summary...")
    try:
        # Calculate displacement mass
        displacement_mass = displaced_volume * rho
        displacement_mass_tonnes = displacement_mass / 1000
        
        # Create comprehensive results dataframe
        results_data = {
            'Parameter': [
                'Draft',
                'Displaced Volume',
                'Displacement Mass',
                'Mean Sectional Area',
                'Max Sectional Area',
                'Longitudinal Center of Buoyancy (LCB)',
                'Longitudinal Center of Flotation (LCF)',
                'Vertical Center of Buoyancy (KB)',
                'Waterplane Area',
                'Transverse Second Moment (I_T)',
                'Metacentric Radius (BM)',
                'Metacentric Height (GM)',
                'Stability Classification',
                'Maximum Righting Arm (GZ)',
                'Angle at Max GZ',
                'Maximum KN',
                'Angle at Max KN',
                'Geometric GZ at 30 Degrees',
                'Range of Stability',
                'Max Volume Rel Error',
                'Fluid Density',
                'Vertical Center of Gravity (assumed)',
            ],
            'Unit': [
                'm',
                'm³',
                'tonnes',
                'm²',
                'm²',
                'm',
                'm',
                'm',
                'm²',
                'm⁴',
                'm',
                'm',
                '—',
                'm',
                '°',
                'm',
                '°',
                'm',
                '°',
                '—',
                'kg/m³',
                'm',
            ],
            'Value': [
                f"{draft:.4f}",
                f"{displaced_volume:,.2f}",
                f"{displacement_mass_tonnes:,.2f}",
                f"{np.mean(sectional_areas):.2f}",
                f"{np.max(sectional_areas):.2f}",
                f"{LCB:.4f}",
                f"{LCF:.4f}",
                f"{KB:.4f}",
                f"{Awp:,.2f}",
                f"{I_T:,.2f}",
                f"{BM:.4f}",
                f"{GM:.4f}",
                stability_class,
                f"{max_gz:.4f}",
                f"{max_gz_angle:.1f}",
                f"{max_kn:.4f}",
                f"{angle_max_kn:.1f}",
                f"{geo_gz_at_30:.4f}",
                f"{range_of_stability_deg:.1f}",
                f"{max_volume_rel_error:.6f}",
                f"{rho:.1f}",
                f"{KG:.4f}",
            ]
        }
        
        results_df = pd.DataFrame(results_data)
        results_csv_path = output_dir / "results.csv"
        results_df.to_csv(results_csv_path, index=False)
        
        print(f"  [OK] Results table created: {len(results_data['Parameter'])} parameters")
        print(f"  [OK] CSV exported: {results_csv_path.name}")
        print("[OK] Phase 10 COMPLETED\n")
    except Exception as e:
        raise RuntimeError(f"Phase 10 failed: {str(e)}")
    
    # ========================================================================
    # FINAL SUMMARY
    # ========================================================================
    print("="*80)
    print("=== FINAL SUMMARY ===")
    print("="*80)
    print(f"Draft: {draft:.2f} m")
    print(f"Displaced Volume: {displaced_volume:,.2f} m³")
    print(f"Displacement Mass: {displacement_mass_tonnes:,.2f} tonnes")
    print(f"Metacentric Height (GM): {GM:.2f} m")
    print(f"Max Righting Arm (GZ): {max_gz:.2f} m @ {max_gz_angle:.1f}°")
    print(f"Max KN: {max_kn:.2f} m @ {angle_max_kn:.1f}°")
    print(f"Stability Classification: {stability_class}")
    print("\n=== OUTPUT FILES ===")
    print(f"[OK] results.csv")
    print(f"[OK] gz_curve.csv")
    print(f"[OK] gz_curve.png")
    print(f"[OK] kn_curve.png")
    print(f"[OK] hull_3d.html")
    print(f"[OK] insights.txt")
    print("="*80)
    print("All outputs generated successfully!")
    print("="*80 + "\n")
    
    # Return aggregated results for programmatic use
    return {
        'ship_data': ship_data,
        'phase3_results': phase3_results,
        'phase4_results': phase4_results,
        'phase5_results': phase5_results,
        'gz_results': gz_results,
        'displacement_mass_tonnes': displacement_mass_tonnes,
        'stability_class': stability_class,
    }


if __name__ == "__main__":
    try:
        results = main()
    except FileNotFoundError as e:
        print(f"\n[ERROR] FILE NOT FOUND: {e}")
        sys.exit(1)
    except RuntimeError as e:
        print(f"\n[ERROR] PIPELINE ERROR: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
