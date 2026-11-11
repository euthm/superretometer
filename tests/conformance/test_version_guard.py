"""Version guard in runtime_server rejects stale packages, accepts current version.

The guard reads the package version from pyproject.toml at install time via
importlib.metadata.  A stale older package on PYTHONPATH must not satisfy it.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

root = Path(__file__).resolve().parents[2]


def _package_version() -> str:
    """Read version from pyproject.toml (same source as setuptools)."""
    text = (root / "pyproject.toml").read_text()
    for line in text.splitlines():
        if line.startswith("version"):
            return line.split('"')[1]
    raise ValueError("no version in pyproject.toml")


def _import_runtime() -> object:
    """Import runtime_server without triggering the startup version check."""
    import importlib.util
    import sys
    import types

    adapter = types.ModuleType("memory_adapter")
    adapter.MemoryAdapter = object
    sys.modules["memory_adapter"] = adapter
    path = root / "transports" / "runtime_server.py"
    spec = importlib.util.spec_from_file_location("_runtime_version_fixture", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestVersionGuardAcceptsCurrent:
    """The version from pyproject.toml must pass the floor check."""

    def test_pyproject_version_accepted(self):
        mod = _import_runtime()
        ver = _package_version()
        _v = tuple(int(x) for x in ver.split(".")[:3])
        assert _v >= (0, 8, 0), f"pyproject.toml version {ver} below MIN_CANONICAL"

    def test_startup_accepts_pyproject_version(self):
        """startup() must not raise for the version declared in pyproject.toml."""
        mod = _import_runtime()
        ver = _package_version()
        env = {
            "CH_SESSION_ID": "test",
            "CH_WORKSPACE": "test",
            "CH_PROJECT_ID": "test",
        }
        mock_storage = type("MockStorage", (), {"list_all_kos": lambda s: []})()
        mock_adapter = lambda **kw: mock_storage
        with patch.object(mod, "validate_tool_schemas"), \
             patch.dict("os.environ", env, clear=True), \
             patch("importlib.metadata.version", return_value=ver), \
             patch.object(mod, "MemoryAdapter", mock_adapter):
            # startup() will raise if the version check fails
            try:
                mod.startup()
            except RuntimeError as e:
                if "Refusing to start" in str(e):
                    pytest.fail(f"Version guard rejected pyproject version: {e}")
                raise  # unrelated error


class TestVersionGuardRejectsStale:
    """A stale old version must be rejected."""

    @pytest.mark.parametrize("stale_ver", ["0.6.4", "0.7.0", "0.7.1"])
    def test_stale_rejected(self, stale_ver):
        mod = _import_runtime()
        env = {
            "CH_SESSION_ID": "test",
            "CH_WORKSPACE": "test",
            "CH_PROJECT_ID": "test",
        }
        with patch.object(mod, "validate_tool_schemas"), \
             patch.dict("os.environ", env, clear=True), \
             patch("importlib.metadata.version", return_value=stale_ver):
            with pytest.raises(RuntimeError, match="Refusing to start"):
                mod.startup()
