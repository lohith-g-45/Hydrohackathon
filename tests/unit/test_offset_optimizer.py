"""Unit tests for offset_optimizer module."""
import json
import numpy as np
import pytest

from offset_optimizer import (
    OptimizationConstraints,
    OptimizationResult,
    InfeasibilityReport,
    perturb_offsets,
    compute_area_under_gz,
    run_optimization,
    analyze_infeasibility,
)


class TestOptimizationConstraints:
    """Tests for OptimizationConstraints dataclass."""

    def test_default_constraints(self):
        """Test default constraints initialization."""
        c = OptimizationConstraints()
        assert c.p_max == 0.05
        assert c.area_min == 0.25
        assert c.target_heel == 30
        assert 10 in c.gz_min_at_angles
        assert c.gz_min_at_angles[30] == 0.5

    def test_custom_constraints(self):
        """Test custom constraints."""
        c = OptimizationConstraints(
            p_max=0.1,
            area_min=0.3,
            target_heel=40,
            gz_min_at_angles={20: 0.3, 40: 0.6},
        )
        assert c.p_max == 0.1
        assert c.target_heel == 40

    def test_invalid_p_max_too_small(self):
        """Test p_max validation - too small."""
        with pytest.raises(ValueError, match="p_max"):
            OptimizationConstraints(p_max=0)

    def test_invalid_p_max_too_large(self):
        """Test p_max validation - too large."""
        with pytest.raises(ValueError, match="p_max"):
            OptimizationConstraints(p_max=0.6)

    def test_invalid_area_min_negative(self):
        """Test area_min validation - negative."""
        with pytest.raises(ValueError, match="area_min"):
            OptimizationConstraints(area_min=-0.1)

    def test_invalid_target_heel(self):
        """Test target_heel validation - out of range."""
        with pytest.raises(ValueError, match="target_heel"):
            OptimizationConstraints(target_heel=100)

    def test_invalid_volume_tolerance(self):
        """Test volume_tolerance validation."""
        with pytest.raises(ValueError, match="volume_tolerance"):
            OptimizationConstraints(volume_tolerance=1.5)


