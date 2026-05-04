# Round 2 Detailed PRD — Hydrostatic & Stability Analysis Tool
**Date:** 2 May 2026 | **Base:** Existing Hydrohackathon codebase

---

## 0. Current State Summary

The existing pipeline (`main.py`) runs 10 sequential phases covering:
- Excel extraction (`ship_excel_extractor.py`)
- Numerical integration of sectional areas and displaced volume (`integration.py`)
- Hydrostatics: LCB, LCF, KB, BM, GM, waterplane area, IT (`hydrostatics.py`, `stability.py`)
- GZ curve via simplified **`GZ = GM × sin(θ)`** approximation (`gz_curve.py`)
- KN curve via derived **`KN = GZ + KG × sin(θ)`** (not geometric)
- 3D hull visualization using Plotly (`visualization_3d.py`)
- Text insights report (`insights.py`)

**Critical gap:** The current GZ/KN approach is a linearized small-angle approximation. It does not account for shift of the center of buoyancy as the hull heels. All four Round 2 requirements depend on a geometrically correct large-angle GZ.

---

## 1. Feature 1 — Volume Conservation Validation

### 1.1 What needs to be built

**New module:** `volume_conservation.py`

The module must validate that, for a fixed upright draft, the displaced volume computed from the heeled hull geometry matches the upright displaced volume within tolerance.

### 1.2 Technical approach

For each heel angle θ ∈ {0°, 5°, 10°, …, 60°}:

1. **Rotate hull coordinates** about the longitudinal (x) axis:
   ```
   y' =  y × cos(θ) - z × sin(θ)
   z' =  y × sin(θ) + z × cos(θ)
   ```
2. **Find the heeled waterplane elevation** `z'_wl` such that the submerged volume of the rotated hull equals the upright displaced volume `V₀`. Solve via bisection on `z'_wl`.
3. **Recompute V(θ)** by integrating sectional areas of the clipped heeled hull up to `z'_wl`.
4. **Report deviation:** `ΔV(θ) = |V(θ) − V₀| / V₀ × 100%`

### 1.3 Acceptance criteria

| Metric | Target | Maximum |
|---|---|---|
| Volume deviation at each heel angle | < 1% | ≤ 3% |

### 1.4 Output

- `volume_conservation.csv` — columns: `heel_deg, V_upright_m3, V_heeled_m3, deviation_pct`
- Console pass/fail summary per angle
- Integration into `main.py` as **Phase 2b** (after geometry validation, before hydrostatics)

### 1.5 Dependency on geometric GZ

This work establishes the heeled-hull integration infrastructure that Feature 2 (geometric GZ/KN), Feature 3 (KG sensitivity), and Feature 4 (optimization) all build on. **Build this first.**

---

## 2. Feature 2 — Geometric GZ / KN Cross-Curves

### 2.1 What needs to be built

**New module:** `geometric_gz.py`

Replace the current `GZ = GM × sin(θ)` approximation with a full geometric GZ computation that remains accurate beyond 15°.

### 2.2 Technical approach

For each heel angle θ:

1. **Heel the hull** (same rotation as §1.2).
2. **Find the waterplane** at which the submerged volume equals `V₀` (same bisection as §1.2 — reuse `volume_conservation.py` internals via a shared helper).
3. **Locate the heeled center of buoyancy B'(θ):**
   - Compute centroid of the submerged volume in the heeled frame.
   - Rotate back to the upright frame to get B'_y, B'_z.
4. **Compute GZ(θ):**
   ```
   GZ(θ) = B'_y(θ) × cos(θ) + (B'_z(θ) − KG) × sin(θ)
   ```
   where KG is the user-supplied vertical center of gravity.
5. **Compute KN(θ):**
   ```
   KN(θ) = GZ(θ) + KG × sin(θ)
   ```
   This is the true KN cross-curve value.

### 2.3 Integration into existing pipeline

- `gz_curve.py`: Add `compute_geometric_gz_curve(stations, waterlines, offset_table, draft, rho, KG, heel_angles)` as the primary path. Keep the old `GM × sin(θ)` function as a fallback clearly labeled `compute_simplified_gz_curve`.
- `main.py`: Phase 6 (GZ curve) calls `compute_geometric_gz_curve` by default.

### 2.4 Output additions

- `gz_curve.csv` — add column `gz_geometric` alongside existing `gz_simplified`
- `kn_curve.csv` (new) — columns: `heel_deg, kn_geometric, kn_simplified`
- `gz_curve.png` — overlay both curves, legend distinguishing geometric vs simplified

### 2.5 Acceptance criteria

- Max deviation between geometric and simplified GZ at θ ≤ 15° must be < 5% (sanity check)
- Geometric GZ must be zero at θ = 0° and physically plausible (positive for stable ship)

---

## 3. Feature 3 — ShipD Benchmark Validation

### 3.1 What needs to be built

**New module:** `shipd_converter.py` — converts ShipD parametric hull to offset table  
**New module:** `benchmark_validation.py` — orchestrates 10-hull benchmark run

### 3.2 Converter: ShipD hull → offset table

**Source data:** `ShipD_repo/Input_Vectors_SampleHulls.csv` (already in workspace)  
**Hull generator:** `ShipD_repo/HullParameterization.py` — `Hull_Parameterization` class

#### Step-by-step

1. **Select 10 diverse hulls** from `Input_Vectors_SampleHulls.csv`:
   - Sample to maximize diversity across LOA, beam, draft ratio (e.g., use k-means on the 45-parameter vectors, pick centroid-nearest hull per cluster).
   
2. **Instantiate hull:** `hull = Hull_Parameterization(design_vector)`

3. **Generate waterline contours** at `N_WL = 20` uniformly spaced waterlines from keel to deck:
   - Use `hull.gen_pointCloud(NUM_WL=20, PointsPerWL=200)` or equivalent method.
   - If the class exposes only an STL generator, extract cross-sections from the mesh triangles via z-plane slicing (z = waterline elevation).

4. **Extract half-breadths at stations** `N_STA = 21` uniformly spaced stations from AP to FP:
   - For each waterline contour, sample the maximum y-coordinate (half-breadth) at each x-station via linear interpolation.

5. **Build offset table:** shape `(N_WL, N_STA)`, values in meters.

6. **Compute reference draft** as `WL` parameter of hull (parameter index 6, scaled by `Dd`).

7. **Compute reference KG** as `2/3 × Dd` (consistent with existing pipeline default).

#### Output per hull `i`

```
benchmarks/sample_i/
  offsets.csv        # offset table (waterlines × stations)
  metadata.json      # LOA, Bd, Dd, draft, KG, rho
```

### 3.3 Hydrostatics computation

For each of the 10 hulls, run the existing pipeline phases 3–7:
- `compute_phase3` → volume, sectional areas
- `compute_phase4` → LCB, LCF, KB, BM, GM
- `compute_geometric_gz_curve` → GZ and KN curves

Output:
```
benchmarks/sample_i/
  gz_model.csv       # columns: heel_deg, gz_geometric, gz_simplified
  kn_model.csv       # columns: heel_deg, kn_geometric
  results.csv        # same schema as main pipeline results.csv
```

### 3.4 Reference comparison and error metrics

#### Reference values

