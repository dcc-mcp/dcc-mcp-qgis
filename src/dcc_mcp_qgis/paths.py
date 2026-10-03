"""Workspace confinement and publication for local GIS artifacts."""

import ctypes
import errno
import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PureWindowsPath


class QgisError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def within(root, relative, suffixes=None, exists=False):
    if not isinstance(relative, str) or not relative or len(relative) > 1024 or "\x00" in relative:
        raise QgisError("invalid_path", "A bounded workspace-relative path is required")
    path = Path(relative)
    windows_path = PureWindowsPath(relative)
    if path.anchor or windows_path.anchor or ".." in path.parts or ".." in windows_path.parts:
        raise QgisError("invalid_path", "Anchored paths and parent traversal are unsupported")
    root = Path(root).resolve()
    result = root / path
    cursor = result
    while cursor != root:
        if cursor.is_symlink():
            raise QgisError("invalid_path", "Symlink paths are unsupported")
        parent = cursor.parent
        if parent == cursor:
            raise QgisError("invalid_path", "Path is outside the workspace")
        cursor = parent
    if not result.resolve().is_relative_to(root):
        raise QgisError("invalid_path", "Path is outside the workspace")
    if suffixes and result.suffix.lower() not in suffixes:
        raise QgisError("invalid_path", "Unsupported file extension")
    if exists and not result.is_file():
        raise QgisError("not_found", "Input file does not exist")
    return result


def digest(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else _hash(stream)


def _hash(stream):
    value = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        value.update(chunk)
    return value.hexdigest()


def publish_file(staged, target):
    # Exclusive hardlink publication never overwrites an existing user artifact.
    try:
        os.link(staged, target)
    except FileExistsError as exc:
        raise QgisError("already_exists", "Output already exists; choose a new path") from exc
    staged.unlink()


def publish_directory(staged, target):
    """Linux atomic no-replace rename; fail closed without kernel support."""
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise QgisError("already_exists", "Output directory already exists; choose a new path")
    if sys.platform != "linux":
        raise QgisError("publication_unavailable", "Atomic directory publication requires Linux renameat2")
    rename = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if rename is None:
        raise QgisError("publication_unavailable", "Atomic directory publication requires Linux renameat2")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(staged), -100, os.fsencode(target), 1) != 0:
        error = ctypes.get_errno()
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise QgisError("already_exists", "Output directory already exists; choose a new path")
        raise QgisError("publication_failed", "Atomic bundle publication failed")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise QgisError("invalid_bundle", "Duplicate manifest keys are unsupported")
        result[key] = value
    return result


def validate_bundle(root, relative):
    """Validate bounded data before either the ZIP parser or native QGIS parser."""
    root = Path(root).resolve()
    project_path = within(root, relative, {".qgz"}, exists=True)
    manifest_path = project_path.parent / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 65536:
        raise QgisError("unsupported_project", "Reopen requires an adapter-created bundle manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        if not isinstance(manifest, dict) or set(manifest) != {"format", "files"}:
            raise QgisError("invalid_bundle", "Bundle manifest must contain format and files only")
        files = manifest["files"]
        if manifest["format"] != "dcc-mcp-qgis-bundle-v1" or not isinstance(files, dict) or not 1 <= len(files) <= 33:
            raise QgisError("unsupported_project", "Unsupported project bundle")
        if project_path.name not in files or sum(name.endswith(".qgz") for name in files) != 1:
            raise QgisError("invalid_bundle", "Bundle must contain exactly its requested project")
        total = 0
        for name, expected in files.items():
            if (
                Path(name).name != name
                or Path(name).suffix not in {".qgz", ".gpkg"}
                or not isinstance(expected, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected) is None
            ):
                raise QgisError("invalid_bundle", "Bundle requires local filenames and SHA-256 digests")
            source = within(root, str(project_path.parent.relative_to(root) / name), exists=True)
            size = source.stat().st_size
            total += size
            if size > 100_000_000 or total > 128 * 1024 * 1024 or digest(source) != expected:
                raise QgisError("invalid_bundle", "Bundle content does not match its bounded manifest")
        with zipfile.ZipFile(project_path) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if (
                len(entries) > 4
                or len(set(names)) != len(names)
                or any(Path(name).name != name or "\\" in name for name in names)
                or sum(entry.file_size for entry in entries) > 16 * 1024 * 1024
                or any(entry.flag_bits & 1 for entry in entries)
            ):
                raise QgisError("invalid_bundle", "Unsafe or oversized project archive")
            qgs = [entry for entry in entries if entry.filename.endswith(".qgs")]
            if len(qgs) != 1 or qgs[0].file_size > 5_000_000:
                raise QgisError("invalid_bundle", "Project XML is missing or too large")
            xml = archive.read(qgs[0])
        if (
            b"<!ENTITY" in xml.upper()
            or b"<!DOCTYPE" in xml.replace(b"<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>", b"").upper()
        ):
            raise QgisError("invalid_bundle", "Unsupported XML declaration")
        document = ET.fromstring(xml)
        if document.tag != "qgis":
            raise QgisError("invalid_bundle", "Project XML root must be qgis")
        if document.findtext("./properties/Macros/pythonCode", "").strip():
            raise QgisError("unsupported_project", "Project macros are unsupported")
        layers = document.findall("./projectlayers/maplayer")
        if len(layers) > 32:
            raise QgisError("limit_exceeded", "Bundle exceeds the 32 layer limit")
        for layer in layers:
            source = layer.findtext("datasource", "")
            filename = source.split("|", 1)[0]
            if layer.findtext("provider") != "ogr" or "|" in source:
                raise QgisError("unsupported_project", "Only bundle-local GeoPackage layers are supported")
            path = (project_path.parent / filename).resolve()
            if path.parent != project_path.parent or path.name not in files or path.suffix != ".gpkg":
                raise QgisError("unsupported_project", "External project data sources are unsupported")
        return project_path
    except (ValueError, TypeError, AttributeError, KeyError, OSError, zipfile.BadZipFile, ET.ParseError) as error:
        if isinstance(error, QgisError):
            raise
        raise QgisError("invalid_bundle", "Bundle manifest or project archive is malformed") from error