class TestInfeasibilityReport:
    """Tests for InfeasibilityReport dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        report = InfeasibilityReport(
            violated_constraints=["volume", "gz_min_at_30deg"],
            per_constraint_relaxation={"volume_tolerance_suggested": 0.02},
            simultaneous_scale_factor=0.8,
            suggested_p_max=0.08,
            explanation="Test explanation",
        )
        d = report.to_dict()
        assert "violated_constraints" in d
        assert d["violated_constraints"] == ["volume", "gz_min_at_30deg"]
        assert "simultaneous_scale_factor" in d
        assert d["simultaneous_scale_factor"] == 0.8

    def test_to_json(self):
        """Test conversion to JSON string."""
        report = InfeasibilityReport(
            violated_constraints=["volume"],
            per_constraint_relaxation={},
            simultaneous_scale_factor=0.7,
            suggested_p_max=0.1,
            explanation="Test",
        )
        json_str = report.to_json()
        data = json.loads(json_str)
        assert data["simultaneous_scale_factor"] == 0.7
        assert data["suggested_p_max"] == 0.1


class TestOptimizationResult:
    """Tests for OptimizationResult dataclass."""

    def test_converged_result(self):
        """Test converged result."""
        result = OptimizationResult(
            status="converged",
            gz_before=0.5,
            gz_after=0.7,
            gz_improvement_pct=40.0,
            area_gz_before=0.2,
            area_gz_after=0.25,
            volume_deviation_pct=0.5,
            max_offset_change_pct=50.0,
            iterations=150,
            optimized_offsets=np.ones((7, 11)) * 1.1,
        )
        assert result.status == "converged"
        assert result.gz_improvement_pct == 40.0

    def test_infeasible_result(self):
        """Test infeasible result with report."""
        report = InfeasibilityReport(
            violated_constraints=["volume"],
            per_constraint_relaxation={},
            simultaneous_scale_factor=0.7,
            suggested_p_max=0.1,
            explanation="Failed",
        )
        result = OptimizationResult(
            status="infeasible",
            gz_before=0.5,
            gz_after=0.55,
            gz_improvement_pct=10.0,
            area_gz_before=0.2,
            area_gz_after=0.21,
            volume_deviation_pct=2.5,
            max_offset_change_pct=95.0,
            iterations=300,
            optimized_offsets=np.ones((7, 11)) * 1.05,
            infeasibility_report=report,
        )
        assert result.status == "infeasible"
        assert result.infeasibility_report is not None

    def test_result_to_dict(self):
        """Test result conversion to dict."""
        result = OptimizationResult(
            status="converged",
            gz_before=0.5,
            gz_after=0.7,
            gz_improvement_pct=40.0,
            area_gz_before=0.2,
            area_gz_after=0.25,
            volume_deviation_pct=0.5,
            max_offset_change_pct=50.0,
            iterations=150,
            optimized_offsets=np.ones((7, 11)),
        )
        d = result.to_dict()
        assert d["status"] == "converged"
        assert d["gz_improvement_pct"] == 40.0
        assert "optimized_offsets" not in d  # Arrays excluded

    def test_result_to_json(self):
        """Test result conversion to JSON."""
        result = OptimizationResult(
            status="converged",
            gz_before=0.5,
            gz_after=0.7,
            gz_improvement_pct=40.0,
            area_gz_before=0.2,
            area_gz_after=0.25,
            volume_deviation_pct=0.5,
            max_offset_change_pct=50.0,
            iterations=150,
            optimized_offsets=np.ones((7, 11)),
        )
        json_str = result.to_json()
        data = json.loads(json_str)
        assert data["status"] == "converged"
        assert isinstance(data["gz_improvement_pct"], (int, float))


class TestPerturbOffsets:
    """Tests for perturb_offsets function."""

    def test_perturb_offsets_basic(self):
        """Test basic offset perturbation."""
        T = np.ones((5, 10)) * 1.0
        delta = np.ones(50) * 0.1
        wl_mask = np.ones(5, dtype=bool)

        T_prime = perturb_offsets(T, delta, wl_mask)
        assert T_prime.shape == T.shape
        assert np.all(T_prime >= 0)
        assert np.allclose(T_prime, 1.1, rtol=1e-10)

    def test_perturb_offsets_partial_mask(self):
        """Test perturbation with partial waterline mask."""
        T = np.ones((5, 10)) * 1.0
        delta = np.ones(30) * 0.1  # Only 3 submerged WLs
        wl_mask = np.array([True, True, True, False, False])

        T_prime = perturb_offsets(T, delta, wl_mask)
        assert T_prime.shape == T.shape
        assert np.allclose(T_prime[:3], 1.1)
        assert np.allclose(T_prime[3:], 1.0)

    def test_perturb_offsets_negative_clamped(self):
        """Test that negative offsets are clamped to zero."""
        T = np.ones((3, 5)) * 0.5
        delta = np.ones(15) * -0.6  # Large negative perturbation
        wl_mask = np.ones(3, dtype=bool)

        T_prime = perturb_offsets(T, delta, wl_mask)
        assert np.all(T_prime >= 0)
        assert np.allclose(T_prime, 0)  # Clamped to 0


class TestComputeAreaUnderGZ:
    """Tests for compute_area_under_gz function."""

    def test_area_zero_gz(self):
        """Test area when GZ is zero."""
        heel_deg = np.array([0, 10, 20, 30, 40, 50, 60])
        gz = np.array([0, 0, 0, 0, 0, 0, 0])
        area = compute_area_under_gz(heel_deg, gz)
        assert area == 0.0

    def test_area_constant_gz(self):
        """Test area with constant GZ."""
        heel_deg = np.linspace(0, 30, 31)
        gz = np.ones_like(heel_deg) * 0.5  # Constant 0.5 m
        area = compute_area_under_gz(heel_deg, gz)
        # Area ≈ 0.5 * (30° in radians) = 0.5 * π/6 ≈ 0.262
        assert area > 0.2 and area < 0.3

    def test_area_with_negative_gz(self):
        """Test that negative GZ values are clipped to zero."""
        heel_deg = np.linspace(0, 30, 31)
        gz = -np.ones_like(heel_deg) * 0.5  # All negative
        area = compute_area_under_gz(heel_deg, gz)
        assert area == 0.0

    def test_area_triangular_gz(self):
        """Test area with triangular GZ curve."""
        heel_deg = np.array([0, 15, 30, 45, 60])
        gz = np.array([0, 0.5, 0.25, 0, 0])  # Peak at 15°
        area = compute_area_under_gz(heel_deg, gz)
        assert area > 0
        # Rough estimate: average ~0.25 m over ~0.52 rad ≈ 0.13 m·rad
        assert 0.05 < area < 0.5


class TestRunOptimization:
    """Tests for run_optimization function (integration tests)."""

    @pytest.fixture
    def box_barge_data(self):
        """Box barge test fixture."""
        stations = np.linspace(0, 10, 11)
        waterlines = np.linspace(0, 3, 7)
        offset_table = np.full((7, 11), 1.0)
        return {
            "stations": stations,
            "waterlines": waterlines,
            "offset_table": offset_table,
            "draft": 1.5,
            "rho": 1025.0,
            "KG": 1.0,
        }

    @pytest.mark.skip(reason="Optimization is computationally intensive")
    def test_optimization_returns_valid_result(self, box_barge_data):
        """Test that optimization returns a valid OptimizationResult."""
        constraints = OptimizationConstraints(
            p_max=0.05,
            target_heel=30,
            area_min=0.1,
        )
        result = run_optimization(
            stations=box_barge_data["stations"],
            waterlines=box_barge_data["waterlines"],
            offset_table=box_barge_data["offset_table"],
            constraints=constraints,
            KG=box_barge_data["KG"],
            draft=box_barge_data["draft"],
            rho=box_barge_data["rho"],
            max_iter=100,
        )
        assert isinstance(result, OptimizationResult)
        assert result.status in ["converged", "infeasible"]
        assert np.isfinite(result.gz_before)
        assert np.isfinite(result.gz_after)

    @pytest.mark.skip(reason="Optimization is computationally intensive")
    def test_optimized_offsets_within_bounds(self, box_barge_data):
        """Test that optimized offsets are within perturbation bounds."""
        constraints = OptimizationConstraints(p_max=0.1)
        result = run_optimization(
            stations=box_barge_data["stations"],
            waterlines=box_barge_data["waterlines"],
            offset_table=box_barge_data["offset_table"],
            constraints=constraints,
            KG=box_barge_data["KG"],
            draft=box_barge_data["draft"],
            rho=box_barge_data["rho"],
            max_iter=50,
        )
        # Check that optimized offsets are non-negative
        assert np.all(result.optimized_offsets >= 0)
        # Relative perturbation should be <= p_max
        T_original = box_barge_data["offset_table"]
        T_opt = result.optimized_offsets
        # Only check submerged part
        draft = box_barge_data["draft"]
        mask = box_barge_data["waterlines"] <= draft
        if np.any(mask):
            relative_change = np.abs(T_opt[mask] - T_original[mask]) / (T_original[mask] + 1e-6)
            assert np.all(relative_change <= constraints.p_max + 1e-3)

    @pytest.mark.skip(reason="Optimization is computationally intensive")
    def test_volume_conservation_constraint(self, box_barge_data):
        """Test that volume is conserved within tolerance."""
        constraints = OptimizationConstraints(volume_tolerance=0.01)
        result = run_optimization(
            stations=box_barge_data["stations"],
            waterlines=box_barge_data["waterlines"],
            offset_table=box_barge_data["offset_table"],
            constraints=constraints,
            KG=box_barge_data["KG"],
            draft=box_barge_data["draft"],
            rho=box_barge_data["rho"],
            max_iter=100,
        )
        # If converged, volume should be conserved
        if result.status == "converged":
            assert result.volume_deviation_pct <= constraints.volume_tolerance * 100 + 0.1

    @pytest.mark.skip(reason="Optimization is computationally intensive")
    def test_optimization_with_realistic_constraints(self, box_barge_data):
        """Test optimization with realistic constraints."""
        constraints = OptimizationConstraints(
            p_max=0.05,
            gz_min_at_angles={20: 0.3, 30: 0.4, 40: 0.35},
            area_min=0.2,
            target_heel=30,
        )
        result = run_optimization(
            stations=box_barge_data["stations"],
            waterlines=box_barge_data["waterlines"],
            offset_table=box_barge_data["offset_table"],
            constraints=constraints,
            KG=box_barge_data["KG"],
            draft=box_barge_data["draft"],
            rho=box_barge_data["rho"],
            max_iter=100,
        )
        assert isinstance(result, OptimizationResult)


class TestAnalyzeInfeasibility:
    """Tests for analyze_infeasibility function."""

    @pytest.fixture
    def box_barge_data(self):
        """Box barge test fixture."""
        stations = np.linspace(0, 10, 11)
        waterlines = np.linspace(0, 3, 7)
        offset_table = np.full((7, 11), 1.0)
        return {
            "stations": stations,
            "waterlines": waterlines,
            "offset_table": offset_table,
            "draft": 1.5,
            "rho": 1025.0,
            "KG": 1.0,
        }

    @pytest.mark.skip(reason="Infeasibility analysis is computationally intensive")
    def test_analyze_infeasibility_returns_report(self, box_barge_data):
        """Test that analyze_infeasibility returns a valid report."""
        constraints = OptimizationConstraints(p_max=0.05)
        delta_final = np.zeros(30)  # No perturbation
        wl_mask = box_barge_data["waterlines"] <= box_barge_data["draft"]

        report = analyze_infeasibility(
            constraints=constraints,
            delta_final=delta_final,
            stations=box_barge_data["stations"],
            waterlines=box_barge_data["waterlines"],
            offset_table=box_barge_data["offset_table"],
            KG=box_barge_data["KG"],
            draft=box_barge_data["draft"],
            rho=box_barge_data["rho"],
            wl_mask=wl_mask,
            baseline_volume=75.0,  # Approximate for box barge
            baseline_gz=0.5,
        )
        assert isinstance(report, InfeasibilityReport)
        assert isinstance(report.violated_constraints, list)
        assert isinstance(report.per_constraint_relaxation, dict)
        assert 0 <= report.simultaneous_scale_factor <= 1
        assert report.suggested_p_max > 0

    @pytest.mark.skip(reason="Infeasibility analysis is computationally intensive")
    def test_infeasibility_report_schema(self, box_barge_data):
        """Test that infeasibility report has required fields."""
        constraints = OptimizationConstraints()
        delta_final = np.zeros(30)
        wl_mask = box_barge_data["waterlines"] <= box_barge_data["draft"]

        report = analyze_infeasibility(
            constraints=constraints,
            delta_final=delta_final,
            stations=box_barge_data["stations"],
            waterlines=box_barge_data["waterlines"],
            offset_table=box_barge_data["offset_table"],
            KG=box_barge_data["KG"],
            draft=box_barge_data["draft"],
            rho=box_barge_data["rho"],
            wl_mask=wl_mask,
            baseline_volume=75.0,
            baseline_gz=0.5,
        )
        # Check all required fields
        assert hasattr(report, "violated_constraints")
        assert hasattr(report, "per_constraint_relaxation")
        assert hasattr(report, "simultaneous_scale_factor")
        assert hasattr(report, "suggested_p_max")
        assert hasattr(report, "explanation")
