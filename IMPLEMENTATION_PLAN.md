# Round 2 — Detailed Implementation Plan
**Generated:** 2 May 2026 | **Tracks:** ROUND2_PRD.md

This plan translates every PRD task into concrete coding steps, ordered by dependency. Each section specifies exact function signatures, algorithm steps, file edits, and acceptance tests. Follow tasks in the order given; do not begin a task until all tasks it depends on are marked done.

---

## Phase 0 — Infrastructure (F0)

### F0.T1 — Project scaffolding

**Files to create/edit:**

1. **`pyproject.toml`** (create)
```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP"]

[tool.mypy]
python_version = "3.11"
strict = true
ignore_missing_imports = false
```

2. **`requirements.txt`** (create) — pinned exact versions after install:
```
numpy==1.26.4
scipy==1.13.0
streamlit==1.34.0
plotly==5.22.0
pandas==2.2.2
matplotlib==3.9.0
numpy-stl==3.1.1
jsonschema==4.22.0
scikit-learn==1.5.0
```

3. **`requirements-dev.txt`** (create):
```
pytest==8.2.0
pytest-cov==5.0.0
pytest-benchmark==4.0.0
playwright==1.44.0
pytest-playwright==0.5.0
mypy==1.10.0
ruff==0.4.4
pre-commit==3.7.1
```

4. **`tests/conftest.py`** (create) — shared fixtures:
```python
import numpy as np
import pytest

@pytest.fixture(scope="session")
def box_barge_data():
    """5 m × 2 m × 3 m box barge. V = 10*5*2*1.5 = 150 m³ at draft=1.5"""
    stations = np.linspace(0, 10, 11)     # 11 stations, 10 m LOA
    waterlines = np.linspace(0, 3, 7)    # 7 waterlines, 3 m depth
    offsets = np.full((7, 11), 1.0)      # half-breadth = 1.0 m (beam = 2 m)
    return {"stations": stations, "waterlines": waterlines,
            "offset_table": offsets, "draft": 1.5, "rho": 1025.0, "KG": 1.0}

@pytest.fixture(scope="session")
def sample_offsets(tmp_path_factory):
    """Load tests/fixtures/sample_offsets.csv"""
    import pandas as pd
    p = tmp_path_factory.getbasetemp() / "sample_offsets.csv"
    # 5 WL × 7 STA, increasing breadths
    df = pd.DataFrame(np.tile(np.linspace(0.1, 1.0, 7), (5, 1)))
    df.to_csv(p, index=False)
    return str(p)
```

5. **`tests/fixtures/box_barge_offsets.csv`** (create) — 7 rows × 11 cols, all values 1.0

6. **`.github/workflows/ci.yml`** (create) — YAML from PRD §11.1

7. **`.pre-commit-config.yaml`** (create):
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.4
    hooks:
      - id: ruff
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks:
      - id: mypy
        additional_dependencies: [numpy, scipy, pandas, streamlit]
```

**Verification:** `ruff check . && mypy --strict hull_geometry.py` (once that file exists) both exit 0.

---

### F0.T2 — Shared fixture data

1. **`tests/fixtures/sample_offsets.csv`** — 5 waterlines × 7 stations, values are a simple parabolic hull form.
2. **`tests/fixtures/box_barge_offsets.csv`** — rectangular barge with analytic V, GZ, BM.
3. **`tests/unit/test_fixtures.py`** — assert both CSVs load with correct shape and dtype.

---

## Phase 1 — Shared Geometry (F1.T1)

### F1.T1 — `hull_geometry.py`

**File to create:** `Hydrohackathon/hull_geometry.py`

#### 1. Module structure

```python
"""Shared heeled-hull geometry helpers used by volume_conservation and geometric_gz."""
from __future__ import annotations
import logging
import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)
```

#### 2. `rotate_hull(stations, waterlines, offset_table, heel_deg) -> dict`

**Purpose:** Transform the offset table into 3-D (x, y, z) point arrays after rotating the hull about the longitudinal (x) axis by `heel_deg` degrees.

**Algorithm:**
1. Build meshgrid: `X[i,j] = stations[j]`, `Y[i,j] = offset_table[i,j]`, `Z[i,j] = waterlines[i]`
2. Also build port-side mirror: `Y_port = -offset_table[i,j]` (to get full cross-section)
3. Apply rotation matrix about x-axis:
   ```
   θ = radians(heel_deg)
   y' =  Y * cos(θ) - Z * sin(θ)
   z' =  Y * sin(θ) + Z * cos(θ)
   ```
4. Return dict: `{"x": X, "y_stbd": y_stbd, "z_stbd": z_stbd, "y_port": y_port, "z_port": z_port, "heel_deg": heel_deg}`

**Type signature:**
```python
def rotate_hull(
    stations: NDArray[np.float64],
    waterlines: NDArray[np.float64],
    offset_table: NDArray[np.float64],
    heel_deg: float,
) -> dict[str, NDArray[np.float64] | float]:
```

#### 3. `integrate_heeled_volume(heeled_hull, z_wl) -> float`

**Purpose:** Compute the displaced volume of the rotated hull below waterplane elevation `z_wl` in the heeled coordinate frame.

**Algorithm:**
1. For each station x-slice (column j), extract all (y', z') points from both port and starboard arrays that have `z' ≤ z_wl`.
2. Compute the cross-sectional area of the submerged slice using the shoelace formula on the clipped polygon.
   - Clip each cross-section polygon to `z' ≤ z_wl` using the Sutherland-Hodgman algorithm (or numpy-based polygon clipping).
   - Area of submerged cross-section = `0.5 * |Σ (y_i * z_{i+1} - y_{i+1} * z_i)|` over clipped vertices.
