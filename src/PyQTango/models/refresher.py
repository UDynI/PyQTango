# -*- coding: utf-8 -*-
"""
AttributeRefresher: polling fallback for attribute models (ATK's refresher).

Attributes registered at the same period on the same device are read with a
single ``read_attributes`` call in a worker thread. A device whose previous read
is still running is skipped for that tick, so a slow or dead device never piles
up requests.
"""

import time
import logging

from ..qt import QtCore, Signal
from ..core.names import normalize_name
from ..core.proxies import proxy_cache
from ..core.errors import error_from_exception
from .worker import run_async

log = logging.getLogger(__name__)

DEFAULT_PERIOD_MS = 1000


class _Group(object):
    __slots__ = ("device", "models", "busy", "last_read", "errors")

    def __init__(self, device):
        self.device = device
        self.models = []
        self.busy = False
        self.last_read = 0.0
        self.errors = 0


class AttributeRefresher(QtCore.QObject):
    """ Periodic reader shared by all attribute models.

    Signals:
        paused(bool): emitted when refreshing is paused or resumed
        tick(int):    period (ms) of the timer that just fired
    """

    paused = Signal(bool)
    tick = Signal(int)

    def __init__(self, parent=None):
        QtCore.QObject.__init__(self, parent)
        self._timers = {}     # period -> QTimer
        self._groups = {}     # (period, device_key) -> _Group
        self._model_key = {}  # id(model) -> (period, device_key)
        self._paused = False

    # -- Registration ----------------------------------------------------------
    def register(self, model, period_ms=None):
        period = int(period_ms or model.polling_period or DEFAULT_PERIOD_MS)
        self.unregister(model)
        dev_key = normalize_name(model.device_name)
        key = (period, dev_key)
        group = self._groups.get(key)
        if group is None:
            group = _Group(model.device_name)
            self._groups[key] = group
        group.models.append(model)
        self._model_key[id(model)] = key
        if period not in self._timers:
            timer = QtCore.QTimer(self)
            timer.setInterval(period)
            timer.timeout.connect(lambda p=period: self._on_timer(p))
            self._timers[period] = timer
            if not self._paused:
                timer.start()
        # First value as soon as possible
        self._read_group(group, force=True)

    def unregister(self, model):
        key = self._model_key.pop(id(model), None)
        if key is None:
            return
        group = self._groups.get(key)
        if group is not None:
            try:
                group.models.remove(model)
            except ValueError:
                pass
            if not group.models:
                del self._groups[key]
        period = key[0]
        if not any(k[0] == period for k in self._groups):
            timer = self._timers.pop(period, None)
            if timer is not None:
                timer.stop()
                timer.deleteLater()

    def is_registered(self, model):
        return id(model) in self._model_key

    # -- Control ---------------------------------------------------------------
    def pause(self):
        self._paused = True
        for t in self._timers.values():
            t.stop()
        self.paused.emit(True)

    def resume(self):
        self._paused = False
        for t in self._timers.values():
            t.start()
        self.paused.emit(False)

    def is_paused(self):
        return self._paused

    def refresh_once(self, models=None):
        """ Read now, even while paused (all groups, or the groups of ``models``) """
        if models is None:
            groups = list(self._groups.values())
        else:
            keys = {self._model_key.get(id(m)) for m in models}
            groups = [g for k, g in self._groups.items() if k in keys]
        for g in groups:
            self._read_group(g, force=True)

    def diagnostics(self):
        """ List of dicts describing every polled attribute """
        out = []
        for (period, _), g in self._groups.items():
            for m in g.models:
                out.append({"attribute": m.name, "period_ms": period, "busy": g.busy,
                            "last_read": g.last_read, "group_errors": g.errors})
        return out

    # -- Internals -------------------------------------------------------------
    def _on_timer(self, period):
        self.tick.emit(period)
        for (p, _), g in list(self._groups.items()):
            if p == period:
                self._read_group(g)

    def _read_group(self, group, force=False):
        if group.busy or not group.models:
            return
        group.busy = True
        models = list(group.models)
        names = [m.attr_name for m in models]
        device = group.device

        def read():
            proxy = proxy_cache.get(device)
            return proxy.read_attributes(names)

        def done(results):
            group.busy = False
            group.last_read = time.time()
            for m, da in zip(models, results):
                if not self.is_registered(m):
                    continue
                if getattr(da, "has_failed", False):
                    m._apply_error(error_from_exception(list(da.get_err_stack()), m.name))
                else:
                    m._apply_value(da)

        def failed(err):
            group.busy = False
            group.last_read = time.time()
            group.errors += 1
            for m in models:
                if self.is_registered(m):
                    m._apply_error(err)

        run_async(read, on_done=done, on_error=failed, source=device)


_refresher = None


def refresher():
    """ The shared AttributeRefresher """
    global _refresher
    if _refresher is None:
        _refresher = AttributeRefresher()
    return _refresher
