"""The process-main-thread PyQGIS execution lane, backed by Core queues."""

import threading
import uuid

from dcc_mcp_core import HostUiDispatcherBase
from dcc_mcp_core.skills_helper import skill_error

from .runtime import assert_main


class QgisDispatcher(HostUiDispatcherBase):
    def __init__(self):
        assert_main()
        super().__init__(label="qgis-process-main")
        self.owner = threading.get_ident()

    def poke_host_pump(self):
        # The owned CLI loop drains at most every 5 ms; never invoke Qt from workers.
        pass

    def drain_queue(self, budget_ms=8):
        assert_main()
        if threading.get_ident() != self.owner:
            raise RuntimeError("QGIS queue must be pumped by its owner thread")
        return super().drain_queue(budget_ms)

    def dispatch_callable(self, func, *, affinity="main", timeout_hint_secs=None, **metadata):
        request_id = str(uuid.uuid4())
        result = self.submit_callable(
            request_id, func, affinity=affinity, timeout_ms=int((timeout_hint_secs or 30) * 1000)
        )
        if not result["success"]:
            # Core submission timeout does not itself remove a pending callback.
            # Explicitly cancel the same public request ID before returning.
            self.cancel(request_id)
            return skill_error("Host dispatch failed", "dispatch_failed", _meta={"dcc.error": result})
        return result["output"]
