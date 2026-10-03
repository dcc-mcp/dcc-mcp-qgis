"""Core HTTP cancellation reaching a real staged native QGIS export.

A test-only writer hook pauses after real QGIS writing. It does not introduce a
product tool, fake the native data, or claim that native C++ calls are preempted.
"""

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import time

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(importlib.util.find_spec("qgis") is None, reason="QGIS not installed"),
]


SERVER = """
import json, signal, sys, time
from pathlib import Path
from dcc_mcp_qgis.runtime import QgisSession
from dcc_mcp_qgis.server import QgisMcpServer
root = Path(sys.argv[1])
session = QgisSession(root / 'workspace')
original = session._write_vector
def controlled_writer(*args):
    original(*args)
    (root / 'staged').write_text('real native write completed')
    deadline = time.monotonic() + 10
    while not (root / 'release').exists() and time.monotonic() < deadline:
        time.sleep(0.01)
session._write_vector = controlled_writer
server = QgisMcpServer(session, enable_file_logging=False, enable_job_persistence=False,
                       enable_telemetry=False, enable_checkpoint_persistence=False)
running = True
def stop(*args):
    global running
    running = False
signal.signal(signal.SIGTERM, stop)
try:
    server.start()
    (root / 'endpoint').write_text(server.mcp_url)
    while running:
        server.pump()
        time.sleep(0.002)
finally:
    try:
        server.stop()
    finally:
        session.close()
"""


def test_core_http_cancel_blocks_final_native_file_publication(tmp_path):
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.types import PaginatedRequestParams

    def payload(result):
        if result.structured_content is not None:
            return result.structured_content
        return json.loads(next(item.text for item in result.content if item.type == "text"))

    script = tmp_path / "owned_server.py"
    script.write_text(SERVER)
    with (tmp_path / "server.log").open("w") as log:
        process = subprocess.Popen(
            [sys.executable, str(script), str(tmp_path)],
            stdout=log,
            stderr=log,
            env={
                **os.environ,
                "HOME": str(tmp_path / "home"),
                "DCC_MCP_DISABLE_TELEMETRY": "1",
                "DCC_MCP_CHECKPOINT_IN_MEMORY": "1",
            },
        )
        try:
            deadline = time.monotonic() + 15
            while not (tmp_path / "endpoint").exists():
                assert process.poll() is None, (tmp_path / "server.log").read_text()
                assert time.monotonic() < deadline
                time.sleep(0.02)
            endpoint = (tmp_path / "endpoint").read_text()

            async def workflow():
                async with httpx2.AsyncClient(trust_env=False, timeout=20) as http:
                    async with streamable_http_client(endpoint, http_client=http) as (read, write):
                        async with ClientSession(read, write) as client:
                            await client.initialize()
                            assert payload(await client.call_tool("load_skill", {"skill_name": "qgis-vector"}))[
                                "loaded"
                            ]
                            cursor = None
                            while True:
                                listed = await client.list_tools(
                                    params=PaginatedRequestParams(cursor=cursor) if cursor else None
                                )
                                cursor = listed.next_cursor
                                if cursor is None:
                                    break
                            made = payload(
                                await client.call_tool("create_layer", {"name": "CancelTest", "geometry_type": "Point"})
                            )
                            layer_id = made["context"]["layer_id"]
                            addition = payload(
                                await client.call_tool(
                                    "add_features", {"layer_id": layer_id, "features": [{"wkt": "POINT (1 2)"}]}
                                )
                            )
                            deadline = time.monotonic() + 10
                            while True:
                                added = payload(
                                    await client.call_tool("jobs_get_status", {"job_id": addition["job_id"]})
                                )
                                if added["status"] == "completed":
                                    assert added["result"]["success"]
                                    break
                                assert time.monotonic() < deadline, added
                                await asyncio.sleep(0.02)
                            launch = payload(
                                await client.call_tool(
                                    "export_layer", {"layer_id": layer_id, "path": "cancelled.geojson"}
                                )
                            )
                            job_id = launch["job_id"]
                            while not (tmp_path / "staged").exists():
                                assert time.monotonic() < deadline
                                await asyncio.sleep(0.02)
                            cancelled = await http.delete(endpoint.rsplit("/mcp", 1)[0] + "/v1/jobs/" + job_id)
                            assert cancelled.is_success, cancelled.text
                            (tmp_path / "release").write_text("continue to cancellation checkpoint")
                            while True:
                                state = payload(await client.call_tool("jobs_get_status", {"job_id": job_id}))
                                assert state["job_id"] == job_id
                                if state["status"] in {"cancelled", "interrupted"}:
                                    break
                                assert time.monotonic() < deadline, state
                                await asyncio.sleep(0.02)
                            # A later main-affinity query establishes that the prior callback exited,
                            # not merely that Core recorded terminal cancellation in another thread.
                            inspected = payload(await client.call_tool("query_features", {"layer_id": layer_id}))
                            assert inspected["success"] and inspected["context"]["total"] == 1
                            assert not (tmp_path / "workspace/cancelled.geojson").exists()
                            assert not list((tmp_path / "workspace").glob(".qgis-export-*"))

            asyncio.run(asyncio.wait_for(workflow(), timeout=25))
        finally:
            (tmp_path / "release").touch()
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        assert process.returncode == 0, (tmp_path / "server.log").read_text()
