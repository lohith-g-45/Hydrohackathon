"""Benchmark validation helpers for coarse vs fine hydrostatic runs."""

from __future__ import annotations

import numpy as np


def compute_error_metrics(coarse: dict, fine: dict) -> dict[str, float]:
    gm_error = abs(float(coarse["GM"]) - float(fine["GM"])) / max(abs(float(fine["GM"])), 1e-12) * 100.0
    gz_c = np.asarray(coarse["gz"], dtype=float)
    gz_f = np.asarray(fine["gz"], dtype=float)
    n = min(gz_c.size, gz_f.size)
    if n == 0:
        gz_dev = 0.0
    else:
        gz_dev = float(np.max(np.abs(gz_c[:n] - gz_f[:n])) / max(np.max(np.abs(gz_f[:n])), 1e-12) * 100.0)

    vol_error = abs(float(coarse["V"]) - float(fine["V"])) / max(abs(float(fine["V"])), 1e-12) * 100.0
    lcb_error = abs(float(coarse["LCB"]) - float(fine["LCB"]))
    kb_error = abs(float(coarse["KB"]) - float(fine["KB"]))

    return {
        "gm_error_pct": float(gm_error),
        "gz_max_deviation_pct": float(gz_dev),
        "volume_deviation_pct": float(vol_error),
        "lcb_error_m": float(lcb_error),
        "kb_error_m": float(kb_error),
    }


def run_benchmark(coarse_results: list[dict], fine_results: list[dict]) -> list[dict[str, float]]:
    """Return per-sample metric deltas for benchmark runs."""
    pairs = zip(coarse_results, fine_results)
    return [compute_error_metrics(c, f) for c, f in pairs]