Since the ShipD dataset provides parametric hulls (not tabulated hydrostatic tables), reference values must be derived analytically:
- **GM_ref:** Compute from the hull's own parametric geometry using a finer grid (`N_WL=50, N_STA=100`) as the ground truth. The coarse-grid computation (`N_WL=20, N_STA=21`) is compared against this.
- **GZ_ref:** GZ curve from fine grid computation.
- **V_ref:** Displaced volume from fine grid.

#### Error metrics

```
benchmarks/sample_i/error_metrics.json
{
  "gm_error_pct":        < 2% target,
  "gz_max_deviation_pct": < 5% target,
  "volume_deviation_pct": < 3% target,
  "lcb_error_m":         informational,
  "kb_error_m":          informational
}
```

### 3.5 Acceptance criteria

| Metric | Acceptance |
|---|---|
| GM error | ≤ 2% vs fine-grid reference |
| GZ deviation (max across angles) | ≤ 5% vs fine-grid reference |
| Volume consistency across heel angles | ≤ 3% (re-uses Feature 1) |
| All 10 hulls must pass | No hull may exceed the maximum thresholds |

### 3.6 Dependencies

- Requires `ShipD_repo/` to be importable — add `ShipD_repo/` to `sys.path` in `shipd_converter.py`
- Requires `numpy-stl` package if using STL path: `pip install numpy-stl`
- Requires Feature 2 (geometric GZ) for KN curves

---

## 4. Feature 4 — KG Sensitivity Analysis + Interactive UI

### 4.1 What needs to be built

**New module:** `kg_sensitivity.py` — batch GZ computation across KG scenarios  
**New module:** `interactive_ui.py` — Streamlit interactive app

### 4.2 KG sensitivity computation

`kg_sensitivity.py` must:

1. Accept a list of KG values (default: 5 scenarios — `KG × {0.7, 0.85, 1.0, 1.15, 1.3}`).
2. For each KG scenario, compute:
   - GZ curve via `compute_geometric_gz_curve` (Feature 2)
   - GM = KB + BM − KG
   - Range of stability (heel angle where GZ first returns to zero after maximum)
   - Area under GZ curve from 0° to 30° (IMO DSC criterion proxy)
3. Output a summary table: `kg_sensitivity.csv` — columns: `kg_m, gm_m, max_gz_m, angle_max_gz_deg, range_stability_deg, area_0_30`

### 4.3 KN → GZ transformation visualization

Produce a static chart (`kn_gz_transform.png`) showing:
- Top subplot: KN cross-curves for each KG scenario (KN vs heel)
- Bottom subplot: GZ curves derived from each KN curve via `GZ = KN − KG × sin(θ)`
- Annotation showing how reducing KG shifts the GZ curve upward

This visualization must clarify the `KN → GZ` transformation explicitly (PRD §4.4).

### 4.4 Interactive Streamlit app

`interactive_ui.py` — `streamlit run interactive_ui.py`

The app has **four tabs**: Stability Explorer, KN → GZ Transform, Benchmark Validation, and Offset Optimizer.

---

#### Tab 1 — Stability Explorer

```
Sidebar controls (shared across Tab 1 & Tab 2)
  - KG slider:  min = 0.5 × KG_default,  max = 1.5 × KG_default,  step = 0.1 m
  - Draft slider: min = 0.5 × draft, max = waterlines[-1], step = 0.5 m
  - Show simplified GZ overlay (checkbox)

Main panel  (three rows)

Row 1 — GZ and KN charts (side by side, 2 columns)
  Left: GZ curve chart (Plotly, updates on slider change)
      - Geometric GZ line (primary)
      - Simplified GZ line (optional overlay)
      - Shaded "positive stability" area under curve
      - Vertical dashed line at current angle of max GZ
  Right: KN curve chart (Plotly)
      - KN cross-curve for current KG
      - Annotation: GZ = KN − KG·sin(θ)

Row 2 — Volume Conservation chart (full width)
  Title: "Displaced Volume vs Heel Angle"
  Data source: volume_conservation.csv (pre-computed by Feature 1 at current draft)
  Chart type: Plotly line + marker
      - Primary y-axis (left):  V_heeled_m3 vs heel_deg
          - Solid blue line labelled "Heeled Volume V(θ)"
          - Horizontal dashed grey line at V_upright_m3 labelled "Upright V₀"
      - Secondary y-axis (right): deviation_pct vs heel_deg
          - Dashed red line labelled "Deviation from V₀ (%)"
          - Horizontal dotted lines at ±1% (green) and ±3% (orange) showing
            acceptance thresholds
      - x-axis: heel angle (degrees), 0–60°
  Below chart: small metric row showing max deviation across all angles,
               with a ✓ (< 1%) / ⚠ (1–3%) / ✗ (> 3%) badge
  Note: if volume_conservation.csv is absent, show a grey placeholder
        panel with the message "Run pipeline first to generate volume
        conservation data."

Row 3 — Hydrostatic summary table (full width)
  - GM, BM, KB, Range of Stability (updates on slider change)
```

---

#### Tab 2 — KN → GZ Transform

Static/interactive chart showing:
- Top subplot: KN cross-curves for all KG sensitivity scenarios
- Bottom subplot: GZ curves derived via `GZ = KN − KG × sin(θ)`, one line per KG
- Annotation arrows showing the vertical shift caused by changing KG

---

#### Tab 3 — Benchmark Validation

Displays results from `benchmark_validation.py` (Feature 3). Requires benchmark run to have been executed; shows a placeholder message if `benchmarks/` directory is absent.

```
Top section — Summary table (one row per hull)
  Columns: Hull ID | LOA (m) | Beam (m) | Draft (m) | GM_coarse (m) | GM_fine (m)
           | GM_error_pct | GZ_max_dev_pct | Volume_dev_pct | Pass/Fail
  - Rows that exceed any acceptance threshold are highlighted in red
  - Rows that pass all criteria are highlighted in green

Hull detail section
  - Dropdown: select hull 0–9
  - On selection, render:
      a) GZ comparison chart (Plotly)
           - Coarse-grid GZ (solid line)
           - Fine-grid GZ reference (dashed line)
           - Shaded band showing ±5% tolerance around fine-grid GZ
      b) KN comparison chart (same coarse vs fine structure)
      c) Error metrics panel
           - GM error %, GZ max deviation %, Volume deviation %
           - Each shown as a metric with a ✓/✗ pass-fail badge
      d) Principal dimensions card
           - LOA, Bd, Dd, draft, KG, rho from metadata.json
```

**Data loading:** Read from `benchmarks/sample_i/` at startup using `st.cache_data`. Re-run button triggers `benchmark_validation.py` as a subprocess and refreshes the cache.

---

#### Tab 4 — Offset Optimizer

Full UI for configuring, running, and reviewing offset optimization (Feature 5). Detailed spec in §5.5 (UI section).

---

**Performance constraint:** GZ curve must recompute in < 3 seconds on the existing hull data when the slider is moved. Achieve this by pre-computing the heeled volume integrals at fixed hull geometry and parameterizing by KG at runtime (since KG only affects the final `GZ = KN − KG × sin(θ)` step, the expensive geometric computation only reruns when draft changes).

**Dependency:** `streamlit`, `plotly` (already in use)

---

## 5. Feature 5 — Offset Optimization

### 5.1 What needs to be built

**New module:** `offset_optimizer.py` — solver logic and infeasibility analysis  
**UI surface:** Tab 4 of `interactive_ui.py` — constraint input forms and results display

