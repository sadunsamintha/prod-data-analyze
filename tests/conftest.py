from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "ge-108-data"
FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(SKILL_DIR))


@pytest.fixture(scope="session")
def cli_module():
    spec = importlib.util.spec_from_file_location("date_executor", SKILL_DIR / "date_executor.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES
