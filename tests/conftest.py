"""Shared fixtures for the top-level test suite.

services/core-api and services/mock-commerce-api both expose a top-level
``app`` package. pytest's shared ``pythonpath`` setting can only bind one of
them to the ``app`` name per process, so ``commerce_app`` loads
mock-commerce-api's ``app`` package on demand and restores whatever was
previously bound afterwards, keeping tests order-independent regardless of
which other test files ran first in the same session.
"""

import importlib
import sys
from pathlib import Path

import pytest

COMMERCE_ROOT = Path(__file__).resolve().parents[1] / "services" / "mock-commerce-api"


@pytest.fixture
def commerce_app(tmp_path, monkeypatch):
    monkeypatch.setenv("COMMERCE_DB_PATH", str(tmp_path / "commerce.db"))
    saved_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "app" or name.startswith("app.")
    }
    for name in saved_modules:
        del sys.modules[name]
    monkeypatch.syspath_prepend(str(COMMERCE_ROOT))
    try:
        db = importlib.import_module("app.db")
        main = importlib.import_module("app.main")
        analytics = importlib.import_module("app.analytics")
        db.initialize_database()
        yield db, main, analytics
    finally:
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        sys.modules.update(saved_modules)
