import argparse
from typing import Dict, Tuple

import numpy as np
import plotly.graph_objects as go

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


def build_full_hull_grid(stations, waterlines, offset_table_clean) -> Dict[str, np.ndarray]:
    """Build full hull 3D coordinate grids from cleaned offset data.

    Returns X_full, Y_full, Z_full where:
    - X_full: station coordinates (both sides mirrored)
    - Y_full: full breadths (port and starboard)
    - Z_full: waterline elevations (both sides mirrored)

    Grid shapes: (num_waterlines, 2 * num_stations)
    """
    x = _as_1d_float_array("stations", stations)
    z = _as_1d_float_array("waterlines", waterlines)
    hb_table = _as_2d_float_array("offset_table_clean", offset_table_clean)

    _validate_increasing("stations", x)
    _validate_increasing("waterlines", z)

    expected_shape = (z.size, x.size)
    if hb_table.shape != expected_shape:
        raise ValueError(
            f"offset_table_clean shape {hb_table.shape} does not match expected {expected_shape}."
        )

    # Half-hull grid (starboard side).
    X_half = np.tile(x, (z.size, 1))
    Z_half = np.tile(z.reshape(-1, 1), (1, x.size))
    Y_half = hb_table.copy()

    # Full hull by mirroring about centerline y=0.
    # Port side: negative y from left-right flipped half-hull.
    # Starboard side: positive y from original half-hull.
    X_full = np.concatenate([np.fliplr(X_half), X_half], axis=1)
    Z_full = np.concatenate([np.fliplr(Z_half), Z_half], axis=1)
    Y_full = np.concatenate([-np.fliplr(Y_half), Y_half], axis=1)

    return {
        "X_full": X_full,
        "Y_full": Y_full,
        "Z_full": Z_full,
    }


def create_waterline_plane(stations, y_min: float, y_max: float, draft: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create a horizontal plane at draft elevation spanning full x-y extent.

    Returns X_plane, Y_plane, Z_plane for plotly surface.
    """
    x = _as_1d_float_array("stations", stations)
    d = float(draft)
    y_min_val = float(y_min)
    y_max_val = float(y_max)

    if np.isnan(d) or np.isnan(y_min_val) or np.isnan(y_max_val):
        raise ValueError("draft, y_min, y_max must be valid numbers.")

    # Create a 2D plane grid.
    x_plane = x
    y_plane = np.linspace(y_min_val, y_max_val, max(5, len(x) // 4))

    X_plane, Y_plane = np.meshgrid(x_plane, y_plane)
    Z_plane = np.full_like(X_plane, d, dtype=float)

    return X_plane, Y_plane, Z_plane


def plot_3d_hull_with_waterline(
    stations,
    waterlines,
    offset_table_clean,
    draft: float,
    output_file: str = "hull_3d.html",
) -> None:
    """Create interactive 3D hull visualization with waterline plane.

    Saves interactive Plotly plot as HTML.
    """
    x = _as_1d_float_array("stations", stations)
    z = _as_1d_float_array("waterlines", waterlines)
    hb_table = _as_2d_float_array("offset_table_clean", offset_table_clean)

    grid = build_full_hull_grid(x, z, hb_table)
    X_full = grid["X_full"]
    Y_full = grid["Y_full"]
    Z_full = grid["Z_full"]

    y_min = float(np.min(Y_full))
    y_max = float(np.max(Y_full))

    X_plane, Y_plane, Z_plane = create_waterline_plane(x, y_min, y_max, draft)

    fig = go.Figure()

    # Add full hull surface (both port and starboard).
    fig.add_trace(
        go.Surface(
            x=X_full,
            y=Y_full,
            z=Z_full,
            colorscale="Viridis",
            name="Hull Surface",
            opacity=0.8,
            showscale=False,
        )
    )

    # Add waterline plane.
    fig.add_trace(
        go.Surface(
            x=X_plane,
            y=Y_plane,
            z=Z_plane,
            colorscale="Reds",
            name="Waterline (Draft = {:.2f}m)".format(draft),
            opacity=0.6,
            showscale=False,
        )
    )

    fig.update_layout(
        title="3D Hull Visualization with Waterline at Draft",
        scene=dict(
            xaxis_title="Length / Stations (m)",
            yaxis_title="Breadth (m)",
            zaxis_title="Height (m)",
            camera=dict(
                eye=dict(x=1.5, y=1.5, z=1.5),
            ),
        ),
        autosize=True,
        width=1000,
        height=800,
        showlegend=True,
    )

    fig.write_html(output_file)


def run_phase8(excel_file: str, output_file: str = "hull_3d.html") -> Dict[str, np.ndarray | float | str]:
    """Execute Phase 8 3D visualization end-to-end."""
    extracted = extract_ship_data(excel_file)
    offset = extracted.get("offset_table")
    if not offset:
        raise ValueError("Offset table is missing in extracted data.")

    stations = offset.get("stations")
    waterlines = offset.get("waterlines")
    offset_table_clean = offset.get("offset_table_clean")
    draft = extracted.get("draft")

    if stations is None or waterlines is None or offset_table_clean is None:
        raise ValueError("stations/waterlines/offset_table_clean are missing.")
    if draft is None:
        raise ValueError("draft is missing.")

    plot_3d_hull_with_waterline(stations, waterlines, offset_table_clean, draft, output_file)

    grid = build_full_hull_grid(stations, waterlines, offset_table_clean)
    X_full = grid["X_full"]

    return {
        "hull_shape": X_full.shape,
        "draft": float(draft),
        "output_file": output_file,
    }


def print_phase8_results(results: Dict[str, np.ndarray | float | str]) -> None:
    print("\n=== PHASE 8: 3D HULL VISUALIZATION ===")
    hull_shape = results["hull_shape"]
    assert isinstance(hull_shape, tuple)
    print(f"Hull grid shape (waterlines x stations)  : {hull_shape[0]} x {hull_shape[1]}")
    print(f"Draft used for waterline plane          : {float(results['draft']):.4f} m")
    print(f"Output file                              : {str(results['output_file'])}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 8: 3D hull visualization with waterline simulation.")
    parser.add_argument("excel_file", help="Path to workbook")
    parser.add_argument("--output", type=str, default="hull_3d.html", help="Output HTML file path")
    args = parser.parse_args()

    results = run_phase8(
        excel_file=args.excel_file,
        output_file=args.output,
    )
    print_phase8_results(results)


if __name__ == "__main__":
    main()
