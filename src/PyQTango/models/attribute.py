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

    # Internal: Tango callbacks arrive on omniORB threads
    _changeEvent = Signal(object)
    _confEvent = Signal(object)

    #: Grace period before unsubscribing when the last widget detaches
    release_delay_ms = 2000
    #: Delay between reconnection attempts when the device cannot be reached
    retry_delay_ms = 5000

    def __init__(self, name, polling_period=DEFAULT_PERIOD_MS, parent=None):
        QtCore.QObject.__init__(self, parent)
        self.name = name
        self.device_name, self.attr_name = split_attribute_name(name)
        self.polling_period = polling_period
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
        self._release_timer = QtCore.QTimer(self)
        self._release_timer.setSingleShot(True)
        self._release_timer.timeout.connect(self._stop_if_unused)
        self._retry_timer = QtCore.QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._start)
        self._changeEvent.connect(self._on_change_event)
        self._confEvent.connect(self._on_conf_event)
        self.on_released = None   # set by the registry

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
        return getattr(cfg, "memorized", None) in (tango.AttrMemorizedType.MEMORIZED,
                                                   tango.AttrMemorizedType.MEMORIZED_WRITE_INIT)

    def attach(self):
        """ Register one more user; starts the model on first use """
        self._refs += 1
        self._release_timer.stop()
        if not self._active and not self._starting:
            self._start()

    def release(self):
        """ Unregister one user; stops the model after a grace period when unused """
        self._refs = max(0, self._refs - 1)
        if self._refs == 0:
            self._release_timer.start(self.release_delay_ms)

    def write(self, value):
        """ Write asynchronously; result in :attr:`writeDone` """
        attr = self.attr_name
        device = self.device_name

        def do_write():
            proxy_cache.get(device).write_attribute(attr, value)

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
        return run_async(lambda: proxy_cache.get(device).read_attribute(attr),
                         on_done=self._apply_value, on_error=self._apply_error, source=self.name)

    def set_polling_period(self, period_ms):
        self.polling_period = int(period_ms)
        if self._mode == MODE_POLLING:
            refresher().register(self, self.polling_period)

    # -- Start / stop --------------------------------------------------------
    def _start(self):
        if self._active or self._starting or self._refs == 0:
            return
        self._starting = True
        device, attr = self.device_name, self.attr_name
        change_cb = self._changeEvent.emit
        conf_cb = self._confEvent.emit

        def setup():
            proxy = proxy_cache.get(device)
            cfg = proxy.get_attribute_config_ex([attr])[0]
            ids = []
            try:
                ids.append(proxy.subscribe_event(attr, tango.EventType.ATTR_CONF_EVENT, conf_cb, stateless=True))
            except tango.DevFailed:
                pass
            # With stateless=True the call does not fail when events are not
            # available: an error event arrives instead and selects polling.
            ids.append(proxy.subscribe_event(attr, tango.EventType.CHANGE_EVENT, change_cb, stateless=True))
            return cfg, ids

        run_async(setup, on_done=self._on_started, on_error=self._on_start_failed, source=self.name)

    def _on_started(self, result):
        cfg, ids = result
        self._starting = False
        self._ids = ids
        self._active = True
        self._set_config(cfg)
        if self._refs == 0:
            self._release_timer.start(self.release_delay_ms)
        if self._mode == MODE_IDLE:
            # No event received yet: poll until one arrives
            self._set_mode(MODE_POLLING)

    def _on_start_failed(self, err):
        self._starting = False
        self._apply_error(err)
        if self._refs > 0:
            self._retry_timer.start(self.retry_delay_ms)

    def _stop_if_unused(self):
        if self._refs == 0:
            self._stop()

    def _stop(self):
        self._retry_timer.stop()
        refresher().unregister(self)
        ids, self._ids = self._ids, []
        self._active = False
        self._mode = MODE_IDLE
        device = self.device_name
        if ids:
            def unsubscribe():
                proxy = proxy_cache.get(device)
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
        self._set_connected(True)
        if self._error is not None:
            self._error = None
            self.errorChanged.emit(None)
        self.valueChanged.emit(self._value)

    def _apply_error(self, err):
        if not err.source:
            err.source = self.name
        new = self._error is None or self._error.message != err.message
        self._error = err
        self._set_connected(False)
        if new:
            error_history().add(err)
            self.errorChanged.emit(err)

    def _set_connected(self, ok):
        if self._connected != ok:
            self._connected = ok
            self.connectionChanged.emit(ok)
