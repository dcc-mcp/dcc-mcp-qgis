"""Host-only acceptance complements (never substitutes for) the MCP smoke."""

import hashlib
import importlib.util
import json

import pytest

from dcc_mcp_qgis.paths import QgisError, validate_bundle
from dcc_mcp_qgis.runtime import QgisSession, invoke

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(importlib.util.find_spec("qgis") is None, reason="QGIS not installed"),
]


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    session = QgisSession(tmp_path_factory.mktemp("qgis-live"))
    yield session
    session.close()


@pytest.fixture
def polygon(session):
    session.new_project(discard_changes=True)
    result = session.create_layer(
        "Parcels", "Polygon", fields=[{"name": "name", "type": "string"}, {"name": "value", "type": "integer"}]
    )
    return result["context"]["layer_id"]


def test_invalid_batch_is_atomic(session, polygon):
    response = invoke(
        "add_features",
        layer_id=polygon,
        features=[
            {"wkt": "POLYGON ((0 0,4 0,4 3,0 3,0 0))", "attributes": {"name": "Alpha", "value": 10}},
            {"wkt": "POINT (0 0)", "attributes": {"name": "wrong"}},
        ],
    )
    assert response["error"] == "invalid_geometry"
    assert session.query_features(polygon)["context"]["total"] == 0


@pytest.mark.parametrize("crs", ["EPSG:0", "bad", "https://remote.invalid/crs"])
def test_crs_rejected(session, crs):
    assert invoke("new_project", crs=crs, discard_changes=True)["error"] == "invalid_crs"


def test_dirty_guard_and_not_found(session, polygon):
    assert invoke("new_project")["error"] == "unsaved_changes"
    assert invoke("query_features", layer_id="missing")["error"] == "layer_not_found"
    assert (
        invoke("update_feature", layer_id=polygon, feature_id=900, attributes={"value": 1})["error"]
        == "feature_not_found"
    )


@pytest.mark.parametrize(
    "field",
    [{"name": "fid", "type": "integer"}, {"name": "invalid name", "type": "string"}, {"name": "x", "type": "date"}],
)
def test_field_rejected(session, polygon, field):
    response = invoke("create_layer", name="Invalid", geometry_type="Polygon", fields=[field])
    assert response["success"] is False
    assert session.inspect_project()["context"]["layer_count"] == 1


def test_unsupported_multigeometry(session, polygon):
    assert invoke("create_layer", name="Multi", geometry_type="MultiPolygon")["error"] == "unsupported_geometry"


def test_save_reopen_preserves_styles_and_original_data(session, polygon):
    session.add_features(
        polygon, [{"wkt": "POLYGON ((0 0,4 0,4 3,0 3,0 0))", "attributes": {"name": "Alpha", "value": 10}}]
    )
    session.style_layer(
        polygon, category_field="name", categories=[{"value": "Alpha", "color": "#00aabb"}], label_field="name"
    )
    session.save_project("styled")
    source = session.workspace / "styled/layer_0.gpkg"
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    reopened = session.reopen_project("styled/project.qgz")["context"]["layers"][0]
    assert reopened["renderer"] == "categorizedSymbol" and reopened["labels_enabled"]
    rows = session.query_features(reopened["layer_id"])["context"]["features"]
    session.update_feature(reopened["layer_id"], rows[0]["feature_id"], attributes={"value": 20})
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    assert invoke("save_project", directory="styled")["error"] == "already_exists"
    assert invoke("export_layer", layer_id=reopened["layer_id"], path="../outside.geojson")["error"] == "invalid_path"


def test_tamper_is_detected(session):
    path = session.workspace / "styled/manifest.json"
    manifest = json.loads(path.read_text())
    manifest["files"]["layer_0.gpkg"] = "0" * 64
    path.write_text(json.dumps(manifest))
    with pytest.raises(QgisError, match="manifest"):
        validate_bundle(session.workspace, "styled/project.qgz")


def test_no_arbitrary_project(session):
    path = session.workspace / "fake.qgz"
    path.write_bytes(b"not a project")
    assert invoke("reopen_project", path="fake.qgz", discard_changes=True)["error"] == "unsupported_project"


