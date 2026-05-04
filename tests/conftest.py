import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Add Hydrohackathon module directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "Hydrohackathon"))


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
    p = tmp_path_factory.getbasetemp() / "sample_offsets.csv"
    # 5 WL × 7 STA, increasing breadths
    df = pd.DataFrame(np.tile(np.linspace(0.1, 1.0, 7), (5, 1)))
    df.to_csv(p, index=False)
    return str(p)
