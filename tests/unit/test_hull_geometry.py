"""Unit tests for hull_geometry.py."""
import numpy as np
import pytest

from Hydrohackathon.hull_geometry import (
    rotate_hull,
    integrate_heeled_volume,
    find_heeled_waterplane,
    heeled_buoyancy_centroid,
)


class TestRotateHull:
    """Tests for rotate_hull function."""

    def test_rotate_hull_at_zero_deg(self, box_barge_data):
        """Output y, z arrays should equal input Y, Z arrays within 1e-10 at 0° heel."""
        stations = box_barge_data["stations"]
        waterlines = box_barge_data["waterlines"]
        offset_table = box_barge_data["offset_table"]

        result = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)

        # At 0° heel:
        # y_stbd = offset_table (unchanged)
        # z_stbd = waterlines (unchanged, cos(0)=1, sin(0)=0)
        np.testing.assert_allclose(result["y_stbd"], offset_table, atol=1e-10)
        np.testing.assert_allclose(
            result["z_stbd"],
            np.tile(waterlines[:, np.newaxis], (1, len(stations))),
            atol=1e-10,
        )

        # y_port should be negative of offset_table
        np.testing.assert_allclose(result["y_port"], -offset_table, atol=1e-10)

    def test_rotate_hull_90deg_swaps_axes(self):
        """At 90° heel, y' ≈ -Z, z' ≈ Y."""
        stations = np.array([0.0, 1.0, 2.0])
        waterlines = np.array([0.0, 1.0, 2.0])
        # Simple offset table: constant half-breadth = 1.0
        offset_table = np.full((3, 3), 1.0)

        result = rotate_hull(stations, waterlines, offset_table, heel_deg=90.0)

        # At 90°: cos(90)=0, sin(90)=1
        # y' = Y * 0 - Z * 1 = -Z
        # z' = Y * 1 + Z * 0 = Y
        expected_z_stbd = offset_table  # z' = Y
        expected_y_stbd = np.tile(-waterlines[:, np.newaxis], (1, len(stations)))  # y' = -Z

        np.testing.assert_allclose(result["z_stbd"], expected_z_stbd, atol=1e-10)
        np.testing.assert_allclose(result["y_stbd"], expected_y_stbd, atol=1e-10)

    def test_rotate_hull_output_shape(self, box_barge_data):
        """Output arrays should have correct shape."""
        stations = box_barge_data["stations"]
        waterlines = box_barge_data["waterlines"]
        offset_table = box_barge_data["offset_table"]

        result = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)

        assert result["x"].shape == offset_table.shape
        assert result["y_stbd"].shape == offset_table.shape
        assert result["z_stbd"].shape == offset_table.shape
        assert result["y_port"].shape == offset_table.shape
        assert result["z_port"].shape == offset_table.shape
        assert isinstance(result["heel_deg"], float)

    def test_rotate_hull_returns_float64(self, box_barge_data):
        """All output arrays should be float64."""
        stations = box_barge_data["stations"]
        waterlines = box_barge_data["waterlines"]
        offset_table = box_barge_data["offset_table"]

        result = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)

        assert result["x"].dtype == np.float64
        assert result["y_stbd"].dtype == np.float64
        assert result["z_stbd"].dtype == np.float64
        assert result["y_port"].dtype == np.float64
        assert result["z_port"].dtype == np.float64


class TestIntegrateHeeledVolume:
    """Tests for integrate_heeled_volume function."""

    def test_integrate_heeled_volume_box_barge_upright(self, box_barge_data):
        """
        For a box barge at 0° heel with draft=1.5:
        V = L * B * draft = 10 * 2 * 1.5 = 30 m³
        Expected: ~30 m³ within 0.1%
        """
        stations = box_barge_data["stations"]
        waterlines = box_barge_data["waterlines"]
        offset_table = box_barge_data["offset_table"]
        draft = box_barge_data["draft"]

        heeled_hull = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)
        volume = integrate_heeled_volume(heeled_hull, z_wl=draft)

        expected_volume = 10.0 * 2.0 * draft  # L * B * draft = 30 m³
        deviation_pct = abs(volume - expected_volume) / expected_volume * 100

        assert deviation_pct < 0.1, f"Volume deviation {deviation_pct:.4f}% exceeds 0.1%"
        assert 29.0 < volume < 31.0

    def test_integrate_heeled_volume_at_zero_waterplane(self, box_barge_data):
        """At waterplane z=0, volume should be negligible."""
        stations = box_barge_data["stations"]
        waterlines = box_barge_data["waterlines"]
        offset_table = box_barge_data["offset_table"]

        heeled_hull = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)
        volume = integrate_heeled_volume(heeled_hull, z_wl=0.0)

        assert volume < 0.01  # Should be very small

    def test_integrate_heeled_volume_at_max_waterplane(self, box_barge_data):
        """At max waterline, volume should approach total box volume."""
        stations = box_barge_data["stations"]
        waterlines = box_barge_data["waterlines"]
        offset_table = box_barge_data["offset_table"]

        heeled_hull = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)
        volume = integrate_heeled_volume(heeled_hull, z_wl=3.0)

        # At max waterline (3.0), should be close to L * B * 3 = 10 * 2 * 3 = 60 m³
        expected = 10.0 * 2.0 * 3.0
        assert volume > expected * 0.95  # Allow small tolerance

    def test_integrate_heeled_volume_returns_float(self, box_barge_data):
        """Return type should be float."""
        stations = box_barge_data["stations"]
        waterlines = box_barge_data["waterlines"]
        offset_table = box_barge_data["offset_table"]
        draft = box_barge_data["draft"]

        heeled_hull = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)
        volume = integrate_heeled_volume(heeled_hull, z_wl=draft)

        assert isinstance(volume, float)


