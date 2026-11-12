# -*- coding: utf-8 -*-
"""
AttributeRefresher: polling fallback for attribute models (ATK's refresher).

Attributes registered at the same period on the same device are read with a
single ``read_attributes`` call in a worker thread. A device whose previous read
is still running is skipped for that tick, so a slow or dead device never piles
up requests.

Reads of one device never overlap: a per-device lock serialises them in the
workers, as the device server would anyway, so they wait for each other here
instead of timing out on the server.

When a grouped read times out as a whole (one slow attribute), the group is
probed: each attribute is read alone, one after the other. If some succeed, the
ones that time out alone are polled on their own ("solo"), at most every
SOLO_PERIOD_MS, so one slow attribute neither makes the others fail nor keeps
the device busy. A solo attribute that reads fine alone goes back to its group.

A dead or hung device must not take the worker pool: a probe gives up after two
timeouts when nothing was read (each probe starts from another attribute, so slow
ones cannot hide the others for good), a failing group backs off exponentially (up
to MAX_BACKOFF_S), and a read waits at most LOCK_WAIT_S for another read of the
same device before giving up its tick.
"""

import threading

import time
import logging

from ..qt import QtCore, Signal
from ..core.names import normalize_name
from ..core.proxies import proxy_cache
from ..core.errors import error_from_exception
from .worker import run_async

log = logging.getLogger(__name__)

DEFAULT_PERIOD_MS = 1000
#: Shortest period of an attribute polled on its own after timing out in a group
SOLO_PERIOD_MS = 10000
#: Longest wait between reads of a group whose device keeps failing
MAX_BACKOFF_S = 30.0
#: Longest wait of a worker for another read of the same device
LOCK_WAIT_S = 0.2

_SKIPPED = object()     # result of a read that gave up its tick (device busy)