3. Integrate cross-sectional areas over x (stations) using the trapezoidal rule.

**Type signature:**
```python
def integrate_heeled_volume(
    heeled_hull: dict[str, NDArray[np.float64] | float],
    z_wl: float,
) -> float:
```

#### 4. `find_heeled_waterplane(heeled_hull, target_volume, tol=1e-4) -> float`

**Purpose:** Bisection search for `z_wl` such that `integrate_heeled_volume(heeled_hull, z_wl) == target_volume`.

**Algorithm:**
1. Set bounds: `z_lo = min(z_stbd, z_port)`, `z_hi = max(z_stbd, z_port)`.
2. Bisect up to 100 iterations; stop when `|V(z_mid) - target_volume| < tol`.
3. Raise `RuntimeError` if 100 iterations exceeded without convergence.

**Type signature:**
```python
def find_heeled_waterplane(
    heeled_hull: dict[str, NDArray[np.float64] | float],
    target_volume: float,
    tol: float = 1e-4,
) -> float:
```

#### 5. `heeled_buoyancy_centroid(heeled_hull, z_wl) -> tuple[float, float]`

**Purpose:** Return `(y_B, z_B)` — the centroid of the submerged volume in the heeled coordinate frame.

**Algorithm:**
1. For each station slice, compute the centroid (ȳ, z̄) and area A of the clipped polygon (same clipping as above).
2. Volume-weighted centroid:
   ```
   y_B = Σ(ȳ_j * A_j * Δx_j) / Σ(A_j * Δx_j)
   z_B = Σ(z̄_j * A_j * Δx_j) / Σ(A_j * Δx_j)
   ```
3. Return `(y_B, z_B)`.

**Type signature:**
```python
def heeled_buoyancy_centroid(
    heeled_hull: dict[str, NDArray[np.float64] | float],
    z_wl: float,
) -> tuple[float, float]:
```

#### Unit tests — `tests/unit/test_hull_geometry.py`

| Test | What to assert |
|---|---|
| `test_rotate_hull_at_zero_deg` | Output y, z arrays equal input Y, Z arrays within 1e-10 |
| `test_rotate_hull_90deg_swaps_axes` | y' ≈ -Z, z' ≈ Y (port); verify with 2×2 example |
| `test_integrate_heeled_volume_box_barge` | `L * B * draft` within 0.1% |
| `test_find_heeled_waterplane_converges` | Returns float, residual < tol |
| `test_heeled_buoyancy_centroid_box_barge` | z_B ≈ draft/2, y_B ≈ 0 at 0° heel |

---

## Phase 2 — Volume Conservation (F1.T2, F1.T3)

### F1.T2 — `volume_conservation.py`

**File to create:** `Hydrohackathon/volume_conservation.py`

#### Functions to implement

**`run_volume_conservation(stations, waterlines, offset_table, draft, rho, heel_angles) -> pd.DataFrame`**

Algorithm:
1. Compute upright volume `V₀` using existing `integration.py` at `heel_deg=0`.
2. For each angle in `heel_angles`:
   a. Call `hull_geometry.rotate_hull(...)` at that angle.
   b. Call `hull_geometry.find_heeled_waterplane(heeled_hull, V₀)` → `z_wl`.
   c. Call `hull_geometry.integrate_heeled_volume(heeled_hull, z_wl)` → `V_heeled`.
   d. Compute `deviation_pct = abs(V_heeled - V₀) / V₀ * 100`.
3. Return DataFrame with columns: `heel_deg, V_upright_m3, V_heeled_m3, deviation_pct`.
4. Log INFO for each angle; log WARNING if `deviation_pct > 1%`.

**`volume_conservation_summary(df) -> dict`**

Returns `{"max_dev_pct": float, "status": "pass"|"warn"|"fail"}` where:
- "pass" if `max_dev_pct < 1%`
- "warn" if `1% ≤ max_dev_pct ≤ 3%`
- "fail" if `max_dev_pct > 3%`

#### Unit tests — `tests/unit/test_volume_conservation.py`

| Test | What to assert |
|---|---|
| `test_volume_conservation_zero_heel` | `deviation_pct` row at θ=0 equals 0.0 |
| `test_volume_conservation_box_barge_30deg` | box barge `deviation_pct` < 0.1% at 30° |
| `test_volume_conservation_summary_pass` | max_dev=0.5 → status="pass" |
| `test_volume_conservation_summary_warn` | max_dev=2.0 → status="warn" |
| `test_volume_conservation_summary_fail` | max_dev=4.0 → status="fail" |
| `test_volume_conservation_csv_output` | output DataFrame has 4 columns, rows = len(heel_angles) |

---

### F1.T3 — Wire Phase 2b into `main.py`

**File to edit:** `Hydrohackathon/main.py`

1. After the existing Phase 2 block (geometry validation), insert:
```python
# Phase 2b — Volume Conservation
logger.info("Phase 2b: Volume conservation validation")
heel_angles = list(range(0, 65, 5))
vc_df = run_volume_conservation(stations, waterlines, offset_table, draft, rho, heel_angles)
vc_summary = volume_conservation_summary(vc_df)
vc_df.to_csv(output_dir / "volume_conservation.csv", index=False)
if vc_summary["status"] == "fail":
    logger.warning("Volume conservation FAILED: max deviation %.2f%%", vc_summary["max_dev_pct"])
else:
    logger.info("Volume conservation %s: max deviation %.2f%%", vc_summary["status"].upper(), vc_summary["max_dev_pct"])
```

2. Add import: `from volume_conservation import run_volume_conservation, volume_conservation_summary`