class TestFindHeeledWaterplane:
    """Tests for find_heeled_waterplane function."""

    def test_find_heeled_waterplane_converges(self, box_barge_data):
        """Bisection search should converge to target volume."""
        stations = box_barge_data["stations"]
        waterlines = box_barge_data["waterlines"]
        offset_table = box_barge_data["offset_table"]
        draft = box_barge_data["draft"]

        heeled_hull = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)

        # Compute volume at design draft
        V0 = integrate_heeled_volume(heeled_hull, z_wl=draft)

        # Find waterplane for same volume
        z_wl_found = find_heeled_waterplane(heeled_hull, target_volume=V0, tol=1e-4)

        # Verify convergence
        V_check = integrate_heeled_volume(heeled_hull, z_wl=z_wl_found)
        assert abs(V_check - V0) < 1e-4

    def test_find_heeled_waterplane_at_zero_heel(self, box_barge_data):
        """At 0° heel, found waterplane should equal draft for upright case."""
        stations = box_barge_data["stations"]
        waterlines = box_barge_data["waterlines"]
        offset_table = box_barge_data["offset_table"]
        draft = box_barge_data["draft"]

        heeled_hull = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)
        V0 = integrate_heeled_volume(heeled_hull, z_wl=draft)

        z_wl_found = find_heeled_waterplane(heeled_hull, target_volume=V0)

        # At 0° heel, should be very close to draft
        assert abs(z_wl_found - draft) < 0.05  # Within 5 cm

    def test_find_heeled_waterplane_returns_float(self, box_barge_data):
        """Return type should be float."""
        stations = box_barge_data["stations"]
        waterlines = box_barge_data["waterlines"]
        offset_table = box_barge_data["offset_table"]
        draft = box_barge_data["draft"]

        heeled_hull = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)
        V0 = integrate_heeled_volume(heeled_hull, z_wl=draft)

        z_wl = find_heeled_waterplane(heeled_hull, target_volume=V0)

        assert isinstance(z_wl, float)

    def test_find_heeled_waterplane_raises_on_impossible_volume(self, box_barge_data):
        """Should raise RuntimeError if target volume is impossible."""
        stations = box_barge_data["stations"]
        waterlines = box_barge_data["waterlines"]
        offset_table = box_barge_data["offset_table"]

        heeled_hull = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)

        # Try to find impossible large volume
        with pytest.raises(RuntimeError):
            find_heeled_waterplane(heeled_hull, target_volume=1e6)

    def test_find_heeled_waterplane_half_volume(self, box_barge_data):
        """Should find waterplane for half the design volume."""
        stations = box_barge_data["stations"]
        waterlines = box_barge_data["waterlines"]
        offset_table = box_barge_data["offset_table"]
        draft = box_barge_data["draft"]

        heeled_hull = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)
        V0 = integrate_heeled_volume(heeled_hull, z_wl=draft)

        # Find waterplane for half volume
        z_wl_half = find_heeled_waterplane(heeled_hull, target_volume=V0 / 2.0)

        # Verify
        V_check = integrate_heeled_volume(heeled_hull, z_wl=z_wl_half)
        assert abs(V_check - V0 / 2.0) < 1e-3


