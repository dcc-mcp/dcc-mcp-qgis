"""Explicit acceptance profile; inspecting it never imports the native host."""

import platform
import sys
from importlib.metadata import version

from .paths import QgisError

SUPPORTED_PROFILE = {
    "platform": "Linux",
    "qgis": "3.40.x",
    "qt": "5.x",
    "python": ">=3.10,<3.14",
    "core": "0.20.41",
    "server": "0.20.41",
    "validated_qgis": "3.40.6-Bratislava",
    "native_acceptance_profile": {"core": "0.20.39", "server": "0.20.39"},
    "current_runtime_native_verified": False,
}


def check_profile(qgis_version_int, qt_version, *, system=None, python=None, core=None, server=None):
    """Reject unvalidated API families before allocating a QgsApplication."""
    detected = {
        "platform": system or platform.system(),
        "qgis_version_int": qgis_version_int,
        "qt": qt_version,
        "python": list(python or sys.version_info[:3]),
        "core": core or version("dcc-mcp-core"),
        "server": server or version("dcc-mcp-server"),
    }
    if (
        detected["platform"] != "Linux"
        or type(qgis_version_int) is not int
        or not 34000 <= qgis_version_int < 34100
        or not isinstance(qt_version, str)
        or not qt_version.startswith("5.")
        or not (3, 10) <= tuple(detected["python"][:2]) < (3, 14)
        or detected["core"] != SUPPORTED_PROFILE["core"]
        or detected["server"] != SUPPORTED_PROFILE["server"]
    ):
        raise QgisError("unsupported_runtime", "Runtime is outside the documented Linux QGIS 3.40 / Qt5 profile")
    return detected
