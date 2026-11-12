# -*- coding: utf-8 -*-
"""
StarterModel: one shared model per Starter device (Astor's TangoHost).

It owns the shared State attribute model (always, while attached) and the
Servers attribute model (while a host panel or a tool asks for it with
:meth:`watch_servers`). Both read with a 1 s timeout, so a dead host never
holds a worker for long, and fall back to polling every 2.5 s when the Starter
pushes no events. Commands run in the worker pool and return a Task; the
models are refreshed afterwards.

Signals:
    stateChanged(str): host state ("running", "moving", "blocked", "alarm",
                       "off", "unreachable", "unknown"; see core.starter)
    serversChanged(list): [ServerLine]
    errorChanged(object): ErrorRecord or None
    statusChanged(str): the Starter Status text

@author: Michele Devetta <michele.devetta@cnr.it>
"""

import logging

from ..qt import QtCore, Signal
from ..core.names import normalize_name
from ..core.proxies import proxy_cache
from ..core.starter import parse_servers, host_state, host_of_starter
from .worker import run_async
from .registry import attribute_model

log = logging.getLogger(__name__)

__all__ = ["StarterModel", "starter_model", "STARTER_TIMEOUT_MS", "STARTER_PERIOD_MS"]

STARTER_TIMEOUT_MS = 1000
STARTER_PERIOD_MS = 2500


class StarterModel(QtCore.QObject):

    stateChanged = Signal(str)
    serversChanged = Signal(object)
    errorChanged = Signal(object)
    statusChanged = Signal(str)
    commandDone = Signal(str, object)          # command text, ErrorRecord or None

    def __init__(self, device, parent=None):
        QtCore.QObject.__init__(self, parent)
        self.device = device
        self.host = host_of_starter(device.split("#")[0])
        self._state = "unknown"
        self._servers = []
        self._status = ""
        self._refs = 0
        self._server_refs = 0
        self.state_model = self._attr("State")
        self.status_model = None
        self.servers_model = None

    # -- Attribute models -------------------------------------------------------
    def _attr(self, name):
        m = attribute_model(self.device + "/" + name)
        m.timeout_ms = STARTER_TIMEOUT_MS
        if m.polling_period != STARTER_PERIOD_MS:
            m.set_polling_period(STARTER_PERIOD_MS)
        return m

    def attach(self):
        """ Follow the State (one more user) """
        self._refs += 1
        if self._refs == 1:
            # Fetch again: the registry forgets idle models, so the stored one may be stale
            self.state_model = self._attr("State")
            m = self.state_model
            m.valueChanged.connect(self._on_state)
            m.errorChanged.connect(self._on_state_error)
            m.attach()
            # Replay what the shared model already knows (another user may follow it)
            if m.last_value() is not None:
                self._on_state(m.last_value())
            if m.last_error() is not None:
                self._on_state_error(m.last_error())

    def release(self):
        self._refs = max(0, self._refs - 1)
        if self._refs == 0:
            _detach(self.state_model, (("valueChanged", self._on_state), ("errorChanged", self._on_state_error)))

    def watch_servers(self):
        """ Follow the Servers attribute and the Status (host panel, tools) """
        self._server_refs += 1
        if self._server_refs == 1:
            self.servers_model = self._attr("Servers")
            self.servers_model.valueChanged.connect(self._on_servers)
            self.servers_model.attach()
            self.status_model = self._attr("Status")
            self.status_model.valueChanged.connect(self._on_status)
            self.status_model.attach()
            if self.servers_model.last_value() is not None:
                self._on_servers(self.servers_model.last_value())
            if self.status_model.last_value() is not None:
                self._on_status(self.status_model.last_value())

    def unwatch_servers(self):
        self._server_refs = max(0, self._server_refs - 1)
        if self._server_refs == 0 and self.servers_model is not None:
            _detach(self.servers_model, (("valueChanged", self._on_servers),))
            _detach(self.status_model, (("valueChanged", self._on_status),))
            self.servers_model = self.status_model = None

    # -- State -------------------------------------------------------------------
    def state(self):
        return self._state

    def servers(self):
        return list(self._servers)

    def status(self):
        return self._status

    def mode(self):
        return self.state_model.mode()

    def _set_state(self, s):
        if s != self._state:
            self._state = s
            self.stateChanged.emit(s)

    def _on_state(self, value):
        self._set_state(host_state(value.value))
        self.errorChanged.emit(None)

    def _on_state_error(self, err):
        if err is not None:
            self._set_state("unreachable")
            self.errorChanged.emit(err)

    def _on_servers(self, value):
        self._servers = parse_servers(list(value.value) if value.value is not None else [])
        self.serversChanged.emit(self.servers())

    def _on_status(self, value):
        self._status = str(value.value or "")
        self.statusChanged.emit(self._status)

    def levels(self):
        """ Startup levels in use (controlled servers, level > 0), ascending """
        return sorted({s.level for s in self._servers if s.controlled and s.level > 0})

    def refresh(self):
        for m in (self.state_model, self.servers_model, self.status_model):
            if m is not None:
                m.refresh()

    # -- Commands ----------------------------------------------------------------
    def proxy(self):
        """ The Starter proxy with the default timeout (blocking: worker threads only) """
        return proxy_cache.get(self.device)

    def command(self, name, argin=None, on_done=None, on_error=None):
        """ Run a Starter command in a worker; refresh afterwards """
        device = self.device
        label = name if argin is None else "{0}({1})".format(name, argin)

        def run():
            p = proxy_cache.get(device)
            return p.command_inout(name) if argin is None else p.command_inout(name, argin)

        def done(result):
            self.commandDone.emit(label, None)
            QtCore.QTimer.singleShot(200, self.refresh)
            if on_done is not None:
                on_done(result)

        def failed(err):
            self.commandDone.emit(label, err)
            QtCore.QTimer.singleShot(200, self.refresh)
            if on_error is not None:
                on_error(err)

        return run_async(run, on_done=done, on_error=failed, source="{0} {1}".format(self.host, label))

    def start_server(self, server, **kw):
        return self.command("DevStart", server, **kw)

    def stop_server(self, server, **kw):
        return self.command("DevStop", server, **kw)

    def hard_kill(self, server, **kw):
        return self.command("HardKillServer", server, **kw)

    def start_level(self, level, **kw):
        return self.command("DevStartAll", int(level), **kw)

    def stop_level(self, level, **kw):
        return self.command("DevStopAll", int(level), **kw)

    def update_servers_info(self, **kw):
        return self.command("UpdateServersInfo", **kw)

    def reset_statistics(self, **kw):
        return self.command("ResetStatistics", **kw)

    def read_log(self, name="Starter", **kw):
        return self.command("DevReadLog", name, **kw)


_models = {}


def _detach(model, connections):
    """ Disconnect and release an attribute model; nothing to do once Qt has deleted it
    (a window closing at exit) """
    try:
        for name, slot in connections:
            try:
                getattr(model, name).disconnect(slot)
            except TypeError:
                pass
        model.release()
    except RuntimeError:
        pass


def starter_model(device):
    """ The shared StarterModel of a Starter device (fully qualified name advised) """
    key = normalize_name(device)
    m = _models.get(key)
    if m is None:
        m = StarterModel(device)
        _models[key] = m
    return m


def is_stop_error_not_running(err):
    """ True for DevStop errors after which Astor offers HardKillServer """
    text = " ".join([getattr(err, "reason", "") or "", getattr(err, "message", "") or ""])
    return "NOT running" in text or "not responding" in text or "SERVER_NOT" in text


__all__.append("is_stop_error_not_running")
