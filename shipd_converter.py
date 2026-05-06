"""Backward-compatible shim for ShipD benchmark conversion helpers.

Prefer importing from shipd_benchmark_converter in benchmark-only code.
"""

from shipd_benchmark_converter import (  # noqa: F401
    DEFAULT_RHO,
    extract_hull_metadata,
    hull_to_offset_table,
    save_benchmark_sample,
    select_diverse_hulls,
)

__all__ = [
    "DEFAULT_RHO",
    "select_diverse_hulls",
    "hull_to_offset_table",
    "extract_hull_metadata",
    "save_benchmark_sample",
]