class TestHeeledBuoyancyCentroid:
    """Tests for heeled_buoyancy_centroid function."""

    def test_heeled_buoyancy_centroid_box_barge_upright(self, box_barge_data):
        """
        For upright box barge at draft=1.5:
        - y_B should be ≈ 0 (symmetric)
        - z_B should be ≈ draft/2 = 0.75 m
        """
        stations = box_barge_data["stations"]
        waterlines = box_barge_data["waterlines"]
        offset_table = box_barge_data["offset_table"]
        draft = box_barge_data["draft"]

        heeled_hull = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)

        y_b, z_b = heeled_buoyancy_centroid(heeled_hull, z_wl=draft)

        # y_B should be very close to 0 (symmetric)
        assert abs(y_b) < 0.1, f"y_B = {y_b}, expected ≈ 0"

        # z_B should be close to draft/2
        expected_z_b = draft / 2.0
        assert abs(z_b - expected_z_b) < 0.1, f"z_B = {z_b}, expected ≈ {expected_z_b}"

    def test_heeled_buoyancy_centroid_returns_tuple_of_floats(self, box_barge_data):
        """Return type should be tuple of floats."""
        stations = box_barge_data["stations"]
        waterlines = box_barge_data["waterlines"]
        offset_table = box_barge_data["offset_table"]
        draft = box_barge_data["draft"]

        heeled_hull = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)

        y_b, z_b = heeled_buoyancy_centroid(heeled_hull, z_wl=draft)

        assert isinstance(y_b, float)
        assert isinstance(z_b, float)

    def test_heeled_buoyancy_centroid_at_shallow_draft(self, box_barge_data):
        """At shallow draft, z_B should be lower."""
        stations = box_barge_data["stations"]
        waterlines = box_barge_data["waterlines"]
        offset_table = box_barge_data["offset_table"]

        heeled_hull = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)

        y_b_shallow, z_b_shallow = heeled_buoyancy_centroid(heeled_hull, z_wl=0.5)
        y_b_deep, z_b_deep = heeled_buoyancy_centroid(heeled_hull, z_wl=1.5)

        # At deeper draft, z_B should be roughly higher
        assert z_b_deep > z_b_shallow

    def test_heeled_buoyancy_centroid_at_heeled_condition(self, box_barge_data):
        """At 30° heel, centroid should shift (y_B != 0)."""
        stations = box_barge_data["stations"]
        waterlines = box_barge_data["waterlines"]
        offset_table = box_barge_data["offset_table"]
        draft = box_barge_data["draft"]

        # For heeled condition, find matching waterplane
        heeled_hull = rotate_hull(stations, waterlines, offset_table, heel_deg=30.0)

        # Upright volume
        upright_hull = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)
        V0 = integrate_heeled_volume(upright_hull, z_wl=draft)

        # Find waterplane at 30° heel for same volume
        z_wl_heeled = find_heeled_waterplane(heeled_hull, target_volume=V0)

        y_b, z_b = heeled_buoyancy_centroid(heeled_hull, z_wl=z_wl_heeled)

        # At 30° heel, y_B should deviate significantly from 0
        assert abs(y_b) > 0.1, f"At 30° heel, expected y_B to deviate from 0, got {y_b}"


class TestIntegration:
    """Integration tests combining multiple functions."""

    def test_volume_conservation_at_zero_heel(self, box_barge_data):
        """Volume should be conserved at 0° heel."""
        stations = box_barge_data["stations"]
        waterlines = box_barge_data["waterlines"]
        offset_table = box_barge_data["offset_table"]
        draft = box_barge_data["draft"]

        upright_hull = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)
        V_upright = integrate_heeled_volume(upright_hull, z_wl=draft)

        # Find waterplane for same volume
        z_wl_found = find_heeled_waterplane(upright_hull, target_volume=V_upright)

        # Should be very close
        assert abs(z_wl_found - draft) < 0.02

    def test_volume_conservation_at_30deg_heel(self, box_barge_data):
        """Volume should be conserved at 30° heel."""
        stations = box_barge_data["stations"]
        waterlines = box_barge_data["waterlines"]
        offset_table = box_barge_data["offset_table"]
        draft = box_barge_data["draft"]

        # Upright volume
        upright_hull = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)
        V_upright = integrate_heeled_volume(upright_hull, z_wl=draft)

        # Heeled hull at 30°
        heeled_hull = rotate_hull(stations, waterlines, offset_table, heel_deg=30.0)
        z_wl_heeled = find_heeled_waterplane(heeled_hull, target_volume=V_upright)

        # Verify volume matches
        V_heeled = integrate_heeled_volume(heeled_hull, z_wl=z_wl_heeled)
        deviation_pct = abs(V_heeled - V_upright) / V_upright * 100

        assert deviation_pct < 0.1, f"Volume deviation {deviation_pct:.4f}% exceeds 0.1%"

    def test_full_workflow_box_barge(self, box_barge_data):
        """Full workflow: rotate → find waterplane → compute centroid."""
        stations = box_barge_data["stations"]
        waterlines = box_barge_data["waterlines"]
        offset_table = box_barge_data["offset_table"]
        draft = box_barge_data["draft"]

        heel_angles = [0, 15, 30, 45]

        upright_hull = rotate_hull(stations, waterlines, offset_table, heel_deg=0.0)
        V_upright = integrate_heeled_volume(upright_hull, z_wl=draft)

        for heel_deg in heel_angles:
            heeled_hull = rotate_hull(
                stations, waterlines, offset_table, heel_deg=float(heel_deg)
            )

            z_wl = find_heeled_waterplane(heeled_hull, target_volume=V_upright)
            y_b, z_b = heeled_buoyancy_centroid(heeled_hull, z_wl=z_wl)

            # Basic sanity checks
            assert isinstance(z_wl, float)
            assert isinstance(y_b, float)
            assert isinstance(z_b, float)
            assert z_wl > 0  # Waterplane should be positive


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