def test_style_validates_before_mutation(session, polygon):
    assert invoke("style_layer", layer_id=polygon, color="https://invalid")["error"] == "invalid_style"
    assert session.inspect_project()["context"]["layers"][0]["renderer"] == "singleSymbol"


def test_exact_add_readback_failure_is_not_success(session, polygon, monkeypatch):
    layer = session._layer(polygon)
    monkeypatch.setattr(layer, "featureCount", lambda: 5)
    result = invoke("add_features", layer_id=polygon, features=[{"wkt": "POLYGON ((0 0,4 0,4 3,0 3,0 0))"}])
    assert result["success"] is False and result["error"] == "verification_failed"


def test_stale_edit_readback_is_not_success(session, polygon, monkeypatch):
    session.add_features(polygon, [{"wkt": "POLYGON ((0 0,4 0,4 3,0 3,0 0))", "attributes": {"value": 1}}])
    layer = session._layer(polygon)
    before = next(layer.getFeatures())
    monkeypatch.setattr(layer, "getFeature", lambda feature_id: before)
    result = invoke("update_feature", layer_id=polygon, feature_id=before.id(), attributes={"value": 2})
    assert result["success"] is False and result["error"] == "verification_failed"


def test_null_attribute_readback(session, polygon):
    session.add_features(polygon, [{"wkt": "POLYGON ((0 0,4 0,4 3,0 3,0 0))", "attributes": {"value": 1}}])
    row = session.query_features(polygon)["context"]["features"][0]
    result = invoke("update_feature", layer_id=polygon, feature_id=row["feature_id"], attributes={"value": None})
    assert result["success"] is True
    assert result["context"]["feature"]["attributes"]["value"] is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"discard_changes": "yes"},
        {"discard_changes": 1},
        {"discard_changes": []},
    ],
)
def test_discard_requires_actual_boolean(session, polygon, kwargs):
    result = invoke("new_project", **kwargs)
    assert result["error"] == "invalid_input"
    assert session.inspect_project()["context"]["layer_count"] == 1


@pytest.mark.parametrize("feature", [[], None, {"wkt": "POINT (0 0)", "surprise": True}])
def test_nested_feature_objects_are_closed(session, polygon, feature):
    assert invoke("add_features", layer_id=polygon, features=[feature])["error"] == "invalid_input"
    assert session.query_features(polygon)["context"]["total"] == 0


def test_aggregate_input_limit(session, polygon):
    features = [{"wkt": " " * 9999, "attributes": {}}] * 110
    assert invoke("add_features", layer_id=polygon, features=features)["error"] == "limit_exceeded"
    assert session.query_features(polygon)["context"]["total"] == 0


def test_duplicate_style_categories_do_not_mutate(session, polygon):
    result = invoke(
        "style_layer",
        layer_id=polygon,
        category_field="name",
        categories=[{"value": "A", "color": "#ff0000"}, {"value": "A", "color": "#00ff00"}],
    )
    assert result["error"] == "invalid_style"
    assert session._layer(polygon).renderer().type() == "singleSymbol"


def test_cancel_after_native_export_has_no_published_artifact(session, polygon, monkeypatch):
    from dcc_mcp_core.cancellation import CancelToken, DccMcpCancelledError, reset_cancel_token, set_cancel_token

    session.add_features(polygon, [{"wkt": "POLYGON ((0 0,4 0,4 3,0 3,0 0))"}])
    token = CancelToken()
    original = session._write_vector

    def cancelled_writer(*args):
        original(*args)
        token.cancel()

    monkeypatch.setattr(session, "_write_vector", cancelled_writer)
    reset = set_cancel_token(token)
    try:
        with pytest.raises(DccMcpCancelledError):
            session.export_layer(polygon, "cancelled.geojson")
    finally:
        reset_cancel_token(reset)
    assert not (session.workspace / "cancelled.geojson").exists()
    assert not list(session.workspace.glob(".qgis-export-*"))