#### Unit tests additions — `tests/unit/test_main_pipeline.py`

- `test_phase2b_runs_without_error` — pipeline reaches Phase 3 without exception.
- `test_phase2b_output_file_exists` — `volume_conservation.csv` present in output dir.

---

## Phase 3 — Geometric GZ (F2.T1, F2.T2, F2.T3)

### F2.T1 — `geometric_gz.py`

**File to create:** `Hydrohackathon/geometric_gz.py`

#### Function: `compute_geometric_gz_curve`

```python
def compute_geometric_gz_curve(
    stations: NDArray[np.float64],
    waterlines: NDArray[np.float64],
    offset_table: NDArray[np.float64],
    draft: float,
    rho: float,
    KG: float,
    heel_angles: list[float],
) -> dict[str, NDArray[np.float64]]:
```

**Algorithm (per angle θ):**
1. `heeled_hull = rotate_hull(stations, waterlines, offset_table, θ)`
2. Compute `V₀` once (upright, θ=0) using `integrate_heeled_volume` at max waterline.
   - Actually use existing integration module for V₀ to stay consistent.
3. `z_wl = find_heeled_waterplane(heeled_hull, V₀)`
4. `(y_B_heeled, z_B_heeled) = heeled_buoyancy_centroid(heeled_hull, z_wl)`
5. Rotate `(y_B_heeled, z_B_heeled)` back to upright frame:
   ```
   θ_rad = radians(θ)
   y_B_upright =  y_B_heeled * cos(θ) + z_B_heeled * sin(θ)
   z_B_upright = -y_B_heeled * sin(θ) + z_B_heeled * cos(θ)
   ```
6. Compute:
   ```
   GZ(θ) = y_B_upright * cos(θ) + (z_B_upright - KG) * sin(θ)
   KN(θ) = GZ(θ) + KG * sin(θ_rad)
   ```
   — which simplifies to `KN = y_B_upright * cos(θ) + z_B_upright * sin(θ)`.
7. Return dict: `{"heel_deg": array, "gz_geometric": array, "kn_geometric": array}`.

**Raise `RuntimeError`** if `GZ[0]` (θ=0°) deviates from 0 by more than 1e-3 m (sanity check).

#### Unit tests — `tests/unit/test_geometric_gz.py`

| Test | Assert |
|---|---|
| `test_gz_zero_at_zero_heel` | `abs(gz[0]) < 1e-6` |
| `test_gz_positive_for_stable_hull` | box barge with `KG < KM`: all `gz[1:]` > 0 for θ ∈ (0°, 60°) |
| `test_kn_equals_gz_plus_kg_sin_theta` | `kn - gz - KG*sin(θ)` < 1e-6 for all θ |
| `test_gz_agrees_with_simplified_at_5deg` | `abs(gz[1] - GM*sin(5°)) / (GM*sin(5°)) < 0.01` |
| `test_gz_negative_for_unstable_hull` | hull with `KG > KM`: `gz[1] < 0` |

---

### F2.T2 — Update `gz_curve.py`

**File to edit:** `Hydrohackathon/gz_curve.py`

1. Rename existing `compute_gz_curve` → `compute_simplified_gz_curve` (add deprecation docstring).
2. Add at top of file:
```python
from geometric_gz import compute_geometric_gz_curve  # re-export
```
3. Update `write_gz_csv(output_dir, simplified_result, geometric_result)`:
   - Merge both result dicts into a single DataFrame.
   - Columns: `heel_deg, gz_simplified, gz_geometric`.
   - Write to `output_dir / "gz_curve.csv"`.
4. Write `output_dir / "kn_curve.csv"` with columns `heel_deg, kn_geometric, kn_simplified` where `kn_simplified = KG * sin(θ) + gz_simplified`.
5. Update `plot_gz_curve(...)` to overlay both curves on same axes, legend labels "Geometric GZ" and "Simplified GZ (GM·sinθ)".

#### Unit tests — `tests/unit/test_gz_curve.py`

| Test | Assert |
|---|---|
| `test_csv_has_geometric_column` | `gz_curve.csv` has column `gz_geometric` |
| `test_csv_has_simplified_column` | `gz_curve.csv` has column `gz_simplified` |
| `test_kn_csv_written` | `kn_curve.csv` created with columns `heel_deg, kn_geometric` |
| `test_png_output_created` | `gz_curve.png` file exists |

---

### F2.T3 — Wire geometric GZ into `main.py` Phase 6

**File to edit:** `Hydrohackathon/main.py`

1. In Phase 6 block, replace call to old `compute_gz_curve` with:
```python
heel_angles = list(range(0, 61, 1))  # 1° resolution
geo_result = compute_geometric_gz_curve(
    stations, waterlines, offset_table, draft, rho, KG, heel_angles
)
simp_result = compute_simplified_gz_curve(GM, heel_angles)
write_gz_csv(output_dir / "results", simp_result, geo_result)
plot_gz_curve(output_dir / "results", simp_result, geo_result)
```
2. Add `gz_geometric_at_30deg` to `results.csv` row (read from `geo_result["gz_geometric"]` at index 30).
3. Compute and add `range_of_stability_deg` — first angle after maximum GZ where `gz_geometric` crosses zero. Use `np.interp` on the zero-crossing.

#### Unit test additions — `tests/unit/test_main_pipeline.py`

- `test_phase6_uses_geometric_gz` — `results.csv` column `gz_geometric_at_30deg` is not NaN.

---

## Phase 4 — ShipD Benchmark (F3.T1, F3.T2, F3.T3)

### F3.T2 — `ship_excel_extractor.py`: add CSV loader (do this first; no dependency on ShipD)

