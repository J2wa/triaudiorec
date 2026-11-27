"""Tests for the package entry point and PyInstaller script compatibility."""

from __future__ import annotations

import ast
import runpy
from pathlib import Path

MAIN_FILE = Path(__file__).resolve().parents[1] / "src" / "tritrack" / "__main__.py"


def test_main_uses_only_absolute_imports() -> None:
    """PyInstaller executes __main__.py as a top-level script with no parent package."""
    tree = ast.parse(MAIN_FILE.read_text(encoding="utf-8"), filename=str(MAIN_FILE))
    relative_imports = [
        (node.lineno, node.module, node.level)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level > 0
    ]
    assert relative_imports == [], f"Relative imports break PyInstaller: {relative_imports}"


def test_main_runs_as_standalone_script() -> None:
    """Running __main__.py directly (without a parent package) must succeed."""
    namespace = runpy.run_path(str(MAIN_FILE), run_name="tritrack_standalone_check")
    args = namespace["parse_args"](["--demo"])
    assert args.demo is True
