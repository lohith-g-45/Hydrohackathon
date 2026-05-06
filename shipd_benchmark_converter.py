"""ShipD benchmark conversion helpers.

This module is benchmark-only and should not be imported by the workbook
offset-data application path.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_RHO = 1025.0

# ShipD vector indices from HullParameterization
IDX_LOA = 0
IDX_LB = 1
IDX_LS = 2
IDX_BD = 3
IDX_DD = 4
IDX_BS = 5
IDX_WL = 6


def _load_design_matrix(csv_path: str) -> np.ndarray:
    try:
        df = pd.read_csv(csv_path, header=0)
        data = df.values.astype(float)
    except Exception:
        df = pd.read_csv(csv_path, header=None)
        data = df.values.astype(float)
    return np.asarray(data, dtype=float)


def select_diverse_hulls(csv_path: str, n: int = 10) -> list[int]:
    """Select up to n representative hull indices using deterministic spacing."""
    if n <= 0:
        return []

    X = _load_design_matrix(csv_path)
    total = int(X.shape[0])
    if total == 0:
        return []

    k = min(int(n), total)
    # Deterministic spread across dataset rows.
    idx = np.linspace(0, total - 1, num=k, dtype=int)
    return sorted(set(int(i) for i in idx))


def hull_to_offset_table(design_vector, n_wl: int = 11, n_sta: int = 23):
    """Convert a design vector into a non-negative half-breadth offset table."""
    v = np.asarray(design_vector, dtype=float).reshape(-1)
    loa = float(v[IDX_LOA]) if v.size > IDX_LOA and np.isfinite(v[IDX_LOA]) and v[IDX_LOA] > 0 else 100.0
    lb_ratio = float(v[IDX_LB]) if v.size > IDX_LB and np.isfinite(v[IDX_LB]) and v[IDX_LB] > 0 else 0.2
    ls_ratio = float(v[IDX_LS]) if v.size > IDX_LS and np.isfinite(v[IDX_LS]) and v[IDX_LS] > 0 else 0.2
    lb_ratio = float(np.clip(lb_ratio, 0.02, 0.49))
    ls_ratio = float(np.clip(ls_ratio, 0.02, 0.49))
    if lb_ratio + ls_ratio > 0.95:
        scale = 0.95 / max(lb_ratio + ls_ratio, 1e-9)
        lb_ratio *= scale
        ls_ratio *= scale

    # ShipD stores Bd and Dd as LOA-normalized values.
    beam = float(v[IDX_BD] * loa) if v.size > IDX_BD and np.isfinite(v[IDX_BD]) and v[IDX_BD] > 0 else 0.18 * loa
    depth = float(v[IDX_DD] * loa) if v.size > IDX_DD and np.isfinite(v[IDX_DD]) and v[IDX_DD] > 0 else 0.08 * loa
    # Bs is stern half-breadth relative to deck half-breadth in ShipD.
    # Apply it as an aft taper target rather than a global beam scale.
    stern_ratio = float(v[IDX_BS]) if v.size > IDX_BS and np.isfinite(v[IDX_BS]) and v[IDX_BS] > 0 else 1.0
    stern_ratio = float(np.clip(stern_ratio, 0.05, 1.0))

    stations = np.linspace(0.0, loa, int(n_sta), dtype=float)
    waterlines = np.linspace(0.0, depth, int(n_wl), dtype=float)

    x_norm = (stations - 0.5 * loa) / max(0.5 * loa, 1e-9)
    z_norm = waterlines / max(depth, 1e-9)
    vertical = 0.15 + 0.85 * np.sqrt(np.clip(z_norm, 0.0, 1.0))

    x01 = np.clip(stations / max(loa, 1e-9), 0.0, 1.0)
    bow_end = lb_ratio
    stern_start = 1.0 - ls_ratio

    longitudinal = np.ones_like(x01)

    bow_mask = x01 < bow_end
    if np.any(bow_mask):
        u = np.clip(x01[bow_mask] / max(bow_end, 1e-9), 0.0, 1.0)
        longitudinal[bow_mask] = u**0.75

    stern_mask = x01 > stern_start
    if np.any(stern_mask):
        v_s = np.clip((1.0 - x01[stern_mask]) / max(ls_ratio, 1e-9), 0.0, 1.0)
        stern_profile = stern_ratio + (1.0 - stern_ratio) * (v_s**0.85)
        longitudinal[stern_mask] = np.minimum(longitudinal[stern_mask], stern_profile)

    baseline_longitudinal = np.clip(1.0 - x_norm**2, 0.0, None)
    longitudinal = 0.55 * longitudinal + 0.45 * baseline_longitudinal

    max_half_beam = 0.5 * beam
    offsets = np.outer(vertical, longitudinal) * max_half_beam
    offsets = np.maximum(offsets, 0.0)

    return offsets.astype(float), stations, waterlines


def extract_hull_metadata(design_vector) -> dict[str, float]:
    """Build metadata used by benchmark test scaffolding."""
    v = np.asarray(design_vector, dtype=float).reshape(-1)
    loa = float(v[IDX_LOA]) if v.size > IDX_LOA and np.isfinite(v[IDX_LOA]) and v[IDX_LOA] > 0 else 100.0
    bd = float(v[IDX_BD] * loa) if v.size > IDX_BD and np.isfinite(v[IDX_BD]) and v[IDX_BD] > 0 else 0.18 * loa
    dd = float(v[IDX_DD] * loa) if v.size > IDX_DD and np.isfinite(v[IDX_DD]) and v[IDX_DD] > 0 else 0.08 * loa

    if v.size > IDX_WL and np.isfinite(v[IDX_WL]) and v[IDX_WL] > 0:
        draft = float(min(v[IDX_WL], 0.995) * dd)
    else:
        draft = 0.6 * dd
    kg = 0.55 * draft

    return {
        "LOA": float(loa),
        "Bd": float(bd),
        "Dd": float(dd),
        "draft": float(draft),
        "KG": float(kg),
        "rho": float(DEFAULT_RHO),
    }


def save_benchmark_sample(
    sample_index: int,
    offsets: np.ndarray,
    stations: np.ndarray,
    waterlines: np.ndarray,
    metadata: dict,
    output_root,
) -> None:
    """Save one benchmark sample in the expected folder structure."""
    out_root = Path(output_root)
    sample_dir = out_root / f"sample_{int(sample_index):02d}"
    sample_dir.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(np.asarray(offsets, dtype=float), index=np.asarray(waterlines, dtype=float), columns=np.asarray(stations, dtype=float))
    df.index.name = "waterline"
    df.columns.name = "station"
    df.to_csv(sample_dir / "offsets.csv")

    with (sample_dir / "metadata.json").open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
