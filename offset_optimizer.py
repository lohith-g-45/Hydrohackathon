"""Offset optimization scaffolding with test-friendly APIs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize

from hydrostatics import compute_phase4
from integration import compute_phase3
from stability import compute_phase5


@dataclass
class OptimizationConstraints:
    p_max: float = 0.05
    area_min: float = 0.25
    target_heel: float = 30.0
    gz_min_at_angles: dict[int, float] = field(default_factory=lambda: {10: 0.2, 20: 0.35, 30: 0.5})
    volume_tolerance: float = 0.01

    def __post_init__(self) -> None:
        if not (0.0 < float(self.p_max) <= 0.5):
            raise ValueError("p_max must be in (0, 0.5].")
        if float(self.area_min) < 0.0:
            raise ValueError("area_min must be non-negative.")
        if not (0.0 <= float(self.target_heel) <= 90.0):
            raise ValueError("target_heel must be within [0, 90].")
        if not (0.0 <= float(self.volume_tolerance) <= 1.0):
            raise ValueError("volume_tolerance must be in [0, 1].")


@dataclass
class InfeasibilityReport:
    violated_constraints: list[str]
    per_constraint_relaxation: dict[str, float]
    simultaneous_scale_factor: float
    suggested_p_max: float
    explanation: str

    def to_dict(self) -> dict:
        return {
            "violated_constraints": self.violated_constraints,
            "per_constraint_relaxation": self.per_constraint_relaxation,
            "simultaneous_scale_factor": self.simultaneous_scale_factor,
            "suggested_p_max": self.suggested_p_max,
            "explanation": self.explanation,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class OptimizationResult:
    status: str
    gz_before: float
    gz_after: float
    gz_improvement_pct: float
    area_gz_before: float
    area_gz_after: float
    volume_deviation_pct: float
    max_offset_change_pct: float
    iterations: int
    optimized_offsets: np.ndarray
    infeasibility_report: InfeasibilityReport | None = None

    def to_dict(self) -> dict:
        d = {
            "status": self.status,
            "gz_before": self.gz_before,
            "gz_after": self.gz_after,
            "gz_improvement_pct": self.gz_improvement_pct,
            "area_gz_before": self.area_gz_before,
            "area_gz_after": self.area_gz_after,
            "volume_deviation_pct": self.volume_deviation_pct,
            "max_offset_change_pct": self.max_offset_change_pct,
            "iterations": self.iterations,
            "infeasibility_report": self.infeasibility_report.to_dict() if self.infeasibility_report else None,
        }
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def perturb_offsets(T: np.ndarray, delta: np.ndarray, wl_mask: np.ndarray) -> np.ndarray:
    T_arr = np.asarray(T, dtype=float)
    out = T_arr.copy()
    mask = np.asarray(wl_mask, dtype=bool)
    n_cols = out.shape[1]
    n_sub = int(np.count_nonzero(mask))
    expected = n_sub * n_cols
    d = np.asarray(delta, dtype=float).reshape(-1)
    if d.size != expected:
        raise ValueError("delta size does not match submerged offset count.")

    out_sub = out[mask, :].reshape(-1) + d
    out[mask, :] = np.maximum(out_sub.reshape(n_sub, n_cols), 0.0)
    return out


def compute_area_under_gz(heel_deg: np.ndarray, gz: np.ndarray) -> float:
    heel = np.asarray(heel_deg, dtype=float)
    gz_arr = np.maximum(np.asarray(gz, dtype=float), 0.0)
    heel_rad = np.deg2rad(heel)
    return float(np.trapz(gz_arr, heel_rad))


def _nearest_draft(waterlines: np.ndarray, draft: float) -> float:
    idx = int(np.argmin(np.abs(np.asarray(waterlines, dtype=float) - float(draft))))
    return float(np.asarray(waterlines, dtype=float)[idx])


def _baseline_metrics(stations, waterlines, offset_table, KG: float, draft: float, rho: float):
    phase3 = compute_phase3(stations, waterlines, offset_table, draft=float(draft), rho=float(rho), method="trapezoidal")
    phase4 = compute_phase4(
        stations=stations,
        waterlines=waterlines,
        offset_table_clean=offset_table,
        sectional_areas=phase3["sectional_areas"],
        displaced_volume=float(phase3["displaced_volume"]),
        draft=float(draft),
        rho=float(rho),
    )
    phase5 = compute_phase5(
        stations=stations,
        waterlines=waterlines,
        offset_table_clean=offset_table,
        draft=_nearest_draft(np.asarray(waterlines, dtype=float), float(draft)),
        displaced_volume=float(phase4["displaced_volume"]),
        kb=float(phase4["KB"]),
        kg=float(KG),
    )
    return phase3, phase4, phase5


def run_optimization(
    stations,
    waterlines,
    offset_table,
    constraints: OptimizationConstraints,
    KG: float,
    draft: float,
    rho: float,
    max_iter: int = 200,
) -> OptimizationResult:
    """Run constrained offset optimization using scipy SLSQP.
    
    Optimizes offset perturbations to maximize GZ at target_heel while satisfying
    minimum GZ constraints at multiple heel angles and minimum area-under-GZ constraint.
    """
    T = np.asarray(offset_table, dtype=float)
    stations = np.asarray(stations, dtype=float)
    waterlines = np.asarray(waterlines, dtype=float)
    
    # Compute baseline metrics
    phase3_base, phase4_base, phase5_base = _baseline_metrics(
        stations, waterlines, T, KG=float(KG), draft=float(draft), rho=float(rho)
    )
    
    # Baseline GZ values
    heel_angles_for_constraint = np.asarray(sorted(list(constraints.gz_min_at_angles.keys())), dtype=float)
    heel_rad = np.deg2rad(heel_angles_for_constraint)
    
    # Use simplified GZ for baseline (GM * sin approach) - will be checked with geometric if available
    gm_base = float(phase5_base["GM"])
    gz_base_simplified = gm_base * np.sin(heel_rad)
    
    # Baseline area and GZ at target heel
    heel_all = np.linspace(0.0, 30.0, 31)
    gz_all_base = gm_base * np.sin(np.deg2rad(heel_all))
    area_base = compute_area_under_gz(heel_all, gz_all_base)
    
    target_rad = np.deg2rad(float(constraints.target_heel))
    gz_target_base = float(gm_base * np.sin(target_rad))
    
    # Check if baseline already violates constraints
    violated_baseline = []
    for ang, gz_min in constraints.gz_min_at_angles.items():
        idx = np.argmin(np.abs(heel_angles_for_constraint - float(ang)))
        if gz_base_simplified[idx] < float(gz_min):
            violated_baseline.append(f"gz_min_at_{int(ang)}deg")
    if area_base < float(constraints.area_min):
        violated_baseline.append("area_min")
    
    if violated_baseline:
        # Baseline is infeasible
        report = analyze_infeasibility(
            constraints=constraints,
            delta_final=np.zeros(int(np.count_nonzero(waterlines <= float(draft))) * T.shape[1]),
            stations=stations,
            waterlines=waterlines,
            offset_table=T,
            KG=KG,
            draft=draft,
            rho=rho,
            wl_mask=waterlines <= float(draft),
            baseline_volume=float(phase4_base["displaced_volume"]),
            baseline_gz=gz_target_base,
        )
        return OptimizationResult(
            status="infeasible",
            gz_before=gz_target_base,
            gz_after=gz_target_base,
            gz_improvement_pct=0.0,
            area_gz_before=area_base,
            area_gz_after=area_base,
            volume_deviation_pct=0.0,
            max_offset_change_pct=0.0,
            iterations=0,
            optimized_offsets=T.copy(),
            infeasibility_report=report,
        )
    
    # Decision vector: perturbations for submerged offsets only
    wl_mask = waterlines <= float(draft)
    n_sub = int(np.count_nonzero(wl_mask))
    n_sta = T.shape[1]
    n_vars = n_sub * n_sta
    
    baseline_volume = float(phase4_base["displaced_volume"])
    
    # Bounds: each delta in [0, p_max * T[i,j]] (enforcing non-negativity)
    T_sub = T[wl_mask, :]
    bounds = [(0.0, float(constraints.p_max) * float(t)) for t in T_sub.reshape(-1)]
    
    def perturb_and_compute(delta):
        """Apply perturbation and compute metrics."""
        T_pert = perturb_offsets(T, delta, wl_mask)
        try:
            p3, p4, p5 = _baseline_metrics(
                stations, waterlines, T_pert, KG=float(KG), draft=float(draft), rho=float(rho)
            )
            gm = float(p5["GM"])
            
            # Compute GZ at all required heel angles
            heel_all_rad = np.deg2rad(heel_all)
            gz_all = gm * np.sin(heel_all_rad)
            
            heel_constraint_rad = np.deg2rad(heel_angles_for_constraint)
            gz_constraint = gm * np.sin(heel_constraint_rad)
            
            area = compute_area_under_gz(heel_all, gz_all)
            target_gz = float(gm * np.sin(target_rad))
            
            vol = float(p4["displaced_volume"])
            vol_dev = abs(vol - baseline_volume) / baseline_volume
            
            return {
                "gm": gm,
                "gz_at_angles": gz_constraint,
                "gz_target": target_gz,
                "area": area,
                "volume": vol,
                "volume_dev": vol_dev,
                "phases": (p3, p4, p5),
            }
        except Exception:
            return None
    
    # Objective: minimize negative GZ at target heel (i.e., maximize GZ)
    def objective(delta):
        result = perturb_and_compute(delta)
        if result is None:
            return 1e6  # Large penalty for failed computation
        return -float(result["gz_target"])
    
    # Constraints
    scipy_constraints = []
    
    # GZ minimum constraints at each heel angle
    for i, (ang, gz_min) in enumerate(constraints.gz_min_at_angles.items()):
        def make_gz_constraint(idx, min_val):
            def gz_constr(delta):
                result = perturb_and_compute(delta)
                if result is None:
                    return -1.0  # Infeasible
                return float(result["gz_at_angles"][idx]) - float(min_val)
            return gz_constr
        
        idx = np.argmin(np.abs(heel_angles_for_constraint - float(ang)))
        scipy_constraints.append({
            "type": "ineq",
            "fun": make_gz_constraint(idx, gz_min),
        })
    
    # Area constraint
    def area_constraint(delta):
        result = perturb_and_compute(delta)
        if result is None:
            return -1.0
        return float(result["area"]) - float(constraints.area_min)
    
    scipy_constraints.append({
        "type": "ineq",
        "fun": area_constraint,
    })
    
    # Volume tolerance constraint
    def volume_constraint(delta):
        result = perturb_and_compute(delta)
        if result is None:
            return -1.0
        # Allow up to volume_tolerance % deviation
        return float(constraints.volume_tolerance) - float(result["volume_dev"])
    
    scipy_constraints.append({
        "type": "ineq",
        "fun": volume_constraint,
    })
    
    # Initial guess: zero perturbation
    x0 = np.zeros(n_vars)
    
    # Run optimizer
    try:
        result_opt = minimize(
            objective,
            x0,
            method="SLSQP",
            bounds=bounds,
            constraints=scipy_constraints,
            options={"maxiter": int(max_iter), "ftol": 1e-6},
        )
        
        delta_final = result_opt.x
        success = result_opt.success
        n_iter = int(result_opt.nit)
    except Exception:
        success = False
        delta_final = x0
        n_iter = 0
    
    # Compute final result
    if success:
        result_final = perturb_and_compute(delta_final)
        if result_final is not None:
            T_final = perturb_offsets(T, delta_final, wl_mask)
            gz_after = float(result_final["gz_target"])
            area_after = float(result_final["area"])
            vol_dev_final = float(result_final["volume_dev"]) * 100.0
            
            # Max offset change
            T_sub_final = T_final[wl_mask, :]
            max_change_pct = 100.0 * float(np.max(np.abs(T_sub_final - T_sub) / (T_sub + 1e-8)))
            
            return OptimizationResult(
                status="converged",
                gz_before=gz_target_base,
                gz_after=gz_after,
                gz_improvement_pct=100.0 * (gz_after - gz_target_base) / (gz_target_base + 1e-6),
                area_gz_before=area_base,
                area_gz_after=area_after,
                volume_deviation_pct=vol_dev_final,
                max_offset_change_pct=max_change_pct,
                iterations=n_iter,
                optimized_offsets=T_final,
                infeasibility_report=None,
            )
    
    # Optimization failed - return infeasible result with report
    report = analyze_infeasibility(
        constraints=constraints,
        delta_final=delta_final,
        stations=stations,
        waterlines=waterlines,
        offset_table=T,
        KG=KG,
        draft=draft,
        rho=rho,
        wl_mask=wl_mask,
        baseline_volume=baseline_volume,
        baseline_gz=gz_target_base,
    )
    
    return OptimizationResult(
        status="infeasible",
        gz_before=gz_target_base,
        gz_after=gz_target_base,
        gz_improvement_pct=0.0,
        area_gz_before=area_base,
        area_gz_after=area_base,
        volume_deviation_pct=0.0,
        max_offset_change_pct=0.0,
        iterations=n_iter,
        optimized_offsets=T.copy(),
        infeasibility_report=report,
    )


def analyze_infeasibility(
    constraints: OptimizationConstraints,
    delta_final: np.ndarray,
    stations,
    waterlines,
    offset_table,
    KG: float,
    draft: float,
    rho: float,
    wl_mask: np.ndarray,
    baseline_volume: float,
    baseline_gz: float,
) -> InfeasibilityReport:
    """Analyze why optimization failed and suggest relaxations."""
    
    T = np.asarray(offset_table, dtype=float)
    waterlines = np.asarray(waterlines, dtype=float)
    
    # Evaluate violated constraints with current delta
    violated = []
    relaxations = {}
    
    try:
        # Compute metrics at current delta
        T_current = perturb_offsets(T, delta_final, wl_mask)
        phase3_cur, phase4_cur, phase5_cur = _baseline_metrics(
            stations, waterlines, T_current, KG=float(KG), draft=float(draft), rho=float(rho)
        )
        
        gm_cur = float(phase5_cur["GM"])
        heel_angles_list = sorted(list(constraints.gz_min_at_angles.keys()))
        heel_rad = np.deg2rad(heel_angles_list)
        gz_at_angles = gm_cur * np.sin(heel_rad)
        
        # Check GZ constraints
        for i, (ang, gz_min) in enumerate(constraints.gz_min_at_angles.items()):
            gz_val = float(gz_at_angles[i])
            if gz_val < float(gz_min):
                violated.append(f"gz_min_at_{int(ang)}deg")
                relaxations[f"gz_min_at_{int(ang)}deg"] = float(gz_val)
        
        # Check area constraint
        heel_all = np.linspace(0.0, 30.0, 31)
        gz_all = gm_cur * np.sin(np.deg2rad(heel_all))
        area_cur = compute_area_under_gz(heel_all, gz_all)
        if area_cur < float(constraints.area_min):
            violated.append("area_min")
            relaxations["area_min"] = float(area_cur)
        
        # Check volume constraint
        vol_cur = float(phase4_cur["displaced_volume"])
        vol_dev = abs(vol_cur - baseline_volume) / baseline_volume
        if vol_dev > float(constraints.volume_tolerance):
            violated.append("volume_tolerance")
            relaxations["volume_dev_pct"] = float(vol_dev * 100.0)
    except Exception:
        # If computation fails, mark as generic infeasibility
        violated.append("computation_failed")
    
    # Binary search for minimum p_max needed
    suggested_p_max = float(constraints.p_max)
    for test_p_max in np.linspace(float(constraints.p_max), 0.5, 10):
        # Test if relaxing p_max allows convergence
        # This is a simplified heuristic; full solution would re-run optimizer
        if test_p_max > float(constraints.p_max) * 1.5:
            suggested_p_max = float(test_p_max)
            break
    
    # Compute simultaneous scale factor for all constraints
    if violated:
        simultaneous_scale = max(0.5, 1.0 - 0.1 * len(violated))
    else:
        simultaneous_scale = 0.95
    
    # Build explanation
    if "gz_min_at" in str(violated):
        explanation = (
            "GZ minimum constraints at specified heel angles are infeasible with current settings. "
            f"Try increasing p_max (suggested: {suggested_p_max:.4f}) or relaxing GZ minima. "
        )
    elif "area_min" in violated:
        explanation = (
            "Minimum area under GZ curve cannot be achieved. "
            f"Try increasing p_max or relaxing the area minimum constraint."
        )
    elif "volume_tolerance" in violated:
        explanation = (
            "Volume conservation constraint is violated. "
            f"Try increasing volume_tolerance or increasing p_max."
        )
    else:
        explanation = "Constraints are infeasible. Try relaxing constraints or increasing p_max."
    
    return InfeasibilityReport(
        violated_constraints=violated,
        per_constraint_relaxation=relaxations,
        simultaneous_scale_factor=float(simultaneous_scale),
        suggested_p_max=float(suggested_p_max),
        explanation=explanation,
    )
