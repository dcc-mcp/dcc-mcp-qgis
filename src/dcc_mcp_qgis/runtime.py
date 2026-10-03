"""An isolated, owned PyQGIS project. All host calls are process-main-only."""

import json
import math
import re
import shutil
import tempfile
import threading
from functools import wraps
from pathlib import Path

from dcc_mcp_core.cancellation import DccMcpCancelledError
from dcc_mcp_core.skills_helper import check_dcc_cancelled, skill_error, skill_success

from .compatibility import SUPPORTED_PROFILE, check_profile
from .paths import QgisError, digest, publish_directory, publish_file, validate_bundle, within

CAPABILITIES = {
    "mode": "owned_headless",
    "supported_profile": SUPPORTED_PROFILE,
    "geometry_types": ["Point", "LineString", "Polygon"],
    "field_types": ["string", "integer", "number", "boolean"],
    "exports": ["GPKG", "GeoJSON", "PNG"],
    "limits": {
        "layers": 32,
        "features_per_layer": 10000,
        "features_per_call": 1000,
        "query_limit": 100,
        "request_bytes": 1048576,
        "coordinate_abs": 1000000000,
    },
    "unsupported": [
        "GUI attachment",
        "external projects",
        "network layers",
        "raster",
        "processing algorithms",
        "raw code",
    ],
}


def assert_main():
    if threading.current_thread() is not threading.main_thread():
        raise QgisError("wrong_thread", "PyQGIS APIs require the process main thread")


def owned_operation(function):
    """Guard public Python and skill entry points independently of HTTP schemas."""

    @wraps(function)
    def guarded(self, *args, **kwargs):
        self.assert_owner()
        if self.closed:
            raise QgisError("session_closed", "Start a new process after closing a QGIS session")
        try:
            encoded = json.dumps([args, kwargs], allow_nan=False).encode("utf-8")
        except (ValueError, TypeError) as error:
            raise QgisError("invalid_input", "Arguments must be finite JSON values") from error
        if len(encoded) > 1024 * 1024:
            raise QgisError("limit_exceeded", "Operation arguments exceed the 1 MiB aggregate limit")
        check_dcc_cancelled()
        return function(self, *args, **kwargs)

    return guarded


def current():
    assert_main()
    from qgis.core import QgsApplication

    app = QgsApplication.instance()
    session = getattr(app, "dcc_mcp_qgis_session", None)
    if session is None or session.closed:
        raise QgisError("not_ready", "Start the owned QGIS runtime first")
    return session


def invoke(operation, **kwargs):
    try:
        session = current()
        check_dcc_cancelled()
        if operation not in {
            "status",
            "inspect_project",
            "new_project",
            "create_layer",
            "query_features",
            "add_features",
            "update_feature",
            "style_layer",
            "save_project",
            "reopen_project",
            "export_layer",
            "render_map",
        }:
            raise QgisError("unknown_operation", "Only declared typed operations are supported")
        result = getattr(session, operation)(**kwargs)
        result.setdefault("context", {})["host_thread_id"] = threading.get_ident()
        return result
    except DccMcpCancelledError:
        raise
    except QgisError as exc:
        return skill_error(str(exc), exc.code)
    except (ValueError, TypeError, KeyError) as exc:
        return skill_error(str(exc), "invalid_input")
    except Exception as exc:
        return skill_error(
            "QGIS operation failed", "host_error", _meta={"dcc.error": {"type": type(exc).__name__, "detail": str(exc)}}
        )


