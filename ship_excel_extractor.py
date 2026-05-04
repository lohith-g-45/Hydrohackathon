import argparse
import json
import re
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


KEYWORDS = {
    "station_spacing": ["station spacing", "spacing station", "station interval", "stn spacing"],
    "waterline_spacing": ["waterline spacing", "wl spacing", "spacing waterline", "waterline interval"],
    "draft": ["draft", "draught"],
    "depth": ["depth", "moulded depth", "hull depth"],
    "rho": ["rho", "fluid density", "density", "water density"],
    "KG": ["kg", "k.g", "vertical cg", "vcg", "center of gravity", "centre of gravity"],
}

OFFSET_HINTS = ["offset", "offsets", "half-breadth", "half breadth", "breadth", "table of offsets"]

DEFAULT_SEAWATER_RHO = 1025.0


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and np.isnan(value):
        return ""
    return str(value).strip().lower()


def parse_numeric(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float, np.number)) and not pd.isna(value):
        return float(value)

    text = normalize_text(value)
    if not text:
        return None

    match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text)
    if not match:
        return None

    try:
        return float(match.group(0))
    except ValueError:
        return None


def clean_dataframe_nan(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.copy()
    cleaned = cleaned.dropna(axis=0, how="all").dropna(axis=1, how="all")
    return cleaned


def map_dataframe(df: pd.DataFrame, func) -> pd.DataFrame:
    return df.apply(lambda col: col.map(func))


def table_to_clean_list(df: pd.DataFrame) -> List[List[Optional[float]]]:
    table: List[List[Optional[float]]] = []
    for row in df.to_numpy().tolist():
        cleaned_row: List[Optional[float]] = []
        for val in row:
            if val is None or (isinstance(val, float) and np.isnan(val)):
                cleaned_row.append(None)
            else:
                cleaned_row.append(float(val))
        table.append(cleaned_row)
    return table


def split_offset_table_components(raw_table: List[List[Optional[float]]]) -> Dict[str, Any]:
    arr = np.array(raw_table, dtype=object)
    if arr.ndim != 2 or arr.shape[0] < 3 or arr.shape[1] < 3:
        return {
            "stations": [],
            "station_labels": [],
            "waterlines": [],
            "offset_table_clean": [],
            "offset_table_clean_shape": {"rows": 0, "cols": 0},
        }

    # Required slicing for integration-ready data:
    # stations = raw_table[0, 2:]
    # station_labels = raw_table[1, 2:]
    # waterlines = raw_table[2:, 1]
    # offset_table_clean = raw_table[2:, 2:]
    stations = arr[0, 2:]
    station_labels = arr[1, 2:]
    waterlines = arr[2:, 1]
    offset_table_clean = arr[2:, 2:]

    def to_float_list(values: np.ndarray) -> List[Optional[float]]:
        out: List[Optional[float]] = []
        for v in values.tolist():
            if v is None or (isinstance(v, float) and np.isnan(v)):
                out.append(None)
            else:
                out.append(float(v))
        return out

    def to_float_matrix(values: np.ndarray) -> List[List[Optional[float]]]:
        matrix: List[List[Optional[float]]] = []
        for row in values.tolist():
            cleaned_row: List[Optional[float]] = []
            for v in row:
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    cleaned_row.append(None)
                else:
                    cleaned_row.append(float(v))
            matrix.append(cleaned_row)
        return matrix

    cleaned_matrix = to_float_matrix(offset_table_clean)
    rows = len(cleaned_matrix)
    cols = len(cleaned_matrix[0]) if rows else 0

    return {
        "stations": to_float_list(stations),
        "station_labels": to_float_list(station_labels),
        "waterlines": to_float_list(waterlines),
        "offset_table_clean": cleaned_matrix,
        "offset_table_clean_shape": {"rows": rows, "cols": cols},
    }


def _ensure_numeric_array(name: str, values: Any) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        raise ValueError(f"{name} is empty.")
    return arr


def build_hull_geometry(
    stations: Any,
    waterlines: Any,
    offset_table_clean: Any,
) -> Dict[str, np.ndarray]:
    """Build half-hull and full-hull geometric grids from offset data.

    Coordinate system:
    - x: ship longitudinal axis (stations)
    - y: transverse axis (half-breadths, mirrored for full hull)
    - z: vertical axis (waterlines)
    """
    stations_arr = _ensure_numeric_array("stations", stations).reshape(-1)
    waterlines_arr = _ensure_numeric_array("waterlines", waterlines).reshape(-1)
    offsets_arr = _ensure_numeric_array("offset_table_clean", offset_table_clean)

    if offsets_arr.ndim != 2:
        raise ValueError("offset_table_clean must be a 2D array.")

    expected_shape = (waterlines_arr.size, stations_arr.size)
    if offsets_arr.shape != expected_shape:
        raise ValueError(
            "Shape mismatch: offset_table_clean has shape "
            f"{offsets_arr.shape}, expected {expected_shape}."
        )

    if offsets_arr.shape != (11, 23):
        raise ValueError(
            "Unexpected cleaned table shape. Expected (11, 23) for this dataset, "
            f"got {offsets_arr.shape}."
        )

    if np.isnan(stations_arr).any() or np.isnan(waterlines_arr).any() or np.isnan(offsets_arr).any():
        raise ValueError("NaN detected in stations, waterlines, or offset_table_clean.")

    # Half hull grid (starboard side) aligned with offset_table_clean[row, col].
    # row -> waterline (z), col -> station (x)
    X_half = np.tile(stations_arr, (waterlines_arr.size, 1))
    Z_half = np.tile(waterlines_arr.reshape(-1, 1), (1, stations_arr.size))
    Y_half = offsets_arr.copy()

    # Full hull by mirroring half-breadths about centerline y=0.
    X_full = np.concatenate([np.fliplr(X_half), X_half], axis=1)
    Z_full = np.concatenate([np.fliplr(Z_half), Z_half], axis=1)
    Y_full = np.concatenate([-np.fliplr(Y_half), Y_half], axis=1)

    return {
        "X_half": X_half,
        "Y_half": Y_half,
        "Z_half": Z_half,
        "X_full": X_full,
        "Y_full": Y_full,
        "Z_full": Z_full,
    }


def print_hull_geometry_debug(geometry: Dict[str, np.ndarray]) -> None:
    xh, yh, zh = geometry["X_half"], geometry["Y_half"], geometry["Z_half"]
    xf, yf, zf = geometry["X_full"], geometry["Y_full"], geometry["Z_full"]

    print("\n[Hull Geometry Validation]")
    print(f"Half hull grid shape (X, Y, Z): {xh.shape}, {yh.shape}, {zh.shape}")
    print(f"Full hull grid shape (X, Y, Z): {xf.shape}, {yf.shape}, {zf.shape}")

    print("\n[Coordinate Ranges]")
    print(f"X range: {float(np.min(xf))} to {float(np.max(xf))}")
    print(f"Y range: {float(np.min(yf))} to {float(np.max(yf))}")
    print(f"Z range: {float(np.min(zf))} to {float(np.max(zf))}")

    sample_indices = [
        (0, 0),
        (0, -1),
        (xh.shape[0] // 2, xh.shape[1] // 2),
        (-1, 0),
        (-1, -1),
    ]
    print("\n[Sample Half-Hull Points] (x, y, z)")
    for i, j in sample_indices:
        print(f"({float(xh[i, j])}, {float(yh[i, j])}, {float(zh[i, j])})")

    sample_indices_full = [
        (0, 0),
        (0, -1),
        (xf.shape[0] // 2, xf.shape[1] // 2),
        (-1, 0),
        (-1, -1),
    ]
    print("\n[Sample Full-Hull Points] (x, y, z)")
    for i, j in sample_indices_full:
        print(f"({float(xf[i, j])}, {float(yf[i, j])}, {float(zf[i, j])})")


def plot_hull_surfaces(geometry: Dict[str, np.ndarray]) -> None:
    try:
        import plotly.graph_objects as go
    except ImportError:
        print("Plotly not installed. Install with: py -3 -m pip install plotly")
        return

    half_fig = go.Figure(
        data=[
            go.Surface(
                x=geometry["X_half"],
                y=geometry["Y_half"],
                z=geometry["Z_half"],
                colorscale="Viridis",
                name="Half Hull",
                showscale=False,
            )
        ]
    )
    half_fig.update_layout(
        title="Half Hull Surface (Starboard)",
        scene=dict(xaxis_title="x", yaxis_title="y", zaxis_title="z"),
    )

    full_fig = go.Figure(
        data=[
            go.Surface(
                x=geometry["X_full"],
                y=geometry["Y_full"],
                z=geometry["Z_full"],
                colorscale="Turbo",
                name="Full Hull",
                showscale=False,
            )
        ]
    )
    full_fig.update_layout(
        title="Full Hull Surface (Port + Starboard)",
        scene=dict(xaxis_title="x", yaxis_title="y", zaxis_title="z"),
    )

    half_fig.show()
    full_fig.show()


def find_keyword_value_candidates(df: pd.DataFrame, sheet_name: str) -> Dict[str, List[Dict[str, Any]]]:
    candidates: Dict[str, List[Dict[str, Any]]] = {k: [] for k in KEYWORDS}

    rows, cols = df.shape
    for r in range(rows):
        for c in range(cols):
            cell_text = normalize_text(df.iat[r, c])
            if not cell_text:
                continue

            for field_name, terms in KEYWORDS.items():
                if any(term in cell_text for term in terms):
                    neighbor_positions = []

                    # Check nearby cells in the same row.
                    for cc in range(max(0, c - 4), min(cols, c + 5)):
                        if cc != c:
                            neighbor_positions.append((r, cc))

                    # Check nearby cells in the same column.
                    for rr in range(max(0, r - 4), min(rows, r + 5)):
                        if rr != r:
                            neighbor_positions.append((rr, c))

                    # Check immediate diagonal neighbors as fallback.
                    for rr in range(max(0, r - 1), min(rows, r + 2)):
                        for cc in range(max(0, c - 1), min(cols, c + 2)):
                            if rr != r or cc != c:
                                neighbor_positions.append((rr, cc))

                    seen = set()
                    for rr, cc in neighbor_positions:
                        if (rr, cc) in seen:
                            continue
                        seen.add((rr, cc))

                        num = parse_numeric(df.iat[rr, cc])
                        if num is not None:
                            candidates[field_name].append(
                                {
                                    "value": num,
                                    "sheet": sheet_name,
                                    "keyword_cell": (r, c),
                                    "value_cell": (rr, cc),
                                    "keyword_text": cell_text,
                                }
                            )
    return candidates


def contiguous_numeric_blocks(df: pd.DataFrame) -> List[Tuple[int, int, int, int]]:
    numeric_mask = map_dataframe(df, lambda x: parse_numeric(x) is not None).to_numpy()
    visited = np.zeros_like(numeric_mask, dtype=bool)

    blocks: List[Tuple[int, int, int, int]] = []
    rows, cols = numeric_mask.shape

    directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]

    for r in range(rows):
        for c in range(cols):
            if not numeric_mask[r, c] or visited[r, c]:
                continue

            q = deque([(r, c)])
            visited[r, c] = True
            min_r = max_r = r
            min_c = max_c = c

            while q:
                rr, cc = q.popleft()
                min_r = min(min_r, rr)
                max_r = max(max_r, rr)
                min_c = min(min_c, cc)
                max_c = max(max_c, cc)

                for dr, dc in directions:
                    nr, nc = rr + dr, cc + dc
                    if 0 <= nr < rows and 0 <= nc < cols and numeric_mask[nr, nc] and not visited[nr, nc]:
                        visited[nr, nc] = True
                        q.append((nr, nc))

            blocks.append((min_r, max_r, min_c, max_c))

    return blocks


def score_offset_candidate(df: pd.DataFrame, block: Tuple[int, int, int, int], sheet_name: str) -> float:
    r0, r1, c0, c1 = block
    height = r1 - r0 + 1
    width = c1 - c0 + 1
    size_score = height * width

    expanded_r0 = max(0, r0 - 2)
    expanded_r1 = min(df.shape[0] - 1, r1 + 2)
    expanded_c0 = max(0, c0 - 2)
    expanded_c1 = min(df.shape[1] - 1, c1 + 2)

    neighborhood = df.iloc[expanded_r0 : expanded_r1 + 1, expanded_c0 : expanded_c1 + 1]
    neighborhood_text = " ".join(normalize_text(v) for v in neighborhood.to_numpy().ravel())

    hint_score = 0
    for hint in OFFSET_HINTS:
        if hint in neighborhood_text:
            hint_score += 25
        if hint in sheet_name.lower():
            hint_score += 25

    shape_bonus = 20 if height >= 4 and width >= 4 else 0
    return size_score + hint_score + shape_bonus


def extract_offset_table(excel_file: pd.ExcelFile) -> Optional[Dict[str, Any]]:
    best: Optional[Dict[str, Any]] = None

    for sheet in excel_file.sheet_names:
        raw = pd.read_excel(excel_file, sheet_name=sheet, header=None)
        df = clean_dataframe_nan(raw)
        if df.empty:
            continue

        blocks = contiguous_numeric_blocks(df)
        for block in blocks:
            r0, r1, c0, c1 = block
            height = r1 - r0 + 1
            width = c1 - c0 + 1
            if height < 2 or width < 2:
                continue

            candidate_df = df.iloc[r0 : r1 + 1, c0 : c1 + 1]
            candidate_df = clean_dataframe_nan(candidate_df)
            if candidate_df.empty:
                continue

            score = score_offset_candidate(df, block, sheet)
            candidate = {
                "sheet": sheet,
                "bounds": {"row_start": int(r0), "row_end": int(r1), "col_start": int(c0), "col_end": int(c1)},
                "score": float(score),
                "table": map_dataframe(candidate_df, parse_numeric),
            }

            if best is None or candidate["score"] > best["score"]:
                best = candidate

    if best is None:
        return None

    table_df: pd.DataFrame = best["table"]
    table_df = clean_dataframe_nan(table_df)
    raw_table = table_to_clean_list(table_df)
    components = split_offset_table_components(raw_table)

    return {
        "sheet": best["sheet"],
        "bounds": best["bounds"],
        "score": best["score"],
        "table": raw_table,
        "shape": {"rows": int(table_df.shape[0]), "cols": int(table_df.shape[1])},
        "stations": components["stations"],
        "station_labels": components["station_labels"],
        "waterlines": components["waterlines"],
        "offset_table_clean": components["offset_table_clean"],
        "offset_table_clean_shape": components["offset_table_clean_shape"],
    }


def pick_best_scalar(field_name: str, candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not candidates:
        return None

    filtered = candidates
    if field_name in {"station_spacing", "waterline_spacing"}:
        positive = [c for c in candidates if c["value"] > 0]
        if positive:
            filtered = positive

    # Prefer values found in the same row as the keyword first, then nearest in grid distance.
    def rank(item: Dict[str, Any]) -> Tuple[int, int]:
        kr, kc = item["keyword_cell"]
        vr, vc = item["value_cell"]
        same_row = 0 if kr == vr else 1
        distance = abs(kr - vr) + abs(kc - vc)
        return same_row, distance

    best = sorted(filtered, key=rank)[0]
    return {
        "value": best["value"],
        "sheet": best["sheet"],
        "keyword_cell": best["keyword_cell"],
        "value_cell": best["value_cell"],
        "keyword_text": best["keyword_text"],
        "candidates_found": len(candidates),
    }


def infer_spacing_from_offset_table(offset_table: Optional[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    inferred = {"station_spacing": None, "waterline_spacing": None}
    if not offset_table:
        return inferred

    stations = np.array(offset_table.get("stations", []), dtype=float)
    waterlines = np.array(offset_table.get("waterlines", []), dtype=float)

    if stations.size == 0 and waterlines.size == 0:
        return inferred

    if stations.size >= 3:
        diffs = np.diff(stations)
        diffs = diffs[np.isfinite(diffs) & (np.abs(diffs) > 1e-12)]
        if diffs.size:
            inferred["station_spacing"] = float(np.median(np.abs(diffs)))

    if waterlines.size >= 3:
        diffs = np.diff(waterlines)
        diffs = diffs[np.isfinite(diffs) & (np.abs(diffs) > 1e-12)]
        if diffs.size:
            inferred["waterline_spacing"] = float(np.median(np.abs(diffs)))

    return inferred


def apply_hackathon_assumptions(result: Dict[str, Any]) -> Dict[str, Any]:
    # Hackathon assumption: if rho is missing from the workbook, use standard seawater density.
    if result.get("rho") is None:
        result["rho"] = DEFAULT_SEAWATER_RHO
        result["rho_source"] = "assumed_standard_seawater"
    else:
        result["rho_source"] = "dataset"

    # Hackathon assumption: if KG is missing, estimate with KG = (2/3) * Depth.
    depth = result.get("depth")
    if depth is None:
        offset = result.get("offset_table")
        if offset and offset.get("waterlines"):
            wl = np.asarray(offset.get("waterlines"), dtype=float)
            wl = wl[np.isfinite(wl)]
            if wl.size > 0:
                depth = float(np.max(wl))
    if depth is None:
        depth = DEFAULT_SEAWATER_RHO  # fallback
    result["depth"] = float(depth)

    if result.get("KG") is None:
        result["KG"] = (2.0 / 3.0) * float(result["depth"])
        result["KG_source"] = "estimated_from_depth"
    elif result.get("KG") is not None:
        result["KG_source"] = "dataset"
    else:
        result["KG_source"] = "unavailable"

    result["assumptions"] = {
        "rho": "If rho is missing, assume standard seawater density (1025 kg/m^3).",
        "KG": "If KG is missing, estimate KG = (2.0 / 3.0) * Depth as specified in the problem statement.",
    }
    return result


def extract_ship_data(file_path: str) -> Dict[str, Any]:
    excel = pd.ExcelFile(file_path)

    all_candidates: Dict[str, List[Dict[str, Any]]] = {k: [] for k in KEYWORDS}
    for sheet in excel.sheet_names:
        df = pd.read_excel(excel, sheet_name=sheet, header=None)
        df = clean_dataframe_nan(df)
        if df.empty:
            continue

        candidates = find_keyword_value_candidates(df, sheet)
        for key, vals in candidates.items():
            all_candidates[key].extend(vals)

    offset_table = extract_offset_table(excel)

    scalars: Dict[str, Optional[Dict[str, Any]]] = {
        field: pick_best_scalar(field, cands) for field, cands in all_candidates.items()
    }

    inferred_spacing = infer_spacing_from_offset_table(offset_table)

    station_spacing = scalars["station_spacing"]["value"] if scalars["station_spacing"] else None
    if station_spacing is None or station_spacing <= 0:
        station_spacing = inferred_spacing["station_spacing"]

    waterline_spacing = scalars["waterline_spacing"]["value"] if scalars["waterline_spacing"] else None
    if waterline_spacing is None or waterline_spacing <= 0:
        waterline_spacing = inferred_spacing["waterline_spacing"]

    result = {
        "file": file_path,
        "sheets_detected": excel.sheet_names,
        "offset_table": offset_table,
        "station_spacing": station_spacing,
        "waterline_spacing": waterline_spacing,
        "draft": scalars["draft"]["value"] if scalars["draft"] else None,
        "depth": scalars["depth"]["value"] if scalars["depth"] else None,
        "rho": scalars["rho"]["value"] if scalars["rho"] else None,
        "KG": scalars["KG"]["value"] if scalars["KG"] else None,
        "debug": {
            "scalar_detection": scalars,
            "scalar_candidates_count": {k: len(v) for k, v in all_candidates.items()},
        },
    }

    result = apply_hackathon_assumptions(result)
    return result


def pretty_print_result(result: Dict[str, Any]) -> None:
    print("\n=== SHIP DATA EXTRACTION RESULT ===")
    print(f"Workbook: {result['file']}")
    print("Sheets:", ", ".join(result["sheets_detected"]))

    print("\n[Scalars]")
    print(f"Station spacing : {result['station_spacing']}")
    print(f"Waterline spacing: {result['waterline_spacing']}")
    print(f"Draft           : {result['draft']}")
    rho_label = "(assumed)" if result.get("rho_source") == "assumed_standard_seawater" else "(from dataset)"
    if result.get("rho") is None:
        print("Fluid Density (rho): None")
    else:
        print(f"Fluid Density (rho): {result['rho']} kg/m^3 {rho_label}")

    kg_source = result.get("KG_source")
    if result.get("KG") is None:
        print("KG: None")
    elif kg_source == "estimated_from_draft":
        print(f"KG: {result['KG']} m (estimated from draft)")
    else:
        print(f"KG: {result['KG']} m (from dataset)")

    print("\n[Assumption Notes]")
    print("Missing rho is assigned standard seawater density for hydrostatics/stability hackathon work.")
    print("Missing KG is estimated as 0.5 x Draft to keep computations usable when loading data is absent.")

    print("\n[Offset Table]")
    offset = result.get("offset_table")
    if not offset:
        print("No offset/half-breadth table detected.")
    else:
        print(f"Detected in sheet: {offset['sheet']}")
        print(f"Raw shape       : {offset['shape']['rows']} x {offset['shape']['cols']}")
        print(f"Clean shape     : {offset['offset_table_clean_shape']['rows']} x {offset['offset_table_clean_shape']['cols']}")
        print(f"Bounds (0-based): {offset['bounds']}")
        print(f"Score           : {offset['score']:.2f}")
        print("Using offset_table_clean for integration (not raw table).")

        print("\nStations (raw_table[0,2:])")
        print(offset["stations"])
        print("Station labels (raw_table[1,2:])")
        print(offset["station_labels"])
        print("Waterlines (raw_table[2:,1])")
        print(offset["waterlines"])

        table = offset["offset_table_clean"]
        max_rows = min(12, len(table))
        print("\nOffset table clean preview (raw_table[2:,2:])")
        for i in range(max_rows):
            print(table[i])
        if len(table) > max_rows:
            print(f"... ({len(table) - max_rows} more rows)")

    print("\n[Debug Counts]")
    for key, count in result["debug"]["scalar_candidates_count"].items():
        print(f"{key}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract ship hydrostatic data from variably structured Excel files.")
    parser.add_argument("excel_file", help="Path to the Excel file")
    parser.add_argument("--json", action="store_true", help="Print full structured output as JSON")
    parser.add_argument("--plotly", action="store_true", help="Show optional Plotly surfaces for half and full hull")
    args = parser.parse_args()

    data = extract_ship_data(args.excel_file)
    pretty_print_result(data)

    offset = data.get("offset_table")
    if offset and offset.get("offset_table_clean"):
        geometry = build_hull_geometry(
            stations=offset["stations"],
            waterlines=offset["waterlines"],
            offset_table_clean=offset["offset_table_clean"],
        )
        print_hull_geometry_debug(geometry)
        if args.plotly:
            plot_hull_surfaces(geometry)
    else:
        print("\nHull geometry not generated: cleaned offset table is unavailable.")

    if args.json:
        print("\n=== JSON OUTPUT ===")
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
