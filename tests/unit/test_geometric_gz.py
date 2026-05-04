"""Unit tests for geometric GZ / KN curve generation."""
import numpy as np

from geometric_gz import compute_geometric_gz_curve


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

    assert results["max_gz_geometric"] > 0.0
    assert results["max_kn_geometric"] > 0.0
    assert np.all(np.isfinite(results["gz_simplified"]))
    assert np.all(np.isfinite(results["kn_simplified"]))