**File to edit:** `Hydrohackathon/ship_excel_extractor.py`

Add function:
```python
def load_offsets_from_csv(csv_path: str) -> dict[str, Any]:
    """
    Load an offset table from CSV and return the same dict schema as extract_ship_data().

    Parameters
    ----------
    csv_path : str
        Path to CSV file. First column = waterline elevations (m),
        first row = station x-positions (m), body = half-breadths (m).

    Returns
    -------
    dict with keys: offset_table, stations, waterlines, draft, rho, KG
    """
```

**Algorithm:**
1. Read CSV. First row is station positions (header), first column is waterline elevations.
2. `waterlines = df.index.to_numpy(dtype=np.float64)`
3. `stations = df.columns.to_numpy(dtype=np.float64)`
4. `offset_table = df.values.astype(np.float64)`
5. Validate: call `validate_offset_csv(csv_path)` first (see §Shared Infrastructure below).
6. `draft = waterlines[-1]` (max waterline = full depth; actual design draft read from metadata if present).
7. Return dict with `rho=1025.0`, `KG=2/3 * draft` as defaults.

Add function `validate_offset_csv(path: str) -> None`:
- Raise `FileNotFoundError` if path not found.
- Raise `ValueError` if non-numeric values, negative breadths, or mismatched column count.

#### Unit tests — `tests/unit/test_ship_excel_extractor.py`

| Test | Assert |
|---|---|
| `test_load_offsets_from_csv_schema` | returned dict has all 6 required keys |
| `test_load_offsets_from_csv_roundtrip` | save → reload → `np.allclose(original, reloaded)` |
| `test_validate_offset_csv_rejects_negatives` | raises `ValueError` |

---

### F3.T1 — `shipd_converter.py`

**File to create:** `Hydrohackathon/shipd_converter.py`

```python
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "ShipD_repo"))
from HullParameterization import Hull_Parameterization  # noqa: E402
```

**Functions:**

**`select_diverse_hulls(input_csv: str, n: int = 10) -> list[int]`**
1. Read `Input_Vectors_SampleHulls.csv` as numpy array of shape `(N, 45)`.
2. Standardize (subtract mean, divide by std per column).
3. Fit `KMeans(n_clusters=n)` from `sklearn.cluster`.
4. For each cluster center, find the hull index with minimum Euclidean distance.
5. Return list of `n` distinct row indices.

**`hull_to_offset_table(design_vector: NDArray[np.float64], n_wl: int = 20, n_sta: int = 21) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]`**
1. Instantiate: `hull = Hull_Parameterization(design_vector)`
2. Call `hull.gen_pointCloud(NUM_WL=n_wl, PointsPerWL=200)` (inspect actual API; fall back to STL if needed).
3. For each waterline elevation z_i, extract the y-coordinates (half-breadths) at n_sta equally-spaced x-stations using linear interpolation.
4. Return `(offset_table, stations, waterlines)` as float64 arrays.

   **STL fallback path** (if `gen_pointCloud` not available):
   - Use `STLGen.py` to generate mesh.
   - Load with `numpy-stl`: `mesh = stl.mesh.Mesh.from_file(...)`.
   - Slice at each waterline z_i: find all triangles straddling z=z_i, compute intersection line segments, extract max y per x-station.

**`extract_hull_metadata(design_vector: NDArray[np.float64]) -> dict[str, float]`**
- Extract LOA (index 0, scaled), Bd (index 1, scaled), Dd (index 6, scaled).
- Compute `draft = 0.9 * Dd` (90% of depth as design draft).
- Compute `KG = 2/3 * Dd`.
- Return `{"LOA": ..., "Bd": ..., "Dd": ..., "draft": ..., "KG": ..., "rho": 1025.0}`.

**`save_benchmark_sample(hull_idx: int, offsets: NDArray, stations: NDArray, waterlines: NDArray, metadata: dict, out_dir: Path) -> None`**
- Create `out_dir/sample_{hull_idx}/`.
- Write `offsets.csv` (waterlines as index, stations as columns).
- Write `metadata.json`.

#### Unit tests — `tests/unit/test_shipd_converter.py`

| Test | Assert |
|---|---|
| `test_select_diverse_hulls_returns_n` | `len(indices) == 10`, all unique |
| `test_hull_to_offset_table_shape` | shape `== (n_wl, n_sta)` |
| `test_hull_to_offset_table_no_negatives` | `np.all(offsets >= 0)` |
| `test_save_benchmark_sample_creates_files` | both `offsets.csv` and `metadata.json` exist |

---

### F3.T3 — `benchmark_validation.py`

**File to create:** `Hydrohackathon/benchmark_validation.py`

**`run_benchmark(input_csv: str, out_dir: str, n_hulls: int = 10) -> list[dict]`**

For each of the `n_hulls` selected hulls:
1. Run `hull_to_offset_table(design_vector, n_wl=20, n_sta=21)` — coarse grid.
2. Run `hull_to_offset_table(design_vector, n_wl=50, n_sta=100)` — fine grid (reference).
3. For both grids, run:
   - Volume integration → `V_coarse`, `V_fine`.
   - `compute_hydrostatics(...)` → `GM_coarse`, `GM_fine`, `KB_coarse`, `LCB_coarse`.
   - `compute_geometric_gz_curve(...)` with `heel_angles = range(0, 65, 5)`.
4. Call `compute_error_metrics(coarse_result, fine_result)` → error_metrics dict.
5. Write all outputs to `out_dir/sample_{i}/`.
6. Return list of per-hull summary dicts.

