import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DCC_MCP_DISABLE_DEFAULT_SKILL_PATHS", "1")


def pytest_sessionstart(session):
    """A native acceptance run must fail rather than report green with skipped hosts."""
    if os.environ.get("DCC_MCP_QGIS_REQUIRE_NATIVE") == "1":
        import importlib.util

        import pytest

        if importlib.util.find_spec("qgis") is None:
            pytest.exit("Native QGIS acceptance required, but PyQGIS is unavailable", returncode=2)
