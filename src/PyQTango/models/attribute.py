# -*- coding: utf-8 -*-
"""
TangoAttributeModel: one shared, event-aware model per Tango attribute.

Widgets never talk to Tango: they attach to a model (through
:func:`PyQTango.models.attribute_model`) and react to its signals.

Life cycle
----------
* The first :meth:`attach` reads the configuration and subscribes, with
  ``stateless=True``, to ``CHANGE_EVENT`` and ``ATTR_CONF_EVENT``.
* While change events are not available (attribute not polled, no event
  criteria, device down) the model is read by the shared
  :class:`AttributeRefresher`. The first good change event switches it back to
  events, and any later event error switches it to polling again.
* When the last widget calls :meth:`release`, the model unsubscribes after a
  grace period (2 s by default), so switching tabs does not churn subscriptions.
"""

import time
import logging
import threading
import itertools
import weakref
import functools
from dataclasses import dataclass

import tango

from ..qt import QtCore, Signal
from ..core.names import split_attribute_name
from ..core.proxies import proxy_cache
from ..core.errors import error_from_exception
from .worker import run_async
from .refresher import refresher, DEFAULT_PERIOD_MS
from .history import error_history

log = logging.getLogger(__name__)

class _EventBridge(QtCore.QObject):
    """ Receives every Tango callback (omniORB threads) and hands the event to its
    model in the GUI thread. It lives as long as the process, so a callback that
    arrives after a model was deleted (between release and unsubscription) finds
    no model instead of emitting on a destroyed QObject. """

    change = Signal(int, object)
    conf = Signal(int, object)

    def __init__(self):
        QtCore.QObject.__init__(self)
        self.models = weakref.WeakValueDictionary()
        self.change.connect(self._change)
        self.conf.connect(self._conf)

    def _change(self, key, ev):
        m = self.models.get(key)
        if m is not None:
            m._on_change_event(ev)

    def _conf(self, key, ev):
        m = self.models.get(key)
        if m is not None:
            m._on_conf_event(ev)


_bridge = None
_bridge_keys = itertools.count(1)


def event_bridge():
    global _bridge
    if _bridge is None:
        _bridge = _EventBridge()
    return _bridge


def _stateless():
    """ Keyword arguments of a stateless subscription (``sub_mode`` from PyTango 10.3 on) """
    mode = getattr(getattr(tango, "EventSubMode", None), "Stateless", None)
    return {"sub_mode": mode} if mode is not None else {"stateless": True}


STATELESS = _stateless()

class SubscriptionLimiter(QtCore.QObject):
    """ Starts at most ``max_active`` model subscriptions at a time (Astor's
    subscribe thread): opening 300 hosts queues 300 setups instead of filling
    the worker pool.

    Signals:
        progress(int done, int total): after each setup of the current batch
        idle(): the batch is over (counters reset)

    ``failures`` lists (name, ErrorRecord) of the current batch.
    """

    progress = Signal(int, int)
    idle = Signal()

    def __init__(self, max_active=16):
        QtCore.QObject.__init__(self)
        self.max_active = max_active
        self._queue = []
        self._active = set()
        self.done = 0
        self.total = 0
        self.failures = []

    def request(self, model):
        self.total += 1
        self._queue.append(model)
        self._pump()

    def finished(self, model, ok, err=None):
        if id(model) not in self._active:
            return
        self._active.discard(id(model))
        self.done += 1
        if not ok:
            self.failures.append((model.name, err))
        self.progress.emit(self.done, self.total)
        self._pump()

    def busy(self):
        return bool(self._active or self._queue)

    def _pump(self):
        # A loop, not recursion: models released while queued are skipped here
        skipped = 0
        while self._queue and len(self._active) < self.max_active:
            m = self._queue.pop(0)
            if m._refs == 0:
                m._starting = False
                self.done += 1
                skipped += 1
                m._stop_if_unused()
                continue
            self._active.add(id(m))
            m._setup()
        if skipped:
            self.progress.emit(self.done, self.total)
        if not self._active and not self._queue and self.total:
            self.done = self.total = 0
            self.failures = []
            self.idle.emit()


_limiter = None


def subscription_limiter():
    """ The process-wide :class:`SubscriptionLimiter` """
    global _limiter
    if _limiter is None:
        _limiter = SubscriptionLimiter()
    return _limiter


