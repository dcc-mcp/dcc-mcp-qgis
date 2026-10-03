import importlib.util
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml
from dcc_mcp_core import HostExecutionBridge

import dcc_mcp_qgis
from dcc_mcp_qgis.dispatcher import QgisDispatcher
from dcc_mcp_qgis.paths import QgisError, publish_file, within
from dcc_mcp_qgis.runtime import invoke

SKILLS = Path(dcc_mcp_qgis.__file__).parent / "skills"


def test_lazy_package_import():
    command = "import sys; import dcc_mcp_qgis.server; assert 'qgis.core' not in sys.modules"
    subprocess.run([sys.executable, "-c", command], check=True)


def test_skill_manifests_and_canonical_shapes():
    from dcc_mcp_core import validate_skill

    for directory in SKILLS.iterdir():
        validation = validate_skill(str(directory))
        assert not validation.has_errors, validation.issues
        assert validation.is_clean, validation.issues
        manifest = yaml.safe_load((directory / "tools.yaml").read_text())
        for tool in manifest["tools"]:
            assert tool["input_schema"]["additionalProperties"] is False
            assert set(tool["annotations"]) >= {
                "read_only_hint",
                "destructive_hint",
                "idempotent_hint",
                "open_world_hint",
            }
            assert tool["affinity"] == ("any" if tool["name"] == "get_capabilities" else "main")
            assert (directory / tool["source_file"]).is_file()
            assert tool["enforce_thread_affinity"] is True


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/tmp/escape",
        "a/../../escape",
        "",
        "\\escape",
        "C:escape",
        "C:\\escape",
        "\\\\server\\share\\escape",
        "//server/share/escape",
        "folder\\..\\escape",
    ],
)
def test_path_escape_refused(tmp_path, path):
    with pytest.raises(QgisError):
        within(tmp_path, path)


