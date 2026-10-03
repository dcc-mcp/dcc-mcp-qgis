"""Composition root: Core owns MCP, catalogs, lifecycle, jobs and discovery."""

from pathlib import Path

from dcc_mcp_core import (
    AdapterInstructionSet,
    AdapterReadinessBinder,
    DccServerBase,
    DccServerOptions,
    HostExecutionBridge,
    MinimalModeConfig,
)

from . import __version__
from .dispatcher import QgisDispatcher
from .runtime import CAPABILITIES, assert_main


class QgisMcpServer(DccServerBase):
    def __init__(self, session, port=None, **options):
        assert_main()
        if options.get("gateway_port", 0) != 0 or options.get("enable_gateway_failover", False):
            raise ValueError("This supported local profile requires gateway_port=0 and gateway failover disabled")
        session.assert_owner()
        if session.closed:
            raise RuntimeError("A closed QGIS session requires a new process")
        self.session = session
        self._stopped = False
        options.setdefault("gateway_port", 0)
        options.setdefault("enable_gateway_failover", False)
        self.qgis_dispatcher = QgisDispatcher()
        self.qgis_dispatcher.drain_queue()
        bridge = HostExecutionBridge(dispatcher=self.qgis_dispatcher)
        config = DccServerOptions.from_env(
            "qgis",
            Path(__file__).parent / "skills",
            port=port,
            server_name="dcc-mcp-qgis",
            server_version=__version__,
            adapter_version=__version__,
            instance_type="standalone",
            execution_bridge=bridge,
            **options,
        )
        super().__init__(options=config)
        self.register_adapter_instructions(
            AdapterInstructionSet(
                dcc="qgis",
                adapter_version=__version__,
                capabilities=CAPABILITIES,
                instructions="Owned headless PyQGIS project. Load qgis-project and qgis-vector. "
                "Paths are workspace-relative. "
                "No overwrite. Reopen adapter bundles only. Start each async operation once and poll jobs_get_status.",
            )
        )
        self.register_builtin_actions(include_bundled=False, minimal_mode=MinimalModeConfig(skills=("qgis-project",)))
        self.readiness = AdapterReadinessBinder.bind_headless(self, dcc_ready_probe=lambda: not self.session.closed)

    def start(self, **kwargs):
        assert_main()
        self.session.assert_owner()
        if self._stopped or self.session.closed:
            raise RuntimeError("A stopped QGIS adapter requires a new process")
        return super().start(**kwargs)

    def _version_string(self):
        return self.session.version

    def pump(self):
        assert_main()
        self.session.assert_owner()
        if self._stopped or self.session.closed:
            raise RuntimeError("A stopped QGIS adapter requires a new process")
        self.qgis_dispatcher.drain_queue(8)
        self.session.app.processEvents()

    def stop(self):
        assert_main()
        self.session.assert_owner()
        self._stopped = True
        self.qgis_dispatcher.shutdown()
        return super().stop()

    def shutdown(self):
        return self.stop()
