"""Launch a new isolated process-main-thread PyQGIS service."""

import argparse
import json
import os
import signal
import time
from pathlib import Path

from . import __version__


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--workspace", type=Path, required=True, help="Root for all GIS input/output artifacts")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--endpoint-file", type=Path, help="Write startup endpoint JSON for clients")
    args = parser.parse_args(argv)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from dcc_mcp_core import capture_bootstrap_errors

    with capture_bootstrap_errors("qgis", adapter_version=__version__, min_core_version="0.20.41"):
        from .runtime import QgisSession
        from .server import QgisMcpServer

        session = QgisSession(args.workspace)
        server = None
        stopping = False

        def stop(*_args):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        try:
            server = QgisMcpServer(session, port=args.port)
            server.start()
            endpoint = {
                "mcp_url": server.mcp_url,
                "instance_id": server.instance_id,
                "qgis_version": session.version,
                "pid": os.getpid(),
                "adapter_version": __version__,
            }
            if args.endpoint_file:
                args.endpoint_file.parent.mkdir(parents=True, exist_ok=True)
                with args.endpoint_file.open("x", encoding="utf-8") as stream:
                    json.dump(endpoint, stream)
            print(json.dumps(endpoint), flush=True)
            while not stopping:
                server.pump()
                time.sleep(0.005)
        finally:
            try:
                if server is not None:
                    server.shutdown()
            finally:
                session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
