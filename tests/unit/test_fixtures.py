from __future__ import annotations

import numpy as np
import pandas as pd


def test_sample_offsets_fixture_shape_and_dtype() -> None:
    df = pd.read_csv("tests/fixtures/sample_offsets.csv", header=None)

    assert df.shape == (5, 7)
    assert np.issubdtype(df.to_numpy().dtype, np.floating)


def test_box_barge_fixture_shape_and_dtype() -> None:
    df = pd.read_csv("tests/fixtures/box_barge_offsets.csv", header=None)

    assert df.shape == (7, 11)
    arr = df.to_numpy(dtype=np.float64)
    assert arr.dtype == np.float64
    assert np.allclose(arr, 1.0)