class _Group(object):
    __slots__ = ("device", "models", "busy", "last_read", "errors", "source", "skipped", "timeout", "probes")

    def __init__(self, device):
        self.device = device
        self.source = None
        self.timeout = None
        self.skipped = 0
        self.models = []
        self.busy = False
        self.last_read = 0.0
        self.errors = 0         # failed reads in a row (back-off)
        self.probes = 0         # probes so far (each starts from another attribute)


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
        self._solo = set()    # id(model) of attributes polled on their own
        self._locks = {}      # device key -> threading.Lock
        self._locks_guard = threading.Lock()
        self._paused = False

    # -- Registration ----------------------------------------------------------
    def register(self, model, period_ms=None):
        period = int(period_ms or model.polling_period or DEFAULT_PERIOD_MS)
        if id(model) in self._solo:
            period = max(period, SOLO_PERIOD_MS)
        self._drop(model)
        source = getattr(model, "source", None)
        timeout = getattr(model, "timeout_ms", None)
        dev_key = (normalize_name(model.device_name), None if source is None else int(source),
                   normalize_name(model.name) if id(model) in self._solo else None, timeout)
        key = (period, dev_key)
        group = self._groups.get(key)
        if group is None:
            group = _Group(model.device_name)
            group.source = source
            group.timeout = timeout
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
        self._solo.discard(id(model))
        self._drop(model)

    def _drop(self, model):
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

    def is_solo(self, model):
        """ True when the model is polled on its own (it timed out in a grouped read) """
        return id(model) in self._solo

    def _make_solo(self, model):
        if id(model) in self._solo or not self.is_registered(model):
            return
        period = self._model_key[id(model)][0]
        self._solo.add(id(model))
        self.register(model, period)

    def _unsolo(self, model):
        if id(model) not in self._solo or not self.is_registered(model):
            return
        self._solo.discard(id(model))
        self.register(model, getattr(model, "polling_period", None))

    def _lock(self, device):
        key = normalize_name(device)
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = self._locks[key] = threading.Lock()
            return lock

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
                            "last_read": g.last_read, "group_errors": g.errors,
                            "suspended": m.is_suspended(), "source": g.source,
                            "solo": self.is_solo(m)})
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
        if group.errors and not force and \
                time.time() - group.last_read < min(MAX_BACKOFF_S, 2.0 ** (group.errors - 1)):
            group.skipped += 1      # failing device: back off
            return
        models = [m for m in group.models if force or not m.is_suspended()]
        if not models:
            group.skipped += 1
            return
        group.busy = True
        names = [m.attr_name for m in models]
        device = group.device
        source = group.source
        timeout = group.timeout
        lock = self._lock(device)

        def read():
            proxy = proxy_cache.get(device, timeout_ms=timeout, source=source)
            if not lock.acquire(timeout=LOCK_WAIT_S):
                return _SKIPPED     # another read of the device is running: next tick
            try:
                return proxy.read_attributes(names)
            finally:
                lock.release()

        def done(results):
            group.busy = False
            if results is _SKIPPED:
                group.skipped += 1
                return
            group.last_read = time.time()
            group.errors = 0
            for m, da in zip(models, results):
                if not self.is_registered(m):
                    continue
                if getattr(da, "has_failed", False):
                    m._apply_error(error_from_exception(list(da.get_err_stack()), m.name))
                else:
                    m._apply_value(da)
                    if id(m) in self._solo:
                        # Fast enough alone: back to its device group (it may have timed
                        # out only because the server was busy with a slow attribute)
                        QtCore.QTimer.singleShot(0, lambda m=m: self._unsolo(m))

        def failed(err):
            group.last_read = time.time()
            group.errors += 1
            if len(models) > 1 and _is_timeout(err):
                self._probe(group, models, source, lock)
                return
            group.busy = False
            for m in models:
                if self.is_registered(m):
                    m._apply_error(err)

        run_async(read, on_done=done, on_error=failed, source=device)

    def _probe(self, group, models, source, lock):
        """ Read each attribute of a timed-out group alone, one after the other """
        device = group.device
        timeout = group.timeout
        # Start from another attribute at each probe: a slow first one cannot hide the others
        start = group.probes % len(models)
        group.probes += 1
        models = models[start:] + models[:start]
        names = [m.attr_name for m in models]

        def probe():
            proxy = proxy_cache.get(device, timeout_ms=timeout, source=source)
            out = []
            timeouts = 0
            for name in names:
                try:
                    if not lock.acquire(timeout=LOCK_WAIT_S):
                        return _SKIPPED
                    try:
                        out.append((True, proxy.read_attribute(name)))
                    finally:
                        lock.release()
                except Exception as e:  # noqa: BLE001 (reported per attribute)
                    out.append((False, e))
                    if _is_timeout(error_from_exception(e)):
                        timeouts += 1
                    if timeouts >= 2 and not any(good for good, _ in out):
                        # Nothing answers: the device is down, do not wait N timeouts
                        out += [(False, e)] * (len(names) - len(out))
                        break
            return out

        def done(results):
            group.busy = False
            if results is _SKIPPED:
                group.skipped += 1
                return
            ok = any(good for good, _ in results)
            if ok:
                group.errors = 0
            for m, (good, res) in zip(models, results):
                if not self.is_registered(m):
                    continue
                if good:
                    if getattr(res, "has_failed", False):
                        m._apply_error(error_from_exception(list(res.get_err_stack()), m.name))
                    else:
                        m._apply_value(res)
                else:
                    err = error_from_exception(res, m.name)
                    m._apply_error(err)
                    if ok and _is_timeout(err):
                        self._make_solo(m)

        def failed(err):
            group.busy = False
            for m in models:
                if self.is_registered(m):
                    m._apply_error(err)

        run_async(probe, on_done=done, on_error=failed, source=device)


def _is_timeout(err):
    text = " ".join([getattr(err, "reason", "") or ""] + [it.reason + " " + it.desc for it in getattr(err, "items", [])])
    return "timeout" in text.lower() or "timedout" in text.lower()


_refresher = None


def refresher():
    """ The shared AttributeRefresher """
    global _refresher
    if _refresher is None:
        _refresher = AttributeRefresher()
    return _refresher
