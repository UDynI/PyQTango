# -*- coding: utf-8 -*-
"""
TangoDeviceModel: shared model of one device (State, Status, commands, info).
"""

import time
import logging

from ..qt import QtCore, Signal
from ..core.proxies import proxy_cache
from .worker import run_async
from .history import error_history

log = logging.getLogger(__name__)


class TangoDeviceModel(QtCore.QObject):
    """ Device-level model.

    ``state_model`` and ``status_model`` are the shared attribute models of the
    ``State`` and ``Status`` attributes, so device widgets get the same event
    and polling behaviour as attribute widgets.

    Signals:
        commandsChanged(list)                     - list of tango.CommandInfo, sorted by name
        commandDone(str, object, float)           - command, result, duration in ms
        commandFailed(str, ErrorRecord)
        infoChanged(object)                       - tango.DeviceInfo
        errorChanged(ErrorRecord)                 - errors of device-level calls
    """

    commandsChanged = Signal(object)
    commandDone = Signal(str, object, float)
    commandFailed = Signal(str, object)
    infoChanged = Signal(object)
    errorChanged = Signal(object)

    def __init__(self, name, registry, parent=None):
        QtCore.QObject.__init__(self, parent)
        self.name = name
        self._registry = registry
        self._commands = None
        self._info = None

    @property
    def state_model(self):
        """ Shared model of the State attribute (looked up each time, as idle models are forgotten) """
        return self._registry.attribute(self._attr("State"))

    @property
    def status_model(self):
        """ Shared model of the Status attribute (looked up each time, as idle models are forgotten) """
        return self._registry.attribute(self._attr("Status"))

    def _attr(self, attr):
        # Insert the attribute before a "#dbase=no" fragment
        if "#" in self.name:
            dev, frag = self.name.split("#", 1)
            return dev + "/" + attr + "#" + frag
        return self.name + "/" + attr

    def attribute(self, attr):
        """ Shared model of one attribute of this device """
        return self._registry.attribute(self._attr(attr))

    def proxy(self):
        """ DeviceProxy (blocking: call from a worker thread) """
        return proxy_cache.get(self.name)

    def commands(self):
        return self._commands

    def info(self):
        return self._info

    def load_commands(self):
        name = self.name

        def query():
            return sorted(proxy_cache.get(name).command_list_query(), key=lambda c: c.cmd_name.lower())

        def done(cmds):
            self._commands = cmds
            self.commandsChanged.emit(cmds)

        return run_async(query, on_done=done, on_error=self._error, source=name)

    def load_info(self):
        name = self.name

        def done(info):
            self._info = info
            self.infoChanged.emit(info)

        return run_async(lambda: proxy_cache.get(name).info(), on_done=done, on_error=self._error, source=name)

    def execute(self, command, argin=None):
        """ Run a command asynchronously; result in commandDone / commandFailed """
        name = self.name

        def run():
            proxy = proxy_cache.get(name)
            t0 = time.perf_counter()
            if argin is None:
                result = proxy.command_inout(command)
            else:
                result = proxy.command_inout(command, argin)
            return result, (time.perf_counter() - t0) * 1000.0

        def done(res):
            self.commandDone.emit(command, res[0], res[1])

        def failed(err):
            err.source = "{0}/{1}".format(name, command)
            error_history().add(err)
            self.commandFailed.emit(command, err)

        return run_async(run, on_done=done, on_error=failed, source=name)

    def _error(self, err):
        error_history().add(err)
        self.errorChanged.emit(err)