def test_cancel_before_commit_rolls_back_edit_buffer(session, polygon, monkeypatch):
    from dcc_mcp_core.cancellation import CancelToken, DccMcpCancelledError, reset_cancel_token, set_cancel_token

    layer = session._layer(polygon)
    original = layer.addFeatures
    token = CancelToken()

    def cancel_after_add(features):
        result = original(features)
        token.cancel()
        return result

    monkeypatch.setattr(layer, "addFeatures", cancel_after_add)
    reset = set_cancel_token(token)
    try:
        with pytest.raises(DccMcpCancelledError):
            session.add_features(polygon, [{"wkt": "POLYGON ((0 0,4 0,4 3,0 3,0 0))"}])
    finally:
        reset_cancel_token(reset)
    assert layer.featureCount() == 0
    assert not layer.isEditable()


def test_export_detects_geometry_or_values_changed_by_writer(session, polygon, monkeypatch):
    session.add_features(polygon, [{"wkt": "POLYGON ((0 0,4 0,4 3,0 3,0 0))", "attributes": {"value": 19}}])
    original = session._write_vector

    def corrupt_writer(layer, path, driver):
        from qgis.core import QgsFeatureRequest

        copy = layer.materialize(QgsFeatureRequest())
        row = next(copy.getFeatures())
        copy.dataProvider().changeAttributeValues({row.id(): {copy.fields().indexFromName("value"): 99}})
        return original(copy, path, driver)

    monkeypatch.setattr(session, "_write_vector", corrupt_writer)
    result = invoke("export_layer", layer_id=polygon, path="wrong.geojson")
    assert result["error"] == "verification_failed"
    assert not (session.workspace / "wrong.geojson").exists()


def test_public_runtime_methods_reject_wrong_thread(session):
    import threading

    results = []

    def call():
        try:
            session.status()
        except QgisError as error:
            results.append(error.code)

    thread = threading.Thread(target=call)
    thread.start()
    thread.join(timeout=2)
    assert results == ["wrong_thread"]


def test_no_field_layer_is_valid(session):
    session.new_project(discard_changes=True)
    result = session.create_layer("NoFields", "Point")
    assert result["success"] is True and result["context"]["fields"] == []
    session.add_features(result["context"]["layer_id"], [{"wkt": "POINT (1.125 2.25)"}])


def test_native_round_trip_preserves_all_supported_attribute_types(session):
    session.new_project(discard_changes=True)
    layer_id = session.create_layer(
        "Values",
        "Point",
        fields=[
            {"name": "label", "type": "string"},
            {"name": "count", "type": "integer"},
            {"name": "ratio", "type": "number"},
            {"name": "active", "type": "boolean"},
        ],
    )["context"]["layer_id"]
    attrs = {"label": "Åland α", "count": 2**40, "ratio": 1.125, "active": True}
    session.add_features(layer_id, [{"wkt": "POINT (1.12345678901234 2.98765432109876)", "attributes": attrs}])
    session.export_layer(layer_id, "types.geojson")
    session.save_project("types")
    reopened = session.reopen_project("types/project.qgz")["context"]["layers"][0]
    row = session.query_features(reopened["layer_id"])["context"]["features"][0]
    assert row["attributes"] == attrs


def test_close_is_idempotent_and_closed_session_refuses_work(tmp_path):
    import os
    import subprocess
    import sys

    script = """
from dcc_mcp_qgis.runtime import QgisSession
from dcc_mcp_qgis.paths import QgisError
session = QgisSession(__import__('sys').argv[1])
session.close()
session.close()
try:
    session.status()
except QgisError as error:
    assert error.code == 'session_closed'
else:
    raise AssertionError('closed session accepted work')
"""
    subprocess.run([sys.executable, "-c", script, str(tmp_path)], env=dict(os.environ), check=True, timeout=20)


def test_extreme_coordinates_cannot_overflow_geometry_readback(session):
    session.new_project(discard_changes=True)
    layer_id = session.create_layer("Bounds", "Point")["context"]["layer_id"]
    result = invoke("add_features", layer_id=layer_id, features=[{"wkt": "POINT (1e200 1e200)"}])
    assert result["error"] == "invalid_geometry"
    assert session.query_features(layer_id)["context"]["total"] == 0