def test_symlink_refused(tmp_path):
    try:
        (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
    except OSError as exc:
        if sys.platform == "win32" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink creation privilege is unavailable; symlink rejection was not tested")
        raise
    with pytest.raises(QgisError):
        within(tmp_path, "link/a")


def test_publication_does_not_overwrite(tmp_path):
    staged, target = tmp_path / "stage", tmp_path / "existing"
    staged.write_text("new")
    target.write_text("old")
    with pytest.raises(QgisError, match="exists"):
        publish_file(staged, target)
    assert target.read_text() == "old"


def test_main_dispatch_really_runs_on_owner():
    dispatcher = QgisDispatcher()
    bridge = HostExecutionBridge(dispatcher=dispatcher)
    bridge.resolve_host_dispatcher()
    values = []
    worker = threading.Thread(
        target=lambda: values.append(bridge.dispatch_callable(threading.get_ident, thread_affinity="main"))
    )
    worker.start()
    deadline = time.monotonic() + 5
    while worker.is_alive() and time.monotonic() < deadline:
        dispatcher.drain_queue()
        time.sleep(0.001)
    worker.join(timeout=1)
    assert values == [threading.get_ident()]
    dispatcher.shutdown()


def test_wrong_thread_fails_before_host_import():
    results = []
    worker = threading.Thread(target=lambda: results.append(invoke("status")))
    worker.start()
    worker.join()
    assert results[0]["success"] is False
    assert results[0]["error"] == "wrong_thread"


def test_queue_timeout_and_shutdown_are_canonical():
    dispatcher = QgisDispatcher()
    result = dispatcher.dispatch_callable(lambda: 1, timeout_hint_secs=0.001)
    assert result["success"] is False
    assert isinstance(result["error"], str)
    dispatcher.shutdown()
    result = dispatcher.dispatch_callable(lambda: 1)
    assert result["success"] is False


def test_queue_cancellation_skips_mutation():
    dispatcher = QgisDispatcher()
    mutated = []
    results = []
    worker = threading.Thread(
        target=lambda: results.append(dispatcher.submit_callable("cancel-me", lambda: mutated.append(1)))
    )
    worker.start()
    deadline = time.monotonic() + 2
    while not dispatcher.has_pending() and time.monotonic() < deadline:
        time.sleep(0.001)
    assert dispatcher.cancel("cancel-me")
    dispatcher.drain_queue()
    worker.join(timeout=2)
    assert not mutated
    assert results[0]["success"] is False


def test_capability_tool_needs_no_qgis():
    source = SKILLS / "qgis-project/scripts/get_capabilities.py"
    spec = importlib.util.spec_from_file_location("qgis_caps", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.main()
    assert result["success"] is True
    assert result["context"]["mode"] == "owned_headless"
    profile = result["context"]["supported_profile"]
    assert profile["core"] == profile["server"] == "0.20.41"
    assert profile["native_acceptance_profile"] == {"core": "0.20.39", "server": "0.20.39"}
    assert profile["validated_qgis"] == "3.40.6-Bratislava"
    assert profile["current_runtime_native_verified"] is False

    import jsonschema

    manifest = yaml.safe_load((source.parent.parent / "tools.yaml").read_text())
    descriptor = next(tool for tool in manifest["tools"] if tool["name"] == "get_capabilities")
    jsonschema.validate(result, descriptor["output_schema"])


def test_any_affinity_does_not_block_host_queue():
    dispatcher = QgisDispatcher()
    bridge = HostExecutionBridge(dispatcher=dispatcher)
    results = []
    worker = threading.Thread(
        target=lambda: results.append(bridge.dispatch_callable(threading.get_ident, thread_affinity="any"))
    )
    worker.start()
    worker.join(timeout=2)
    assert len(results) == 1 and results[0] != threading.get_ident()
    assert not dispatcher.has_pending()
    dispatcher.shutdown()


@pytest.mark.parametrize("relative", ["a\x00b", "x" * 1025])
def test_malformed_path_is_canonical(tmp_path, relative):
    with pytest.raises(QgisError, match="bounded"):
        within(tmp_path, relative)


@pytest.mark.parametrize("system", ["linux", "win32", "darwin"])
def test_directory_publication_preserves_concurrent_empty_target(tmp_path, monkeypatch, system):
    from dcc_mcp_qgis import paths

    monkeypatch.setattr(paths.sys, "platform", system)

    def refuse_native_load(*args, **kwargs):
        pytest.fail("An existing output must be rejected before loading a native library")

    monkeypatch.setattr(paths.ctypes, "CDLL", refuse_native_load)

    staged, target = tmp_path / "stage", tmp_path / "target"
    staged.mkdir()
    (staged / "artifact").write_text("new")
    target.mkdir()
    with pytest.raises(QgisError, match="exists") as error:
        paths.publish_directory(staged, target)
    assert error.value.code == "already_exists"
    assert list(target.iterdir()) == []
    assert (staged / "artifact").read_text() == "new"


@pytest.mark.parametrize("system", ["win32", "darwin", "freebsd14"])
def test_directory_publication_fails_closed_without_linux(tmp_path, monkeypatch, system):
    from dcc_mcp_qgis import paths

    monkeypatch.setattr(paths.sys, "platform", system)

    def refuse_native_load(*args, **kwargs):
        pytest.fail("Unsupported platforms must not load the Linux native library")

    monkeypatch.setattr(paths.ctypes, "CDLL", refuse_native_load)
    staged, target = tmp_path / "stage", tmp_path / "target"
    staged.mkdir()
    (staged / "artifact").write_text("new")
    with pytest.raises(QgisError) as error:
        paths.publish_directory(staged, target)
    assert error.value.code == "publication_unavailable"
    assert not target.exists()
    assert list(staged.iterdir()) == [staged / "artifact"]
    assert (staged / "artifact").read_text() == "new"


@pytest.mark.parametrize(
    "manifest",
    [
        "[]",
        "null",
        '{"format":"x","files":[]}',
        '{"format":"x","files":1}',
        '{"format":"x","files":{},"unexpected":1}',
        '{"files":{},"files":{}}',
    ],
)
def test_malformed_manifests_are_canonical(tmp_path, manifest):
    from dcc_mcp_qgis.paths import validate_bundle

    (tmp_path / "project.qgz").write_bytes(b"invalid")
    (tmp_path / "manifest.json").write_text(manifest)
    with pytest.raises(QgisError):
        validate_bundle(tmp_path, "project.qgz")


def test_archive_path_traversal_refused_before_native_parser(tmp_path):
    import json
    import zipfile

    from dcc_mcp_qgis.paths import digest, validate_bundle

    target = tmp_path / "project.qgz"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("../project.qgs", "<qgis/>")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"format": "dcc-mcp-qgis-bundle-v1", "files": {target.name: digest(target)}})
    )
    with pytest.raises(QgisError, match="archive"):
        validate_bundle(tmp_path, "project.qgz")


