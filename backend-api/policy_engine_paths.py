"""
Import shim: `policy-engine/` and `usecase-demo/` have hyphens in their names (fine for
folders, not valid Python package names), so we load their modules by file path instead
of a normal `import`. Everyone in backend-api should get at them via this module:

    from policy_engine_paths import policy_engine, escalation, usecase_demo
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


policy_engine = _load("policy_engine", ROOT / "policy-engine" / "engine.py")
escalation = _load("escalation", ROOT / "policy-engine" / "escalation.py")
usecase_demo = _load("usecase_demo", ROOT / "usecase-demo" / "seed_data.py")