### 5.2 Optimization problem definition

**Decision variables:** A perturbed offset table `T'` where each half-breadth `b'[i,j]` is derived from the original `b[i,j]`:
```
b'[i,j] = b[i,j] × (1 + δ[i,j])
```
Only waterlines at or below draft are optimized (above-waterline offsets are fixed).

**Objective:** Maximize GZ at a user-specified target heel angle `θ_target` (default 30°):
```
maximize  GZ(θ_target; T', KG)
```

**Constraints (all user-configurable via UI — see §5.5):**
1. **Half-breadth perturbation bound** `p_max`: `|δ[i,j]| ≤ p_max` (box constraint; default 5%)
2. **Volume conservation**: `|V(T') − V(T)| / V(T) ≤ 0.01`
3. **Minimum GZ at 5 user-specified heel angles**: `GZ(θₖ; T') ≥ gz_min_k` for k = 1…5
4. **Minimum area under GZ curve**: `∫₀^{θ_max} GZ dθ ≥ area_min`
5. **Offset non-negativity**: `b'[i,j] ≥ 0` for all i, j

Constraints 3 and 4 are the new additions. All five are exposed as editable inputs in Tab 4 of the UI.

### 5.3 Solver approach

Use `scipy.optimize.minimize` with method `SLSQP`:
- Variables: flattened `δ` array of shape `(N_WL_submerged × N_STA,)`
- Bounds: `(-p_max, +p_max)` for all (driven by UI input)
- Constraints expressed as `{'type': 'ineq', 'fun': ...}` entries:
  - Volume: `V_0 × 0.99 ≤ V(T') ≤ V_0 × 1.01`
  - Per-angle GZ: `GZ(θₖ; T') − gz_min_k ≥ 0` for each of the 5 heel angles
  - Area: `area(T') − area_min ≥ 0`
- Gradient approximation: `'2-point'` finite differences
- Max iterations: 300

Initial guess: `δ = 0` (start from existing offsets).

### 5.4 Infeasibility detection and relaxation guidance

When SLSQP returns `status != 0` (infeasible or no convergence), `offset_optimizer.py` must run a **constraint relaxation analysis** before surfacing a result.

#### Algorithm

1. **Identify violated constraints** by evaluating each constraint function at the final (failed) iterate `δ*`.

2. For each violated constraint, compute the **minimum relaxation needed** to make it individually satisfiable while holding all others fixed:

   | Constraint | Relaxation metric | How computed |
   |---|---|---|
   | GZ at θₖ ≥ gz_min_k | Reduce `gz_min_k` by Δ | Binary search on Δ until feasibility is recovered for that constraint alone |
   | Area ≥ area_min | Reduce `area_min` by Δ | Same binary search |
   | p_max too tight | Increase `p_max` by Δ% | Solve 1-D problem: minimum `p_max` that achieves the objective ignoring GZ/area constraints |

3. Compute **simultaneous relaxation**: the minimum uniform scale factor `s < 1` applied to all soft constraints (`gz_min_k × s`, `area_min × s`) that restores feasibility, using a bisection on `s` ∈ [0, 1].

4. Package results into `InfeasibilityReport`:

```python
@dataclass
class InfeasibilityReport:
    violated_constraints: list[str]         # names of violated constraints
    per_constraint_relaxation: dict[str, float]  # min Δ per constraint
    simultaneous_scale_factor: float        # s such that all soft constraints × s is feasible
    suggested_p_max: float                  # minimum p_max to achieve objective alone
    explanation: str                        # human-readable summary
```

#### Explanation string format

```
The optimization is infeasible with the current constraints.

Violated constraints:
  • GZ at 20° ≥ 0.45 m  →  relax to ≥ 0.38 m  (reduce by 0.07 m / 15.6%)
  • Area under GZ ≥ 0.30 m·rad  →  relax to ≥ 0.24 m·rad  (reduce by 0.06 m·rad / 20.0%)

Alternatively, relaxing all soft constraints uniformly by 18% restores feasibility.

If you prefer not to relax GZ/area constraints, increasing the maximum offset
perturbation from 5% to 7.2% would allow the optimizer to meet the objective.
```

### 5.5 UI — Tab 4 (Offset Optimizer)

```
Tab 4 layout

┌─ Constraint Configuration ──────────────────────────────────────┐
│  Target heel angle for GZ objective:  [30°  ▼]                  │
│                                                                   │
│  Max half-breadth perturbation (%):   [5 ────────────── 20]      │
│                                                                   │
│  Minimum GZ constraints (5 heel angles)                          │
│  ┌──────────┬──────────┬──────────┬──────────┬──────────┐        │
│  │ Heel (°) │ 10       │ 20       │ 30       │ 40       │ 50     │
│  │ Min GZ   │ [0.20 m] │ [0.40 m] │ [0.50 m] │ [0.45 m] │[0.30m]│
│  └──────────┴──────────┴──────────┴──────────┴──────────┘        │
│  (heel angles are editable number inputs; GZ mins are sliders)    │
│                                                                   │
│  Minimum area under GZ curve (m·rad):  [0.25 ──────── 0.60]      │
│                                                                   │
│  [Run Optimization]  button                                       │
└───────────────────────────────────────────────────────────────────┘

┌─ Results ───────────────────────────────────────────────────────┐
│  [shown only after run]                                          │
│                                                                   │
│  Status badge:  ✓ CONVERGED  /  ✗ INFEASIBLE                    │
│                                                                   │
│  If CONVERGED:                                                    │
│    - Before / After comparison table                             │
│        GZ at target heel, max GZ, area under curve,             │
│        max offset change %, volume deviation %                   │
│    - GZ curve overlay chart                                      │
│        Original GZ (dashed) vs Optimized GZ (solid)             │
│        Horizontal lines at each gz_min_k constraint              │
│    - Offset perturbation heatmap                                 │
│        Plotly heatmap of δ[i,j] × 100 (%)                       │
│        x-axis = stations, y-axis = waterlines                    │
│        Color scale: red = +p_max%, blue = −p_max%, white = 0     │
│    - [Download optimized_offsets.csv] button                     │
│    - [Download optimization_report.json] button                  │
│                                                                   │
│  If INFEASIBLE:                                                   │
│    - Red banner: "Optimization infeasible"                       │
│    - Violated constraints list (from InfeasibilityReport)        │
│    - Relaxation suggestions table                                │
│        ┌────────────────────┬──────────────┬───────────────┐     │
│        │ Constraint         │ Current value│ Suggested     │     │
│        │                    │              │ (min relaxed) │     │
│        ├────────────────────┼──────────────┼───────────────┤     │
│        │ GZ at 20° (m)      │ 0.45         │ 0.38          │     │
│        │ Area (m·rad)       │ 0.30         │ 0.24          │     │
│        │ Max perturbation % │ 5.0          │ 7.2           │     │
│        └────────────────────┴──────────────┴───────────────┘     │
│    - "Apply suggested relaxations" button                        │
│        → pre-fills the constraint inputs above with the          │
│          suggested values, ready for re-run                      │
└───────────────────────────────────────────────────────────────────┘
```

**"Apply suggested relaxations"** populates the constraint form fields with the per-constraint suggestions from `InfeasibilityReport.per_constraint_relaxation` and scrolls back to the configuration panel so the user can review before re-running.

### 5.6 CLI integration

