"""Exercise thread guards before Core or Qt side effects without a native host."""

import threading
from unittest.mock import Mock

import pytest
from dcc_mcp_core import DccServerBase, HostUiDispatcherBase

from dcc_mcp_qgis import server as server_module
from dcc_mcp_qgis.dispatcher import QgisDispatcher
from dcc_mcp_qgis.paths import QgisError
from dcc_mcp_qgis.runtime import QgisSession
from dcc_mcp_qgis.server import QgisMcpServer


def run_worker(operation):
    errors = []

    def run():
        try:
            operation()
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=run)
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], QgisError)
    assert errors[0].code == "wrong_thread"


def owned_session():
    session = QgisSession.__new__(QgisSession)
    session.owner = threading.get_ident()
    session.closed = False
    session.app = Mock()
    return session


def unstarted_server(session):
    server = QgisMcpServer.__new__(QgisMcpServer)
    server.session = session
    server._stopped = False
    server.qgis_dispatcher = Mock()
    return server


def test_worker_cannot_construct_dispatcher_before_core_init(monkeypatch):
    core_init = Mock()
    monkeypatch.setattr(HostUiDispatcherBase, "__init__", core_init)
    run_worker(QgisDispatcher)
    core_init.assert_not_called()


def test_worker_cannot_drain_even_if_recorded_as_dispatcher_owner(monkeypatch):
    dispatcher = QgisDispatcher()
    core_drain = Mock()
    monkeypatch.setattr(HostUiDispatcherBase, "drain_queue", core_drain)

    def drain():
        dispatcher.owner = threading.get_ident()
        dispatcher.drain_queue()

    try:
        run_worker(drain)
        core_drain.assert_not_called()
    finally:
        dispatcher.shutdown()


def test_worker_cannot_construct_server_before_dispatcher_or_core(monkeypatch):
    session = owned_session()
    dispatcher_init = Mock()
    core_init = Mock()
    monkeypatch.setattr(server_module, "QgisDispatcher", dispatcher_init)
    monkeypatch.setattr(DccServerBase, "__init__", core_init)
    run_worker(lambda: QgisMcpServer(session))
    dispatcher_init.assert_not_called()
    core_init.assert_not_called()
    session.app.assert_not_called()
    session.app.processEvents.assert_not_called()


@pytest.mark.parametrize("operation", ["start", "pump", "stop", "shutdown"])
def test_worker_lifecycle_rejected_before_core_queue_or_qt(monkeypatch, operation):
    session = owned_session()
    server = unstarted_server(session)
    core_start, core_stop = Mock(), Mock()
    monkeypatch.setattr(DccServerBase, "start", core_start)
    monkeypatch.setattr(DccServerBase, "stop", core_stop)
    run_worker(getattr(server, operation))
    assert server._stopped is False
    core_start.assert_not_called()
    core_stop.assert_not_called()
    server.qgis_dispatcher.drain_queue.assert_not_called()
    server.qgis_dispatcher.shutdown.assert_not_called()
    session.app.processEvents.assert_not_called()


@pytest.mark.parametrize("operation", ["construct", "start", "pump", "stop", "shutdown"])
def test_session_owner_mismatch_rejected_before_side_effects(monkeypatch, operation):
    session = owned_session()
    session.owner = -1
    server = unstarted_server(session)
    core_init, core_start, core_stop, dispatcher_init = Mock(), Mock(), Mock(), Mock()
    monkeypatch.setattr(DccServerBase, "__init__", core_init)
    monkeypatch.setattr(DccServerBase, "start", core_start)
    monkeypatch.setattr(DccServerBase, "stop", core_stop)
    monkeypatch.setattr(server_module, "QgisDispatcher", dispatcher_init)
    with pytest.raises(QgisError) as error:
        if operation == "construct":
            QgisMcpServer(session)
        else:
            getattr(server, operation)()
    assert error.value.code == "wrong_thread"
    assert server._stopped is False
    core_init.assert_not_called()
    core_start.assert_not_called()
    core_stop.assert_not_called()
    dispatcher_init.assert_not_called()
    server.qgis_dispatcher.drain_queue.assert_not_called()
    server.qgis_dispatcher.shutdown.assert_not_called()
    session.app.processEvents.assert_not_called()


def test_main_thread_pump_keeps_queue_then_qt_order():
    session = owned_session()
    server = unstarted_server(session)
    calls = Mock()
    calls.attach_mock(server.qgis_dispatcher.drain_queue, "drain")
    calls.attach_mock(session.app.processEvents, "events")
    server.pump()
    assert [call[0] for call in calls.mock_calls] == ["drain", "events"]
    server.qgis_dispatcher.drain_queue.assert_called_once_with(8)


def test_main_thread_start_stop_and_repeated_shutdown(monkeypatch):
    session = owned_session()
    server = unstarted_server(session)
    core_start = Mock(return_value="started")
    core_stop = Mock(return_value="stopped")
    monkeypatch.setattr(DccServerBase, "start", core_start)
    monkeypatch.setattr(DccServerBase, "stop", core_stop)
    assert server.start() == "started"
    assert server.stop() == "stopped"
    assert server.shutdown() == "stopped"
    assert server._stopped is True
    assert server.qgis_dispatcher.shutdown.call_count == core_stop.call_count == 2
    with pytest.raises(RuntimeError, match="new process"):
        server.start()
    with pytest.raises(RuntimeError, match="new process"):
        server.pump()
    core_start.assert_called_once()
    server.qgis_dispatcher.drain_queue.assert_not_called()
    session.app.processEvents.assert_not_called()


def test_closed_session_rejected_before_core_construction(monkeypatch):
    session = owned_session()
    session.closed = True
    dispatcher_init, core_init = Mock(), Mock()
    monkeypatch.setattr(server_module, "QgisDispatcher", dispatcher_init)
    monkeypatch.setattr(DccServerBase, "__init__", core_init)
    with pytest.raises(RuntimeError, match="closed QGIS session"):
        QgisMcpServer(session)
    dispatcher_init.assert_not_called()
    core_init.assert_not_called()


def test_session_operations_reuse_owner_guard():
    session = owned_session()
    session.owner = -1
    with pytest.raises(QgisError) as error:
        session.status()
    assert error.value.code == "wrong_thread"
    with pytest.raises(QgisError) as error:
        session.close()
    assert error.value.code == "wrong_thread"
    assert session.closed is False
    session.app.exitQgis.assert_not_called()