**`compute_error_metrics(coarse: dict, fine: dict) -> dict`**
```python
{
    "gm_error_pct": abs(coarse["GM"] - fine["GM"]) / fine["GM"] * 100,
    "gz_max_deviation_pct": max(abs(coarse["gz"] - fine["gz"]) / abs(fine["gz"] + 1e-9)) * 100,
    "volume_deviation_pct": abs(coarse["V"] - fine["V"]) / fine["V"] * 100,
    "lcb_error_m": abs(coarse["LCB"] - fine["LCB"]),
    "kb_error_m": abs(coarse["KB"] - fine["KB"]),
}
```

**Pass/Fail logic:** `pass = gm_error_pct ≤ 2 AND gz_max_deviation_pct ≤ 5 AND volume_deviation_pct ≤ 3`

#### Unit tests — `tests/unit/test_benchmark_validation.py`

| Test | Assert |
|---|---|
| `test_error_metrics_schema` | all 5 keys present in output dict |
| `test_gm_error_formula` | manually computed value matches function output |
| `test_all_output_files_written` | 4 per-hull files present (1-hull run) |

---

## Phase 5 — KG Sensitivity (F4.T1)

### F4.T1 — `kg_sensitivity.py`

**File to create:** `Hydrohackathon/kg_sensitivity.py`

**`run_kg_sensitivity(stations, waterlines, offset_table, draft, rho, kg_values, heel_angles) -> pd.DataFrame`**