Add CLI flags to `main.py` for headless runs (constraints passed as JSON):
```
python main.py "HYDRO HACKATHON DATA.xlsx" \
  --optimize \
  --target-heel 30 \
  --opt-constraints '{"p_max": 0.05, "gz_min": {"10":0.2, "20":0.4, "30":0.5, "40":0.45, "50":0.3}, "area_min": 0.25}'
```

### 5.7 Output files

`optimized_offsets.csv` — same format as input offset table, with optimized half-breadths

`optimization_report.json`:
```json
{
  "status": "converged",
  "target_heel_deg": 30,
  "constraints": {
    "p_max_pct": 5.0,
    "gz_min_at_angles": {"10": 0.20, "20": 0.40, "30": 0.50, "40": 0.45, "50": 0.30},
    "area_min": 0.25
  },
  "gz_before": 0.612,
  "gz_after":  0.718,
  "gz_improvement_pct": 17.3,
  "area_gz_before": 0.284,
  "area_gz_after":  0.331,
  "volume_deviation_pct": 0.43,
  "max_offset_change_pct": 4.97,
  "iterations": 87,
  "infeasibility_report": null
}
```

When infeasible, `"status": "infeasible"`, `"infeasibility_report"` is populated with per-constraint relaxation values, and `gz_after` / `area_gz_after` reflect the best iterate found.

### 5.8 Acceptance criteria

| Metric | Requirement |
|---|---|
| Offset variation | ≤ p_max per cell (user-set, default 5%) |
| Volume conservation | ≤ 1% deviation |
| GZ at target heel | Must meet or exceed objective when feasible |
| GZ at 5 constrained angles | Must meet gz_min_k when converged |
| Area under GZ | Must meet area_min when converged |
| Infeasibility response | Must always produce relaxation suggestions; never silently fail |

---

## 6. Shared Infrastructure Changes

### 6.1 Heeled-hull integration helper

Both Feature 1 and Feature 2 require rotating hull coordinates and integrating submerged volume. Extract this into a shared helper to avoid duplication.

**New file:** `hull_geometry.py`

```python
def rotate_hull(stations, waterlines, offset_table, heel_deg) -> dict:
    """Return heeled hull coordinate arrays (x, y, z grids)."""

def find_heeled_waterplane(heeled_hull, target_volume, tol=1e-4) -> float:
    """Bisection search for z'_wl such that submerged volume == target_volume."""

def integrate_heeled_volume(heeled_hull, z_wl) -> float:
    """Integrate submerged volume of heeled hull up to waterplane z_wl."""

def heeled_buoyancy_centroid(heeled_hull, z_wl) -> tuple[float, float]:
    """Return (y_B, z_B) of buoyancy centroid in heeled frame."""
```

### 6.2 CSV offset input support

`ship_excel_extractor.py` currently only reads `.xlsx`. Add a CSV path in `main.py`:
- If input file ends in `.csv`, load directly as offset table using `offsetdata.csv` column schema.
- Needed for ShipD benchmark (`benchmarks/sample_i/offsets.csv` files).

**New function:** `load_offsets_from_csv(csv_path) -> dict` in `ship_excel_extractor.py`.

### 6.3 Results schema extension

`results.csv` currently outputs 19 scalar parameters. Extend schema to include:

| New column | Source |
|---|---|
| `gz_geometric_at_30deg` | Feature 2 |
| `range_of_stability_deg` | Feature 2 |
| `area_under_gz_0_30` | Feature 4 |
| `volume_conservation_max_dev_pct` | Feature 1 |

### 6.4 Dependency additions

Add to `requirements.txt` (create if absent):
```
numpy>=1.24
scipy>=1.10         # Feature 5 optimizer
streamlit>=1.30     # Feature 4 UI
plotly>=5.0         # existing, verify version
pandas>=2.0
matplotlib>=3.7
numpy-stl>=3.0      # Feature 3, STL path only
```

---

## 7. File Structure After Round 2

```
Hydrohackathon/
  main.py                  # updated: --optimize flag, Phase 2b, CSV input
  ship_excel_extractor.py  # updated: load_offsets_from_csv()
  integration.py           # unchanged
  hydrostatics.py          # unchanged
  stability.py             # unchanged
  gz_curve.py              # updated: geometric path + simplified fallback
  visualization_3d.py      # unchanged
  insights.py              # minor: add optimization summary section
  hull_geometry.py         # NEW: shared heeled-hull integration helpers
  volume_conservation.py   # NEW: Feature 1
  geometric_gz.py          # NEW: Feature 2
  shipd_converter.py       # NEW: Feature 3 converter
  benchmark_validation.py  # NEW: Feature 3 orchestrator
  kg_sensitivity.py        # NEW: Feature 4 batch sensitivity
  interactive_ui.py        # NEW: Feature 4 Streamlit app (4 tabs)
  offset_optimizer.py      # NEW: Feature 5 solver + InfeasibilityReport
  requirements.txt         # NEW
  benchmarks/
    sample_0/ … sample_9/
      offsets.csv
      metadata.json
      gz_model.csv
      kn_model.csv
      results.csv
      error_metrics.json
  results/
    gz_curve.csv            # extended with geometric column
    kn_curve.csv            # NEW
    volume_conservation.csv # NEW
    kg_sensitivity.csv      # NEW
    kn_gz_transform.png     # NEW
    optimized_offsets.csv   # NEW (if --optimize)
    optimization_report.json # NEW (if --optimize; includes infeasibility_report when infeasible)
```

---

## 8. Technical Requirements

These requirements apply globally across all features and must be satisfied independently of any individual feature.

### 8.1 Language and runtime
- Python 3.11+. All new modules must include type annotations on public function signatures.
- No global mutable state. All computation functions must be pure (same inputs → same outputs, no side effects other than explicit file I/O).

### 8.2 Code quality
- **Linting:** `ruff check .` must pass with zero errors. Config in `pyproject.toml`.
- **Type checking:** `mypy --strict` must pass on all new modules. Existing modules are exempt but must not regress.
- **Formatting:** `ruff format .` (line length 100). Enforced in CI.
- **Docstrings:** Every public function in new modules must have a one-line summary docstring. Full NumPy-style docstrings for functions with more than 3 parameters.

### 8.3 Dependency management
- `requirements.txt` pinned to exact versions (`==`) for reproducibility.
- A separate `requirements-dev.txt` for test/lint tools: `pytest`, `pytest-cov`, `playwright`, `mypy`, `ruff`.
- No transitive dependency may be added without being explicitly listed.

### 8.4 Numerical precision
- All floating-point intermediate results must use `float64`. No implicit `float32` downcasting.
- Integration tolerance for bisection solver (volume conservation, waterplane search): `tol = 1e-4 m³` absolute.
- GZ values rounded to 6 decimal places in all CSV outputs to prevent false precision.

### 8.5 Error handling
- All file I/O must raise `FileNotFoundError` with a descriptive message rather than letting Python's default traceback propagate to the user.
- Numerical failures (NaN in output, non-convergence of bisection after 100 iterations) must raise `RuntimeError` with the failed angle and last residual in the message.
- The UI must catch all `RuntimeError` / `ValueError` from backend modules and display them as `st.error()` banners, never as unhandled exceptions.