@pytest.mark.parametrize("override", [{"qgis_version_int": 34099}, {}])
def test_supported_runtime_profile(override):
    from dcc_mcp_qgis.compatibility import check_profile

    values = dict(
        qgis_version_int=34006,
        qt_version="5.15.15",
        system="Linux",
        python=(3, 13, 5),
        core="0.20.41",
        server="0.20.41",
    )
    values.update(override)
    assert check_profile(**values)["platform"] == "Linux"


@pytest.mark.parametrize(
    "override",
    [
        {"qgis_version_int": 33800},
        {"qgis_version_int": 40000},
        {"qt_version": "6.8.0"},
        {"python": (3, 14, 0)},
        {"core": "0.20.39"},
        {"core": "0.20.40"},
        {"server": "0.20.39"},
        {"server": "0.20.38"},
        {"system": "Windows"},
    ],
)
def test_unsupported_runtime_refused(override):
    from dcc_mcp_qgis.compatibility import check_profile

    values = dict(
        qgis_version_int=34006,
        qt_version="5.15.15",
        system="Linux",
        python=(3, 13, 5),
        core="0.20.41",
        server="0.20.41",
    )
    values.update(override)
    with pytest.raises(QgisError, match="Runtime"):
        check_profile(**values)


def test_timed_out_queue_does_not_mutate_when_pumped_later():
    dispatcher = QgisDispatcher()
    effects = []
    result = dispatcher.dispatch_callable(lambda: effects.append("late"), timeout_hint_secs=0.005)
    assert result["success"] is False
    dispatcher.drain_queue()
    assert effects == []
    dispatcher.shutdown()


def test_concurrent_queue_results_keep_request_identity():
    dispatcher = QgisDispatcher()
    results = {}
    workers = [
        threading.Thread(
            target=lambda i=i: results.setdefault(
                i, dispatcher.submit_callable(str(i), lambda: {"marker": i, "thread": threading.get_ident()})
            )
        )
        for i in range(12)
    ]
    for worker in workers:
        worker.start()
    deadline = time.monotonic() + 5
    while any(worker.is_alive() for worker in workers) and time.monotonic() < deadline:
        dispatcher.drain_queue()
        time.sleep(0.001)
    for worker in workers:
        worker.join(timeout=1)
    assert len(results) == 12
    for i, result in results.items():
        assert result["success"] and result["output"] == {"marker": i, "thread": threading.get_ident()}
    dispatcher.shutdown()


def test_async_output_schema_rejects_missing_domain_and_job_identity():
    import jsonschema

    for path in SKILLS.glob("*/tools.yaml"):
        for tool in yaml.safe_load(path.read_text())["tools"]:
            if tool["execution"] != "async":
                continue
            schema = tool["output_schema"]
            for invalid in ({}, {"job_id": "orphan"}, {"success": True}):
                with pytest.raises(jsonschema.ValidationError):
                    jsonschema.validate(invalid, schema)
            jsonschema.validate({"success": True, "message": "ok", "error": None, "context": {}}, schema)
            jsonschema.validate(
                {"job_id": "job", "core_job_id": "job", "job_id_owner": "core", "status": "pending", "core_poll": {}},
                schema,
            )


def test_loopback_profile_cannot_enable_gateway():
    from dcc_mcp_qgis.server import QgisMcpServer

    for kwargs in ({"gateway_port": 8080}, {"enable_gateway_failover": True}):
        with pytest.raises(ValueError, match="gateway"):
            QgisMcpServer(object(), **kwargs)
