# -*- coding: utf-8 -*-
"""
Render the screenshots of the PyQTango documentation (docs/images/*.png).

    cd PyQTango
    PYQTANGO_QT_API=pyqt6 QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=2 python docs/make_screenshots.py
    python docs/make_screenshots.py value_label trend      # only some images

The script starts the test database of ``tests/`` (``TANGO_HOST`` points to it),
registers and runs the documentation device ``lab/laser/1`` (``DocDevice`` below,
the same script in ``--server`` mode) and the polled test device ``test/pqt/1``.
Every widget is built the way the documentation shows it, given time to read
its attributes, then grabbed. Rendering offscreen with ``QT_SCALE_FACTOR=2``
gives sharp images; ``docs/images/sizes.json`` keeps the logical sizes.
"""

import json
import math
import os
import sys
import time

import numpy as np
import tango
from tango import AttrWriteType, AttrQuality, DevState, DispLevel
from tango.server import Device, attribute, command

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
IMAGES = os.path.join(HERE, "images")
sys.path.insert(0, os.path.join(ROOT, "tests"))      # dbserver.py, pqtserver.py


# -- The documentation device ---------------------------------------------------------------------

class DocDevice(Device):
    """ A small laser-lab device with one attribute of each kind """

    def init_device(self):
        super().init_device()
        self._current = 120.5
        self._gain = 25
        self._pump = True
        self._mode = 1
        self._message = "Ready for scan"
        self._profile = [0.2, 0.5, 0.9, 1.0, 0.9, 0.5, 0.2]
        self.set_state(DevState.ON)
        self.set_status("Laser ready.\nShutter open, cooling OK.")

    @attribute(dtype=float, unit="°C", format="%5.1f", label="Temperature")
    def temperature(self):
        return 21.0 + 0.4 * math.sin(time.time() / 3.0)

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE, unit="mA", format="%6.2f", label="Current",
               min_value=0, max_value=500, max_alarm=450, memorized=True)
    def current(self):
        return self._current

    @current.write
    def current(self, v):
        self._current = v

    @attribute(dtype=float, unit="W", format="%5.2f", label="Power", max_alarm=12.0)
    def power(self):
        return 12.7

    @attribute(dtype=int, access=AttrWriteType.READ_WRITE, format="%4d", label="Gain", min_value=1,
               max_value=1000)
    def gain(self):
        return self._gain

    @gain.write
    def gain(self, v):
        self._gain = v

    @attribute(dtype=bool, access=AttrWriteType.READ_WRITE, label="Pump")
    def pump(self):
        return self._pump

    @pump.write
    def pump(self, v):
        self._pump = v

    @attribute(dtype=bool, label="Interlock")
    def interlock(self):
        return False

    @attribute(dtype=tango.DevEnum, access=AttrWriteType.READ_WRITE, label="Mode",
               enum_labels=["Idle", "Scan", "Calibrate"])
    def mode(self):
        return self._mode

    @mode.write
    def mode(self, v):
        self._mode = v

    @attribute(dtype=str, access=AttrWriteType.READ_WRITE, label="Message")
    def message(self):
        return self._message

    @message.write
    def message(self, v):
        self._message = v

    @attribute(dtype=float, label="Offset", display_level=DispLevel.EXPERT, unit="mV")
    def offset(self):
        return 0.35

    @attribute(dtype=(float,), max_dim_x=400, label="Waveform", unit="V")
    def waveform(self):
        x = np.linspace(0, 4 * np.pi, 300)
        return np.sin(x) * np.exp(-x / 8) + 0.03 * np.sin(17 * x)

    @attribute(dtype=(float,), max_dim_x=16, access=AttrWriteType.READ_WRITE, label="Profile")
    def profile(self):
        return self._profile

    @profile.write
    def profile(self, v):
        self._profile = list(v)

    @attribute(dtype=(str,), max_dim_x=8, label="Channels")
    def channels(self):
        return ["Seed", "Amplifier", "Compressor", "Diagnostics"]

    @attribute(dtype=(DevState,), max_dim_x=8, label="Channel states")
    def channel_states(self):
        return [DevState.ON, DevState.ON, DevState.ALARM, DevState.FAULT]

    @attribute(dtype=(bool,), max_dim_x=8, label="Channel enabled")
    def channel_enabled(self):
        return [True, True, False, True]

    @attribute(dtype=((float,),), max_dim_x=256, max_dim_y=256, label="Camera")
    def camera(self):
        y, x = np.mgrid[0:120, 0:160]
        r = np.hypot(x - 85, y - 55)
        return np.exp(-r ** 2 / 600.0) * (1 + 0.3 * np.cos(r / 2.5)) + 0.05 * np.cos(x / 7.0)

    @attribute(dtype=((str,),), max_dim_x=4, max_dim_y=4, label="Settings table")
    def settings_table(self):
        return [["Seed", "800 nm", "on"], ["Amplifier", "1 kHz", "on"], ["Compressor", "35 fs", "off"]]

    @attribute(dtype=tango.DevEncoded, label="Snapshot")
    def snapshot(self):
        y, x = np.mgrid[0:96, 0:128]
        img = (127 + 127 * np.sin(x / 9.0) * np.cos(y / 11.0)).astype(np.uint8)
        enc = tango.EncodedAttribute()
        enc.encode_gray8(img)
        return enc

    @command
    def Start(self):
        self.set_state(DevState.RUNNING)

    @command
    def Stop(self):
        self.set_state(DevState.ON)

    @command(dtype_in=str, dtype_out=str, doc_in="Any text", doc_out="The same text")
    def Echo(self, s):
        return s

    @command(dtype_in=(float,), dtype_out=float, doc_in="Numbers to add", doc_out="Their sum")
    def Sum(self, values):
        return float(sum(values))

    @command(display_level=DispLevel.EXPERT)
    def Calibrate(self):
        pass


