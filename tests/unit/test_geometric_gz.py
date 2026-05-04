"""Unit tests for geometric GZ / KN curve generation."""
import numpy as np

from geometric_gz import compute_geometric_gz_curve
from gz_curve import estimate_angle_of_vanishing_stability, estimate_deck_immersion_angle


def test_geometric_gz_curve_box_barge_zero_heel(box_barge_data):
    heel_angles = [0.0, 10.0, 20.0, 30.0]

    results = compute_geometric_gz_curve(
        stations=box_barge_data["stations"],
        waterlines=box_barge_data["waterlines"],
        offset_table=box_barge_data["offset_table"],
        draft=box_barge_data["draft"],
        rho=box_barge_data["rho"],
        KG=box_barge_data["KG"],
        heel_angles=heel_angles,
    )

    assert np.isclose(results["gz_geometric"][0], 0.0, atol=1e-8)
    assert np.isclose(results["kn_geometric"][0], 0.0, atol=1e-8)
    assert len(results["gz_geometric"]) == len(heel_angles)
    assert len(results["kn_geometric"]) == len(heel_angles)


def test_geometric_gz_curve_box_barge_positive_righting_arm(box_barge_data):
    heel_angles = [0.0, 15.0, 30.0]

    results = compute_geometric_gz_curve(
        stations=box_barge_data["stations"],
        waterlines=box_barge_data["waterlines"],
        offset_table=box_barge_data["offset_table"],
        draft=box_barge_data["draft"],
        rho=box_barge_data["rho"],
        KG=box_barge_data["KG"],
        heel_angles=heel_angles,
    )

    assert np.isfinite(results["max_gz_geometric"])
    assert np.isfinite(results["max_kn_geometric"])
    assert np.all(np.isfinite(results["gz_simplified"]))
    assert np.all(np.isfinite(results["kn_simplified"]))


def test_geometric_gz_uses_true_buoyancy_relation(box_barge_data):
    heel_angles = np.array([0.0, 10.0, 20.0, 40.0, 60.0], dtype=float)
    kg = float(box_barge_data["KG"])

    # Validate the requested formula: GZ = B_y - KG*sin(theta)
    results = compute_geometric_gz_curve(
        offset_table=box_barge_data["offset_table"],
        stations=box_barge_data["stations"],
        waterlines=box_barge_data["waterlines"],
        heel_angles=heel_angles,
        KG=kg,
        draft=box_barge_data["draft"],
        rho=box_barge_data["rho"],
    )

    expected_gz = np.asarray(results["buoyancy_transverse_arm"], dtype=float) - kg * np.sin(
        np.deg2rad(heel_angles)
    )
    np.testing.assert_allclose(
        np.asarray(results["gz_geometric"], dtype=float),
        expected_gz,
        atol=1e-10,
    )


def test_geometric_gz_volume_conservation_tolerance(box_barge_data):
    results = compute_geometric_gz_curve(
        offset_table=box_barge_data["offset_table"],
        stations=box_barge_data["stations"],
        waterlines=box_barge_data["waterlines"],
        heel_angles=np.arange(0.0, 61.0, 5.0),
        KG=float(box_barge_data["KG"]),
        draft=box_barge_data["draft"],
        rho=box_barge_data["rho"],
        volume_tol=1e-4,
    )

    rel_err = np.asarray(results["volume_rel_error"], dtype=float)
    assert rel_err.size == 13
    assert float(np.max(rel_err)) <= 1e-4


def test_geometric_gz_returns_buoyancy_coordinates(box_barge_data):
    results = compute_geometric_gz_curve(
        offset_table=box_barge_data["offset_table"],
        stations=box_barge_data["stations"],
        waterlines=box_barge_data["waterlines"],
        heel_angles=[0.0, 30.0, 60.0],
        KG=float(box_barge_data["KG"]),
        draft=box_barge_data["draft"],
        rho=box_barge_data["rho"],
    )

    assert "buoyancy_y" in results
    assert "buoyancy_z" in results
    assert len(results["buoyancy_y"]) == 3
    assert len(results["buoyancy_z"]) == 3
    assert np.all(np.isfinite(np.asarray(results["buoyancy_y"], dtype=float)))
    assert np.all(np.isfinite(np.asarray(results["buoyancy_z"], dtype=float)))


def test_gz_angle_helpers_return_expected_values():
    offsets = np.array([[0.0, 1.0, 2.0], [0.5, 1.5, 2.0]], dtype=float)
    deck_angle = estimate_deck_immersion_angle(depth=12.0, draft=9.0, offset_table=offsets)
    assert np.isclose(deck_angle, np.degrees(np.arctan2(3.0, 2.0)), atol=1e-9)

    heel = np.array([0.0, 10.0, 20.0, 30.0, 40.0], dtype=float)
    gz = np.array([0.0, 0.4, 0.6, 0.2, -0.1], dtype=float)
    avs_angle = estimate_angle_of_vanishing_stability(heel, gz)
    expected_avs = float(np.interp(0.0, [0.2, -0.1], [30.0, 40.0]))
    assert np.isclose(avs_angle, expected_avs, atol=1e-9)