### 8.6 Performance targets
| Operation | Target wall time |
|---|---|
| `hull_geometry.rotate_hull` for one angle | < 50 ms |
| Full volume conservation pass (13 angles) | < 2 s |
| Full geometric GZ curve (61 angles, 1° step) | < 30 s |
| Streamlit GZ recompute on KG slider change | < 3 s (cached KN table) |
| Benchmark: one hull full pipeline | < 60 s |

### 8.7 Logging
- Use Python's `logging` module. Default level `INFO` for pipeline runs, `DEBUG` available via `--verbose` flag.
- Never use bare `print()` in library modules (`hull_geometry.py`, `geometric_gz.py`, etc.). Only `main.py` and `interactive_ui.py` may use `print()` / `st.write()`.

### 8.8 Security
- No `eval()` or `exec()` anywhere in the codebase.
- JSON constraint input from CLI (`--opt-constraints`) must be parsed with `json.loads()` and validated against a schema (use `jsonschema`) before being passed to the optimizer. Invalid input must raise a clear `ValueError`, not crash with a `KeyError`.

---

## 9. Implementation Plan

### 9.1 Philosophy

Each deliverable below is a **task**: the smallest independently mergeable unit of work. A task is "done" only when its code, its unit tests, and (where applicable) its E2E tests all pass in CI. Tasks are ordered so that each one's dependencies are already merged before it begins.

Tasks within the same feature are numbered `Fx.Ty` (Feature x, Task y). Tasks are designed so that no two within the same feature have a hard dependency on each other unless explicitly stated — this keeps parallel development possible within a feature once its predecessors are merged.

### 9.2 Task breakdown

---

#### F0 — Infrastructure (no feature dependency)

**F0.T1 — Project scaffolding**
- Create `pyproject.toml` with ruff + mypy config
- Create `requirements.txt` and `requirements-dev.txt`
- Create `tests/` directory with `conftest.py` (shared fixtures: sample offset table, stations, waterlines arrays)
- Create `.github/workflows/ci.yml` (see §11)
- *Tests:* CI workflow runs `ruff check .` and `mypy` — both must exit 0

**F0.T2 — Shared fixture data**
- Add `tests/fixtures/sample_offsets.csv` — a minimal synthetic offset table (5 waterlines × 7 stations, known analytic volume)
- Add `tests/fixtures/box_barge_offsets.csv` — rectangular barge with analytically known V, GZ, BM
- *Tests:* `test_fixtures.py` — assert fixtures load correctly and have expected shape

---

#### F1 — Volume Conservation

**F1.T1 — `hull_geometry.py`: rotation and volume integration**
- Implement `rotate_hull()`, `integrate_heeled_volume()`, `find_heeled_waterplane()`, `heeled_buoyancy_centroid()`
- *Unit tests* (`tests/test_hull_geometry.py`):
  - `test_rotate_hull_at_zero_deg` — rotation at 0° returns input unchanged
  - `test_rotate_hull_90deg_swaps_axes` — at 90°, y and z coordinates swap with correct sign
  - `test_integrate_heeled_volume_box_barge` — box barge volume matches analytic `L × B × draft`
  - `test_find_heeled_waterplane_converges` — bisection returns result within tolerance
  - `test_heeled_buoyancy_centroid_box_barge` — centroid at `draft/2` for box barge at 0°

**F1.T2 — `volume_conservation.py`: validation pass**
- Implement `run_volume_conservation(stations, waterlines, offset_table, draft, rho, heel_angles)` returning a DataFrame
- Implement `volume_conservation_summary(df)` returning `{"max_dev_pct": float, "status": "pass"|"warn"|"fail"}`
- *Unit tests* (`tests/test_volume_conservation.py`):
  - `test_volume_conservation_zero_heel` — deviation = 0% at θ = 0°
  - `test_volume_conservation_box_barge_30deg` — box barge deviation < 0.1% (analytic case)
  - `test_volume_conservation_summary_pass` — max_dev < 1% → status = "pass"
  - `test_volume_conservation_summary_warn` — max_dev between 1–3% → status = "warn"
  - `test_volume_conservation_summary_fail` — max_dev > 3% → status = "fail"
  - `test_volume_conservation_csv_output` — output CSV has correct columns and row count

**F1.T3 — Integrate into `main.py` as Phase 2b**
- Wire `run_volume_conservation()` into the pipeline after Phase 2
- Write `volume_conservation.csv` to output directory
- *Unit tests* (`tests/test_main_pipeline.py`):
  - `test_phase2b_runs_without_error` — pipeline completes Phase 2b on sample fixture
  - `test_phase2b_output_file_exists` — `volume_conservation.csv` written to output dir

---

#### F2 — Geometric GZ / KN

**F2.T1 — `geometric_gz.py`: core GZ computation**
- Implement `compute_geometric_gz_curve(stations, waterlines, offset_table, draft, rho, KG, heel_angles)` returning `{"heel_deg", "gz_geometric", "kn_geometric"}`
- Internally calls `hull_geometry` helpers from F1.T1
- *Unit tests* (`tests/test_geometric_gz.py`):
  - `test_gz_zero_at_zero_heel` — GZ(0°) = 0.0
  - `test_gz_positive_for_stable_hull` — GZ > 0 for θ ∈ (0°, 90°) on box barge with positive GM
  - `test_kn_equals_gz_plus_kg_sin_theta` — identity `KN = GZ + KG × sin(θ)` holds to 1e-6
  - `test_gz_agrees_with_simplified_at_5deg` — deviation < 1% vs `GM × sin(5°)` on box barge
  - `test_gz_negative_for_unstable_hull` — hull with KG > KM returns negative GM and GZ < 0 near 0°

**F2.T2 — Update `gz_curve.py` to expose both paths**
- Rename existing function to `compute_simplified_gz_curve`
- Add `compute_geometric_gz_curve` as re-export from `geometric_gz.py`
- Update CSV and PNG outputs to include both columns
- *Unit tests* (`tests/test_gz_curve.py`):
  - `test_csv_has_geometric_column` — `gz_curve.csv` includes `gz_geometric`
  - `test_csv_has_simplified_column` — `gz_curve.csv` includes `gz_simplified`
  - `test_kn_csv_written` — `kn_curve.csv` created with correct columns
  - `test_png_output_created` — `gz_curve.png` file exists after call

**F2.T3 — Wire geometric GZ into `main.py` Phase 6**
- Phase 6 calls geometric path by default
- *Unit tests* (`tests/test_main_pipeline.py`):
  - `test_phase6_uses_geometric_gz` — results.csv `gz_geometric_at_30deg` column is non-NaN

---

#### F3 — ShipD Benchmark

**F3.T1 — `shipd_converter.py`: parametric hull → offset table**
- Implement `select_diverse_hulls(input_csv, n=10)` using k-means on design vectors
- Implement `hull_to_offset_table(design_vector, n_wl=20, n_sta=21)` using `Hull_Parameterization`
- Implement `save_benchmark_sample(hull_idx, offsets, metadata, out_dir)`
- *Unit tests* (`tests/test_shipd_converter.py`):
  - `test_select_diverse_hulls_returns_n` — returns exactly 10 indices
  - `test_hull_to_offset_table_shape` — output shape is `(n_wl, n_sta)`
  - `test_hull_to_offset_table_no_negatives` — all half-breadths ≥ 0
  - `test_hull_to_offset_table_monotone_keel` — breadths at keel station non-negative
  - `test_save_benchmark_sample_creates_files` — `offsets.csv` and `metadata.json` written