def test_endpoint_file_is_not_overwritten_and_failed_start_cleans_up(tmp_path):
    import os
    import subprocess
    import sys

    endpoint = tmp_path / "endpoint.json"
    endpoint.write_text("preserve this file")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "dcc_mcp_qgis.cli",
            "--workspace",
            str(tmp_path / "work"),
            "--endpoint-file",
            str(endpoint),
        ],
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "DCC_MCP_DISABLE_FILE_LOGGING": "1",
            "DCC_MCP_DISABLE_JOB_PERSISTENCE": "1",
            "DCC_MCP_CHECKPOINT_IN_MEMORY": "1",
        },
        capture_output=True,
        timeout=20,
    )
    assert result.returncode != 0
    assert endpoint.read_text() == "preserve this file"


@pytest.mark.parametrize("value", [-35, 0, 17, -0.0, 17.25])
def test_number_fields_normalize_json_integers_and_roundtrip(session, tmp_path, value):
    session.new_project(discard_changes=True)
    layer_id = session.create_layer("Numbers", "Point", fields=[{"name": "elevation", "type": "number"}])["context"][
        "layer_id"
    ]
    result = invoke(
        "add_features", layer_id=layer_id, features=[{"wkt": "POINT (1 2)", "attributes": {"elevation": value}}]
    )
    assert result["success"], result
    rows = session.query_features(layer_id)["context"]["features"]
    assert len(rows) == 1 and rows[0]["attributes"]["elevation"] == float(value)
    assert type(rows[0]["attributes"]["elevation"]) is float
    feature_id = rows[0]["feature_id"]
    updated = invoke("update_feature", layer_id=layer_id, feature_id=feature_id, attributes={"elevation": -35})
    assert updated["success"], updated
    stem = "numeric_" + str(value).replace("-", "minus").replace(".", "_")
    for suffix, driver in [(".geojson", "GeoJSON"), (".gpkg", "GPKG")]:
        exported = invoke("export_layer", layer_id=layer_id, path=stem + suffix, format=driver)
        assert exported["success"], exported


def test_number_field_oversized_integer_is_rejected_before_commit(session):
    session.new_project(discard_changes=True)
    layer_id = session.create_layer("Numbers", "Point", fields=[{"name": "value", "type": "number"}])["context"][
        "layer_id"
    ]
    for value in [2**10000, 2**53, -(2**53)]:
        result = invoke(
            "add_features", layer_id=layer_id, features=[{"wkt": "POINT (0 0)", "attributes": {"value": value}}]
        )
        assert result["error"] == "invalid_attribute", result
        assert session.query_features(layer_id)["context"]["total"] == 0


def test_label_presentation_controls_roundtrip(session, polygon):
    from qgis.PyQt.QtGui import QFontDatabase

    family = sorted(QFontDatabase().families())[0]
    session.add_features(
        polygon, [{"wkt": "POLYGON ((0 0,4 0,4 3,0 3,0 0))", "attributes": {"name": "Label", "value": 5}}]
    )
    styled = invoke(
        "style_layer",
        layer_id=polygon,
        label_field="name",
        font_family=family,
        label_bold=True,
        label_buffer_size=0,
        label_buffer_color="#123456",
    )
    assert styled["success"], styled
    expected = styled["context"]["style"]
    assert expected["labels"]["font_family"] == family
    assert expected["labels"]["bold"] is True
    assert expected["labels"]["buffer_enabled"] is False
    assert expected["labels"]["buffer_size"] == 0
    assert expected["labels"]["buffer_color"] == "#123456"
    saved = session.save_project("label_controls")
    session.reopen_project(saved["context"]["project_path"])
    reopened = session._ordered_layers()[0]
    assert session._style_snapshot(reopened.renderer(), reopened.labeling(), reopened.labelsEnabled()) == expected


@pytest.mark.parametrize(
    "parameters",
    [
        {"label_buffer_size": -1},
        {"label_buffer_size": 2.1},
        {"label_buffer_size": True},
        {"label_buffer_color": "red"},
        {"label_bold": 1},
        {"font_family": "DCC_MCP_FONT_THAT_IS_NOT_INSTALLED"},
    ],
)
def test_invalid_label_controls_do_not_mutate(session, polygon, parameters):
    layer = session._layer(polygon)
    before = session._style_snapshot(layer.renderer(), layer.labeling(), layer.labelsEnabled())
    result = invoke("style_layer", layer_id=polygon, label_field="name", **parameters)
    assert result["error"] == "invalid_style", result
    assert session._style_snapshot(layer.renderer(), layer.labeling(), layer.labelsEnabled()) == before
