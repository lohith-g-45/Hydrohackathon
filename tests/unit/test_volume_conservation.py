"""Unit tests for Phase 2 — Volume Conservation module."""
import numpy as np
import pandas as pd
import pytest
import sys
from pathlib import Path

# Add Hydrohackathon to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "Hydrohackathon"))

from volume_conservation import run_volume_conservation, volume_conservation_summary


class TestVolumeConservation:
    """Test suite for volume conservation validation."""

    def test_volume_conservation_zero_heel(self, box_barge_data):
        """Test that deviation is near zero at 0° heel."""
        heel_angles = [0.0]
        df = run_volume_conservation(
            stations=box_barge_data["stations"],
            waterlines=box_barge_data["waterlines"],
            offset_table=box_barge_data["offset_table"],
            draft=box_barge_data["draft"],
            rho=box_barge_data["rho"],
            heel_angles=heel_angles,
        )

        # At zero heel, deviation should be essentially 0
        assert len(df) == 1
        assert df.iloc[0]["heel_deg"] == 0.0
        assert abs(df.iloc[0]["deviation_pct"]) < 0.01, \
            f"Expected deviation near 0% at 0° heel, got {df.iloc[0]['deviation_pct']}%"

    def test_volume_conservation_box_barge_30deg(self, box_barge_data):
        """Test that box barge maintains volume within tolerance at 30°."""
        heel_angles = [30.0]
        df = run_volume_conservation(
            stations=box_barge_data["stations"],
            waterlines=box_barge_data["waterlines"],
            offset_table=box_barge_data["offset_table"],
            draft=box_barge_data["draft"],
            rho=box_barge_data["rho"],
            heel_angles=heel_angles,
        )

        # For a rectangular barge, deviation should be very small
        assert len(df) == 1
        assert df.iloc[0]["heel_deg"] == 30.0
        assert df.iloc[0]["deviation_pct"] < 0.1, \
            f"Expected deviation < 0.1% at 30°, got {df.iloc[0]['deviation_pct']}%"

    def test_volume_conservation_summary_pass(self):
        """Test that summary correctly identifies 'pass' status."""
        # Create mock DataFrame with max deviation < 1%
        df = pd.DataFrame({
            "heel_deg": [0, 5, 10],
            "V_upright_m3": [100.0, 100.0, 100.0],
            "V_heeled_m3": [100.0, 100.004, 100.003],
            "deviation_pct": [0.0, 0.004, 0.003],
        })

        result = volume_conservation_summary(df)
        assert result["max_dev_pct"] < 1.0
        assert result["status"] == "pass"

    def test_volume_conservation_summary_warn(self):
        """Test that summary correctly identifies 'warn' status."""
        # Create mock DataFrame with 1% <= max deviation <= 3%
        df = pd.DataFrame({
            "heel_deg": [0, 5, 10],
            "V_upright_m3": [100.0, 100.0, 100.0],
            "V_heeled_m3": [100.0, 101.5, 100.0],
            "deviation_pct": [0.0, 1.5, 0.0],
        })

        result = volume_conservation_summary(df)
        assert 1.0 <= result["max_dev_pct"] <= 3.0
        assert result["status"] == "warn"

    def test_volume_conservation_summary_fail(self):
        """Test that summary correctly identifies 'fail' status."""
        # Create mock DataFrame with max deviation > 3%
        df = pd.DataFrame({
            "heel_deg": [0, 5, 10],
            "V_upright_m3": [100.0, 100.0, 100.0],
            "V_heeled_m3": [100.0, 105.0, 100.0],
            "deviation_pct": [0.0, 5.0, 0.0],
        })

        result = volume_conservation_summary(df)
        assert result["max_dev_pct"] > 3.0
        assert result["status"] == "fail"

    def test_volume_conservation_csv_output(self, box_barge_data):
        """Test that output DataFrame has correct structure."""
        heel_angles = [0, 5, 10, 15, 20]
        df = run_volume_conservation(
            stations=box_barge_data["stations"],
            waterlines=box_barge_data["waterlines"],
            offset_table=box_barge_data["offset_table"],
            draft=box_barge_data["draft"],
            rho=box_barge_data["rho"],
            heel_angles=heel_angles,
        )

        # Check DataFrame structure
        assert isinstance(df, pd.DataFrame)
        assert len(df) == len(heel_angles), \
            f"Expected {len(heel_angles)} rows, got {len(df)}"
        assert set(df.columns) == {
            "heel_deg",
            "V_upright_m3",
            "V_heeled_m3",
            "deviation_pct",
        }, f"Unexpected columns: {df.columns.tolist()}"
        
        # Check that heel_deg matches input
        assert list(df["heel_deg"]) == heel_angles

    def test_volume_conservation_range(self, box_barge_data):
        """Test volume conservation over a range of heel angles (0-60°)."""
        heel_angles = list(range(0, 65, 5))  # 0, 5, 10, ..., 60
        df = run_volume_conservation(
            stations=box_barge_data["stations"],
            waterlines=box_barge_data["waterlines"],
            offset_table=box_barge_data["offset_table"],
            draft=box_barge_data["draft"],
            rho=box_barge_data["rho"],
            heel_angles=heel_angles,
        )

        # Check all rows present
        assert len(df) == len(heel_angles)
        
        # For box barge, deviations should be very small across all angles
        max_dev = df["deviation_pct"].max()
        assert max_dev < 0.1, \
            f"Box barge max deviation {max_dev}% exceeds expected 0.1%"
        
        # Check monotonicity and sign of volumes (all should be positive)
        assert (df["V_heeled_m3"] > 0).all(), "Found non-positive volumes"
        assert (df["V_upright_m3"] > 0).all(), "Found non-positive upright volumes"