**F3.T2 — `ship_excel_extractor.py`: add `load_offsets_from_csv()`**
- Implement `load_offsets_from_csv(csv_path) -> dict` matching the dict schema of `extract_ship_data()`
- *Unit tests* (`tests/test_ship_excel_extractor.py`):
  - `test_load_offsets_from_csv_schema` — returned dict has keys `offset_table`, `stations`, `waterlines`, `draft`, `rho`, `KG`
  - `test_load_offsets_from_csv_roundtrip` — save then reload returns identical arrays

**F3.T3 — `benchmark_validation.py`: orchestrate 10-hull run**
- Implement `run_benchmark(input_csv, out_dir, n_hulls=10)` running coarse + fine grid on each hull
- Implement `compute_error_metrics(coarse_results, fine_results)` returning `error_metrics.json` schema
- *Unit tests* (`tests/test_benchmark_validation.py`):
  - `test_error_metrics_schema` — JSON has required keys
  - `test_gm_error_formula` — `gm_error_pct = |gm_coarse - gm_fine| / gm_fine × 100`
  - `test_all_output_files_written` — all 4 files exist per sample dir after run (using 1 hull for speed)

---

#### F4 — KG Sensitivity + Interactive UI

**F4.T1 — `kg_sensitivity.py`**
- Implement `run_kg_sensitivity(stations, waterlines, offset_table, draft, rho, kg_values, heel_angles)`
- *Unit tests* (`tests/test_kg_sensitivity.py`):
  - `test_higher_kg_lower_gm` — monotone inverse relationship
  - `test_area_decreases_with_kg` — area under GZ curve decreases as KG increases
  - `test_csv_output_schema` — `kg_sensitivity.csv` has all required columns

**F4.T2 — `interactive_ui.py`: Tab 1 (Stability Explorer) + Tab 2 (KN→GZ)**
- Implement Tabs 1 and 2 with KG/draft sliders, GZ chart, KN chart, volume conservation chart, hydrostatic table
- *E2E tests* (`tests/e2e/test_ui_tab1.py` via Playwright):
  - `test_tab1_loads` — page loads with title visible
  - `test_gz_chart_renders` — Plotly GZ chart element present in DOM
  - `test_volume_conservation_chart_renders` — dual-axis chart element present
  - `test_kg_slider_updates_gm` — move KG slider, assert GM metric value changes
  - `test_tab2_kn_chart_renders` — KN cross-curve chart visible on Tab 2

**F4.T3 — `interactive_ui.py`: Tab 3 (Benchmark Validation)**
- Implement summary table and hull-detail drill-down
- *E2E tests* (`tests/e2e/test_ui_tab3.py`):
  - `test_tab3_placeholder_when_no_benchmarks` — placeholder message shown if `benchmarks/` absent
  - `test_tab3_summary_table_renders` — table with ≥1 row shown when benchmarks present (use stub data)
  - `test_tab3_hull_dropdown_changes_chart` — select hull 1, GZ chart updates

**F4.T4 — `interactive_ui.py`: Tab 4 (Offset Optimizer UI)**
- Implement constraint input form, run button, converged results panel, infeasibility panel
- *E2E tests* (`tests/e2e/test_ui_tab4.py`):
  - `test_tab4_form_renders` — all 5 GZ-min inputs and area-min slider present
  - `test_tab4_run_button_exists` — "Run Optimization" button in DOM
  - `test_tab4_infeasibility_panel_shown` — given stub infeasible result, red banner visible
  - `test_tab4_apply_relaxations_button_prefills_form` — click "Apply suggested relaxations", assert input values updated

---

#### F5 — Offset Optimization

**F5.T1 — `offset_optimizer.py`: solver**
- Implement `OptimizationConstraints` dataclass and `run_optimization(offsets, constraints, KG, draft, rho)` returning `OptimizationResult`
- *Unit tests* (`tests/test_offset_optimizer.py`):
  - `test_optimization_converges_default_constraints` — status = "converged" on sample hull
  - `test_optimized_offsets_within_bounds` — all `|δ| ≤ p_max`
  - `test_optimized_volume_deviation` — ≤ 1%
  - `test_gz_constraint_satisfied` — GZ at each of 5 angles ≥ gz_min_k
  - `test_area_constraint_satisfied` — area ≥ area_min
  - `test_optimization_report_json_schema` — required keys present

**F5.T2 — `offset_optimizer.py`: `InfeasibilityReport`**
- Implement `analyze_infeasibility(constraints, final_iterate, hull_data)` returning `InfeasibilityReport`
- *Unit tests* (`tests/test_offset_optimizer.py`):
  - `test_infeasibility_detected_on_tight_constraints` — status = "infeasible" when `gz_min = current_max_gz × 2`
  - `test_infeasibility_report_populated` — `violated_constraints` list non-empty
  - `test_per_constraint_relaxation_positive` — all values > 0
  - `test_simultaneous_scale_factor_in_0_1` — value between 0 and 1
  - `test_rerun_with_suggested_relaxations_converges` — applying report values to constraints → status = "converged"

**F5.T3 — Wire optimizer into `main.py` CLI**
- Add `--optimize` and `--opt-constraints` flags
- *Unit tests* (`tests/test_main_pipeline.py`):
  - `test_optimize_flag_writes_output_files` — `optimized_offsets.csv` and `optimization_report.json` written
  - `test_opt_constraints_invalid_json_raises` — malformed JSON → `ValueError` with descriptive message

---

### 9.3 Task dependency graph

```
F0.T1 ──► F0.T2
           │
           ▼
F1.T1 ──► F1.T2 ──► F1.T3
           │
           ▼
F2.T1 ──► F2.T2 ──► F2.T3
           │
    ┌──────┴──────────┐
    ▼                 ▼
F3.T1              F4.T1
F3.T2                │
    │                ▼
F3.T3 ──► F4.T2 ──► F4.T3 ──► F4.T4
                                │
                                ▼
                   F5.T1 ──► F5.T2 ──► F5.T3
```

---

## 10. Testing Strategy

### 10.1 Test tooling

| Tool | Purpose | Command |
|---|---|---|
| `pytest` | Unit test runner | `pytest tests/unit/` |
| `pytest-cov` | Coverage measurement | `pytest --cov=. --cov-report=xml --cov-report=term-missing` |
| `playwright` | E2E browser tests | `pytest tests/e2e/` (requires `playwright install chromium`) |
| `mypy` | Static type checking | `mypy --strict src/` |
| `ruff` | Lint + format | `ruff check . && ruff format --check .` |

### 10.2 Coverage targets

| Module | Line coverage target |
|---|---|
| `hull_geometry.py` | ≥ 95% |
| `volume_conservation.py` | ≥ 95% |
| `geometric_gz.py` | ≥ 95% |
| `shipd_converter.py` | ≥ 90% |
| `benchmark_validation.py` | ≥ 90% |
| `kg_sensitivity.py` | ≥ 95% |
| `offset_optimizer.py` | ≥ 90% |
| `interactive_ui.py` | ≥ 70% (UI logic only; chart rendering covered by E2E) |

Coverage below target is a CI failure.

### 10.3 Test directory layout

