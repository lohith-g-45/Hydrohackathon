"""Unit tests for Phase 4 - ShipD Benchmark (F3.T1, F3.T2, F3.T3)."""
import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from shipd_benchmark_converter import (
    select_diverse_hulls,
    hull_to_offset_table,
    extract_hull_metadata,
    save_benchmark_sample,
)
from benchmark_validation import compute_error_metrics, run_benchmark
from ship_excel_extractor import load_offsets_from_csv, validate_offset_csv


class TestShipExcelExtractor:
    """Tests for F3.T2 - CSV offset loader."""

    def test_load_offsets_from_csv_schema(self, tmp_path):
        """Test that loaded data has all required keys."""
        # Create a simple offset CSV
        offsets = np.array([[0.5, 1.0, 0.8], [0.6, 1.2, 0.9], [0.4, 0.9, 0.7]])
        stations = np.array([0.0, 50.0, 100.0])
        waterlines = np.array([0.0, 1.0, 2.0])

        csv_file = tmp_path / "test_offsets.csv"
        df = pd.DataFrame(offsets, index=waterlines, columns=stations)
        df.index.name = "waterline"
        df.columns.name = "station"
        df.to_csv(csv_file)

        result = load_offsets_from_csv(str(csv_file))

        assert isinstance(result, dict)
        assert "stations" in result
        assert "waterlines" in result
        assert "offset_table" in result
        assert "draft" in result
        assert "rho" in result
        assert "KG" in result

    def test_load_offsets_from_csv_roundtrip(self, tmp_path):
        """Test save → load → compare cycle."""
        offsets_orig = np.array([[0.5, 1.0, 0.8], [0.6, 1.2, 0.9], [0.4, 0.9, 0.7]])
        stations = np.array([0.0, 50.0, 100.0])
        waterlines = np.array([0.0, 1.0, 2.0])

        csv_file = tmp_path / "roundtrip.csv"
        df = pd.DataFrame(offsets_orig, index=waterlines, columns=stations)
        df.index.name = "waterline"
        df.to_csv(csv_file)

        result = load_offsets_from_csv(str(csv_file))
        offsets_loaded = result["offset_table"]

        assert np.allclose(offsets_orig, offsets_loaded)

    def test_validate_offset_csv_rejects_negatives(self, tmp_path):
        """Test that negative breadths are rejected."""
        offsets = np.array([[0.5, -1.0, 0.8], [0.6, 1.2, 0.9]])
        stations = np.array([0.0, 50.0, 100.0])
        waterlines = np.array([0.0, 1.0])

        csv_file = tmp_path / "bad_offsets.csv"
        df = pd.DataFrame(offsets, index=waterlines, columns=stations)
        df.to_csv(csv_file)

        with pytest.raises(ValueError, match="Negative"):
            validate_offset_csv(str(csv_file))

    def test_validate_offset_csv_missing_file(self, tmp_path):
        """Test that missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            validate_offset_csv(str(tmp_path / "nonexistent.csv"))


class TestShipDConverter:
    """Tests for F3.T1 - ShipD hull converter."""

    @pytest.fixture
    def sample_design_vector(self):
        """Sample 45-element design vector."""
        v = np.zeros(45)
        v[0] = 150.0  # LOA
        v[3] = 0.2    # Bd / LOA
        v[4] = 0.1    # Dd / LOA
        v[5] = 1.0    # Bs ratio
        v[6] = 0.7    # WL / Dd
        return v

    def test_select_diverse_hulls_returns_n(self, tmp_path):
        """Test that select_diverse_hulls returns n unique indices."""
        # Create synthetic dataset
        csv_file = tmp_path / "hulls.csv"
        X = np.random.randn(100, 45)
        np.savetxt(csv_file, X, delimiter=",", header="," * 44)

        indices = select_diverse_hulls(str(csv_file), n=10)

        assert len(indices) == 10
        assert len(set(indices)) == 10  # All unique
        assert all(0 <= i < 100 for i in indices)

    def test_select_diverse_hulls_handles_small_dataset(self, tmp_path):
        """Test behavior when n_hulls > dataset size."""
        csv_file = tmp_path / "small_hulls.csv"
        X = np.random.randn(5, 45)
        np.savetxt(csv_file, X, delimiter=",")

        indices = select_diverse_hulls(str(csv_file), n=10)

        assert len(indices) <= 5

    def test_hull_to_offset_table_shape(self, sample_design_vector):
        """Test that output shape matches requested (n_wl, n_sta)."""
        offsets, stations, waterlines = hull_to_offset_table(
            sample_design_vector, n_wl=20, n_sta=21
        )

        assert offsets.shape == (20, 21)
        assert stations.shape == (21,)
        assert waterlines.shape == (20,)

    def test_hull_to_offset_table_no_negatives(self, sample_design_vector):
        """Test that all half-breadths are non-negative."""
        offsets, _, _ = hull_to_offset_table(sample_design_vector, n_wl=20, n_sta=21)

        assert np.all(offsets >= 0)

    def test_hull_to_offset_table_monotonic_stations(self, sample_design_vector):
        """Test that stations are monotonically increasing."""
        _, stations, _ = hull_to_offset_table(sample_design_vector, n_wl=20, n_sta=21)

        assert np.all(np.diff(stations) > 0)

    def test_hull_to_offset_table_monotonic_waterlines(self, sample_design_vector):
        """Test that waterlines are monotonically increasing."""
        _, _, waterlines = hull_to_offset_table(sample_design_vector, n_wl=20, n_sta=21)

        assert np.all(np.diff(waterlines) >= 0)

    def test_extract_hull_metadata(self, sample_design_vector):
        """Test that metadata dict has all required keys."""
        metadata = extract_hull_metadata(sample_design_vector)

        assert "LOA" in metadata
        assert "Bd" in metadata
        assert "Dd" in metadata
        assert "draft" in metadata
        assert "KG" in metadata
        assert "rho" in metadata
        assert metadata["rho"] == 1025.0
        assert 0 < metadata["KG"] < metadata["Dd"]  # KG should be between 0 and depth

    def test_save_benchmark_sample_creates_files(self, tmp_path, sample_design_vector):
        """Test that save function creates both CSV and JSON files."""
        offsets, stations, waterlines = hull_to_offset_table(sample_design_vector)
        metadata = extract_hull_metadata(sample_design_vector)

        save_benchmark_sample(0, offsets, stations, waterlines, metadata, tmp_path)

        assert (tmp_path / "sample_00" / "offsets.csv").exists()
        assert (tmp_path / "sample_00" / "metadata.json").exists()

    def test_save_benchmark_sample_csv_format(self, tmp_path, sample_design_vector):
        """Test that saved CSV can be reloaded correctly."""
        offsets, stations, waterlines = hull_to_offset_table(sample_design_vector, n_wl=5, n_sta=5)
        metadata = extract_hull_metadata(sample_design_vector)

        save_benchmark_sample(1, offsets, stations, waterlines, metadata, tmp_path)

        csv_file = tmp_path / "sample_01" / "offsets.csv"
        reloaded = pd.read_csv(csv_file, index_col=0)

        assert reloaded.shape == (5, 5)

    def test_save_benchmark_sample_metadata_json(self, tmp_path, sample_design_vector):
        """Test that saved JSON metadata is valid."""
        offsets, stations, waterlines = hull_to_offset_table(sample_design_vector)
        metadata = extract_hull_metadata(sample_design_vector)

        save_benchmark_sample(2, offsets, stations, waterlines, metadata, tmp_path)

        json_file = tmp_path / "sample_02" / "metadata.json"
        with open(json_file) as f:
            loaded_meta = json.load(f)

        assert loaded_meta == metadata


class TestBenchmarkValidation:
    """Tests for F3.T3 - Benchmark validation."""

    @pytest.fixture
    def sample_results(self):
        """Sample coarse and fine results."""
        coarse = {
            "V": 5000.0,
            "GM": 1.5,
            "KB": 2.0,
            "LCB": 75.0,
            "gz": [0.0, 0.1, 0.25, 0.4, 0.5, 0.45, 0.3],
        }
        fine = {
            "V": 5050.0,
            "GM": 1.51,
            "KB": 2.01,
            "LCB": 75.1,
            "gz": [0.0, 0.11, 0.26, 0.41, 0.51, 0.46, 0.31],
        }
        return coarse, fine

    def test_error_metrics_schema(self, sample_results):
        """Test that error_metrics dict has all required keys."""
        coarse, fine = sample_results
        errors = compute_error_metrics(coarse, fine)

        assert "gm_error_pct" in errors
        assert "gz_max_deviation_pct" in errors
        assert "volume_deviation_pct" in errors
        assert "lcb_error_m" in errors
        assert "kb_error_m" in errors

    def test_gm_error_formula(self, sample_results):
        """Test that GM error is computed correctly."""
        coarse, fine = sample_results
        errors = compute_error_metrics(coarse, fine)

        expected = abs(1.5 - 1.51) / 1.51 * 100
        assert np.isclose(errors["gm_error_pct"], expected, atol=0.01)

    def test_volume_error_formula(self, sample_results):
        """Test that volume error is computed correctly."""
        coarse, fine = sample_results
        errors = compute_error_metrics(coarse, fine)

        expected = abs(5000 - 5050) / 5050 * 100
        assert np.isclose(errors["volume_deviation_pct"], expected, atol=0.01)

    def test_error_metrics_all_positive(self, sample_results):
        """Test that all error metrics are non-negative."""
        coarse, fine = sample_results
        errors = compute_error_metrics(coarse, fine)

        assert all(v >= 0 for v in errors.values())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