MODE_IDLE = "idle"
MODE_EVENTS = "events"
MODE_POLLING = "polling"


@dataclass
class AttrValue:
    """ One reading of an attribute """
    value: object
    w_value: object
    quality: object
    time: float
    dim_x: int = 0
    dim_y: int = 0
    raw: object = None

    @classmethod
    def from_device_attribute(cls, da):
        try:
            t = da.time.totime()
        except Exception:
            t = time.time()
        return cls(value=da.value, w_value=getattr(da, "w_value", None), quality=da.quality, time=t,
                   dim_x=getattr(da, "dim_x", 0), dim_y=getattr(da, "dim_y", 0), raw=da)


class TangoAttributeModel(QtCore.QObject):
    """ Shared model of one attribute.

    Signals:
        valueChanged(AttrValue)
        configChanged(tango.AttributeInfoEx)
        errorChanged(ErrorRecord or None)  - None when the error clears
        connectionChanged(bool)
        writeDone(ErrorRecord or None)     - None on success
        modeChanged(str)                   - "idle", "events" or "polling"
    """

    valueChanged = Signal(object)
    configChanged = Signal(object)
    errorChanged = Signal(object)
    connectionChanged = Signal(bool)
    writeDone = Signal(object)
    modeChanged = Signal(str)


    #: Grace period before unsubscribing when the last widget detaches
    release_delay_ms = 2000
    #: Delay before the first reconnection attempt when the device cannot be reached
    #: (doubled at each failure, up to max_retry_delay_ms)
    retry_delay_ms = 5000
    max_retry_delay_ms = 60000

    def __init__(self, name, polling_period=DEFAULT_PERIOD_MS, parent=None):
        QtCore.QObject.__init__(self, parent)
        self.name = name
        self.device_name, self.attr_name = split_attribute_name(name)
        self.polling_period = polling_period    # in use: see request_period()
        self._base_period = polling_period
        self._period_requests = {}              # owner -> ms
        self._base_source = None
        self._source_requests = {}              # owner -> tango.DevSource (latest last)
        self._refs = 0
        self._active = False
        self._starting = False
        self._config = None
        self._value = None
        self._error = None
        self._connected = None
        self._mode = MODE_IDLE
        self._written = False
        self._ids = []
        self._start_failures = 0    # failed setups in a row (retry back-off)
        self._sub_proxy = None      # the proxy that holds the subscriptions in _ids
        self._suspended = 0
        self.source = None          # tango.DevSource for polled reads (None = default)
        self.timeout_ms = None      # read timeout of this model's proxy (None = cache default)
        self.n_events = 0           # good change events received
        self.n_updates = 0          # values applied (events + polled reads)
        self.n_errors = 0
        self.last_update = None     # time.time() of the last value
        self._release_timer = QtCore.QTimer(self)
        self._release_timer.setSingleShot(True)
        self._release_timer.timeout.connect(self._stop_if_unused)
        self._retry_timer = QtCore.QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._start)
        # Tango callbacks arrive on omniORB threads: they go through the event bridge
        self._bridge_key = next(_bridge_keys)
        event_bridge().models[self._bridge_key] = self
        self.on_released = None   # set by the registry
        self.on_revive = None     # set by the registry: called when a forgotten model is attached again

    # -- Public API ----------------------------------------------------------
    def config(self):
        """ Last tango.AttributeInfoEx, or None before the first read """
        return self._config

    def last_value(self):
        """ Last :class:`AttrValue`, or None """
        return self._value

    def last_error(self):
        return self._error

    def mode(self):
        return self._mode

    def is_connected(self):
        return bool(self._connected)

    def ref_count(self):
        return self._refs

    def label(self):
        return self._config.label if self._config is not None else self.attr_name

    def is_writable(self):
        cfg = self._config
        return cfg is not None and cfg.writable in (tango.AttrWriteType.WRITE,
                                                     tango.AttrWriteType.READ_WRITE,
                                                     tango.AttrWriteType.READ_WITH_WRITE)

    def has_valid_set_point(self):
        """ True when ``w_value`` is meaningful: the attribute is memorized,
        write-only, or was written by this process. For other attributes Tango
        returns a default (0, False, "Not initialised") until the first write. """
        cfg = self._config
        if self._written:
            return True
        if cfg is None:
            return False
        if cfg.writable == tango.AttrWriteType.WRITE:
            return True
        # By name: PyTango 9.5 does not export AttrMemorizedType from the tango module
        return getattr(getattr(cfg, "memorized", None), "name", None) in ("MEMORIZED", "MEMORIZED_WRITE_INIT")

    def attach(self):
        """ Register one more user; starts the model on first use """
        self._refs += 1
        self._release_timer.stop()
        if self._refs == 1 and self.on_revive is not None:
            self.on_revive(self)
        self._apply_period()
        if not self._active and not self._starting:
            self._start()

    def release(self):
        """ Unregister one user; stops the model after a grace period when unused """
        self._refs = max(0, self._refs - 1)
        self._apply_period()
        if self._refs == 0:
            self._release_timer.start(self.release_delay_ms)

    def write(self, value):
        """ Write asynchronously; result in :attr:`writeDone` """
        attr = self.attr_name
        device = self.device_name
        timeout = self.timeout_ms

        def do_write():
            proxy_cache.get(device, timeout_ms=timeout).write_attribute(attr, value)

        def done(_):
            self._written = True
            self.writeDone.emit(None)
            self.refresh()

        def failed(err):
            err.source = "Write " + self.name
            error_history().add(err)
            self.writeDone.emit(err)

        return run_async(do_write, on_done=done, on_error=failed, source=self.name)

    def refresh(self):
        """ Read once now, whatever the mode """
        attr = self.attr_name
        device = self.device_name
        timeout = self.timeout_ms
        return run_async(lambda: proxy_cache.get(device, timeout_ms=timeout).read_attribute(attr),
                         on_done=self._apply_value, on_error=self._apply_error, source=self.name)

    def set_polling_period(self, period_ms):
        """ Default polling period (users without a :meth:`request_period`) """
        self._base_period = int(period_ms)
        self._apply_period(force=True)

    def set_source(self, source):
        """ Default read source of polled reads: tango.DevSource.DEV, CACHE or CACHE_DEV (default) """
        self._base_source = source
        self._apply_source()

    # -- Per-user requests (a trend asks for its own rate without imposing it) ---------
    def request_period(self, owner, period_ms):
        """ ``owner`` (a hashable key) asks for polling every ``period_ms`` (None
        withdraws the request). The model polls at the fastest request, and never
        slower than the default period while users without a request are attached. """
        if period_ms is None:
            self._period_requests.pop(owner, None)
        else:
            self._period_requests[owner] = int(period_ms)
        self._apply_period()

    def request_source(self, owner, source):
        """ ``owner`` asks for a read source (None withdraws the request); the latest
        request is used, the default source once every request is withdrawn """
        self._source_requests.pop(owner, None)
        if source is not None:
            self._source_requests[owner] = source
        self._apply_source()

    def _apply_period(self, force=False):
        reqs = self._period_requests
        period = min(reqs.values()) if reqs else self._base_period
        if self._refs > len(reqs):
            period = min(period, self._base_period)     # plain users get at least the default
        if period != self.polling_period or force:
            self.polling_period = period
            if self._mode == MODE_POLLING:
                refresher().register(self, self.polling_period)

    def _apply_source(self):
        source = list(self._source_requests.values())[-1] if self._source_requests else self._base_source
        if source != self.source:
            self.source = source
            if self._mode == MODE_POLLING:
                refresher().register(self, self.polling_period)

    # -- Suspension (window "Stop refreshing", hidden tabs) ----------------------
    def suspend(self):
        """ One user stops looking at values. While every user is suspended the
        refresher skips this model (events still arrive and are cheap). """
        self._suspended += 1

    def resume(self):
        self._suspended = max(0, self._suspended - 1)

    def is_suspended(self):
        return self._refs > 0 and self._suspended >= self._refs

    # -- Start / stop --------------------------------------------------------
    def _start(self):
        if self._active or self._starting or self._refs == 0:
            return
        self._starting = True
        subscription_limiter().request(self)

    def _setup(self):
        """ Called by the subscription limiter when a slot is free (never for a released model) """
        device, attr = self.device_name, self.attr_name
        bridge = event_bridge()
        change_cb = functools.partial(bridge.change.emit, self._bridge_key)
        conf_cb = functools.partial(bridge.conf.emit, self._bridge_key)

        timeout = self.timeout_ms

        def setup():
            proxy = proxy_cache.get(device, timeout_ms=timeout)
            cfg = proxy.get_attribute_config_ex([attr])[0]
            ids = []
            try:
                ids.append(proxy.subscribe_event(attr, tango.EventType.ATTR_CONF_EVENT, conf_cb, **STATELESS))
            except tango.DevFailed:
                pass
            # With a stateless subscription the call does not fail when events are
            # not available: an error event arrives instead and selects polling.
            ids.append(proxy.subscribe_event(attr, tango.EventType.CHANGE_EVENT, change_cb, **STATELESS))
            return cfg, ids, proxy

        # Strong references: Qt keeps only a weak one to a bound method, and the
        # registry may drop the model while the setup runs
        m = self
        run_async(setup, on_done=lambda r: m._on_started(r), on_error=lambda e: m._on_start_failed(e),
                  source=self.name)

    def _on_started(self, result):
        cfg, ids, proxy = result
        self._starting = False
        self._start_failures = 0
        subscription_limiter().finished(self, True)
        self._ids = ids
        self._sub_proxy = proxy
        self._active = True
        self._set_config(cfg)
        if self._refs == 0:
            self._release_timer.start(self.release_delay_ms)
        if self._mode == MODE_IDLE:
            # No event received yet: poll until one arrives
            self._set_mode(MODE_POLLING)

    def _on_start_failed(self, err):
        self._starting = False
        subscription_limiter().finished(self, False, err)
        self._apply_error(err)
        self._start_failures += 1
        if self._refs > 0:
            # Exponential back-off: a dead device must not keep a worker busy every few seconds
            delay = min(self.max_retry_delay_ms, self.retry_delay_ms * 2 ** (self._start_failures - 1))
            self._retry_timer.start(int(delay))
        else:
            self._stop()

    def _stop_if_unused(self):
        if self._refs == 0:
            self._stop()

    def _stop(self):
        self._retry_timer.stop()
        if self._starting:
            return      # _on_started / _on_start_failed stop it once the setup is over
        refresher().unregister(self)
        ids, self._ids = self._ids, []
        proxy, self._sub_proxy = self._sub_proxy, None
        self._active = False
        self._set_mode(MODE_IDLE)
        if ids and proxy is not None:
            # Unsubscribe on the proxy that subscribed: another one raises KeyError
            def unsubscribe():
                for i in ids:
                    try:
                        proxy.unsubscribe_event(i)
                    except Exception:  # noqa: BLE001
                        pass
            run_async(unsubscribe, source=self.name)
        if self.on_released is not None:
            self.on_released(self)

    def shutdown(self):
        """ Stop immediately, whatever the reference count """
        self._refs = 0
        self._release_timer.stop()
        self._stop()

    # -- Event handling (GUI thread) -----------------------------------------
    def _on_change_event(self, ev):
        if not self._active and not self._starting:
            return
        if ev.err:
            # No events (not polled, no criteria, device down...): poll instead
            if self._mode != MODE_POLLING:
                self._set_mode(MODE_POLLING)
            return
        if self._mode != MODE_EVENTS:
            self._set_mode(MODE_EVENTS)
        self.n_events += 1
        self._apply_value(ev.attr_value)

    def _on_conf_event(self, ev):
        if ev.err or ev.attr_conf is None:
            return
        self._set_config(ev.attr_conf)

    def _set_mode(self, mode):
        if mode == self._mode:
            return
        self._mode = mode
        if mode == MODE_POLLING:
            refresher().register(self, self.polling_period)
        else:
            refresher().unregister(self)
        self.modeChanged.emit(mode)

    def _set_config(self, cfg):
        self._config = cfg
        self.configChanged.emit(cfg)

    def _apply_value(self, da):
        if da is None:
            return
        if getattr(da, "has_failed", False):
            self._apply_error(error_from_exception(list(da.get_err_stack()), self.name))
            return
        self._value = AttrValue.from_device_attribute(da)
        self.n_updates += 1
        self.last_update = time.time()
        self._set_connected(True)
        if self._error is not None:
            self._error = None
            self.errorChanged.emit(None)
        self.valueChanged.emit(self._value)

    def _apply_error(self, err):
        if not err.source:
            err.source = self.name
        new = self._error is None or self._error.message != err.message
        self.n_errors += 1
        self._error = err
        self._set_connected(False)
        if new:
            error_history().add(err)
            self.errorChanged.emit(err)

    def _set_connected(self, ok):
        if self._connected != ok:
            self._connected = ok
            self.connectionChanged.emit(ok)
