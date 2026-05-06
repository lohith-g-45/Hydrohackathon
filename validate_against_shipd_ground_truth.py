"""Compare Hydrohackathon generated hydrostatics against ShipD reference computations.

This script computes "reference" hydrostatics using ShipD's own Hull_Parameterization
volume-property pipeline and compares them against the current Hydrohackathon
adapted-offset workflow for the same design vectors.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from hydrostatics import compute_phase4
from integration import compute_phase3
from shipd_benchmark_converter import extract_hull_metadata, hull_to_offset_table
from stability import compute_BM, compute_GM, compute_IT, extract_draft_breadths


def _safe_pct_diff(app_value: float, ref_value: float) -> float:
    denom = abs(float(ref_value))
    if denom <= 1e-12:
        return float("nan")
    return (float(app_value) - float(ref_value)) / float(ref_value) * 100.0


def _sample_indices(total: int, n: int) -> np.ndarray:
    if total <= 0:
        return np.asarray([], dtype=int)
    k = min(max(int(n), 1), total)
    return np.linspace(0, total - 1, num=k, dtype=int)


def run_validation(
    vectors_path: Path,
    out_csv: Path,
    n_hulls: int,
    n_wl_app: int,
    n_sta_app: int,
    num_wl_ref: int,
    points_per_wl_ref: int,
) -> pd.DataFrame:
    workspace_root = Path(__file__).resolve().parents[1]
    shipd_repo = workspace_root / "ShipD_repo"
    if not shipd_repo.exists():
        raise FileNotFoundError(f"ShipD repo not found at {shipd_repo}")

    sys.path.insert(0, str(shipd_repo))
    from HullParameterization import Hull_Parameterization  # type: ignore

    vectors = np.load(str(vectors_path), allow_pickle=True)
    vectors = np.asarray(vectors, dtype=float)
    if vectors.ndim != 2 or vectors.shape[1] < 7:
        raise ValueError(f"Unexpected vectors shape: {vectors.shape}")

    indices = _sample_indices(vectors.shape[0], n_hulls)
    rows: list[dict[str, float | int]] = []

    for idx in indices:
        design_vector = vectors[int(idx)]

        # ShipD reference hydrostatics at the deepest computed waterline.
        hull = Hull_Parameterization(design_vector)
        hull.Calc_VolumeProperties(NUM_WL=int(num_wl_ref), PointsPerWL=int(points_per_wl_ref))
        vol_ref = float(hull.Volumes[-1])
        lcb_ref = float(hull.VolumeCentroids[-1, 0])
        kb_ref = float(hull.VolumeCentroids[-1, 1])
        ixx_ref = float(hull.I_WP[-1, 0])

        # Hydrohackathon adapted-offset pipeline.
        metadata = extract_hull_metadata(design_vector)
        offsets, stations, waterlines = hull_to_offset_table(
            design_vector,
            n_wl=int(n_wl_app),
            n_sta=int(n_sta_app),
        )
        draft = float(waterlines[-1])
        rho = float(metadata["rho"])
        kg = float(metadata["KG"])

        phase3 = compute_phase3(stations, waterlines, offsets, draft=draft, rho=rho)
        vol_app = float(phase3["displaced_volume"])

        phase4 = compute_phase4(
            stations,
            waterlines,
            offsets,
            phase3["sectional_areas"],
            displaced_volume=vol_app,
            draft=draft,
            rho=rho,
        )
        lcb_app = float(phase4["LCB"])
        kb_app = float(phase4["KB"])

        breadths = extract_draft_breadths(stations, waterlines, offsets, draft)
        it_app = compute_IT(stations, breadths)
        bm_app = float(compute_BM(it_app, vol_app))
        gm_app = float(compute_GM(kb_app, bm_app, kg))

        # GM reference derived from ShipD hydrostatic terms under the same KG assumption.
        bm_ref = float(ixx_ref / max(abs(vol_ref), 1e-12))
        gm_ref = float(kb_ref + bm_ref - kg)

        rows.append(
            {
                "hull_idx": int(idx),
                "Volume_ref": vol_ref,
                "Volume_app": vol_app,
                "Volume_pct_diff": _safe_pct_diff(vol_app, vol_ref),
                "LCB_ref": lcb_ref,
                "LCB_app": lcb_app,
                "LCB_pct_diff": _safe_pct_diff(lcb_app, lcb_ref),
                "KB_ref": kb_ref,
                "KB_app": kb_app,
                "KB_pct_diff": _safe_pct_diff(kb_app, kb_ref),
                "GM_ref_derived": gm_ref,
                "GM_app": gm_app,
                "GM_pct_diff": _safe_pct_diff(gm_app, gm_ref),
            }
        )

    df = pd.DataFrame(rows)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    return df


def _print_summary(df: pd.DataFrame) -> None:
    print("\n=== ShipD Ground-Truth Validation Summary ===")
    print(f"Hull count: {len(df)}")
    metrics = ["Volume_pct_diff", "LCB_pct_diff", "KB_pct_diff", "GM_pct_diff"]
    for metric in metrics:
        vals = pd.to_numeric(df[metric], errors="coerce").dropna()
        if vals.empty:
            print(f"{metric}: no valid values")
            continue
        print(
            f"{metric}: mean={vals.mean():+.3f}% | "
            f"mean_abs={vals.abs().mean():.3f}% | "
            f"max_abs={vals.abs().max():.3f}%"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate Hydrohackathon outputs against ShipD reference hydrostatics.")
    parser.add_argument(
        "--vectors",
        default="../ShipD_repo/InputVectors_30k.npy",
        help="Path to ShipD design vectors .npy file",
    )
    parser.add_argument(
        "--out",
        default="results/shipd_ground_truth_validation.csv",
        help="Path to output CSV report",
    )
    parser.add_argument("--n-hulls", type=int, default=10, help="Number of hulls to compare")
    parser.add_argument("--n-wl-app", type=int, default=60, help="Hydrohackathon waterline count")
    parser.add_argument("--n-sta-app", type=int, default=150, help="Hydrohackathon station count")
    parser.add_argument("--num-wl-ref", type=int, default=101, help="ShipD reference waterline count")
    parser.add_argument("--points-per-wl-ref", type=int, default=400, help="ShipD reference points per waterline")

    args = parser.parse_args()
    report = run_validation(
        vectors_path=Path(args.vectors),
        out_csv=Path(args.out),
        n_hulls=int(args.n_hulls),
        n_wl_app=int(args.n_wl_app),
        n_sta_app=int(args.n_sta_app),
        num_wl_ref=int(args.num_wl_ref),
        points_per_wl_ref=int(args.points_per_wl_ref),
    )
    _print_summary(report)
    print(f"\nWrote detailed report: {Path(args.out)}")
