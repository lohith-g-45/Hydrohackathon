"""Import boundary tests to protect workbook offset-data workflow from benchmark-only code."""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_MODULES = {"shipd_converter", "shipd_benchmark_converter"}


def _imported_modules(py_path: Path) -> set[str]:
    tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
    mods: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])

    return mods


def test_core_app_modules_do_not_import_shipd_benchmark_code() -> None:
    app_modules = [
        PROJECT_ROOT / "interactive_ui.py",
        PROJECT_ROOT / "main.py",
        PROJECT_ROOT / "ship_excel_extractor.py",
        PROJECT_ROOT / "integration.py",
        PROJECT_ROOT / "hydrostatics.py",
        PROJECT_ROOT / "stability.py",
    ]

    for module_path in app_modules:
        imports = _imported_modules(module_path)
        overlap = imports.intersection(BENCHMARK_MODULES)
        assert not overlap, f"{module_path.name} imports benchmark-only modules: {sorted(overlap)}"


def test_benchmark_tools_use_benchmark_converter_module() -> None:
    benchmark_modules = [
        PROJECT_ROOT / "run_benchmark.py",
        PROJECT_ROOT / "validate_against_shipd_ground_truth.py",
    ]

    for module_path in benchmark_modules:
        imports = _imported_modules(module_path)
        assert "shipd_benchmark_converter" in imports, (
            f"{module_path.name} should import shipd_benchmark_converter"
        )