For each `kg` in `kg_values`:
1. Call `compute_geometric_gz_curve(..., KG=kg, ...)`.
2. Compute:
   - `GM = KB + BM - kg` (from hydrostatics, KB and BM don't change with KG).
   - `max_gz = max(gz_curve)`.
   - `angle_max_gz = heel_angles[argmax(gz_curve)]`.
   - `range_of_stability` = heel angle where GZ returns to 0 after maximum (linear interp on zero-crossing).
   - `area_0_30 = trapz(gz_curve[0:31], heel_angles[0:31])` (degrees, convert to radians for m·rad).
3. Collect into DataFrame rows.

**Output:** `kg_sensitivity.csv` with columns `kg_m, gm_m, max_gz_m, angle_max_gz_deg, range_stability_deg, area_0_30`.

#### Unit tests — `tests/unit/test_kg_sensitivity.py`

| Test | Assert |
|---|---|
| `test_higher_kg_lower_gm` | `gm[i] > gm[i+1]` for strictly increasing `kg_values` |
| `test_area_decreases_with_kg` | `area[i] > area[i+1]` for increasing KG |
| `test_csv_output_schema` | DataFrame has all 6 required columns |

---

## Phase 6 — Offset Optimizer (F5.T1, F5.T2, F5.T3)

### F5.T1 — `offset_optimizer.py`: solver

**File to create:** `Hydrohackathon/offset_optimizer.py`

#### Dataclasses

```python
from dataclasses import dataclass, field

@dataclass
class OptimizationConstraints:
    p_max: float = 0.05                         # max offset perturbation fraction
    gz_min_at_angles: dict[int, float] = field( # key: heel angle deg, value: min GZ m
        default_factory=lambda: {10: 0.2, 20: 0.4, 30: 0.5, 40: 0.45, 50: 0.3}
    )
    area_min: float = 0.25                       # min area under GZ (m·rad)
    target_heel: int = 30                        # heel angle to maximize GZ at

@dataclass
class OptimizationResult:
    status: str                  # "converged" or "infeasible"
    gz_before: float
    gz_after: float
    gz_improvement_pct: float
    area_gz_before: float
    area_gz_after: float
    volume_deviation_pct: float
    max_offset_change_pct: float
    iterations: int
    optimized_offsets: NDArray[np.float64]
    infeasibility_report: "InfeasibilityReport | None"
```

#### Function: `run_optimization`

```python
def run_optimization(
    stations: NDArray[np.float64],
    waterlines: NDArray[np.float64],
    offset_table: NDArray[np.float64],
    constraints: OptimizationConstraints,
    KG: float,
    draft: float,
    rho: float,
) -> OptimizationResult:
```

**Algorithm:**
1. Identify submerged waterlines: `wl_mask = waterlines <= draft`. Shape: `(N_WL_sub, N_STA)`.
2. Flatten δ: `delta = zeros(N_WL_sub * N_STA)`.
3. Define objective:
   ```python
   def objective(delta):
       T_prime = perturb_offsets(offset_table, delta, wl_mask)
       gz = compute_geometric_gz_curve(..., KG=KG, heel_angles=[target_heel])[target_heel]
       return -gz  # negate to maximize
   ```
4. Define constraints as `scipy.optimize.LinearConstraint` / `NonlinearConstraint` / `{'type': 'ineq', 'fun': ...}` entries:
   - Volume: `V(T') ≥ 0.99*V₀` and `V(T') ≤ 1.01*V₀`.
   - Per-angle GZ: for each `(θ_k, gz_min_k)`, `GZ(θ_k; T') ≥ gz_min_k`.
   - Area: `area_under_gz(T') ≥ area_min`.
   - Non-negativity of offsets: built into bounds.
5. Bounds: `(-p_max, +p_max)` for each element of δ.
6. Call:
   ```python
   result = minimize(
       objective, delta, method="SLSQP",
       bounds=bounds, constraints=scipy_constraints,
       options={"maxiter": 300, "ftol": 1e-7},
       jac="2-point",
   )
   ```
7. Build and return `OptimizationResult`. If `result.status != 0`, call `analyze_infeasibility(...)`.

**Performance note:** Cache KN table pre-computation. Since `KN(θ)` is independent of KG, compute the KN array once outside the optimization loop. Inside the loop only compute `GZ = KN - KG * sin(θ)` — this keeps objective evaluations to < 10 ms each.

---

### F5.T2 — `offset_optimizer.py`: `InfeasibilityReport`

```python
@dataclass
class InfeasibilityReport:
    violated_constraints: list[str]
    per_constraint_relaxation: dict[str, float]
    simultaneous_scale_factor: float
    suggested_p_max: float
    explanation: str
```

**`analyze_infeasibility(constraints, final_delta, stations, waterlines, offset_table, KG, draft, rho) -> InfeasibilityReport`**

Algorithm (per PRD §5.4):
1. Evaluate each constraint function at `final_delta`. Collect names of all constraints where `fun(delta) < 0`.
2. For each violated GZ constraint at angle θ_k:
   - Binary search `gz_min_relaxed` in `[0, gz_min_k]` until `run_optimization(..., gz_min_at_angles={θ_k: gz_min_relaxed}, all_others=original)` converges. Record `Δ = gz_min_k - gz_min_relaxed`.
3. For area constraint: binary search `area_min_relaxed` similarly.
4. Compute `simultaneous_scale_factor`: bisect `s ∈ [0, 1]` — replace all soft constraint targets with `target × s`, check if `run_optimization` converges.
5. Compute `suggested_p_max`: solve 1-D problem ignoring GZ/area constraints — minimum `p_max` achieving `GZ(target_heel) > original_gz`.
6. Build `explanation` string using template from PRD §5.4.

#### Unit tests — `tests/unit/test_offset_optimizer.py`

| Test | Assert |
|---|---|
| `test_optimization_converges_default_constraints` | `status == "converged"` |
| `test_optimized_offsets_within_bounds` | `np.all(abs(delta) <= p_max)` |
| `test_optimized_volume_deviation` | `volume_deviation_pct <= 1.0` |
| `test_gz_constraint_satisfied` | all `GZ(θ_k) >= gz_min_k - 1e-6` |
| `test_area_constraint_satisfied` | `area >= area_min - 1e-6` |
| `test_optimization_report_json_schema` | all required keys present in JSON output |
| `test_infeasibility_detected_on_tight_constraints` | `status == "infeasible"` when `gz_min = 2 × current_max` |
| `test_infeasibility_report_populated` | `violated_constraints` non-empty |
| `test_per_constraint_relaxation_positive` | all values > 0 |
| `test_simultaneous_scale_factor_in_0_1` | `0 < s < 1` |
| `test_rerun_with_suggested_relaxations_converges` | applying report values → `status == "converged"` |

---

### F5.T3 — Wire optimizer into `main.py` CLI

**File to edit:** `Hydrohackathon/main.py`

1. Add `argparse` flags at top of `main()`:
```python
parser.add_argument("--optimize", action="store_true")
parser.add_argument("--target-heel", type=int, default=30)
parser.add_argument("--opt-constraints", type=str, default=None,
                    help="JSON string of constraints")
```
2. Validate JSON input:
```python
if args.opt_constraints:
    import json, jsonschema
    raw = json.loads(args.opt_constraints)   # raises json.JSONDecodeError on malformed
    jsonschema.validate(raw, CONSTRAINTS_SCHEMA)  # raises ValidationError
    constraints = OptimizationConstraints(**raw)
```
3. Define `CONSTRAINTS_SCHEMA` as a module-level constant with required properties and types.
4. After Phase 6, if `--optimize`:
```python
opt_result = run_optimization(stations, waterlines, offset_table, constraints, KG, draft, rho)
write_optimization_outputs(output_dir, opt_result)
```

**`write_optimization_outputs(output_dir, result)`** — writes `optimized_offsets.csv` and `optimization_report.json`.

---

## Phase 7 — Interactive UI (F4.T2, F4.T3, F4.T4)

### F4.T2 — `interactive_ui.py`: Tabs 1 and 2

**File to create:** `Hydrohackathon/interactive_ui.py`

#### App structure
```python
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from pathlib import Path

STUB_DATA = os.getenv("STUB_DATA") == "1"
OUTPUT_DIR = Path("results")

st.set_page_config(page_title="Ship Stability Analysis", layout="wide")
tab1, tab2, tab3, tab4 = st.tabs([
    "Stability Explorer", "KN → GZ Transform", "Benchmark Validation", "Offset Optimizer"
])
```

#### Sidebar (shared across Tab 1 & 2)
```python
with st.sidebar:
    kg_default = load_kg_default()
    KG = st.slider("KG (m)", min_value=0.5*kg_default, max_value=1.5*kg_default,
                   value=kg_default, step=0.1)
    draft_val = st.slider("Draft (m)", ...)
    show_simplified = st.checkbox("Show simplified GZ overlay", value=False)
```

#### Tab 1 — Stability Explorer

**Row 1 — GZ chart (left) + KN chart (right):**
- GZ chart: Plotly `go.Scatter` for geometric GZ, optional simplified overlay, shaded area `go.Scatter(fill='tozeroy')`, vertical dashed line at angle of max GZ.
- KN chart: `go.Scatter` for KN cross-curve, annotation `GZ = KN − KG·sin(θ)`.

**Row 2 — Volume Conservation chart (full width):**
- Load `results/volume_conservation.csv` with `@st.cache_data`.
- If file absent, show grey placeholder with message.
- Primary y-axis: `V_heeled_m3` (solid blue) + `V_upright_m3` (horizontal dashed grey).
- Secondary y-axis: `deviation_pct` (dashed red) + ±1% green dotted + ±3% orange dotted threshold lines.
- Below chart: metric row with `max_deviation`, `✓/⚠/✗` badge.

**Row 3 — Hydrostatic summary table:**
- Display GM, BM, KB, range of stability. Recompute when KG or draft sliders change.
- Use `st.metric()` for each value.

**Performance:** Wrap GZ recomputation in `@st.cache_data(ttl=None)` with `draft` as the hash key. Since KG only affects `GZ = KN - KG*sin(θ)`, pre-cache the KN array per draft; apply KG transformation at runtime (< 1 ms).

#### Tab 2 — KN → GZ Transform

- Load `kg_sensitivity.csv` or recompute if absent.
- Two-subplot Plotly figure: top = KN curves (one per KG scenario), bottom = GZ curves.
- Add annotation arrows showing vertical shift direction.

#### E2E tests — `tests/e2e/test_ui_tab1.py`

| Test | Playwright assertion |
|---|---|
| `test_tab1_loads` | `page.title()` contains "Ship Stability" |
| `test_gz_chart_renders` | `.plotly-graph-div` element visible on Tab 1 |
| `test_volume_conservation_chart_renders` | second `.plotly-graph-div` on Tab 1 visible |
| `test_kg_slider_updates_gm` | move slider, assert GM metric text changes |
| `test_tab2_kn_chart_renders` | click Tab 2, assert chart visible |

---

### F4.T3 — `interactive_ui.py`: Tab 3

#### Tab 3 — Benchmark Validation

```python
with tab3:
    bench_dir = Path("benchmarks")
    if not bench_dir.exists():
        st.info("Run `python benchmark_validation.py` first to generate benchmark data.")
    else:
        summary_df = load_benchmark_summary(bench_dir)  # cached
        # Color rows: red if fail, green if pass
        st.dataframe(summary_df.style.apply(color_pass_fail, axis=1))
        
        hull_id = st.selectbox("Select hull", options=range(10))
        render_hull_detail(hull_id, bench_dir)
```

**`render_hull_detail(hull_id, bench_dir)`:**
1. Load `gz_model.csv` (coarse) and compute fine-grid reference (or load `gz_fine.csv` if pre-computed).
2. GZ comparison chart: coarse (solid), fine reference (dashed), ±5% tolerance band.
3. KN comparison chart: same structure.
4. Error metrics panel: three `st.metric()` calls with `✓/✗` badges.
5. Principal dimensions card: `st.json(metadata)` or formatted `st.table()`.

---

### F4.T4 — `interactive_ui.py`: Tab 4

#### Tab 4 — Offset Optimizer

**Constraint configuration form:**
```python
with tab4:
    with st.form("optimizer_config"):
        target_heel = st.selectbox("Target heel angle (°)", [20, 30, 40, 50], index=1)
        p_max_pct = st.slider("Max half-breadth perturbation (%)", 1, 20, 5)
        
        st.subheader("Minimum GZ constraints")
        cols = st.columns(5)
        gz_angles = [10, 20, 30, 40, 50]
        gz_defaults = [0.20, 0.40, 0.50, 0.45, 0.30]
        gz_mins = {
            int(cols[i].number_input(f"Heel (°)", value=gz_angles[i], key=f"angle_{i}")):
            cols[i].slider(f"Min GZ (m)", 0.0, 2.0, gz_defaults[i], key=f"gz_{i}")
            for i in range(5)
        }
        area_min = st.slider("Min area under GZ (m·rad)", 0.0, 1.0, 0.25)
        submitted = st.form_submit_button("Run Optimization")
    
    if submitted:
        with st.spinner("Running optimizer..."):
            constraints = OptimizationConstraints(
                p_max=p_max_pct/100, gz_min_at_angles=gz_mins,
                area_min=area_min, target_heel=target_heel
            )
            result = run_optimization(stations, wl, offsets, constraints, KG, draft, rho)
        render_optimization_result(result)
```

**`render_optimization_result(result)`:**
- If `status == "converged"`:
  - Green `st.success("✓ CONVERGED")` badge.
  - Before/after comparison table.
  - GZ overlay chart (Plotly): original GZ (dashed) vs optimized GZ (solid) + horizontal constraint lines.
  - Offset perturbation heatmap: `go.Heatmap(z=delta*100, colorscale=[[0,"blue"],[0.5,"white"],[1,"red"]])`.
  - Download buttons for `optimized_offsets.csv` and `optimization_report.json`.

- If `status == "infeasible"`:
  - Red `st.error("✗ INFEASIBLE — Optimization did not converge")` banner.
  - List violated constraints.
  - Relaxation suggestions table.
  - "Apply suggested relaxations" button: writes suggestions to `st.session_state` and calls `st.rerun()` to repopulate the form.

#### E2E tests — `tests/e2e/test_ui_tab4.py`

| Test | Playwright assertion |
|---|---|
| `test_tab4_form_renders` | 5 GZ-min inputs visible after clicking Tab 4 |
| `test_tab4_run_button_exists` | button "Run Optimization" in DOM |
| `test_tab4_infeasibility_panel_shown` | given stub infeasible result, red banner `st.error` visible |
| `test_tab4_apply_relaxations_button_prefills_form` | click button, assert form values updated |

---

## Phase 8 — Shared Infrastructure Changes (§6 of PRD)

These can be done in parallel with Phases 1–7 or as part of the specific feature task they unblock.

### 6.3 — Extend `results.csv` schema

**File to edit:** `Hydrohackathon/main.py` (results assembly section)

Add to the results dict before writing:
```python
results["gz_geometric_at_30deg"] = float(np.round(geo_gz_at_30, 6))
results["range_of_stability_deg"] = float(range_of_stability)
results["area_under_gz_0_30"] = float(np.round(area_0_30, 6))
results["volume_conservation_max_dev_pct"] = float(np.round(vc_summary["max_dev_pct"], 4))
```

### 6.4 — `requirements.txt` (done in F0.T1)

Already specified above.

---

## Phase 9 — Quality and Polish (§8, §13 of PRD)

### 8.2 Code quality

After each module is written:
1. Run `ruff check Hydrohackathon/<module>.py` — fix all flagged issues.
2. Run `mypy --strict Hydrohackathon/<module>.py` — fix all type errors.
3. Confirm no `print()` in library modules (only `main.py` and `interactive_ui.py`).

### 8.4 Numerical precision

In all new modules, ensure:
- All arrays created with `dtype=np.float64` explicitly.
- GZ values rounded to 6 decimal places before writing to CSV: `np.round(value, 6)`.
- Integration tolerance `tol=1e-4` passed through consistently.

### 8.7 Logging

Add to each new module:
```python
import logging
logger = logging.getLogger(__name__)
```
Replace any bare `print()` with `logger.info(...)` or `logger.debug(...)`.

### §13 Bonus practices

1. **`CHANGELOG.md`** — create after first feature merge; update per PR.
2. **Numerical snapshot golden files** — after Phase 3 (geometric_gz) passes, run:
   ```bash
   python -c "
   import numpy as np
   from geometric_gz import compute_geometric_gz_curve
   # load offsetdata.csv, compute GZ
   np.save('tests/fixtures/gz_golden.npy', gz_array)
   "
   ```
   Add `test_gz_matches_golden` using `np.testing.assert_allclose(..., rtol=1e-4)`.
3. **`pytest-benchmark`** — add `@pytest.mark.benchmark` to volume conservation and GZ curve tests; CI threshold: < 2 s and < 30 s respectively.
4. **`README.md`** — add Round 2 section with:
   - `streamlit run interactive_ui.py` quick-start
   - `python benchmark_validation.py` benchmark run
   - CLI optimizer example from PRD §5.6

---

## Task Execution Order Summary

```
Week 1
  Day 1–2:  F0.T1, F0.T2       — scaffolding, fixtures, CI
  Day 2–3:  F1.T1               — hull_geometry.py (all 4 functions + tests)
  Day 3–4:  F1.T2, F1.T3        — volume_conservation.py + Phase 2b wiring

Week 2
  Day 1–2:  F2.T1               — geometric_gz.py (core GZ computation + tests)
  Day 2–3:  F2.T2, F2.T3        — gz_curve.py updates + Phase 6 wiring
  Day 3–4:  F3.T2               — ship_excel_extractor.py CSV loader

Week 3
  Day 1–2:  F3.T1               — shipd_converter.py
  Day 2–3:  F3.T3               — benchmark_validation.py
  Day 3–4:  F4.T1               — kg_sensitivity.py

Week 4
  Day 1–2:  F5.T1               — offset_optimizer.py solver
  Day 2–3:  F5.T2               — InfeasibilityReport analysis
  Day 3:    F5.T3               — CLI --optimize flag

Week 5
  Day 1–2:  F4.T2               — UI Tabs 1 + 2 (Stability Explorer, KN→GZ)
  Day 2–3:  F4.T3               — UI Tab 3 (Benchmark Validation)
  Day 3–4:  F4.T4               — UI Tab 4 (Offset Optimizer)
  Day 4–5:  Quality pass — ruff, mypy, coverage, snapshot tests, CHANGELOG
```

---

## Dependency Graph (re-stated concisely)

```
F0.T1 → F0.T2
F0.T2 → F1.T1 → F1.T2 → F1.T3
              → F2.T1 → F2.T2 → F2.T3
                      → F3.T1
                      → F4.T1
F3.T2 → F3.T3
F3.T3 → F4.T3
F4.T1 → F4.T2 → F4.T3 → F4.T4
F2.T1 → F5.T1 → F5.T2 → F5.T3
F5.T1 → F4.T4
```

No task in the graph can begin until all of its left-hand dependencies are marked complete.

---

## Traceability Quick-Reference

| PRD Req | Task | New File |
|---|---|---|
| R1.1–R1.3 (hull rotation, bisection, volume) | F1.T1 | `hull_geometry.py` |
| R1.4–R1.5 (volume conservation pass + CSV) | F1.T2 | `volume_conservation.py` |
| R1.6 (Phase 2b in pipeline) | F1.T3 | `main.py` |
| R2.1–R2.2 (geometric GZ, KN) | F2.T1 | `geometric_gz.py` |
| R2.3 (GZ CSV with both columns) | F2.T2 | `gz_curve.py` |
| R2.4 (Phase 6 uses geometric) | F2.T3 | `main.py` |
| R3.1–R3.2 (ShipD hull selection + converter) | F3.T1 | `shipd_converter.py` |
| R3.3 (CSV offset loader) | F3.T2 | `ship_excel_extractor.py` |
| R3.4–R3.5 (benchmark GM/GZ error metrics) | F3.T3 | `benchmark_validation.py` |
| R4.1 (KG sensitivity) | F4.T1 | `kg_sensitivity.py` |
| R4.2–R4.4 (UI Tabs 1+2) | F4.T2 | `interactive_ui.py` |
| R3.6–R3.7 (UI Tab 3) | F4.T3 | `interactive_ui.py` |
| R5.10–R5.11 (UI Tab 4) | F4.T4 | `interactive_ui.py` |
| R5.1–R5.5 (optimizer solver) | F5.T1 | `offset_optimizer.py` |
| R5.6–R5.9 (infeasibility analysis) | F5.T2 | `offset_optimizer.py` |
| R5.12 (CLI flags) | F5.T3 | `main.py` |
