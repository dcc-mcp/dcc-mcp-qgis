"""Portable control-flow regressions; geometry doubles do not prove PyQGIS behavior."""

import sys
from types import ModuleType, SimpleNamespace

import pytest

from dcc_mcp_qgis.paths import QgisError
from dcc_mcp_qgis.runtime import QgisSession


@pytest.fixture
def readback(monkeypatch):
    coordinates = []
    for edge in range(4):
        for i in range(150):
            coordinates.append(
                [(0.1 + i / 10, 0.2), (15.1, 0.2 + i / 10), (15.1 - i / 10, 15.2), (0.1, 15.2 - i / 10)][edge]
            )
    coordinates.append(coordinates[0])
    wkt = "POLYGON ((" + ",".join(f"{x:.1f} {y:.1f}" for x, y in coordinates) + "))"
    expanded = "POLYGON ((" + ",".join(f"{x:.17f} {y:.17f}" for x, y in coordinates) + "))"
    calls = []
    geometry = SimpleNamespace(
        isNull=lambda: False,
        isEmpty=lambda: False,
        wkbType=lambda: 3,
        isGeosValid=lambda: True,
        vertices=lambda: [SimpleNamespace(x=lambda x=x: x, y=lambda y=y: y) for x, y in coordinates],
        asWkt=lambda precision: calls.append(("asWkt", precision)) or expanded,
    )

    def from_wkt(text):
        calls.append(("fromWkt", text))
        return geometry

    for name in ("qgis", "qgis.core", "qgis.PyQt", "qgis.PyQt.QtCore"):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    sys.modules["qgis.core"].QgsGeometry = SimpleNamespace(fromWkt=from_wkt)
    sys.modules["qgis.PyQt.QtCore"].QVariant = SimpleNamespace(String=1, Int=2, LongLong=3, Double=4, Bool=5)
    layer = SimpleNamespace(
        isValid=lambda: True,
        featureCount=lambda: 1,
        wkbType=lambda: 3,
        crs=lambda: SimpleNamespace(authid=lambda: "EPSG:3857"),
        fields=lambda: [],
        getFeatures=lambda: [SimpleNamespace(geometry=lambda: geometry)],
    )
    session = object.__new__(QgisSession)
    monkeypatch.setattr(session, "_feature", lambda feature: {"attributes": {}})
    return session, layer, geometry, wkt, expanded, calls


def test_reopened_geometry_avoids_precision_expansion_and_reparse(readback):
    session, layer, geometry, wkt, expanded, calls = readback
    assert len(wkt) < 10000 < len(expanded)
    assert session._geometry(layer, wkt) is geometry
    session._validate_reopened_layer(layer)
    assert calls == [("fromWkt", wkt)]


def test_client_wkt_limit_still_rejects_expanded_text(readback):
    session, layer, _, _, expanded, calls = readback
    with pytest.raises(QgisError, match="1 to 10000"):
        session._geometry(layer, expanded)
    assert calls == []


@pytest.mark.parametrize("failure", ["null", "empty", "type", "geos", "nan", "infinite", "coordinate_bound"])
def test_reopened_geometry_retains_native_safety_checks(readback, failure):
    session, layer, geometry, _, _, _ = readback
    if failure in {"nan", "infinite", "coordinate_bound"}:
        coordinate = {"nan": float("nan"), "infinite": float("inf"), "coordinate_bound": 1e9 + 1}[failure]
        geometry.vertices = lambda: [SimpleNamespace(x=lambda: coordinate, y=lambda: 0)]
    else:
        method, value = {
            "null": ("isNull", True),
            "empty": ("isEmpty", True),
            "type": ("wkbType", 1003),
            "geos": ("isGeosValid", False),
        }[failure]
        setattr(geometry, method, lambda: value)
    with pytest.raises(QgisError) as error:
        session._validate_reopened_layer(layer)
    assert error.value.code == "invalid_geometry"