```
tests/
  conftest.py              # shared pytest fixtures
  fixtures/
    sample_offsets.csv
    box_barge_offsets.csv
    stub_benchmark_results/ # pre-computed JSON/CSV for UI E2E stubs
  unit/
    test_hull_geometry.py
    test_volume_conservation.py
    test_geometric_gz.py
    test_gz_curve.py
    test_shipd_converter.py
    test_ship_excel_extractor.py
    test_benchmark_validation.py
    test_kg_sensitivity.py
    test_offset_optimizer.py
    test_main_pipeline.py
  e2e/
    test_ui_tab1.py
    test_ui_tab2.py  (KN→GZ transform)
    test_ui_tab3.py
    test_ui_tab4.py
```

### 10.4 Playwright E2E setup

The E2E tests launch the Streamlit app as a subprocess fixture in `conftest.py`:

```python
@pytest.fixture(scope="session")
def streamlit_server():
    """Start Streamlit app on port 8502 for the test session."""
    proc = subprocess.Popen(
        ["streamlit", "run", "interactive_ui.py", "--server.port", "8502",
         "--server.headless", "true"],
        env={**os.environ, "STUB_DATA": "1"},  # use stub data, not live computation
    )
    time.sleep(5)  # wait for startup
    yield "http://localhost:8502"
    proc.terminate()
```

Each E2E test file uses `page.goto(base_url)` and navigates to the relevant tab before asserting.

`STUB_DATA=1` environment variable causes `interactive_ui.py` to load pre-computed fixtures from `tests/fixtures/stub_benchmark_results/` instead of running full computations — keeping E2E suite runtime < 2 minutes.

### 10.5 Marking slow tests

Tests that require full geometric GZ computation (> 5 s) must be decorated `@pytest.mark.slow`. CI runs `pytest -m "not slow"` on every push; the full suite including slow tests runs on pull requests targeting `main` only.

---

## 11. CI/CD — GitHub Actions

### 11.1 Workflow file: `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: ["**"]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install ruff mypy
      - run: ruff check .
      - run: ruff format --check .
      - run: mypy --strict hull_geometry.py geometric_gz.py volume_conservation.py
               offset_optimizer.py kg_sensitivity.py shipd_converter.py
               benchmark_validation.py

  unit-tests:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: pytest tests/unit/ -m "not slow"
               --cov=. --cov-report=xml --cov-report=term-missing
               --cov-fail-under=90
      - uses: codecov/codecov-action@v4

  e2e-tests:
    runs-on: ubuntu-latest
    needs: unit-tests
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: playwright install chromium
      - run: pytest tests/e2e/ --timeout=120

  slow-tests:
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request' && github.base_ref == 'main'
    needs: unit-tests
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: pytest tests/unit/ -m slow --cov=. --cov-report=xml
      - uses: codecov/codecov-action@v4
