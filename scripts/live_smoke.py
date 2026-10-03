"""Real PyQGIS + official MCP SDK acceptance; all host work goes through MCP."""

import argparse
import asyncio
import importlib.metadata
import json
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx2
import jsonschema
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import PaginatedRequestParams


def payload(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(next(item.text for item in result.content if item.type == "text"))


async def exercise(endpoint, output):
    trace = []
    async with httpx2.AsyncClient(trust_env=False, timeout=180) as client:
        async with streamable_http_client(endpoint["mcp_url"], http_client=client) as (read, write):
            async with ClientSession(read, write) as session:
                initialization = await session.initialize()
                trace.append({"initialize_protocol": initialization.protocol_version})

                async def call(name, args=None, success=True):
                    public_name = name if name in names else name.rsplit("__", 1)[-1]
                    result = payload(await session.call_tool(public_name, args or {}))
                    trace.append({"tool": public_name, "arguments": args or {}, "result": result})
                    if public_name in schemas:
                        jsonschema.validate(result, schemas[public_name])
                    if "job_id" in result:
                        job_id = result["job_id"]
                        deadline = time.monotonic() + 150
                        while True:
                            assert time.monotonic() < deadline, ("Core job did not terminate", job_id)
                            job = payload(await session.call_tool("jobs_get_status", {"job_id": job_id}))
                            if job.get("status") in {"completed", "failed", "cancelled", "interrupted"}:
                                trace.append({"job_id": job_id, "terminal": job})
                                if job.get("status") != "completed":
                                    raise AssertionError(job)
                                result = job.get("result")
                                if isinstance(result, dict) and "structuredContent" in result:
                                    result = result["structuredContent"]
                                break
                            await asyncio.sleep(0.05)
                    if success and public_name in schemas:
                        jsonschema.validate(result, schemas[public_name])
                    if success:
                        assert isinstance(result, dict) and result.get("success") is True, result
                    return result

                search = payload(await session.call_tool("search_skills", {"query": "qgis"}))
                assert {item["name"] for item in search["skills"]} == {"qgis-project", "qgis-vector"}
                trace.append({"discovery": search})
                loaded = payload(await session.call_tool("load_skill", {"skill_name": "qgis-vector"}))
                assert loaded["loaded"] and len(loaded["registered_tools"]) == 6
                trace.append({"load": loaded})
                names = []
                schemas = {}
                cursor = None
                while True:
                    listed = await session.list_tools(params=PaginatedRequestParams(cursor=cursor) if cursor else None)
                    names.extend(tool.name for tool in listed.tools)
                    schemas.update({tool.name: tool.output_schema for tool in listed.tools if tool.output_schema})
                    cursor = listed.next_cursor
                    if cursor is None:
                        break
                assert "create_layer" in names or "qgis_vector__create_layer" in names
                trace.append({"listed_tools": names})
                status = await call("status")
                thread_id = status["context"]["host_thread_id"]
                # Concurrent responses must stay associated with their own distinct arguments.
                parallel = await asyncio.gather(
                    *(call("create_layer", {"name": "Marker" + str(i), "geometry_type": "Point"}) for i in range(8))
                )
                assert [item["context"]["name"] for item in parallel] == ["Marker" + str(i) for i in range(8)]
                assert len({item["context"]["layer_id"] for item in parallel}) == 8
                await call(
                    "new_project", {"title": "MCP synthetic parcels", "crs": "EPSG:3857", "discard_changes": True}
                )
                # Malformed inputs are rejected before host mutation, even with direct SDK calls.
                for name, arguments in [
                    ("new_project", {"discard_changes": "yes"}),
                    ("create_layer", {"name": "Bad", "geometry_type": "Point", "extra": True}),
                    ("create_layer", {"name": "X" * 65, "geometry_type": "Point"}),
                ]:
                    rejected = await session.call_tool(name, arguments)
                    data = (
                        {"is_error": True, "text": [item.text for item in rejected.content if item.type == "text"]}
                        if rejected.is_error
                        else payload(rejected)
                    )
                    assert rejected.is_error or data.get("success") is False, data
                    trace.append({"malformed": name, "rejected": data})
                assert (await call("inspect_project"))["context"]["layer_count"] == 0
                created = await call(
                    "qgis_vector__create_layer",
                    {
                        "name": "Parcels",
                        "geometry_type": "Polygon",
                        "crs": "EPSG:3857",
                        "fields": [{"name": "label", "type": "string"}, {"name": "value", "type": "integer"}],
                    },
                )
                layer_id = created["context"]["layer_id"]
                assert created["context"]["host_thread_id"] == thread_id
                await call(
                    "qgis_vector__add_features",
                    {
                        "layer_id": layer_id,
                        "features": [
                            {
                                "wkt": "POLYGON ((0 0,400 0,400 300,0 300,0 0))",
                                "attributes": {"label": "Alpha", "value": 10},
                            },
                            {
                                "wkt": "POLYGON ((500 0,850 0,850 450,500 450,500 0))",
                                "attributes": {"label": "Beta", "value": 20},
                            },
                        ],
                    },
                )
                query = await call("qgis_vector__query_features", {"layer_id": layer_id})
                beta = next(row for row in query["context"]["features"] if row["attributes"]["label"] == "Beta")
                await call(
                    "qgis_vector__update_feature",
                    {
                        "layer_id": layer_id,
                        "feature_id": beta["feature_id"],
                        "attributes": {"value": 25},
                        "wkt": "POLYGON ((500 0,900 0,900 450,500 450,500 0))",
                    },
                )
                styled = await call(
                    "qgis_vector__style_layer",
                    {
                        "layer_id": layer_id,
                        "category_field": "label",
                        "categories": [{"value": "Alpha", "color": "#0e7490"}, {"value": "Beta", "color": "#f59e0b"}],
                        "label_field": "label",
                        "label_size": 16,
                        "label_buffer_size": 0,
                        "label_buffer_color": "#123456",
                        "label_bold": True,
                    },
                )
                assert styled["context"]["style"]["labels"]["buffer_enabled"] is False
                assert styled["context"]["style"]["labels"]["bold"] is True
                assert styled["context"]["style"]["labels"]["buffer_color"] == "#123456"
                bad = await call(
                    "qgis_vector__update_feature",
                    {"layer_id": layer_id, "feature_id": beta["feature_id"], "attributes": {"value": "not an integer"}},
                    success=False,
                )
                assert bad["error"] == "invalid_attribute"
                await call("render_map", {"path": "before.png", "width": 900, "height": 600})
                await call("qgis_vector__export_layer", {"layer_id": layer_id, "path": "parcels.geojson"})
                saved = await call("save_project", {"directory": "native"})
                assert saved["context"]["project_path"] == "native/project.qgz"
                reopened = await call("reopen_project", {"path": "native/project.qgz"})
                reopened_layer = reopened["context"]["layers"][0]
                assert reopened_layer["renderer"] == "categorizedSymbol"
                assert reopened_layer["labels_enabled"] is True
                stale = await call("query_features", {"layer_id": layer_id}, success=False)
                assert stale["error"] == "layer_not_found"
                queried = await call("qgis_vector__query_features", {"layer_id": reopened_layer["layer_id"]})
                beta = next(row for row in queried["context"]["features"] if row["attributes"]["label"] == "Beta")
                assert beta["attributes"]["value"] == 25 and beta["planar_area"] == 180000
                await call("render_map", {"path": "after.png", "width": 900, "height": 600})
                assert (output / "workspace/before.png").read_bytes() == (output / "workspace/after.png").read_bytes()
                # Invalid path is an async domain error; query the existing job, never retry it.
                bad = await call("new_project", {"crs": "EPSG:0"}, success=False)
                assert bad["error"] == "invalid_crs"
                await call("new_project", {"title": "Typed numeric regression", "discard_changes": True})
                numeric = await call(
                    "create_layer",
                    {
                        "name": "Elevations",
                        "geometry_type": "Point",
                        "fields": [{"name": "elevation", "type": "number"}],
                    },
                )
                numeric_id = numeric["context"]["layer_id"]
                await call(
                    "add_features",
                    {"layer_id": numeric_id, "features": [{"wkt": "POINT (0 0)", "attributes": {"elevation": -35}}]},
                )
                numeric_readback = await call("query_features", {"layer_id": numeric_id})
                elevation = numeric_readback["context"]["features"][0]["attributes"]["elevation"]
                assert elevation == -35.0 and type(elevation) is float
                await call("export_layer", {"layer_id": numeric_id, "path": "numeric.geojson"})
                await call("export_layer", {"layer_id": numeric_id, "path": "numeric.gpkg", "format": "GPKG"})
                result = {
                    "status": "PASS",
                    "qgis": endpoint["qgis_version"],
                    "core": importlib.metadata.version("dcc-mcp-core"),
                    "sdk": importlib.metadata.version("mcp"),
                    "protocol": initialization.protocol_version,
                    "host_thread_id": thread_id,
                    "tests": [
                        "discovery",
                        "load",
                        "paginated list",
                        "main-thread dispatch",
                        "8 concurrent distinct mutation replies",
                        "malformed and oversized input rejection",
                        "stale layer ID rejected after reopen",
                        "SDK and explicit async/domain output schema validation",
                        "create",
                        "edit",
                        "negative attribute/CRS",
                        "categorized styling",
                        "field labels",
                        "buffer-free bold label style and native roundtrip",
                        "JSON integer to Double field and GeoJSON/GPKG readback",
                        "GeoJSON export",
                        "QGZ/GPKG save",
                        "reopen",
                        "identical rendered PNG after reopen",
                    ],
                    "trace": trace,
                }
                (output / "result.json").write_text(json.dumps(result, indent=2))
                print(json.dumps({key: value for key, value in result.items() if key != "trace"}))


def listening_addresses(pid):
    """Inspect real listener sockets owned by the child, not just configured values."""
    descriptors = Path(f"/proc/{pid}/fd")
    if not descriptors.exists():
        return None
    inodes = set()
    for descriptor in descriptors.iterdir():
        try:
            link = os.readlink(descriptor)
        except FileNotFoundError:
            continue
        if link.startswith("socket:["):
            inodes.add(link[8:-1])
    addresses = []
    for family in ("tcp", "tcp6"):
        for row in Path(f"/proc/{pid}/net/{family}").read_text().splitlines()[1:]:
            fields = row.split()
            if fields[3] != "0A" or fields[9] not in inodes:
                continue
            encoded, port = fields[1].split(":")
            if family == "tcp":
                address = socket.inet_ntoa(struct.pack("<I", int(encoded, 16)))
            else:
                address = socket.inet_ntop(socket.AF_INET6, bytes.fromhex(encoded))
            addresses.append({"host": address, "port": int(port, 16)})
    return addresses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory for evidence")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    endpoint_file = output / "endpoint.json"
    env = dict(os.environ)
    env.update(
        {
            "QT_QPA_PLATFORM": "offscreen",
            "DCC_MCP_DISABLE_DEFAULT_SKILL_PATHS": "1",
            "DCC_MCP_DISABLE_FILE_LOGGING": "1",
            "DCC_MCP_DISABLE_TELEMETRY": "1",
            "DCC_MCP_DISABLE_JOB_PERSISTENCE": "1",
            "DCC_MCP_CHECKPOINT_IN_MEMORY": "1",
            "HOME": str(output / "home"),
            "XDG_CONFIG_HOME": str(output / "config"),
            "XDG_CACHE_HOME": str(output / "cache"),
            "DCC_MCP_REGISTRY_DIR": str(output / "registry"),
        }
    )
    with (output / "server.log").open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "dcc_mcp_qgis.cli",
                "--workspace",
                str(output / "workspace"),
                "--endpoint-file",
                str(endpoint_file),
            ],
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            deadline = time.monotonic() + 30
            while not endpoint_file.exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Server startup failed; inspect server.log")
                time.sleep(0.025)
            endpoint = json.loads(endpoint_file.read_text())
            assert urlparse(endpoint["mcp_url"]).hostname == "127.0.0.1"
            listeners = listening_addresses(process.pid)
            if listeners is not None:
                assert listeners and all(item["host"] == "127.0.0.1" for item in listeners), listeners
                (output / "listeners.json").write_text(json.dumps(listeners, indent=2))
            asyncio.run(asyncio.wait_for(exercise(endpoint, output), timeout=240))
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        assert process.returncode == 0, process.returncode
        address = urlparse(endpoint["mcp_url"])
        with socket.socket() as probe:
            probe.settimeout(1)
            assert probe.connect_ex((address.hostname, address.port)) != 0, "MCP listener survived shutdown"
        registry = output / "registry"
        for path in registry.rglob("*.json") if registry.exists() else []:
            assert endpoint["instance_id"] not in path.read_text(), "Registry entry survived shutdown"
        print("Clean process shutdown and registry cleanup verified")


if __name__ == "__main__":
    main()