# -- Rendering ----------------------------------------------------------------------------------------

SHOTS = []


def shot(name):
    """ Register a function returning (widget, ready condition) for images/<name>.png """
    def deco(fn):
        SHOTS.append((name, fn))
        return fn
    return deco


class Env(object):
    """ What the shot functions need: the app, the device names, helpers """

    def __init__(self, app, dev, tango_host, poll_dev):
        self.app, self.dev, self.tango_host, self.poll_dev = app, dev, tango_host, poll_dev

    def attr(self, name):
        return self.dev + "/" + name

    def wait(self, cond, timeout=8.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            self.app.processEvents()
            try:
                if cond():
                    break
            except Exception:  # noqa: BLE001 (not ready yet)
                pass
            time.sleep(0.02)
        for _ in range(10):
            self.app.processEvents()
            time.sleep(0.01)


def framed(title, rows, width=None):
    """ A small panel: one widget per row with a label on the left """
    from PyQTango.qt import QtWidgets
    w = QtWidgets.QWidget()
    form = QtWidgets.QFormLayout(w)
    for label, widget in rows:
        form.addRow(label, widget)
    if width:
        w.setFixedWidth(width)
    w.setWindowTitle(title)
    return w


def wrap(widget, width=None, height=None):
    from PyQTango.qt import QtWidgets
    w = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(w)
    lay.addWidget(widget)
    if width or height:
        w.resize(width or w.sizeHint().width(), height or w.sizeHint().height())
    return w


# -- Attribute viewers -----------------------------------------------------------------------------

@shot("value_label")
def _(env):
    from PyQTango.widgets import QValueLabel
    rows = []
    labels = []
    for name, kw in (("temperature", {}), ("current", {"showSetPoint": True}), ("power", {}),
                     ("mode", {}), ("waveform", {"maxItems": 4}),
                     ("power", {"qualityStyle": "background"})):
        v = QValueLabel()
        v.setModel(env.attr(name))
        for k, val in kw.items():
            getattr(v, "set" + k[0].upper() + k[1:])(val)
        labels.append(v)
        rows.append((name + ("" if not kw else "  " + ", ".join("{0}={1!r}".format(k, x) for k, x in kw.items())), v))
    return framed("QValueLabel", rows, 520), lambda: all(v.attributeValue() for v in labels)


@shot("state_status")
def _(env):
    from PyQTango.widgets import QStateLabel, QStatusViewer, QStateStatusViewer
    from PyQTango.qt import QtWidgets
    w = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(w)
    header = QStateStatusViewer()
    header.setDevice(env.dev)
    lay.addWidget(QtWidgets.QLabel("QStateStatusViewer"))
    lay.addWidget(header)
    row = QtWidgets.QHBoxLayout()
    state = QStateLabel()
    state.setDevice(env.dev)
    status = QStatusViewer()
    status.setDevice(env.dev)
    status.setFixedHeight(60)
    row.addWidget(QtWidgets.QLabel("QStateLabel"))
    row.addWidget(state)
    row.addWidget(QtWidgets.QLabel("QStatusViewer"))
    row.addWidget(status, 1)
    lay.addLayout(row)
    w.resize(560, 200)
    return w, lambda: state.attributeValue() is not None and status.toPlainText()


@shot("boolean_label")
def _(env):
    from PyQTango.widgets import QBooleanLabel
    a, b, c, d = QBooleanLabel(), QBooleanLabel(), QBooleanLabel(), QBooleanLabel()
    a.setModel(env.attr("pump"))
    b.setModel(env.attr("interlock"))
    c.setModel(env.attr("pump"))
    c.setDisplayMode("tick")
    d.setModel(env.attr("interlock"))
    d.setDisplayMode("tick")
    rows = [("pump (label)", a), ("interlock (label)", b), ("pump (tick)", c), ("interlock (tick)", d)]
    return framed("QBooleanLabel", rows, 300), lambda: all(x.attributeValue() for x in (a, b, c, d))


# -- Setters ----------------------------------------------------------------------------------------

@shot("setters")
def _(env):
    from PyQTango import widgets as W
    n, s, b, e, arr = W.QNumberSetter(), W.QStringSetter(), W.QBooleanSetter(), W.QEnumSetter(), W.QArraySetter()
    n.setModel(env.attr("current"))
    s.setModel(env.attr("message"))
    b.setModel(env.attr("pump"))
    e.setModel(env.attr("mode"))
    arr.setModel(env.attr("profile"))
    nc = W.QNumberComboSetter(values=["1", "10", "25", "100"])
    nc.setModel(env.attr("gain"))
    sc = W.QStringComboSetter(values=["Ready for scan", "Calibrating", "Maintenance"])
    sc.setModel(env.attr("message"))
    rows = [("QNumberSetter", n), ("QStringSetter", s), ("QBooleanSetter", b), ("QEnumSetter", e),
            ("QArraySetter", arr), ("QNumberComboSetter", nc), ("QStringComboSetter", sc)]
    ws = [n, s, b, e, arr, nc, sc]
    return framed("Setters", rows, 420), lambda: all(x.attributeValue() for x in ws) and n.text()


@shot("setter_states")
def _(env):
    from PyQTango.widgets import QNumberSetter
    editing, failed = QNumberSetter(), QNumberSetter()
    editing.setModel(env.attr("current"))
    failed.setModel(env.attr("current"))
    w = framed("Setter states", [("Being edited", editing), ("Write refused", failed)], 320)
    env.wait(lambda: editing.text() and failed.text())
    editing.setText("135.00")
    editing.textEdited.emit("135.00")
    failed.setText("900")
    failed.textEdited.emit("900")
    failed.returnPressed.emit()           # above max_value: refused, red frame
    return w, lambda: "red" in failed.styleSheet()


@shot("wheel")
def _(env):
    from PyQTango.widgets import QAttributeWheelEditor
    a, b = QAttributeWheelEditor(), QAttributeWheelEditor()
    a.setModel(env.attr("current"))
    b.setModel(env.attr("gain"))
    w = framed("QAttributeWheelEditor", [("current (%6.2f)", a), ("gain (%4d)", b)], 300)
    return w, lambda: a.attributeValue() and b.attributeValue()


@shot("switch")
def _(env):
    from PyQTango.widgets import QSwitchSetter, QSwitchButton
    s = QSwitchSetter()
    s.setModel(env.attr("pump"))
    off = QSwitchButton(onText="AUTO", offText="MANUAL")
    on = QSwitchButton()
    on.setChecked(True)
    w = framed("Switches", [("QSwitchSetter", s), ("QSwitchButton", on), ("QSwitchButton (custom)", off)], 330)
    return w, lambda: s.attributeValue()


# -- Device widgets -------------------------------------------------------------------------------

@shot("scalar_list")
def _(env):
    from PyQTango.widgets import QScalarListViewer
    v = QScalarListViewer()
    v.setDevice(env.dev)
    v.resize(560, 330)
    return v, lambda: v.models() and all(r[2][1].attributeValue() is not None for r in v._rows
                                         if hasattr(r[2][1], "attributeValue"))


@shot("command_combo")
def _(env):
    from PyQTango.widgets import QCommandCombo
    from PyQTango.qt import QtWidgets
    c = QCommandCombo()
    c.setDevice(env.dev)
    w = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(w)
    lay.addWidget(QtWidgets.QLabel("Commands:"))
    lay.addWidget(c, 1)
    w.resize(320, 50)
    return w, lambda: c.count() > 1


# -- Charts and trends -----------------------------------------------------------------------------

@shot("chart")
def _(env):
    from PyQTango.widgets.plot import QTangoChart, DataView
    c = QTangoChart(title="Scan")
    x = np.linspace(0, 10, 200)
    c.set_curve("Signal", np.sin(x) * np.exp(-x / 6), x=x)
    c.set_curve("Reference", np.cos(x) * 0.6, x=x, view=DataView(color="#0050c0", line_style=2))
    c.set_curve("Counts", 200 + 40 * np.sin(x / 2), x=x, axis="y2",
                view=DataView(color="#008000", marker=1, marker_size=4, width=0))
    c.set_axis_labels(x="Position (mm)", y="Signal (V)", y2="Counts")
    c.resize(640, 380)
    return c, lambda: True


@shot("chart_properties")
def _(env):
    from PyQTango.widgets.plot import QTangoChart
    from PyQTango.widgets.chartdialogs import QChartPropertiesDialog
    c = QTangoChart()
    c.set_curve("a", [1, 2, 3])
    d = QChartPropertiesDialog(c)
    d._keep = c
    return d, lambda: True


@shot("trend")
def _(env):
    from PyQTango.widgets.trend import QTrend, SEL_Y1, SEL_Y2, SEL_NONE
    t = QTrend(refresh_ms=1000)
    t.add_attribute(env.attr("current"), SEL_Y1)
    t.add_attribute(env.attr("power"), SEL_Y2)
    t.add_attribute(env.attr("temperature"), SEL_NONE)     # listed, not drawn
    t.set_show_device_names(False)
    t.set_offline(True)
    now = time.time()
    times = now - 600 + np.arange(600.0)
    data = {"temperature": 21 + 0.4 * np.sin(times / 40.0),
            "current": 120 + 6 * np.sin(times / 90.0) + 0.5 * np.sin(times / 7.0),
            "power": 12 + 0.8 * np.cos(times / 60.0)}
    for it in t.items():
        it.buffer.clear()
        it.buffer.extend(times, data[it.attribute])
    t.set_display_duration(600)
    t.redraw()
    t.resize(900, 400)
    return t, lambda: True


@shot("boolean_trend")
def _(env):
    from PyQTango.widgets.trend import QBooleanTrend
    t = QBooleanTrend(refresh_ms=1000)
    t.add_attribute(env.attr("pump"))
    t.add_attribute(env.attr("interlock"))
    t.set_offline(True)
    now = time.time()
    times = now - 300 + np.arange(300.0)
    for it, period in zip(t.items(), (60, 37)):
        it.buffer.clear()
        it.buffer.extend(times, ((times // period) % 2).astype(float))
    t.redraw()
    t.resize(800, 320)
    return t, lambda: True


@shot("spectrum")
def _(env):
    from PyQTango.widgets.spectrum import QSpectrumViewer
    v = QSpectrumViewer()
    v.setModel(env.attr("waveform"))
    v.setXRange(0, 20)
    v.resize(600, 340)
    return v, lambda: v.curve_names()


@shot("spectrum_lists")
def _(env):
    from PyQTango.widgets.spectrum import QStringSpectrumViewer, QStateSpectrumViewer, QBooleanSpectrumViewer
    from PyQTango.qt import QtWidgets
    w = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(w)
    views = []
    for cls, name in ((QStringSpectrumViewer, "channels"), (QStateSpectrumViewer, "channel_states"),
                      (QBooleanSpectrumViewer, "channel_enabled")):
        box = QtWidgets.QGroupBox(cls.__name__)
        bl = QtWidgets.QVBoxLayout(box)
        v = cls()
        v.setModel(env.attr(name))
        bl.addWidget(v)
        lay.addWidget(box)
        views.append(v)
    w.resize(720, 220)
    return w, lambda: all(v.attributeValue() for v in views)


@shot("image")
def _(env):
    from PyQTango.widgets.image import QImageViewer
    v = QImageViewer()
    v.setModel(env.attr("camera"))
    v.set_colormap("Inferno")
    v.show_profiles(True)
    v.resize(760, 560)

    def ready():
        if v.data() is None:
            return False
        v.set_profile_position(85, 55)      # through the beam
        return True
    return v, ready


@shot("image_string_raw")
def _(env):
    from PyQTango.widgets.image import QStringImageViewer, QRawImageViewer
    from PyQTango.qt import QtWidgets
    w = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(w)
    s = QStringImageViewer()
    s.setModel(env.attr("settings_table"))
    r = QRawImageViewer(toolbar=False)
    r.setModel(env.attr("snapshot"))
    for title, x, stretch in (("QStringImageViewer", s, 2), ("QRawImageViewer (GRAY8)", r, 3)):
        box = QtWidgets.QGroupBox(title)
        QtWidgets.QVBoxLayout(box).addWidget(x)
        lay.addWidget(box, stretch)
    w.resize(820, 300)
    return w, lambda: s.data() and r.data() is not None


# -- Dialogs and tools ------------------------------------------------------------------------------

@shot("attribute_properties")
def _(env):
    from PyQTango.widgets import QAttributePropertyDialog
    d = QAttributePropertyDialog(env.attr("current"))
    return d, lambda: d.fields["label"].text()


@shot("diagnostic")
def _(env):
    from PyQTango.widgets import QRefresherDiagnostic, QValueLabel
    keep = []
    for name in ("temperature", "current", "power", "gain"):
        v = QValueLabel()
        v.setModel(env.attr(name))
        keep.append(v)
    env.wait(lambda: all(v.attributeValue() for v in keep))
    d = QRefresherDiagnostic(models=[env.attr(n) for n in ("temperature", "current", "power", "gain")])
    d._keep = keep
    d.resize(900, 250)
    return d, lambda: True


@shot("error_dialog")
def _(env):
    from PyQTango.widgets import QErrorDialog
    from PyQTango.core.errors import error_from_exception
    try:
        tango.Except.throw_exception("API_AttrNotFound", "Attribute lasr_power not found",
                                     "DeviceImpl::get_attribute")
    except tango.DevFailed as e:
        rec = error_from_exception(e, "lab/laser/1/lasr_power")
    d = QErrorDialog(rec, "Read failed")
    return d, lambda: True


@shot("error_history")
def _(env):
    from PyQTango.widgets import QErrorHistory
    from PyQTango.models import error_history
    from PyQTango.core.errors import error_from_exception
    for reason, desc, src in (("API_DeviceTimedOut", "Timeout (3000 mS) exceeded on device lab/motor/2",
                               "lab/motor/2/position"),
                              ("API_AttrValueNotSet", "Value above the maximum (500)", "Write lab/laser/1/current")):
        try:
            tango.Except.throw_exception(reason, desc, "test")
        except tango.DevFailed as e:
            error_history().add(error_from_exception(e, src))
    h = QErrorHistory()
    h.resize(700, 220)
    return h, lambda: True


@shot("black_box")
def _(env):
    from PyQTango.widgets import QBlackBoxDialog
    from PyQTango.models import run_async
    from PyQTango.core.proxies import proxy_cache
    run_async(lambda: [proxy_cache.get(env.dev).command_inout("State") for _ in range(3)])
    d = QBlackBoxDialog(env.dev, depth=50)
    d.resize(860, 380)

    def ready():
        if not d.view.records():
            return False
        # Only the polling thread's requests: the other rows would publish this machine's name
        d.view.column.setCurrentText("Host")
        d.view.filter.setText("polling")
        return True
    return d, ready


@shot("polling_profiler")
def _(env):
    from PyQTango.widgets.profiler import QPollingProfilerDialog
    d = QPollingProfilerDialog([env.dev])
    d.resize(900, 560)
    return d, lambda: len(d.profiler.elements) >= 2


@shot("polling_panel")
def _(env):
    from PyQTango.widgets import QPollingPanel
    from PyQTango.core.db import DatabaseService
    panel = QPollingPanel()
    panel.show_devices(DatabaseService(env.tango_host), [env.poll_dev])
    panel.select_tab("attribute")
    panel.resize(620, 360)
    return panel, lambda: panel.models["attribute"].rowCount() > 0


@shot("job_progress")
def _(env):
    import threading
    from PyQTango.models import Job
    from PyQTango.widgets import QJobProgressDialog
    from PyQTango.qt import QtWidgets
    gate = threading.Event()

    def body(job, devices):
        job.set_progress(40, "Updating lab/motor/4")
        gate.wait(10)
    parent = QtWidgets.QWidget()
    dlg = QJobProgressDialog.run(Job(body, ["lab/motor/1"], title="Applying polling settings"), parent)
    dlg.show()
    dlg._gate, dlg._parent = gate, parent
    return dlg, lambda: dlg.value() == 40


@shot("table_dialog")
def _(env):
    from PyQTango.widgets import QTableDialog
    rows = [["PowerSupply/lab", "hosta", 1, "Running"], ["Motion/axis", "hosta", 2, "Running"],
            ["Camera/front", "hostb", 2, "Stopped"], ["TangoTest/test", "hostb", 0, "Running"]]
    d = QTableDialog("Servers", ["Server", "Host", "Level", "State"], rows, info="4 servers")
    d.resize(520, 260)
    return d, lambda: True


@shot("text_dialog")
def _(env):
    from PyQTango.widgets import QTextDialog
    text = "\n".join("2026-11-13 09:{0:02d}:00  PowerSupply/lab  started".format(i) for i in range(12))
    d = QTextDialog("Starter log", text)
    d.resize(520, 300)
    return d, lambda: True


@shot("multi_change")
def _(env):
    from PyQTango.widgets.confirm import QMultiChangeDialog
    d = QMultiChangeDialog([("polled_attr", "current, 1000"), ("poll_ring_depth", "20")], 12)
    return d, lambda: True


@shot("level_dialogs")
def _(env):
    from PyQTango.widgets.levels import QStartupLevelDialog, QServerPickerDialog, QLevelWalkerDialog
    from PyQTango.core.levels import START
    from PyQTango.qt import QtWidgets, QtCore
    w = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(w)
    a = QStartupLevelDialog(["PowerSupply/lab", "Motion/axis"])
    b = QServerPickerDialog(["PowerSupply/lab", "Motion/axis", "Camera/front", "TangoTest/test"])
    c = QLevelWalkerDialog(START, {"hosta": [1, 2]}, lambda host, level: None, pause_start=0)
    for x in (a, b, c):
        box = QtWidgets.QGroupBox(type(x).__name__)
        x.setWindowFlags(QtCore.Qt.WindowType.Widget)      # embed the dialog in the picture
        QtWidgets.QVBoxLayout(box).addWidget(x)
        lay.addWidget(box)
    c.start()
    w.resize(1100, 330)
    w._walker = c
    return w, lambda: c.question.isVisible()


# -- Building blocks ----------------------------------------------------------------------------------

@shot("console_navigation")
def _(env):
    from PyQTango.widgets import QConsole, QNavigationBar
    from PyQTango.qt import QtWidgets
    w = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(w)
    nav = QNavigationBar()
    nav.addLink("lab/laser/1")
    nav.search.setEditText("lab/laser/1")
    con = QConsole(dismiss_button=True)
    con.print("lab/laser/1 Echo(\"hello\")\n")
    con.print("Duration: 1 msec\nhello\n")
    con.separator()
    con.print("lab/laser/1 Sum([1, 2, 3.5])\nDuration: 1 msec\n6.5\n")
    for title, x in (("QNavigationBar", nav), ("QConsole", con)):
        lay.addWidget(QtWidgets.QLabel(title))
        lay.addWidget(x)
    w.resize(620, 360)
    return w, lambda: True


@shot("lazy_tree_property_table")
def _(env):
    from PyQTango.widgets import LazyTreeModel, TreeNode, PropertyTableModel, QPropertyTable
    from PyQTango.qt import QtWidgets

    class Domain(TreeNode):
        def populate(self, ctx):
            return [Family(n) for n in ("laser", "motor", "camera")]

    class Family(TreeNode):
        def populate(self, ctx):
            return [TreeNode(m, leaf=True) for m in ("1", "2")]

    w = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(w)
    tree = QtWidgets.QTreeView()
    model = LazyTreeModel(Domain("lab"))
    tree.setModel(model)
    tree.setHeaderHidden(True)
    found = []
    model.find_path(["laser"], found.append)
    table_model = PropertyTableModel()
    table_model.set_properties([("polled_attr", ["current", "1000", "power", "3000"]), ("wavelength", "800"),
                                ("description", "Front-end laser")])
    table_model.set_value(1, "1030")
    table = QPropertyTable(model=table_model)
    table.resizeRowsToContents()
    for title, x in (("LazyTreeModel", tree), ("QPropertyTable", table)):
        box = QtWidgets.QGroupBox(title)
        QtWidgets.QVBoxLayout(box).addWidget(x)
        lay.addWidget(box)
    w._model = model
    w.resize(760, 300)
    return w, lambda: found and (tree.expand(found[0]) or True) and model.rowCount(found[0]) == 2


@shot("editors")
def _(env):
    from PyQTango.widgets import QSearchableEditor, QCompleterLineEdit
    from PyQTango.qt import QtWidgets
    w = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(w)
    ed = QSearchableEditor()
    ed.setText("# Device properties\npolled_attr = current, 1000\nwavelength = 800\n"
               "description = Front-end laser\n")
    comp = QCompleterLineEdit(items=["lab/laser/1", "lab/motor/1", "lab/motor/2", "lab/camera/front"])
    comp.setPlaceholderText("Device name (completes as you type)")
    lay.addWidget(QtWidgets.QLabel("QSearchableEditor"))
    lay.addWidget(ed)
    lay.addWidget(QtWidgets.QLabel("QCompleterLineEdit"))
    lay.addWidget(comp)
    w.resize(560, 300)
    return w, lambda: True


@shot("icons")
def _(env):
    from PyQTango.widgets.icons import state_icon, host_icon
    from PyQTango.qt import QtWidgets, QtCore
    w = QtWidgets.QWidget()
    grid = QtWidgets.QGridLayout(w)
    for i, s in enumerate(("ON", "OFF", "ALARM", "FAULT", "MOVING", "UNKNOWN")):
        lab = QtWidgets.QLabel(s)
        lab.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        ic = QtWidgets.QLabel()
        ic.setPixmap(state_icon(s).pixmap(24, 24))
        ic.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(ic, 0, i)
        grid.addWidget(lab, 1, i)
    for i, s in enumerate(("running", "alarm", "moving", "off", "unreachable", "unknown")):
        lab = QtWidgets.QLabel(s)
        lab.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        ic = QtWidgets.QLabel()
        ic.setPixmap(host_icon(s).pixmap(32, 32))
        ic.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(ic, 2, i)
        grid.addWidget(lab, 3, i)
    return w, lambda: True


# -- Legacy widgets ----------------------------------------------------------------------------------

@shot("legacy_qattribute")
def _(env):
    from PyQTango import QAttribute
    ws = []
    rows = []
    for name in ("temperature", "current", "pump", "mode", "message", "State"):
        a = QAttribute()
        a.setTangoAttribute(env.attr(name))
        ws.append(a)
        rows.append((name, a))
    return framed("QAttribute", rows, 420), lambda: all(a.attributeValue() for a in ws)


@shot("legacy_executer")
def _(env):
    from PyQTango import QCommandExecuter
    e = QCommandExecuter()
    e.setDevice(env.dev)
    e.resize(460, 280)
    env.wait(lambda: e.selector.count() > 1)
    e.selector.setCurrentIndex(e.selector.findText("Sum"))
    e.arg.setText("1, 2, 3.5")
    e.on_released()
    return e, lambda: "6.5" in e.results.toPlainText()


@shot("legacy_digitdial_led")
def _(env):
    from PyQTango import QDigitDial, QStatusLed
    from PyQTango.qt import QtWidgets
    dial = QDigitDial("3.2f")
    dial.setValue(120.5)
    dial.setWriteValue(135.25)
    dial.setFixedSize(dial.size())          # its digits are placed by hand: keep its own size
    leds = QtWidgets.QWidget()
    ll = QtWidgets.QHBoxLayout(leds)
    for state, text in ((QStatusLed.On, "On"), (QStatusLed.Off, "Off"), (QStatusLed.Error, "Error")):
        led = QStatusLed()
        led.setFixedSize(24, 24)
        led.setState(state)
        ll.addWidget(led)
        ll.addWidget(QtWidgets.QLabel(text))
    ll.addStretch(1)
    w = framed("Legacy", [("QDigitDial(\"3.2f\")", dial), ("QStatusLed", leds)])
    return w, lambda: True


@shot("legacy_trees")
def _(env):
    from PyQTango import QDeviceTree, QAttributeTree
    from PyQTango.qt import QtWidgets
    host, port = env.tango_host.split(":")
    w = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(w)
    d = QDeviceTree(host, int(port), label="Devices", load_async=True)
    s = QDeviceTree(host, int(port), label="Servers", structure=QDeviceTree.ByServer, load_async=True)
    a = QAttributeTree(host, int(port), label="Attributes", load_async=True)
    done = []
    for t in (d, s, a):
        t.loaded.connect(lambda t=t: (done.append(t), t.expandToDepth(1)))
        box = QtWidgets.QGroupBox(type(t).__name__)
        QtWidgets.QVBoxLayout(box).addWidget(t)
        lay.addWidget(box)
    w.resize(900, 340)
    return w, lambda: len(done) == 3


# -- Main -------------------------------------------------------------------------------------------

def _wait_ping(name, proc, timeout=40.0):
    proxy = tango.DeviceProxy(name)
    deadline = time.time() + timeout
    while True:
        try:
            proxy.ping()
            return proxy
        except tango.DevFailed:
            if proc.poll() is not None or time.time() > deadline:
                raise RuntimeError("{0} did not start".format(name))
            time.sleep(0.3)


def _register(db, name, cls, server):
    info = tango.DbDevInfo()
    info.name, info._class, info.server = name, cls, server
    db.add_device(info)


def _step(text):
    print("..", text, flush=True)


def main():
    import subprocess
    import tempfile
    from dbserver import start_database, stop_database, populate
    only = set(sys.argv[1:])
    _step("database")
    db_proc, th = start_database(tempfile.mkdtemp(prefix="pqt-docs-"))
    os.environ["TANGO_HOST"] = th             # plain names everywhere, as in a control room
    servers = []
    try:
        populate(th)
        host, port = th.split(":")
        db = tango.Database(host, int(port))
        _register(db, "lab/laser/1", "DocDevice", "DocDevice/1")
        _register(db, "test/pqt/1", "PQTPoll", "PQTPoll/1")
        _step("device servers")
        env_vars = dict(os.environ, TANGO_HOST=th)
        servers.append(subprocess.Popen([sys.executable, os.path.abspath(__file__), "--server"], env=env_vars,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        servers.append(subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "pqtserver.py"), "1"],
                                        env=env_vars, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        laser = _wait_ping("lab/laser/1", servers[0])
        poll = _wait_ping("test/pqt/1", servers[1])
        laser.poll_attribute("temperature", 500)
        laser.poll_attribute("power", 1000)
        laser.write_attribute("current", 120.5)    # memorized: a meaningful set point
        poll.poll_attribute("current", 1000)
        time.sleep(1.5)                            # some polling history for the profiler
        _render(only, th)
    finally:
        for p in servers:
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        stop_database(db_proc)


def _render(only, tango_host):
    from PyQTango.qt import QtCore, QtGui, QtWidgets, API, sip
    _step("rendering")
    app = QtWidgets.QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    # The same numbers on every machine (spin boxes follow the locale: "120,50" in Italy)
    QtCore.QLocale.setDefault(QtCore.QLocale(QtCore.QLocale.Language.English, QtCore.QLocale.Country.UnitedStates))
    # Offscreen Qt maps "monospace" to whatever comes first: name real fixed-width fonts
    QtGui.QFont.insertSubstitutions("monospace", ["Menlo", "DejaVu Sans Mono", "Liberation Mono", "Courier New"])
    os.makedirs(IMAGES, exist_ok=True)
    env = Env(app, "lab/laser/1", tango_host, "test/pqt/1")
    sizes_path = os.path.join(IMAGES, "sizes.json")
    try:
        with open(sizes_path) as f:
            sizes = json.load(f)
    except (OSError, ValueError):
        sizes = {}
    try:
        for name, fn in SHOTS:
            if only and name not in only:
                continue
            widget, ready = fn(env)
            widget.show()
            env.wait(ready)
            env.wait(lambda: False, 0.4)      # last repaints
            widget.grab().save(os.path.join(IMAGES, name + ".png"))
            sizes[name] = [widget.width(), widget.height()]
            print("{0:28s} {1}x{2}".format(name, widget.width(), widget.height()), flush=True)
            gate = getattr(widget, "_gate", None)
            if gate is not None:
                gate.set()
            widget.close()
            sip.delete(widget)                # now: its models are released before the next shot
            env.wait(lambda: False, 0.1)
    finally:
        with open(sizes_path, "w") as f:
            json.dump(sizes, f, indent=1, sort_keys=True)
        from PyQTango.models import registry
        registry().shutdown()
    print("Rendered with", API, flush=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--server"]:
        from tango.server import run
        run((DocDevice,), args=["DocDevice", "1"])
    else:
        main()
