# -*- coding: utf-8 -*-
"""
Shared fixtures.

Run on both bindings::

    PYQTANGO_QT_API=pyqt5 PYTEST_QT_API=pyqt5 QT_QPA_PLATFORM=offscreen pytest
    PYQTANGO_QT_API=pyqt6 PYTEST_QT_API=pyqt6 QT_QPA_PLATFORM=offscreen pytest
"""

import os
import enum
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTEST_QT_API", os.environ.get("PYQTANGO_QT_API", "pyqt5"))

import tango  # noqa: E402
from tango import AttrWriteType, DevState, DispLevel  # noqa: E402
from tango.server import Device, attribute, command  # noqa: E402
from tango.test_context import DeviceTestContext  # noqa: E402


class Color(enum.IntEnum):
    Red = 0
    Green = 1
    Blue = 2


class PQTDevice(Device):
    """ Test device: one pushed-event attribute, the rest only readable by polling """

    def init_device(self):
        super().init_device()
        self._ev = 1.0
        self._rw = 10.0
        self._long = 5
        self._bool = False
        self._switch = False
        self._enum = Color.Red
        self._str = "hello"
        self.set_state(DevState.ON)
        self.set_status("Device is ON")
        self.set_change_event("ev_double", True, False)

    @attribute(dtype=float, format="%6.3f", unit="V")
    def ev_double(self):
        return self._ev

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE, format="%6.2f", unit="mm",
               min_value=-100, max_value=100, label="RW double")
    def rw_double(self):
        return self._rw

    @rw_double.write
    def rw_double(self, v):
        self._rw = v

    @attribute(dtype=int, access=AttrWriteType.READ_WRITE, format="%4d")
    def rw_long(self):
        return self._long

    @rw_long.write
    def rw_long(self, v):
        self._long = v

    @attribute(dtype=bool, access=AttrWriteType.READ_WRITE)
    def rw_bool(self):
        return self._bool

    @rw_bool.write
    def rw_bool(self, v):
        self._bool = v

    @attribute(dtype=bool, access=AttrWriteType.READ_WRITE, label="Pump")
    def rw_switch(self):
        return self._switch

    @rw_switch.write
    def rw_switch(self, v):
        self._switch = v

    @attribute(dtype=bool, access=AttrWriteType.READ_WRITE)
    def rw_locked(self):
        return False

    @rw_locked.write
    def rw_locked(self, v):
        raise RuntimeError("Locked on purpose")

    @attribute(dtype=Color, access=AttrWriteType.READ_WRITE)
    def rw_enum(self):
        return self._enum

    @rw_enum.write
    def rw_enum(self, v):
        self._enum = Color(v)

    @attribute(dtype=str, access=AttrWriteType.READ_WRITE)
    def rw_string(self):
        return self._str

    @rw_string.write
    def rw_string(self, v):
        self._str = v

    @attribute(dtype=(float,), max_dim_x=10)
    def spectrum(self):
        return [1.0, 2.0, 3.0]

    @attribute(dtype=float, max_alarm=5.0)
    def alarm_double(self):
        return 10.0

    @attribute(dtype=float, display_level=DispLevel.EXPERT)
    def expert_double(self):
        return 3.0

    @attribute(dtype=((float,),), max_dim_x=8, max_dim_y=8)
    def image(self):
        return [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]

    @attribute(dtype=(str,), max_dim_x=8)
    def str_spectrum(self):
        return ["alpha", "beta"]

    @attribute(dtype=(DevState,), max_dim_x=8)
    def state_spectrum(self):
        return [DevState.ON, DevState.FAULT, DevState.ALARM]

    @attribute(dtype=(bool,), max_dim_x=8)
    def bool_spectrum(self):
        return [True, False, True]

    @attribute(dtype=((str,),), max_dim_x=4, max_dim_y=4)
    def str_image(self):
        return [["a", "b"], ["c", "d"]]

    @attribute(dtype=tango.DevEncoded)
    def gray8(self):
        enc = tango.EncodedAttribute()
        import numpy as np
        enc.encode_gray8(np.array([[0, 64, 128], [192, 255, 10]], dtype=np.uint8))
        return enc

    @attribute(dtype=(float,), max_dim_x=10, access=AttrWriteType.READ_WRITE)
    def rw_spectrum(self):
        return getattr(self, "_rw_spectrum", [0.5, 1.5])

    @rw_spectrum.write
    def rw_spectrum(self, v):
        self._rw_spectrum = list(v)

    @attribute(dtype=int, access=AttrWriteType.READ_WRITE)
    def counter(self):
        return getattr(self, "_counter", 0)

    @counter.write
    def counter(self, v):
        self._counter = v

    @attribute(dtype=float)
    def tab_a(self):
        return 1.0

    @attribute(dtype=float)
    def tab_b(self):
        return 2.0

    @attribute(dtype=float)
    def slow(self):
        import time
        time.sleep(0.6)
        return 1.0

    @command(display_level=DispLevel.EXPERT)
    def ExpertCmd(self):
        pass

    @command(dtype_out=(float,))
    def Values(self):
        return [1.0, 2.5]

    @command
    def Push(self):
        self._ev += 1.0
        self.push_change_event("ev_double", self._ev)

    @command(dtype_in=str, dtype_out=str)
    def Echo(self, s):
        return s

    @command(dtype_in=(float,), dtype_out=float)
    def Sum(self, values):
        return float(sum(values))

    @command
    def Fail(self):
        raise RuntimeError("Fail on purpose")


