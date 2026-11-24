#!/usr/bin/env python3
"""Compatibility shim forwarding to skills/ste-clarity/scripts/ste_lint.py.

Keeps repo-root CLI commands (`python3 scripts/ste_lint.py ...`) and Python
imports (`from scripts.ste_lint import lint_file`) working across macOS, Linux,
and Windows without relying on git symlinks.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_TARGET = Path(__file__).resolve().parent.parent / "skills" / "ste-clarity" / "scripts" / "ste_lint.py"
_SPEC = importlib.util.spec_from_file_location("_bundled_ste_lint", _TARGET)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Unable to load bundled STE linter at {_TARGET}")

_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

FileStats = _MODULE.FileStats
Violation = _MODULE.Violation
lint_file = _MODULE.lint_file
main = _MODULE.main

__all__ = ["FileStats", "Violation", "lint_file", "main"]

if __name__ == "__main__":
    sys.exit(main())
