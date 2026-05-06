"""Run an external offset-only benchmark using KCS hull offsets.

Downloads are expected under data/external_benchmarks/kcs from SIMMAN/NMRI sources.
This script parses kcs.fix into an offset grid, runs the Hydrohackathon pipeline,
and compares results to published KCS reference particulars.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from hydrostatics import compute_phase4
from integration import compute_phase3


KCS_REF = {
    "Lpp_m": 230.0,
    "Bwl_m": 32.2,
    "draft_m": 10.8,
    "displacement_m3": 52030.0,
    "cb": 0.651,
    "lcb_pct_lpp_fwd_plus": -1.48,
}


def _safe_pct_diff(app_value: float, ref_value: float) -> float:
    denom = abs(float(ref_value))
    if denom <= 1e-12:
        return float("nan")
    return (float(app_value) - float(ref_value)) / float(ref_value) * 100.0


def _read_float_tokens(lines: list[str], start_idx: int, count: int) -> tuple[np.ndarray, int]:
    values: list[float] = []
    idx = start_idx
    while idx < len(lines) and len(values) < count:
        stripped = lines[idx].strip()
        if stripped:
            values.extend(float(tok) for tok in stripped.split())
        idx += 1
    if len(values) < count:
        raise ValueError(f"Expected {count} float values, got {len(values)}")
    return np.asarray(values[:count], dtype=float), idx


def parse_kcs_fix(path: Path) -> tuple[np.ndarray, list[np.ndarray], list[np.ndarray]]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if len(lines) < 3:
        raise ValueError("kcs.fix appears incomplete")

    inum = int(lines[1].strip())
    idx = 2

    stations: list[float] = []
    breadths_per_station: list[np.ndarray] = []
    heights_per_station: list[np.ndarray] = []

    for _ in range(inum):
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        if idx >= len(lines):
            raise ValueError("Unexpected end of file while reading station header")

        header = lines[idx].split()
        idx += 1
        if len(header) < 2:
            raise ValueError(f"Invalid station header line: {lines[idx - 1]!r}")

        xlongi = float(header[0])
        jnum = int(float(header[1]))

        breadths, idx = _read_float_tokens(lines, idx, jnum)
        heights, idx = _read_float_tokens(lines, idx, jnum)

        order = np.argsort(heights)
        heights = heights[order]
        breadths = breadths[order]

        stations.append(xlongi)
        breadths_per_station.append(breadths)
        heights_per_station.append(heights)

    stations_arr = np.asarray(stations, dtype=float)
    order = np.argsort(stations_arr)
    stations_arr = stations_arr[order]
    breadths_sorted = [breadths_per_station[i] for i in order]
    heights_sorted = [heights_per_station[i] for i in order]
    return stations_arr, breadths_sorted, heights_sorted


def build_offset_grid(
    stations: np.ndarray,
    breadths_per_station: list[np.ndarray],
    heights_per_station: list[np.ndarray],
    n_wl: int = 121,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    max_height = max(float(h.max()) for h in heights_per_station)
    waterlines = np.linspace(0.0, max_height, int(n_wl), dtype=float)
    offsets = np.zeros((waterlines.size, stations.size), dtype=float)

    for i, (b, z) in enumerate(zip(breadths_per_station, heights_per_station)):
        offsets[:, i] = np.interp(waterlines, z, b, left=0.0, right=0.0)

    return offsets, stations, waterlines


def run_benchmark(kcs_fix: Path, out_csv: Path) -> pd.DataFrame:
    offsets, stations, waterlines = build_offset_grid(*parse_kcs_fix(kcs_fix))

    draft = float(KCS_REF["draft_m"])
    rho = 1025.0

    phase3 = compute_phase3(stations, waterlines, offsets, draft=draft, rho=rho)
    volume_app = float(phase3["displaced_volume"])

    phase4 = compute_phase4(
        stations,
        waterlines,
        offsets,
        phase3["sectional_areas"],
        displaced_volume=volume_app,
        draft=draft,
        rho=rho,
    )

    lpp = float(KCS_REF["Lpp_m"])
    bwl = float(KCS_REF["Bwl_m"])
    cb_app = volume_app / max(lpp * bwl * draft, 1e-12)
    lcb_app = float(phase4["LCB"])
    lcb_pct_app = (lcb_app - 0.5 * lpp) / lpp * 100.0

    rows = [
        {
            "metric": "Displacement",
            "unit": "m^3",
            "reference": float(KCS_REF["displacement_m3"]),
            "generated": volume_app,
            "pct_diff": _safe_pct_diff(volume_app, float(KCS_REF["displacement_m3"])),
            "source": "SIMMAN KCS particulars",
        },
        {
            "metric": "Block Coefficient (CB)",
            "unit": "-",
            "reference": float(KCS_REF["cb"]),
            "generated": cb_app,
            "pct_diff": _safe_pct_diff(cb_app, float(KCS_REF["cb"])),
            "source": "SIMMAN KCS particulars",
        },
        {
            "metric": "LCB (%Lpp, fwd+)",
            "unit": "%",
            "reference": float(KCS_REF["lcb_pct_lpp_fwd_plus"]),
            "generated": lcb_pct_app,
            "pct_diff": _safe_pct_diff(lcb_pct_app, float(KCS_REF["lcb_pct_lpp_fwd_plus"])),
            "source": "SIMMAN KCS particulars",
        },
    ]

    out_df = pd.DataFrame(rows)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_csv, index=False)

    offsets_csv = out_csv.parent / "kcs_offsets_table.csv"
    pd.DataFrame(offsets, index=waterlines, columns=stations).to_csv(offsets_csv)
    return out_df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run KCS offset-only external benchmark")
    parser.add_argument(
        "--kcs-fix",
        default="data/external_benchmarks/kcs/kcs.fix",
        help="Path to KCS kcs.fix file",
    )
    parser.add_argument(
        "--out",
        default="results/kcs_offset_benchmark.csv",
        help="Output benchmark CSV path",
    )
    args = parser.parse_args()

    report = run_benchmark(Path(args.kcs_fix), Path(args.out))
    print("\n=== KCS Offset Benchmark Summary ===")
    for _, row in report.iterrows():
        print(
            f"{row['metric']}: ref={row['reference']:.4f} | "
            f"app={row['generated']:.4f} | diff={row['pct_diff']:+.2f}%"
        )
    print(f"\nWrote report: {Path(args.out)}")