@pytest.fixture(scope="session")
def device_name():
    """ Fully qualified name of a running PQTDevice (no database) """
    ctx = DeviceTestContext(PQTDevice, process=True, timeout=15)
    ctx.start()
    try:
        yield ctx.get_device_access()
    finally:
        ctx.stop()


def attr(device, name):
    """ Full attribute name for a device name with a #dbase=no fragment """
    dev, frag = device.split("#", 1)
    return "{0}/{1}#{2}".format(dev, name, frag)


@pytest.fixture
def no_tango_in_gui_thread(monkeypatch):
    """ Fail if any proxy is fetched from the GUI (main) thread """
    from PyQTango.core import proxies
    original = proxies.ProxyCache.get

    def guarded(self, name, timeout_ms=None, **kw):
        assert threading.current_thread() is not threading.main_thread(), \
            "Tango proxy requested from the GUI thread: " + name
        return original(self, name, timeout_ms, **kw)

    monkeypatch.setattr(proxies.ProxyCache, "get", guarded)
    yield


@pytest.fixture(autouse=True)
def _fast_release():
    """ Short grace period so tests can observe unsubscription """
    from PyQTango.models.attribute import TangoAttributeModel
    old = TangoAttributeModel.release_delay_ms
    TangoAttributeModel.release_delay_ms = 100
    yield
    TangoAttributeModel.release_delay_ms = old


def wait(qtbot, condition, timeout=5000):
    """ qtbot.waitUntil with truthy (not only bool) conditions """
    qtbot.waitUntil(lambda: bool(condition()), timeout=timeout)


def value_of(name):
    """ Last value of the shared model of ``name``, or None """
    from PyQTango.models import attribute_model
    v = attribute_model(name).last_value()
    return None if v is None else v.value


@pytest.fixture(autouse=True)
def _no_modal_change_confirmation(monkeypatch):
    """ The multiple change confirmation is modal: tests proceed unless they replace the hook """
    from PyQTango.widgets import confirm
    asked = []
    monkeypatch.setattr(confirm, "confirm_changes", lambda *a, **k: asked.append(a) or True)
    yield asked

# -- Proxies created by tests are never destroyed (PyTango #302) --------------------------------------
# Destroying a DeviceProxy while failing stateless subscriptions exist can deadlock the process
# (the destroying thread holds the GIL and waits for an event-consumer lock that a keep-alive thread
# holds while it waits for the GIL). PyQTango never destroys its proxies; the tests' own throwaway
# proxies are kept alive the same way.
def _keep_test_proxies():
    import tango as _tango
    from PyQTango.core.proxies import keep_alive
    if getattr(_tango.DeviceProxy, "_kept_by_tests", False):
        return
    base = _tango.DeviceProxy

    class DeviceProxy(base):
        _kept_by_tests = True

        def __init__(self, *args, **kwargs):
            base.__init__(self, *args, **kwargs)
            keep_alive(self)
    DeviceProxy.__name__ = DeviceProxy.__qualname__ = "DeviceProxy"
    _tango.DeviceProxy = DeviceProxy


_keep_test_proxies()