class QgisSession:
    def __init__(self, workspace):
        assert_main()
        self.owner = threading.get_ident()
        from qgis.core import Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsProject
        from qgis.PyQt.QtCore import QT_VERSION_STR

        self.detected_profile = check_profile(Qgis.QGIS_VERSION_INT, QT_VERSION_STR)

        if QgsApplication.instance() is not None:
            raise QgisError(
                "existing_application", "Use a separate process; attaching to an existing Qt/QGIS app is unsupported"
            )
        if Path(workspace).is_symlink():
            raise QgisError("invalid_path", "Workspace must not be a symlink")
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.app = QgsApplication([], False)
        self.app.initQgis()
        self.app.dcc_mcp_qgis_session = self
        self.version = Qgis.QGIS_VERSION
        self.project = QgsProject()
        self.project.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
        self.project.setTitle("Untitled")
        self.dirty = False
        self.closed = False

    def assert_owner(self):
        assert_main()
        if threading.get_ident() != self.owner:
            raise QgisError("wrong_thread", "PyQGIS APIs require the owned session thread")

    def close(self):
        self.assert_owner()
        if self.closed:
            return
        self.closed = True
        try:
            self.project.clear()
        finally:
            self.project = None
            self.app.dcc_mcp_qgis_session = None
            self.app.exitQgis()

    @owned_operation
    def status(self):
        return skill_success(
            "QGIS runtime ready",
            version=self.version,
            mode="owned_headless",
            dirty=self.dirty,
            capabilities=CAPABILITIES,
            detected_profile=self.detected_profile,
        )

    @owned_operation
    def inspect_project(self, limit=25):
        self._integer(limit, 1, 100)
        layers = [self._layer_info(layer) for layer in self.project.mapLayers().values()]
        return skill_success(
            "Project inspected",
            title=self.project.title(),
            crs=self.project.crs().authid(),
            dirty=self.dirty,
            layer_count=len(layers),
            layers=layers[:limit],
            truncated=len(layers) > limit,
        )

    @staticmethod
    def _integer(value, low, high):
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise QgisError("invalid_input", "Integer is outside the supported range")

    @staticmethod
    def _name(value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", value):
            raise QgisError(
                "invalid_input", "Names must start with a letter and contain at most 64 letters, digits or underscores"
            )
        return value

    @staticmethod
    def _crs(value):
        from qgis.core import QgsCoordinateReferenceSystem

        if not isinstance(value, str) or not re.fullmatch(r"EPSG:[0-9]{1,6}", value):
            raise QgisError("invalid_crs", "Use an EPSG authority code")
        crs = QgsCoordinateReferenceSystem(value)
        if not crs.isValid():
            raise QgisError("invalid_crs", "Unknown EPSG code")
        return crs

    @owned_operation
    def new_project(self, title="Untitled", crs="EPSG:3857", discard_changes=False):
        if type(discard_changes) is not bool:
            raise QgisError("invalid_input", "discard_changes must be a boolean")
        if self.dirty and not discard_changes:
            raise QgisError("unsaved_changes", "Save first or explicitly discard changes")
        if not isinstance(title, str) or not 1 <= len(title) <= 128:
            raise QgisError("invalid_input", "Project title must be 1 to 128 characters")
        target_crs = self._crs(crs)
        check_dcc_cancelled()
        self.project.clear()
        self.project.setTitle(title)
        self.project.setCrs(target_crs)
        self.dirty = True
        return skill_success(
            "Project created",
            verified=True,
            postcondition={"method": "project_readback", "actual": self.project.title()},
            title=title,
            crs=target_crs.authid(),
        )

    def _layer(self, layer_id):
        if not isinstance(layer_id, str) or not 1 <= len(layer_id) <= 128:
            raise QgisError("invalid_input", "A bounded layer ID is required")
        layer = self.project.mapLayer(layer_id)
        if layer is None:
            raise QgisError("layer_not_found", "Layer ID was not found in the owned project")
        return layer

    @staticmethod
    def _layer_info(layer):
        return {
            "layer_id": layer.id(),
            "name": layer.name(),
            "feature_count": layer.featureCount(),
            "crs": layer.crs().authid(),
            "geometry_type": int(layer.wkbType()),
            "renderer": layer.renderer().type(),
            "labels_enabled": layer.labelsEnabled(),
            "fields": [{"name": f.name(), "type": f.typeName()} for f in layer.fields()],
        }

    @owned_operation
    def create_layer(self, name, geometry_type, crs="EPSG:3857", fields=None):
        from qgis.core import QgsField, QgsVectorLayer
        from qgis.PyQt.QtCore import QVariant

        self._name(name)
        if len(self.project.mapLayers()) >= 32:
            raise QgisError("limit_exceeded", "At most 32 layers are supported")
        if geometry_type not in CAPABILITIES["geometry_types"]:
            raise QgisError("unsupported_geometry", "Only 2D Point, LineString and Polygon are supported")
        authority = self._crs(crs).authid()
        types = {
            "string": QVariant.String,
            "integer": QVariant.LongLong,
            "number": QVariant.Double,
            "boolean": QVariant.Bool,
        }
        fields = [] if fields is None else fields
        if not isinstance(fields, list) or len(fields) > 32:
            raise QgisError("invalid_input", "At most 32 fields are supported")
        names = set()
        schema = []
        for field in fields:
            if not isinstance(field, dict) or set(field) != {"name", "type"}:
                raise QgisError("invalid_input", "Fields require name and type only")
            if not isinstance(field["type"], str):
                raise QgisError("invalid_input", "Field type must be a string")
            name_value = self._name(field["name"])
            if name_value.lower() == "fid" or name_value.lower() in names or field["type"] not in types:
                raise QgisError("invalid_input", "Duplicate, reserved fid, or unsupported field")
            names.add(name_value.lower())
            schema.append(QgsField(name_value, types[field["type"]]))
        layer = QgsVectorLayer(f"{geometry_type}?crs={authority}", name, "memory")
        if not layer.isValid() or (schema and not layer.dataProvider().addAttributes(schema)):
            raise QgisError("host_error", "Could not create vector layer")
        layer.updateFields()
        check_dcc_cancelled()
        self.project.addMapLayer(layer)
        self.dirty = True
        return skill_success(
            "Vector layer created",
            verified=True,
            postcondition={"method": "layer_readback", "actual": layer.isValid()},
            **self._layer_info(layer),
        )

    @staticmethod
    def _geometry(layer, wkt):
        from qgis.core import QgsGeometry

        if not isinstance(wkt, str) or not 1 <= len(wkt) <= 10000:
            raise QgisError("invalid_geometry", "WKT must be 1 to 10000 characters")
        geometry = QgsGeometry.fromWkt(wkt)
        if (
            geometry.isNull()
            or geometry.isEmpty()
            or geometry.wkbType() != layer.wkbType()
            or not geometry.isGeosValid()
        ):
            raise QgisError(
                "invalid_geometry", "WKT must be valid, nonempty and match the layer's exact 2D geometry type"
            )
        for vertex in geometry.vertices():
            if any(not math.isfinite(value) or abs(value) > 1e9 for value in (vertex.x(), vertex.y())):
                raise QgisError("invalid_geometry", "Coordinates must be finite and within ±1e9 CRS units")
        return geometry

    @staticmethod
    def _attributes(layer, attributes):
        from qgis.PyQt.QtCore import QVariant

        if not isinstance(attributes, dict) or len(attributes) > 32:
            raise QgisError("invalid_input", "Attributes must be an object with at most 32 fields")
        result = {}
        for name, value in attributes.items():
            if not isinstance(name, str):
                raise QgisError("invalid_field", "Field names must be strings")
            index = layer.fields().indexFromName(name)
            if index < 0 or name.lower() == "fid":
                raise QgisError("invalid_field", "Unknown or reserved field")
            field = layer.fields().at(index)
            if value is not None:
                expected = field.type()
                valid = (
                    (expected == QVariant.String and isinstance(value, str) and len(value) <= 1024)
                    or (
                        expected in {QVariant.Int, QVariant.LongLong}
                        and type(value) is int
                        and -(2**53) < value < 2**53
                    )
                    or (
                        expected == QVariant.Double
                        and (
                            (type(value) is int and -(2**53) < value < 2**53)
                            or (type(value) is float and math.isfinite(value))
                        )
                    )
                    or (expected == QVariant.Bool and type(value) is bool)
                )
                if not valid:
                    raise QgisError("invalid_attribute", "Attribute does not match its field type or bounds")
                if expected == QVariant.Double:
                    # JSON integers are valid numbers; normalize before native commit
                    # so their Double readback is not a false postcondition failure.
                    value = float(value)
            result[index] = value
        return result

    @staticmethod
    def _feature(feature):
        from qgis.core import QgsVariantUtils

        attrs = {
            field.name(): (None if QgsVariantUtils.isNull(feature[index]) else feature[index])
            for index, field in enumerate(feature.fields())
        }
        geometry = feature.geometry()
        return {
            "feature_id": feature.id(),
            "attributes": attrs,
            "wkt": geometry.asWkt(8),
            "planar_area": geometry.area(),
        }

    @owned_operation
    def query_features(self, layer_id, limit=25, offset=0):
        from qgis.core import QgsFeatureRequest

        self._integer(limit, 1, 100)
        self._integer(offset, 0, 10000)
        layer = self._layer(layer_id)
        request = QgsFeatureRequest().setLimit(offset + limit)
        rows = [self._feature(feature) for index, feature in enumerate(layer.getFeatures(request)) if index >= offset]
        return skill_success(
            "Features queried", layer_id=layer_id, features=rows, total=layer.featureCount(), offset=offset
        )

    @owned_operation
    def add_features(self, layer_id, features):
        from qgis.core import QgsFeature

        layer = self._layer(layer_id)
        if (
            not isinstance(features, list)
            or not 1 <= len(features) <= 1000
            or layer.featureCount() + len(features) > 10000
        ):
            raise QgisError(
                "limit_exceeded", "Batch must contain 1 to 1000 features and layer total must not exceed 10000"
            )
        before_count = layer.featureCount()
        before_rows = [self._feature_signature(feature) for feature in layer.getFeatures()]
        prepared = []
        for item in features:
            check_dcc_cancelled()
            if not isinstance(item, dict) or "wkt" not in item or set(item) - {"wkt", "attributes"}:
                raise QgisError("invalid_input", "Each feature requires WKT and optional attributes only")
            feature = QgsFeature(layer.fields())
            feature.setGeometry(self._geometry(layer, item["wkt"]))
            for index, value in self._attributes(layer, item.get("attributes", {})).items():
                feature.setAttribute(index, value)
            prepared.append(feature)
        check_dcc_cancelled()
        if not layer.startEditing():
            raise QgisError("host_error", "Could not start layer edit")
        try:
            ok = layer.addFeatures(prepared)
            check_dcc_cancelled()
            if not ok or not layer.commitChanges():
                raise QgisError("host_error", "Failed to commit feature batch")
        except BaseException:
            layer.rollBack()
            raise
        layer.updateExtents()
        self.dirty = True
        # Temporary edit-buffer IDs change on commit. Verify count and query persisted IDs.
        actual = layer.featureCount()
        expected_rows = sorted(before_rows + [self._feature_signature(feature) for feature in prepared])
        actual_rows = sorted(self._feature_signature(feature) for feature in layer.getFeatures())
        if actual != before_count + len(prepared) or actual_rows != expected_rows:
            raise QgisError(
                "verification_failed", "Committed feature count, geometry or attributes differ from the requested batch"
            )
        return skill_success(
            "Features added",
            verified=actual == before_count + len(prepared),
            postcondition={"method": "feature_count_geometry_attribute_readback", "actual": actual},
            layer_id=layer_id,
            added=len(prepared),
            feature_count=actual,
        )

    @owned_operation
    def update_feature(self, layer_id, feature_id, attributes=None, wkt=None):
        self._integer(feature_id, 0, 2**53 - 1)
        layer = self._layer(layer_id)
        feature = layer.getFeature(feature_id)
        if not feature.isValid():
            raise QgisError("feature_not_found", "Feature ID was not found")
        if attributes is None and wkt is None:
            raise QgisError("invalid_input", "Supply attributes or WKT")
        values = self._attributes(layer, {} if attributes is None else attributes)
        geometry = self._geometry(layer, wkt) if wkt is not None else None
        check_dcc_cancelled()
        if not layer.startEditing():
            raise QgisError("host_error", "Could not start layer edit")
        try:
            for index, value in values.items():
                if not layer.changeAttributeValue(feature_id, index, value):
                    raise QgisError("host_error", "Attribute update failed")
            if geometry is not None and not layer.changeGeometry(feature_id, geometry):
                raise QgisError("host_error", "Geometry update failed")
            check_dcc_cancelled()
            if not layer.commitChanges():
                raise QgisError("host_error", "Feature commit failed")
        except BaseException:
            layer.rollBack()
            raise
        layer.updateExtents()
        self.dirty = True
        actual = layer.getFeature(feature_id)
        actual_view = self._feature(actual)
        verified = all(
            actual_view["attributes"][layer.fields().at(index).name()] == value for index, value in values.items()
        ) and (geometry is None or actual.geometry().equals(geometry))
        if not verified:
            raise QgisError("verification_failed", "Feature readback differs from the requested edit")
        return skill_success(
            "Feature updated",
            verified=verified,
            postcondition={"method": "feature_readback"},
            feature=actual_view,
        )

    @owned_operation
    def style_layer(
        self,
        layer_id,
        color="#38bdf8",
        outline_color="#0f172a",
        opacity=1.0,
        width=0.5,
        size=3.0,
        category_field=None,
        categories=None,
        label_field=None,
        label_size=10,
        label_color="#0f172a",
        label_buffer_size=0.7,
        label_buffer_color="#ffffff",
        font_family=None,
        label_bold=False,
    ):
        from qgis.core import (
            QgsCategorizedSymbolRenderer,
            QgsPalLayerSettings,
            QgsRendererCategory,
            QgsSingleSymbolRenderer,
            QgsSymbol,
            QgsTextBufferSettings,
            QgsTextFormat,
            QgsVectorLayerSimpleLabeling,
        )
        from qgis.PyQt.QtGui import QColor, QFontDatabase

        layer = self._layer(layer_id)
        if type(label_bold) is not bool:
            raise QgisError("invalid_style", "label_bold must be a boolean")
        if font_family is not None and (
            not isinstance(font_family, str)
            or not 1 <= len(font_family) <= 80
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in font_family)
            or font_family not in QFontDatabase().families()
        ):
            raise QgisError("invalid_style", "font_family must name an installed local font family")
        for value in (color, outline_color, label_color, label_buffer_color):
            if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                raise QgisError("invalid_style", "Colors must be six-digit hex RGB")
        for value, lower, upper in (
            (opacity, 0, 1),
            (width, 0.1, 5),
            (size, 0.5, 20),
            (label_size, 6, 32),
            (label_buffer_size, 0, 2),
        ):
            if type(value) not in {int, float} or not math.isfinite(value) or not lower <= value <= upper:
                raise QgisError("invalid_style", "Style size, width, opacity or label size is out of bounds")
        categories = [] if categories is None else categories
        if not isinstance(categories, list) or len(categories) > 32:
            raise QgisError("invalid_style", "At most 32 categories are supported")
        if category_field is not None and (not isinstance(category_field, str) or len(category_field) > 64):
            raise QgisError("invalid_field", "Category field must be a bounded string")
        if label_field is not None and (not isinstance(label_field, str) or len(label_field) > 64):
            raise QgisError("invalid_field", "Label field must be a bounded string")
        if categories and (category_field is None or layer.fields().indexFromName(category_field) < 0):
            raise QgisError("invalid_field", "Categorized style needs an existing field")
        if label_field is not None and layer.fields().indexFromName(label_field) < 0:
            raise QgisError("invalid_field", "Label field was not found")

        def symbol(fill):
            item = QgsSymbol.defaultSymbol(layer.geometryType())
            item.setColor(QColor(fill))
            item.setOpacity(float(opacity))
            if hasattr(item, "setWidth"):
                item.setWidth(float(width))
            if hasattr(item, "setSize"):
                item.setSize(float(size))
            part = item.symbolLayer(0)
            if hasattr(part, "setStrokeColor"):
                part.setStrokeColor(QColor(outline_color))
            if hasattr(part, "setStrokeWidth"):
                part.setStrokeWidth(float(width))
            return item

        renderer_categories = []
        category_values = set()
        for item in categories:
            if not isinstance(item, dict):
                raise QgisError("invalid_style", "Each category must be an object")
            if set(item) != {"value", "color"} or not isinstance(item["value"], str) or len(item["value"]) > 128:
                raise QgisError("invalid_style", "Each category requires a bounded string value and color")
            if not isinstance(item["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", item["color"]):
                raise QgisError("invalid_style", "Category colors must be six-digit hex RGB")
            if item["value"] in category_values:
                raise QgisError("invalid_style", "Category values must be unique")
            category_values.add(item["value"])
            renderer_categories.append(QgsRendererCategory(item["value"], symbol(item["color"]), item["value"]))
        if renderer_categories:
            renderer_categories.append(QgsRendererCategory(None, symbol(color), "Other"))
            renderer = QgsCategorizedSymbolRenderer(category_field, renderer_categories)
        else:
            renderer = QgsSingleSymbolRenderer(symbol(color))
        labeling = None
        if label_field is not None:
            labels = QgsPalLayerSettings()
            labels.fieldName = label_field
            labels.isExpression = False
            text = QgsTextFormat()
            font = text.font()
            if font_family is not None:
                font.setFamily(font_family)
            font.setBold(label_bold)
            text.setFont(font)
            text.setSize(float(label_size))
            text.setColor(QColor(label_color))
            buffer = QgsTextBufferSettings()
            buffer.setEnabled(label_buffer_size > 0)
            buffer.setSize(float(label_buffer_size))
            buffer.setColor(QColor(label_buffer_color))
            text.setBuffer(buffer)
            labels.setFormat(text)
            labeling = QgsVectorLayerSimpleLabeling(labels)
        expected_style = self._style_snapshot(renderer, labeling, label_field is not None)
        check_dcc_cancelled()
        layer.setRenderer(renderer)
        if labeling is not None:
            layer.setLabeling(labeling)
        layer.setLabelsEnabled(label_field is not None)
        actual_style = self._style_snapshot(layer.renderer(), layer.labeling(), layer.labelsEnabled())
        self.dirty = True
        if expected_style != actual_style:
            raise QgisError("verification_failed", "Renderer or label readback differs")
        return skill_success(
            "Layer styled",
            verified=True,
            postcondition={"method": "renderer_and_label_readback", "actual": layer.renderer().type()},
            layer_id=layer_id,
            renderer=layer.renderer().type(),
            labels_enabled=layer.labelsEnabled(),
            style=actual_style,
        )

    @staticmethod
    def _style_snapshot(renderer, labeling, enabled):
        from qgis.core import QgsRenderContext

        symbols = renderer.symbols(QgsRenderContext())
        value = {
            "renderer": renderer.type(),
            "symbols": [
                {
                    "color": symbol.color().name(),
                    "opacity": symbol.opacity(),
                    "layers": [symbol.symbolLayer(i).properties() for i in range(symbol.symbolLayerCount())],
                }
                for symbol in symbols
            ],
            "labels_enabled": enabled,
        }
        if renderer.type() == "categorizedSymbol":
            value["category_field"] = renderer.classAttribute()
            value["categories"] = [category.value() for category in renderer.categories()]
        if enabled:
            settings = labeling.settings()
            # Keep SIP-owned parents alive while reading their nested value objects.
            text_format = settings.format()
            text_buffer = text_format.buffer()
            text_font = text_format.font()
            value["labels"] = {
                "field": settings.fieldName,
                "size": text_format.size(),
                "color": text_format.color().name(),
                "expression": settings.isExpression,
                "font_family": text_font.family(),
                "bold": text_font.bold(),
                "buffer_enabled": text_buffer.enabled(),
                "buffer_size": text_buffer.size(),
                "buffer_color": text_buffer.color().name(),
            }
        return value

    @staticmethod
    def _copy_style(source, target):
        if source.renderer() is not None:
            target.setRenderer(source.renderer().clone())
        if source.labeling() is not None:
            target.setLabeling(source.labeling().clone())
        target.setLabelsEnabled(source.labelsEnabled())

    def _ordered_layers(self):
        return self.project.layerTreeRoot().layerOrder()

    def _validate_reopened_layer(self, layer):
        from qgis.PyQt.QtCore import QVariant

        types = {QVariant.String, QVariant.Int, QVariant.LongLong, QVariant.Double, QVariant.Bool}
        if (
            not layer.isValid()
            or layer.featureCount() > 10000
            or int(layer.wkbType()) not in {1, 2, 3}
            or not layer.crs().authid().startswith("EPSG:")
            or len([field for field in layer.fields() if field.name() != "fid"]) > 32
            or any(field.type() not in types for field in layer.fields())
        ):
            raise QgisError("unsupported_project", "Reopened layer is outside supported geometry, CRS or field limits")
        for feature in layer.getFeatures():
            check_dcc_cancelled()
            self._geometry(layer, feature.geometry().asWkt(17))
            attrs = self._feature(feature)["attributes"]
            attrs.pop("fid", None)
            self._attributes(layer, attrs)

    @classmethod
    def _feature_signature(cls, feature, skip_fid=False):
        attrs = cls._feature(feature)["attributes"]
        if skip_fid:
            attrs.pop("fid", None)
        # GeoJSON has no separate integer/Double field schema. Compare numeric
        # values canonically while preserving the distinction from booleans/nulls.
        attrs = {
            name: (0.0 if value == 0 else float(value)) if type(value) in {int, float} else value
            for name, value in attrs.items()
        }
        return bytes(feature.geometry().asWkb()).hex(), json.dumps(attrs, sort_keys=True)

    def _verify_layer(self, expected, actual, skip_fid=False):
        """Read geometry and all user values, not merely feature counts."""
        if not actual.isValid() or actual.featureCount() != expected.featureCount():
            raise QgisError("verification_failed", "Layer feature count readback differs")
        if actual.crs() != expected.crs() or actual.wkbType() != expected.wkbType():
            raise QgisError("verification_failed", "Layer CRS or geometry type readback differs")

        def rows(layer):
            result = []
            for feature in layer.getFeatures():
                check_dcc_cancelled()
                # WKB retains native coordinate precision; source feature IDs can change on export.
                result.append(self._feature_signature(feature, skip_fid=skip_fid))
            return sorted(result)

        if rows(expected) != rows(actual):
            raise QgisError("verification_failed", "Layer geometry or attribute readback differs")

    def _write_vector(self, layer, path, driver):
        from qgis.core import QgsVectorFileWriter

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = driver
        options.layerName = "features"
        options.fileEncoding = "UTF-8"
        if driver == "GeoJSON":
            options.layerOptions = ["COORDINATE_PRECISION=17"]
        result = QgsVectorFileWriter.writeAsVectorFormatV3(layer, str(path), self.project.transformContext(), options)
        if result[0] != QgsVectorFileWriter.NoError:
            raise QgisError("export_failed", "QGIS vector writer failed: " + str(result[1]))

    @owned_operation
    def save_project(self, directory):
        from qgis.core import QgsMapSettings, QgsProject, QgsReferencedRectangle, QgsVectorLayer

        target = within(self.workspace, directory)
        if target == self.workspace or target.exists():
            raise QgisError("already_exists", "Choose a new bundle directory; existing paths are never overwritten")
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".qgis-bundle-", dir=target.parent))
        saved = QgsProject()
        try:
            saved.setTitle(self.project.title())
            saved.setCrs(self.project.crs())
            for index, layer in enumerate(reversed(self._ordered_layers())):
                check_dcc_cancelled()
                path = staging / f"layer_{index}.gpkg"
                self._write_vector(layer, path, "GPKG")
                persisted = QgsVectorLayer(str(path), layer.name(), "ogr")
                if not persisted.isValid() or persisted.featureCount() != layer.featureCount():
                    raise QgisError("verification_failed", "GeoPackage readback did not match feature count")
                self._verify_layer(layer, persisted, skip_fid=True)
                self._copy_style(layer, persisted)
                saved.addMapLayer(persisted)
            if saved.mapLayers():
                settings = QgsMapSettings()
                settings.setLayers(saved.layerTreeRoot().layerOrder())
                settings.setDestinationCrs(saved.crs())
                extent = settings.fullExtent()
                if extent.width() == 0 or extent.height() == 0:
                    extent.grow(1)
                extent.scale(1.1)
                saved.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(extent, saved.crs()))
            project_path = staging / "project.qgz"
            if not saved.write(str(project_path)):
                raise QgisError("save_failed", "QGIS did not write the project")
            saved.clear()
            files = {path.name: digest(path) for path in staging.iterdir() if path.suffix in {".qgz", ".gpkg"}}
            (staging / "manifest.json").write_text(
                json.dumps({"format": "dcc-mcp-qgis-bundle-v1", "files": files}, indent=2)
            )
            validate_bundle(self.workspace, str(project_path.relative_to(self.workspace)))
            check_dcc_cancelled()
            publish_directory(staging, target)
            self.dirty = False
            return skill_success(
                "Project bundle saved",
                verified=True,
                postcondition={"method": "gpkg_readback_and_file_hashes"},
                project_path=str((target / "project.qgz").relative_to(self.workspace)),
                files=files,
            )
        finally:
            saved.clear()
            if staging.exists():
                shutil.rmtree(staging)

    @owned_operation
    def reopen_project(self, path, discard_changes=False):
        from qgis.core import QgsProject

        if type(discard_changes) is not bool:
            raise QgisError("invalid_input", "discard_changes must be a boolean")
        if self.dirty and not discard_changes:
            raise QgisError("unsaved_changes", "Save first or explicitly discard changes")
        target = validate_bundle(self.workspace, path)
        candidate = QgsProject()
        try:
            if not candidate.read(str(target)) or any(not layer.isValid() for layer in candidate.mapLayers().values()):
                raise QgisError("invalid_bundle", "Project or layer readback failed")
            # Detach persisted data into owned memory so future edits never alter saved artifacts.
            layers = list(reversed(candidate.layerTreeRoot().layerOrder()))
            from qgis.core import QgsFeatureRequest

            copies = []
            for layer in layers:
                check_dcc_cancelled()
                self._validate_reopened_layer(layer)
                copy = layer.materialize(QgsFeatureRequest())
                self._verify_layer(layer, copy, skip_fid=True)
                copies.append(copy)
            for source, copy in zip(layers, copies, strict=True):
                self._copy_style(source, copy)
                fid = copy.fields().indexFromName("fid")
                if fid >= 0:
                    copy.dataProvider().deleteAttributes([fid])
                    copy.updateFields()
            for layer in copies:
                if not layer.isValid() or layer.featureCount() > 10000:
                    raise QgisError("limit_exceeded", "Reopened layer is invalid or exceeds the feature limit")
            check_dcc_cancelled()
            self.project.clear()
            self.project.setTitle(candidate.title())
            self.project.setCrs(candidate.crs())
            for layer in copies:
                layer.setName(layer.name())
                self.project.addMapLayer(layer)
            self.dirty = False
            return skill_success(
                "Project reopened into owned memory",
                verified=True,
                postcondition={"method": "project_and_layer_readback"},
                layers=[self._layer_info(layer) for layer in self.project.mapLayers().values()],
            )
        finally:
            candidate.clear()

    @owned_operation
    def export_layer(self, layer_id, path, format="GeoJSON"):
        from qgis.core import QgsVectorLayer

        layer = self._layer(layer_id)
        if format not in {"GeoJSON", "GPKG"}:
            raise QgisError("unsupported_format", "Use GeoJSON or GPKG")
        suffix = ".geojson" if format == "GeoJSON" else ".gpkg"
        target = within(self.workspace, path, {suffix})
        if target.exists():
            raise QgisError("already_exists", "Choose a new output path")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".qgis-export-", dir=target.parent) as directory:
            staged = Path(directory) / ("export" + suffix)
            self._write_vector(layer, staged, format)
            verification = QgsVectorLayer(str(staged), "verification", "ogr")
            count = verification.featureCount() if verification.isValid() else -1
            self._verify_layer(layer, verification, skip_fid=True)
            del verification
            if count != layer.featureCount():
                raise QgisError("verification_failed", "Export feature count did not match")
            sha256 = digest(staged)
            check_dcc_cancelled()
            publish_file(staged, target)
        return skill_success(
            "Layer exported",
            verified=True,
            postcondition={"method": "export_reopen", "actual": count},
            path=path,
            sha256=sha256,
            bytes=target.stat().st_size,
        )

    @owned_operation
    def render_map(self, path, width=800, height=600):
        from qgis.core import QgsMapRendererSequentialJob, QgsMapSettings, QgsRectangle
        from qgis.PyQt.QtCore import QSize
        from qgis.PyQt.QtGui import QColor

        self._integer(width, 64, 2048)
        self._integer(height, 64, 2048)
        layers = self._ordered_layers()
        if not layers or not any(layer.featureCount() for layer in layers):
            raise QgisError("empty_project", "Add features before rendering")
        target = within(self.workspace, path, {".png"})
        if target.exists():
            raise QgisError("already_exists", "Choose a new output path")
        target.parent.mkdir(parents=True, exist_ok=True)
        settings = QgsMapSettings()
        settings.setLayers(layers)
        settings.setDestinationCrs(self.project.crs())
        settings.setOutputSize(QSize(width, height))
        extent = QgsRectangle(settings.fullExtent())
        if extent.width() == 0 or extent.height() == 0:
            extent.grow(1)
        extent.scale(1.1)
        settings.setExtent(extent)
        settings.setBackgroundColor(QColor("#ffffff"))
        job = QgsMapRendererSequentialJob(settings)
        check_dcc_cancelled()
        job.start()
        try:
            job.waitForFinished()
            check_dcc_cancelled()
        except BaseException:
            job.cancel()
            raise
        image = job.renderedImage()
        if image.isNull() or job.errors():
            raise QgisError("render_failed", "QGIS rendering failed")
        with tempfile.TemporaryDirectory(prefix=".qgis-render-", dir=target.parent) as directory:
            staged = Path(directory) / "map.png"
            if not image.save(str(staged), "PNG"):
                raise QgisError("render_failed", "PNG write failed")
            check_dcc_cancelled()
            publish_file(staged, target)
        return skill_success(
            "Map rendered",
            verified=True,
            postcondition={"method": "qimage_dimensions", "actual": [image.width(), image.height()]},
            path=path,
            width=width,
            height=height,
            sha256=digest(target),
        )