```

### 11.2 Branch protection rules (to configure in GitHub repo settings)

- `main` branch requires all three jobs (`lint`, `unit-tests`, `e2e-tests`) to pass before merge
- At least 1 approving review required
- Force-push disabled on `main`

---

## 12. Traceability Matrix

Each row maps a PRD requirement to the task that implements it, the source file(s), approximate line ranges (to be filled in as code is written — placeholders shown as `TBD`), and the test(s) that verify it.

| Req ID | Requirement | Task | Source file | Lines | Unit tests | E2E tests |
|---|---|---|---|---|---|---|
| R1.1 | Hull rotation at arbitrary heel angle | F1.T1 | `hull_geometry.py` | TBD | `test_rotate_hull_at_zero_deg`, `test_rotate_hull_90deg_swaps_axes` | — |
| R1.2 | Bisection waterplane search | F1.T1 | `hull_geometry.py` | TBD | `test_find_heeled_waterplane_converges` | — |
| R1.3 | Volume integration for heeled hull | F1.T1 | `hull_geometry.py` | TBD | `test_integrate_heeled_volume_box_barge` | — |
| R1.4 | Volume deviation < 1% target, ≤ 3% max | F1.T2 | `volume_conservation.py` | TBD | `test_volume_conservation_box_barge_30deg` | — |
| R1.5 | `volume_conservation.csv` output | F1.T2 | `volume_conservation.py` | TBD | `test_volume_conservation_csv_output` | — |
| R1.6 | Phase 2b integration in pipeline | F1.T3 | `main.py` | TBD | `test_phase2b_runs_without_error` | — |
| R2.1 | Geometric GZ via buoyancy centroid shift | F2.T1 | `geometric_gz.py` | TBD | `test_gz_zero_at_zero_heel`, `test_gz_positive_for_stable_hull` | — |
| R2.2 | KN cross-curve from geometry | F2.T1 | `geometric_gz.py` | TBD | `test_kn_equals_gz_plus_kg_sin_theta` | — |
| R2.3 | GZ CSV with geometric + simplified columns | F2.T2 | `gz_curve.py` | TBD | `test_csv_has_geometric_column`, `test_csv_has_simplified_column` | — |
| R2.4 | Phase 6 uses geometric GZ by default | F2.T3 | `main.py` | TBD | `test_phase6_uses_geometric_gz` | — |
| R3.1 | Select 10 diverse ShipD hulls | F3.T1 | `shipd_converter.py` | TBD | `test_select_diverse_hulls_returns_n` | — |
| R3.2 | ShipD hull → offset table conversion | F3.T1 | `shipd_converter.py` | TBD | `test_hull_to_offset_table_shape`, `test_hull_to_offset_table_no_negatives` | — |
| R3.3 | CSV offset loading for benchmark pipeline | F3.T2 | `ship_excel_extractor.py` | TBD | `test_load_offsets_from_csv_schema` | — |
| R3.4 | GM error ≤ 2% vs fine-grid reference | F3.T3 | `benchmark_validation.py` | TBD | `test_gm_error_formula` | — |
| R3.5 | GZ deviation ≤ 5% vs fine-grid reference | F3.T3 | `benchmark_validation.py` | TBD | `test_error_metrics_schema` | — |
| R3.6 | Benchmark results shown in UI Tab 3 | F4.T3 | `interactive_ui.py` | TBD | — | `test_tab3_summary_table_renders` |
| R3.7 | Hull detail drill-down with GZ overlay | F4.T3 | `interactive_ui.py` | TBD | — | `test_tab3_hull_dropdown_changes_chart` |
| R4.1 | KG sensitivity across 5 scenarios | F4.T1 | `kg_sensitivity.py` | TBD | `test_higher_kg_lower_gm`, `test_area_decreases_with_kg` | — |
| R4.2 | GZ + KN charts with KG/draft sliders | F4.T2 | `interactive_ui.py` | TBD | — | `test_gz_chart_renders`, `test_kg_slider_updates_gm` |
| R4.3 | Volume conservation chart in Tab 1 | F4.T2 | `interactive_ui.py` | TBD | — | `test_volume_conservation_chart_renders` |
| R4.4 | KN → GZ transform chart in Tab 2 | F4.T2 | `interactive_ui.py` | TBD | — | `test_tab2_kn_chart_renders` |
| R5.1 | Offset optimization with SLSQP | F5.T1 | `offset_optimizer.py` | TBD | `test_optimization_converges_default_constraints` | — |
| R5.2 | Offset variation ≤ p_max constraint | F5.T1 | `offset_optimizer.py` | TBD | `test_optimized_offsets_within_bounds` | — |
| R5.3 | Volume conservation ≤ 1% constraint | F5.T1 | `offset_optimizer.py` | TBD | `test_optimized_volume_deviation` | — |
| R5.4 | Min GZ at 5 heel angles constraint | F5.T1 | `offset_optimizer.py` | TBD | `test_gz_constraint_satisfied` | — |
| R5.5 | Min area under GZ constraint | F5.T1 | `offset_optimizer.py` | TBD | `test_area_constraint_satisfied` | — |
| R5.6 | Infeasibility detection | F5.T2 | `offset_optimizer.py` | TBD | `test_infeasibility_detected_on_tight_constraints` | — |
| R5.7 | Per-constraint relaxation suggestions | F5.T2 | `offset_optimizer.py` | TBD | `test_per_constraint_relaxation_positive` | — |
| R5.8 | Simultaneous scale factor suggestion | F5.T2 | `offset_optimizer.py` | TBD | `test_simultaneous_scale_factor_in_0_1` | — |
| R5.9 | Re-run with suggestions → converges | F5.T2 | `offset_optimizer.py` | TBD | `test_rerun_with_suggested_relaxations_converges` | — |
| R5.10 | Optimizer UI — constraint input form | F4.T4 | `interactive_ui.py` | TBD | — | `test_tab4_form_renders` |
| R5.11 | "Apply suggested relaxations" button | F4.T4 | `interactive_ui.py` | TBD | — | `test_tab4_apply_relaxations_button_prefills_form` |
| R5.12 | Optimizer CLI `--opt-constraints` flag | F5.T3 | `main.py` | TBD | `test_optimize_flag_writes_output_files` | — |

> **Line numbers** in the `Lines` column are filled in after each task is merged, by running `grep -n "def <function_name>" <file>` and recording the result. The matrix is updated in the same PR as the code change.

---

## 13. What else makes this a solid product

Beyond the above, the following practices are recommended:

1. **Pre-commit hooks** — install `pre-commit` with hooks for `ruff`, `ruff format`, and `mypy`. Catches issues before they ever reach CI, reducing wasted CI minutes. Config in `.pre-commit-config.yaml`.

2. **Regression benchmark** — after Feature 3 (benchmark validation) passes, pin the 10-hull error metric results as a JSON golden file. Any future change that increases GM error beyond the golden values fails CI. This guards against algorithmic regressions during refactoring.

3. **Numerical snapshot tests** — for `hull_geometry.py` and `geometric_gz.py`, store the expected GZ array for the existing `offsetdata.csv` hull as a numpy `.npy` golden file. Use `np.testing.assert_allclose(result, golden, rtol=1e-4)`. Added via `pytest --snapshot-update` when intentionally changing numerics.

4. **Performance regression tests** — use `pytest-benchmark` to measure wall time of `run_volume_conservation` and `compute_geometric_gz_curve`. If a commit makes either > 2× slower, CI fails. Add `@pytest.mark.benchmark` decorator.

5. **Changelog (`CHANGELOG.md`)** — maintained in Keep A Changelog format. Each merged PR adds an entry. Required by branch protection rule (PR description must include changelog entry).

6. **Semantic versioning** — tag releases `v2.0.0` (Round 2 complete), `v2.1.0` (patch releases). CI publishes a GitHub Release with attached `results/` artifacts on push to `main`.

7. **`README.md` update** — Round 2 section with quick-start for the Streamlit UI (`streamlit run interactive_ui.py`), how to run the benchmark (`python benchmark_validation.py`), and how to run the optimizer with custom constraints.

8. **Doctest smoke tests** — each utility function in `hull_geometry.py` should include a `>>> ` doctest demonstrating basic usage. `pytest --doctest-modules hull_geometry.py` runs these as part of the unit suite.

9. **Input schema validation** — the offset CSV format must be validated on load (correct column count, all-numeric values, no negative breadths). Add `validate_offset_csv(path)` in `ship_excel_extractor.py`, called before any computation. This prevents cryptic numerical failures from propagating into the pipeline.

10. **Graceful degradation in the UI** — if `benchmarks/` or `volume_conservation.csv` are absent, every tab that depends on them shows a styled placeholder rather than crashing. This allows demoing the UI before the full pipeline has been run on a new machine.

---

## 14. Build Order & Dependencies

```
F0.T1 → F0.T2 (scaffolding first, always)
F1.T1 → F1.T2 → F1.T3
F2.T1 → F2.T2 → F2.T3          (depends on F1.T1)
F3.T1 → F3.T2 → F3.T3          (depends on F2.T1)
F4.T1                            (depends on F2.T1)
F4.T2 → F4.T3 → F4.T4          (depends on F4.T1, F3.T3, F5.T2)
F5.T1 → F5.T2 → F5.T3          (depends on F2.T1)
```

Recommended branch-per-task workflow: create branch `feat/F1-T1-hull-geometry`, merge via PR, then branch `feat/F1-T2-volume-conservation` from the updated `main`.

---

## 15. Validation Checklist

| # | Check | Expected result |
|---|---|---|
| V1 | Volume conservation at θ = 0° | Deviation = 0% (identity check) |
| V2 | Volume conservation at θ = 30° | < 1% |
| V3 | Volume conservation at θ = 60° | < 3% |
| V4 | Geometric GZ at θ = 0° | GZ = 0.0 m |
| V5 | Geometric GZ agrees with simplified at θ = 5° | < 1% difference |
| V6 | 10 ShipD hulls converge (no NaN/error) | All 10 pass |
| V7 | GM error vs fine-grid reference (ShipD) | ≤ 2% for all 10 |
| V8 | GZ deviation vs fine-grid (ShipD) | ≤ 5% for all 10 |
| V9 | KG sensitivity: 5 scenarios produce distinct GZ curves | Monotone shift with KG |
| V9b | Volume Conservation chart renders in Tab 1 with dual y-axes | V(θ) line + deviation % line visible |
| V9c | Volume Conservation chart threshold lines shown (±1%, ±3%) | Both horizontal lines present |
| V9d | Badge below chart reflects correct pass/warn/fail status | Matches max deviation in CSV |
| V10 | Benchmark Tab shows all 10 hull rows with pass/fail badges | No missing data rows |
| V11 | Benchmark Tab hull-detail GZ chart renders coarse vs fine overlay | ±5% shaded band visible |
| V12 | Optimizer converges on existing hull data with default constraints | `status = converged` |
| V13 | Optimized offsets within ±p_max of original (default 5%) | All cells pass |
| V14 | Optimized volume deviation | ≤ 1% |
| V15 | GZ at all 5 constrained heel angles ≥ gz_min_k after optimization | All 5 pass |
| V16 | Area under optimized GZ curve ≥ area_min | Passes |
| V17 | Infeasible scenario (tight constraints): InfeasibilityReport generated | `status = infeasible`, report non-null |
| V18 | Infeasibility relaxation suggestions are actionable (re-run with suggestions → converges) | `status = converged` on re-run |
| V19 | "Apply suggested relaxations" button pre-fills form fields correctly | Fields match per_constraint_relaxation values |
| V20 | `pytest --cov` overall line coverage ≥ 90% | CI green |
| V21 | All E2E tests pass in CI with stub data | playwright exit 0 |
| V22 | `ruff check .` and `mypy --strict` pass | zero errors |
| V23 | Performance: full GZ curve (61 angles) < 30 s | benchmark test passes |
| V24 | Regression benchmark: ShipD GM errors ≤ golden file values | no regression |
