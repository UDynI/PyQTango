# -*- coding: utf-8 -*-
"""
Attribute trends (ATK ``Trend`` and ``BooleanTrend``).

* :class:`TrendBuffer`: fixed-size numpy ring buffer of (time, value) samples.
  It holds one day at the refresh period by default, so memory is bounded.
* :class:`QTrend`: selection tree (device, then attribute, each on no axis, X,
  Y1 or Y2) next to a :class:`QTangoChart` with a time axis, plus the ATK
  toolbar and menu: Global settings, Start/Stop monitoring, Load and Save
  configuration, Zoom, Set refresh interval, Source, Add new attribute, Reset
  trend, Hide toolbar, Off line mode, View errors, Diagnostic. The attribute menu
  offers Set to X, Add to Y1, Add to Y2, Remove, Show min alarm, Show max alarm,
  Graphic properties and Attribute properties.
* :class:`QBooleanTrend`: one stepped lane per boolean attribute.

Values come from the shared attribute models: every value the model gets
(change event or polled read at the trend's refresh period) is a sample at its
device time stamp. An attribute on events that does not change is held: at
each refresh period its last value is repeated at the current time, so the
curve reaches "now" as in ATK. States plot as their integer code, enums as
their index, booleans as 0 or 1; an invalid quality or an error leaves a gap.

Settings are saved as JSON (``.trend.json``); :func:`parse_atk_settings` reads
ATK key:value trend files so existing configurations keep working.

@author: Michele Devetta <michele.devetta@cnr.it>
"""

import json
import math
import re
import time

import numpy as np
import tango

from ..qt import QtCore, QtGui, QtWidgets, Qt, Signal, QAction, QActionGroup, connect_destroyed
from ..core.names import split_attribute_name, normalize_name
from ..core.formatting import format_value, quality_name, state_name
from ..models.registry import attribute_model
from .plot import QTangoChart, DataView, AxisSettings
from .colors import quality_qcolor

__all__ = ["TrendBuffer", "TrendItem", "QTrend", "QBooleanTrend", "SEL_NONE", "SEL_X", "SEL_Y1", "SEL_Y2",
           "numeric_value", "parse_atk_settings", "load_settings_file", "split_index",
           "DEFAULT_REFRESH_MS", "DEFAULT_DURATION_S", "BUFFER_SECONDS"]

#: ATK selection codes
SEL_NONE = 0
SEL_X = 1
SEL_Y1 = 2
SEL_Y2 = 3
SEL_LABELS = {SEL_NONE: "", SEL_X: "X", SEL_Y1: "Y1", SEL_Y2: "Y2"}

DEFAULT_REFRESH_MS = 1000
DEFAULT_DURATION_S = 300.0
#: Buffers hold this many seconds at the refresh period
BUFFER_SECONDS = 86400
MAX_BUFFER = 2000000

SOURCES = (("Device", tango.DevSource.DEV), ("Cache", tango.DevSource.CACHE),
           ("Cache Device", tango.DevSource.CACHE_DEV))


class TrendBuffer(object):
    """ Ring buffer of (time, value) samples with increasing times """

    def __init__(self, capacity):
        self.capacity = max(2, int(capacity))
        self._t = np.empty(self.capacity)
        self._v = np.empty(self.capacity)
        self._start = 0
        self._n = 0

    def __len__(self):
        return self._n

    @property
    def nbytes(self):
        return self._t.nbytes + self._v.nbytes

    def clear(self):
        self._start = 0
        self._n = 0

    def last(self):
        if self._n == 0:
            return None
        i = (self._start + self._n - 1) % self.capacity
        return float(self._t[i]), float(self._v[i])

    def append(self, t, v):
        """ Add a sample; one not after the last one is dropped (returns False) """
        last = self.last()
        if last is not None and t <= last[0]:
            return False
        i = (self._start + self._n) % self.capacity
        self._t[i] = t
        self._v[i] = v
        if self._n < self.capacity:
            self._n += 1
        else:
            self._start = (self._start + 1) % self.capacity
        return True

    def extend(self, times, values):
        for t, v in zip(times, values):
            self.append(float(t), float(v))

    def _segments(self):
        end = self._start + self._n
        if end <= self.capacity:
            return [(self._start, end)]
        return [(self._start, self.capacity), (0, end - self.capacity)]

    def data(self):
        """ (times, values) in order (copies) """
        t = np.concatenate([self._t[a:b] for a, b in self._segments()]) if self._n else np.zeros(0)
        v = np.concatenate([self._v[a:b] for a, b in self._segments()]) if self._n else np.zeros(0)
        return t, v

    def window(self, t0, t1, extra=1):
        """ Samples with t0 <= t <= t1, plus ``extra`` samples on each side (lines reach the edges) """
        ts, vs = [], []
        for a, b in self._segments():
            seg = self._t[a:b]
            i0 = max(0, int(np.searchsorted(seg, t0, "left")) - extra)
            i1 = min(len(seg), int(np.searchsorted(seg, t1, "right")) + extra)
            if i1 > i0:
                ts.append(seg[i0:i1])
                vs.append(self._v[a + i0:a + i1])
        if not ts:
            return np.zeros(0), np.zeros(0)
        return np.concatenate(ts), np.concatenate(vs)

    def resize(self, capacity):
        t, v = self.data()
        self.capacity = max(2, int(capacity))
        self._t = np.empty(self.capacity)
        self._v = np.empty(self.capacity)
        self.clear()
        keep = min(len(t), self.capacity)
        if keep:
            self._t[:keep] = t[-keep:]
            self._v[:keep] = v[-keep:]
            self._n = keep


def split_index(name):
    """ "dev/attr[3]" -> ("dev/attr", 3); no index -> (name, None). A "#dbase=no"
    fragment may follow the index: "dev/attr[3]#dbase=no" -> ("dev/attr#dbase=no", 3) """
    m = re.match(r"^(.*)\[(\d+)\](#.*)?$", name.strip())
    if m:
        return m.group(1) + (m.group(3) or ""), int(m.group(2))
    return name.strip(), None


def numeric_value(value, index=None):
    """ Float sample for an AttrValue (NaN for an invalid quality or no value) """
    if value is None or value.value is None or value.quality == tango.AttrQuality.ATTR_INVALID:
        return math.nan
    v = value.value
    if index is not None:
        try:
            v = v[index]
        except (IndexError, TypeError):
            return math.nan
    try:
        if isinstance(v, tango.DevState):
            return float(int(v))
        if isinstance(v, (bool, np.bool_)):
            return 1.0 if v else 0.0
        return float(v)
    except (TypeError, ValueError):
        try:
            return float(int(v))
        except (TypeError, ValueError):
            return math.nan


def _short(name):
    """ "tango://host:port/a/b/c/d" -> "a/b/c/d" """
    if name.startswith("tango://"):
        rest = name[len("tango://"):]
        return rest.split("/", 1)[1] if "/" in rest else rest
    return name


def _unbind_model(model, connections, owner, stopped):
    """ Undo QTrend._bind for one model (also used once the trend is destroyed) """
    for sig, slot in connections:
        try:
            sig.disconnect(slot)
        except (TypeError, RuntimeError):
            pass
    try:
        model.request_period(owner, None)
        model.request_source(owner, None)
        if stopped:
            model.resume()
        model.release()
    except RuntimeError:
        pass        # the model went away first (application shutdown)


def _release_on_destroy(bound):
    # Must not capture the trend (it is being destroyed): ``bound`` lists what it holds
    def release(*_):
        models, bound["models"] = bound["models"], {}
        for m, connections in models.values():
            _unbind_model(m, connections, bound["owner"], bound["stopped"])
    return release


class TrendItem(object):
    """ One attribute (or spectrum element) of a trend """

    def __init__(self, name, selected=SEL_Y1, view=None, capacity=86400):
        self.name = name
        self.base, self.index = split_index(name)
        self.device, self.attribute = split_attribute_name(self.base)
        if self.index is not None:
            self.attribute = "{0}[{1}]".format(self.attribute, self.index)
        self.selected = selected
        self.view = view or DataView(name=name)
        self.show_min_alarm = False
        self.show_max_alarm = False
        self.buffer = TrendBuffer(capacity)
        self.model = None
        self.last = None
        self.error = None
        self.config = None
        self.connections = []
        self.tree_item = None
        self.last_sample_time = 0.0
        self.clock_offset = 0.0     # local time - device time of the last value

    def label(self, show_device=True):
        """ Name shown in the legend: without the tango://host:port/ prefix """
        return _short(self.name) if show_device else self.attribute

    def alarm(self, which):
        """ min or max alarm (float) from the configuration, or None """
        cfg = self.config
        if cfg is None:
            return None
        text = getattr(getattr(cfg, "alarms", None), which + "_alarm", None)
        try:
            return float(text)
        except (TypeError, ValueError):
            return None

    def to_dict(self):
        return {"name": self.name, "selected": self.selected, "show_min_alarm": self.show_min_alarm,
                "show_max_alarm": self.show_max_alarm, "view": self.view.to_dict()}


class QTrend(QtWidgets.QWidget):
    """ Trend of scalar attributes against time (or against an X attribute).

    Signals:
        itemsChanged(): attributes added, removed or moved between axes
        sampled(): new samples arrived (before the throttled redraw)
        redrawn(): the chart was updated
        monitoringChanged(bool)
    """

    itemsChanged = Signal()
    sampled = Signal()
    redrawn = Signal()
    monitoringChanged = Signal(bool)

    #: Accepted attribute kinds (QBooleanTrend narrows them)
    boolean = False

    def __init__(self, parent=None, refresh_ms=DEFAULT_REFRESH_MS, toolbar=True):
        QtWidgets.QWidget.__init__(self, parent)
        self._items = []
        self._refresh_ms = int(refresh_ms)
        self._monitoring = True
        self._offline = False
        self._source = None
        self._show_device = True
        self._title = ""
        self._dialogs = {}
        self._last_config = None
        # What the destroy handler must undo (it cannot use the widget, which is going away)
        self._owner = ("QTrend", id(self))
        self._bound = {"owner": self._owner, "models": {}, "stopped": False}
        connect_destroyed(self, _release_on_destroy(self._bound))
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toolbar = QtWidgets.QToolBar(self)
        self.toolbar.setIconSize(QtCore.QSize(18, 18))
        layout.addWidget(self.toolbar)
        self.splitter = QtWidgets.QSplitter(Qt.Orientation.Horizontal, self)
        self.tree = QtWidgets.QTreeWidget(self.splitter)
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Attribute", "Axis", "Value", "Quality"])
        self.tree.setRootIsDecorated(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.itemClicked.connect(self._tree_clicked)
        self.tree.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DropOnly)
        self.tree.setAcceptDrops(True)
        self.tree.viewport().installEventFilter(self)
        self.chart = QTangoChart(self.splitter, time_axis=True)
        self.chart.display_duration = DEFAULT_DURATION_S
        # Data file operations cover the whole buffers, not only the drawn window
        self.chart.save_data = self.save_data
        self.chart.load_data = self.load_data
        self.chart.plot_item.vb.sigXRangeChanged.connect(self._view_moved)
        self.chart.zoomed.connect(self.schedule_redraw)
        self.chart.durationChanged.connect(lambda _: self.schedule_redraw())
        self.splitter.addWidget(self.tree)
        self.splitter.addWidget(self.chart)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([360, 640])
        layout.addWidget(self.splitter, 1)
        self.date_label = QtWidgets.QLabel(self)
        layout.addWidget(self.date_label)
        self._build_actions()
        self.toolbar.setVisible(toolbar)
        self._tick = QtCore.QTimer(self)
        self._tick.setInterval(self._refresh_ms)
        self._tick.timeout.connect(self._hold_samples)
        self._tick.start()
        self._redraw_timer = QtCore.QTimer(self)
        self._redraw_timer.setSingleShot(True)
        self._redraw_timer.setInterval(min(250, self._refresh_ms))
        self._redraw_timer.timeout.connect(self.redraw)
        self.setAcceptDrops(True)

    # -- Actions ---------------------------------------------------------------
    def _icon(self, name):
        sp = getattr(QtWidgets.QStyle.StandardPixmap, name)
        return self.style().standardIcon(sp)

    def _build_actions(self):
        A = QAction
        self.actions = {}

        def act(key, text, slot, icon=None, checkable=False, toolbar=True):
            a = A(text, self)
            if icon:
                a.setIcon(self._icon(icon))
            a.setToolTip(text)
            a.setCheckable(checkable)
            if checkable:
                a.toggled.connect(slot)
            else:
                a.triggered.connect(lambda _c=False, s=slot: s())
            self.actions[key] = a
            if toolbar:
                self.toolbar.addAction(a)
            return a

        # ATK order: Load, Save, Global settings, Zoom, Start/Stop, refresh interval, Add, Reset
        act("load", "Load configuration", self.load_configuration_dialog, "SP_DialogOpenButton")
        act("save", "Save configuration", self.save_configuration_dialog, "SP_DialogSaveButton")
        act("options", "Global settings", self.show_global_settings, "SP_FileDialogDetailedView")
        act("zoom", "Zoom", self.chart.set_rect_zoom, "SP_FileDialogContentsView", checkable=True)
        act("start_stop", "Stop monitoring", self.toggle_monitoring, "SP_MediaPause")
        act("time", "Set refresh interval", self.ask_refresh_interval, "SP_BrowserReload")
        act("add", "Add new attribute", self.add_attribute_dialog, "SP_FileDialogNewFolder")
        act("reset", "Reset trend", self.reset, "SP_DialogResetButton")
        act("toolbar", "Hide toolbar", self.toggle_toolbar, toolbar=False)
        act("offline", "Off line mode", self.set_offline, checkable=True, toolbar=False)
        act("errors", "View errors", self.show_errors, toolbar=False)
        act("diagnostic", "Diagnostic", self.show_diagnostic, toolbar=False)
        self.source_actions = {}
        group = QActionGroup(self)
        for label, src in SOURCES:
            a = A(label, self)
            a.setCheckable(True)
            a.setChecked(src == tango.DevSource.CACHE_DEV)
            a.triggered.connect(lambda _c=False, s=src: self.set_source(s))
            group.addAction(a)
            self.source_actions[int(src)] = a

    def build_menu(self, menu=None):
        """ The trend menu (ATK's toolbar menu) """
        menu = menu or QtWidgets.QMenu(self)
        a = self.actions
        for key in ("load", "save", "options", "zoom", "start_stop", "time"):
            menu.addAction(a[key])
        src = menu.addMenu("Source")
        for _, s in SOURCES:
            src.addAction(self.source_actions[int(s)])
        for key in ("add", "reset", "toolbar", "offline", "errors", "diagnostic"):
            menu.addAction(a[key])
        return menu

    # -- Items -----------------------------------------------------------------
    def items(self):
        return list(self._items)

    def item(self, name):
        key = normalize_name(name)
        for it in self._items:
            if normalize_name(it.name) == key:
                return it
        return None

    def capacity(self):
        return int(min(MAX_BUFFER, max(1000, BUFFER_SECONDS * 1000 / max(1, self._refresh_ms))))

    def accepts(self, cfg):
        """ True for attribute configurations this trend can plot """
        if cfg is None:
            return True
        dt = cfg.data_type
        if self.boolean:
            return cfg.data_format == tango.AttrDataFormat.SCALAR and dt == tango.CmdArgType.DevBoolean
        if dt in (tango.CmdArgType.DevString, tango.CmdArgType.DevEncoded):
            return False
        return cfg.data_format in (tango.AttrDataFormat.SCALAR, tango.AttrDataFormat.SPECTRUM)

    def add_attribute(self, name, selected=SEL_Y1, view=None):
        """ Add one attribute ("dev/attr", or "dev/attr[i]" for a spectrum element) """
        if isinstance(name, (list, tuple)):
            return [self.add_attribute(n, selected) for n in name]
        existing = self.item(name)
        if existing is not None:
            if existing.selected != selected:
                self.set_selected(name, selected)
            return existing
        it = TrendItem(name, selected, view, capacity=self.capacity())
        if view is None:
            it.view = DataView(name=name, color=self.chart.next_color())
        if self.boolean:
            it.view.step = True
        it.view.axis = "y2" if selected == SEL_Y2 else "y1"
        self._items.append(it)
        self._bind(it)
        self._add_tree_item(it)
        self.itemsChanged.emit()
        self.schedule_redraw()
        return it

    def remove_attribute(self, name):
        it = self.item(name)
        if it is None:
            return
        self._unbind(it)
        self._items.remove(it)
        for curve in self._curve_names(it):
            if curve in self.chart.curve_names():
                self.chart.remove_curve(curve)
        self._remove_tree_item(it)
        self.itemsChanged.emit()
        self.schedule_redraw()

    def clear(self):
        for it in list(self._items):
            self.remove_attribute(it.name)

    def set_selected(self, name, selected):
        it = self.item(name)
        if it is None:
            return
        if selected == SEL_X:
            for other in self._items:
                if other is not it and other.selected == SEL_X:
                    other.selected = SEL_NONE
                    self._update_tree_item(other)
        it.selected = selected
        if selected in (SEL_Y1, SEL_Y2):
            it.view.axis = "y2" if selected == SEL_Y2 else "y1"
        for curve in self._curve_names(it):
            if curve in self.chart.curve_names():
                self.chart.remove_curve(curve)
        self._update_tree_item(it)
        self.itemsChanged.emit()
        self.redraw()

    def set_show_alarm(self, name, which, on):
        it = self.item(name)
        if it is None:
            return
        setattr(it, "show_{0}_alarm".format(which), bool(on))
        if not on:
            curve = self._alarm_curve(it, which)
            if curve in self.chart.curve_names():
                self.chart.remove_curve(curve)
        self.redraw()

    def x_item(self):
        for it in self._items:
            if it.selected == SEL_X:
                return it
        return None

    # -- Model binding ---------------------------------------------------------
    def _bind(self, it):
        m = attribute_model(it.base)
        it.model = m
        it.connections = [(m.valueChanged, lambda v, it=it: self._on_value(it, v)),
                          (m.configChanged, lambda c, it=it: self._on_config(it, c)),
                          (m.errorChanged, lambda e, it=it: self._on_error(it, e))]
        for sig, slot in it.connections:
            sig.connect(slot)
        m.attach()
        # Requests, not settings: the model is shared with other widgets
        m.request_period(self._owner, self._refresh_ms)
        m.request_source(self._owner, self._source)
        if not self._monitoring:
            m.suspend()
        self._bound["models"][id(it)] = (m, it.connections)
        if m.config() is not None:
            self._on_config(it, m.config())
        if m.last_value() is not None:
            self._on_value(it, m.last_value())

    def _unbind(self, it):
        m = it.model
        if m is None:
            return
        self._bound["models"].pop(id(it), None)
        _unbind_model(m, it.connections, self._owner, not self._monitoring)
        it.connections = []
        it.model = None

    def _on_config(self, it, cfg):
        it.config = cfg
        if not self.accepts(cfg):
            it.error = "Boolean scalars only" if self.boolean else \
                "Not a numeric, state or boolean scalar (or spectrum element)"
        elif cfg.data_format == tango.AttrDataFormat.SPECTRUM and it.index is None:
            it.error = "Spectrum: add one element, as dev/attr[index]"
        self._update_tree_item(it)
        self.schedule_redraw()

    def _on_value(self, it, value):
        it.last = value
        if it.config is not None and (not self.accepts(it.config) or (
                it.config.data_format == tango.AttrDataFormat.SPECTRUM and it.index is None)):
            self._update_tree_item(it)
            return
        it.error = None
        it.clock_offset = time.time() - value.time
        if self._monitoring and not self._offline:
            if it.buffer.append(value.time, numeric_value(value, it.index)):
                it.last_sample_time = time.time()
                self.sampled.emit()
                self.schedule_redraw()
        self._update_tree_item(it)

    def _on_error(self, it, err):
        it.error = None if err is None else err.message
        if err is not None and self._monitoring and not self._offline:
            # On the device clock, like the values (the buffer drops samples out of order)
            if it.buffer.append(time.time() - it.clock_offset, math.nan):
                self.schedule_redraw()
        self._update_tree_item(it)

    def _hold_samples(self):
        """ Each period: repeat the last value of attributes on events that did not change """
        if not self._monitoring or self._offline:
            return
        now = time.time()
        added = False
        for it in self._items:
            m = it.model
            if m is None or it.last is None or it.error is not None or m.mode() != "events":
                continue
            if now - it.last_sample_time >= self._refresh_ms / 1000.0 * 0.9:
                if it.buffer.append(now - it.clock_offset, numeric_value(it.last, it.index)):
                    it.last_sample_time = now
                    added = True
        if added:
            self.sampled.emit()
            self.schedule_redraw()

    # -- Monitoring, refresh, source -------------------------------------------
    def is_monitoring(self):
        return self._monitoring

    def start(self):
        if self._monitoring:
            return
        self._monitoring = True
        self._bound["stopped"] = False
        for it in self._items:
            if it.model is not None:
                it.model.resume()
        self._tick.start()
        a = self.actions["start_stop"]
        a.setText("Stop monitoring")
        a.setToolTip("Stop monitoring")
        a.setIcon(self._icon("SP_MediaPause"))
        self.monitoringChanged.emit(True)

    def stop(self):
        if not self._monitoring:
            return
        self._monitoring = False
        self._bound["stopped"] = True
        for it in self._items:
            if it.model is not None:
                it.model.suspend()
        self._tick.stop()
        a = self.actions["start_stop"]
        a.setText("Start monitoring")
        a.setToolTip("Start monitoring")
        a.setIcon(self._icon("SP_MediaPlay"))
        self.monitoringChanged.emit(False)

    def toggle_monitoring(self):
        if self._monitoring:
            self.stop()
        else:
            self.start()

    def refresh_once(self):
        for it in self._items:
            if it.model is not None:
                it.model.refresh()

    def refresh_interval(self):
        return self._refresh_ms

    def set_refresh_interval(self, ms):
        ms = int(ms)
        if ms <= 0:
            raise ValueError("Invalid refresh interval")
        self._refresh_ms = ms
        self._tick.setInterval(ms)
        self._redraw_timer.setInterval(min(250, ms))
        cap = self.capacity()
        for it in self._items:
            if it.buffer.capacity != cap:
                it.buffer.resize(cap)
            if it.model is not None:
                it.model.request_period(self._owner, ms)

    def source(self):
        return tango.DevSource.CACHE_DEV if self._source is None else self._source

    def set_source(self, source):
        self._source = None if source == tango.DevSource.CACHE_DEV else source
        for s, a in self.source_actions.items():
            a.setChecked(s == int(source))
        for it in self._items:
            if it.model is not None:
                it.model.request_source(self._owner, self._source)

    def is_offline(self):
        return self._offline

    def set_offline(self, on=True):
        """ Off line mode: no new samples, the data stay browsable """
        self._offline = bool(on)
        a = self.actions["offline"]
        if a.isChecked() != self._offline:
            a.blockSignals(True)
            a.setChecked(self._offline)
            a.blockSignals(False)
        self.schedule_redraw()

    def reset(self):
        """ Reset trend: clear every buffer """
        for it in self._items:
            it.buffer.clear()
            it.last_sample_time = 0.0
        for name in list(self.chart.curve_names()):
            self.chart.remove_curve(name)
        self.chart.reset_zoom()
        self.schedule_redraw()

    def display_duration(self):
        return self.chart.display_duration

    def set_display_duration(self, seconds):
        self.chart.set_display_duration(seconds)
        self.schedule_redraw()

    def show_device_names(self):
        return self._show_device

    def set_show_device_names(self, on):
        self._show_device = bool(on)
        for name in list(self.chart.curve_names()):
            self.chart.remove_curve(name)
        self.labels_changed()
        self.redraw()

    def labels_changed(self):
        """ Item labels changed (device names shown or hidden) """

    def toggle_toolbar(self):
        self.set_toolbar_visible(not self.toolbar.isVisible() if self.isVisible() else self.toolbar.isHidden())

    def set_toolbar_visible(self, on):
        self.toolbar.setVisible(bool(on))
        self.actions["toolbar"].setText("Hide toolbar" if on else "Show toolbar")

    def is_toolbar_visible(self):
        return not self.toolbar.isHidden()

    # -- Drawing ---------------------------------------------------------------
    def schedule_redraw(self):
        if not self._redraw_timer.isActive():
            self._redraw_timer.start()

    def _view_moved(self, *_):
        if self._offline or self.chart.is_zoomed():
            self.schedule_redraw()

    def curve_key(self, it):
        """ Chart curve of ``it``: its label, made unique when two items share it
        (same attribute name on two devices with device names hidden) """
        label = it.label(self._show_device)
        same = [o for o in self._items if o.label(self._show_device) == label]
        n = next((i for i, o in enumerate(same) if o is it), 0)
        return label if n == 0 else "{0} ({1})".format(label, n + 1)

    def _curve_names(self, it):
        key = self.curve_key(it)
        return [key, key + " min alarm", key + " max alarm"]

    def _alarm_curve(self, it, which):
        return self.curve_key(it) + " {0} alarm".format(which)

    def _window(self):
        """ Time window to extract: the display window when following, else the visible range +/- one span """
        last = None
        for it in self._items:
            lt = it.buffer.last()
            if lt is not None and (last is None or lt[0] > last):
                last = lt[0]
        if last is None:
            return None
        live = not self._offline and not self.chart.is_zoomed()
        if live and math.isfinite(self.chart.display_duration):
            return last - self.chart.display_duration, last
        if live or self.x_item() is not None:
            # XY: the visible X range is in X-attribute units, not a time window
            return -math.inf, math.inf
        x0, x1 = self.chart.visible_x_range()
        span = max(x1 - x0, 1e-3)
        return x0 - span, x1 + span

    def curve_values(self, it, values):
        """ Values drawn for ``it`` (QBooleanTrend shifts them into lanes) """
        return values

    def redraw(self):
        xi = self.x_item()
        self.chart.set_time_axis(xi is None)
        win = self._window()
        drawn = set()
        for it in self._items:
            if it.selected not in (SEL_Y1, SEL_Y2):
                continue
            if win is None:
                continue
            t, v = it.buffer.window(*win) if math.isfinite(win[0]) else it.buffer.data()
            label = self.curve_key(it)
            it.view.name = label
            if xi is not None:
                xt, xv = xi.buffer.data()
                if len(xt) == 0:
                    continue
                x = np.interp(t, xt, xv, left=math.nan, right=math.nan)
                order = np.argsort(x, kind="stable")
                self.chart.set_curve(label, self.curve_values(it, v)[order], x=x[order], view=it.view)
            else:
                self.chart.set_curve(label, self.curve_values(it, v), x=t, view=it.view)
            drawn.add(label)
            for which in ("min", "max"):
                if not getattr(it, "show_{0}_alarm".format(which)) or xi is not None:
                    continue
                level = it.alarm(which)
                if level is None or len(t) == 0:
                    continue
                name = self._alarm_curve(it, which)
                view = DataView(name=name, axis=it.view.axis, color=it.view.color, line_style=2, width=1)
                self.chart.set_curve(name, [level, level], x=[t[0], t[-1]], view=view)
                drawn.add(name)
        for name in self.chart.curve_names():
            if name not in drawn:
                self.chart.remove_curve(name)
        self.date_label.setText(time.strftime("%d/%m/%Y %H:%M:%S") if xi is None else "")
        self.redrawn.emit()

    # -- Tree ------------------------------------------------------------------
    def _device_node(self, device, create=True):
        for i in range(self.tree.topLevelItemCount()):
            node = self.tree.topLevelItem(i)
            if normalize_name(node.data(0, Qt.ItemDataRole.UserRole) or "") == normalize_name(device):
                return node
        if not create:
            return None
        node = QtWidgets.QTreeWidgetItem([_short(device)])
        node.setToolTip(0, device)
        node.setData(0, Qt.ItemDataRole.UserRole, device)
        self.tree.addTopLevelItem(node)
        node.setExpanded(True)
        return node

    def _add_tree_item(self, it):
        parent = self._device_node(it.device)
        node = QtWidgets.QTreeWidgetItem([it.attribute, "", "", ""])
        node.setData(0, Qt.ItemDataRole.UserRole + 1, it.name)
        parent.addChild(node)
        parent.setExpanded(True)
        it.tree_item = node
        self._update_tree_item(it)
        for c in range(4):
            self.tree.resizeColumnToContents(c)
        self.tree.setColumnWidth(0, min(self.tree.columnWidth(0), 200))

    def _remove_tree_item(self, it):
        node = it.tree_item
        if node is None:
            return
        parent = node.parent()
        parent.removeChild(node)
        if parent.childCount() == 0:
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(parent))
        it.tree_item = None

    def _update_tree_item(self, it):
        node = it.tree_item
        if node is None:
            return
        pix = QtGui.QPixmap(12, 12)
        pix.fill(QtGui.QColor(it.view.color) if it.selected != SEL_NONE else QtGui.QColor("#d0d0d0"))
        node.setIcon(0, QtGui.QIcon(pix))
        node.setText(1, self.axis_text(it))
        if it.error:
            node.setText(2, "")
            node.setText(3, "")
            node.setToolTip(0, it.name + "\n" + it.error)
            node.setForeground(0, QtGui.QBrush(QtGui.QColor("red")))
            return
        node.setForeground(0, QtGui.QBrush(QtGui.QColor("black")))
        node.setToolTip(0, it.name)
        v = it.last
        if v is not None:
            cfg = it.config
            value = v.value
            if it.index is not None:
                try:
                    value = value[it.index]
                except (IndexError, TypeError):
                    value = None
            if isinstance(value, tango.DevState):
                text = state_name(value)
            else:
                text = format_value(value, cfg.format if cfg else "", cfg.data_type if cfg else None,
                                    list(getattr(cfg, "enum_labels", []) or []) if cfg else None)
            node.setText(2, text)
            node.setText(3, quality_name(v.quality).replace("ATTR_", ""))
            node.setForeground(3, QtGui.QBrush(quality_qcolor(v.quality)))

    def axis_text(self, it):
        return SEL_LABELS.get(it.selected, "")

    def _tree_clicked(self, node, column):
        name = node.data(0, Qt.ItemDataRole.UserRole + 1)
        if name and column == 1:
            it = self.item(name)
            self.set_selected(name, self.next_selection(it.selected))

    def next_selection(self, selected):
        """ Axis column click: none -> Y1 -> Y2 -> none (X only from the menu) """
        return {SEL_NONE: SEL_Y1, SEL_Y1: SEL_Y2, SEL_Y2: SEL_NONE, SEL_X: SEL_NONE}[selected]

    def item_menu(self, name):
        it = self.item(name)
        menu = QtWidgets.QMenu(self)
        menu.addAction("Set to X", lambda: self.set_selected(name, SEL_X))
        menu.addAction("Add to Y1", lambda: self.set_selected(name, SEL_Y1))
        menu.addAction("Add to Y2", lambda: self.set_selected(name, SEL_Y2))
        menu.addAction("Remove", lambda: self.remove_attribute(name))
        menu.addSeparator()
        for which in ("min", "max"):
            a = menu.addAction("Show {0} alarm".format(which))
            a.setCheckable(True)
            a.setChecked(getattr(it, "show_{0}_alarm".format(which)))
            a.toggled.connect(lambda on, w=which: self.set_show_alarm(name, w, on))
        menu.addSeparator()
        menu.addAction("Graphic properties", lambda: self.show_graphic_properties(name))
        menu.addAction("Attribute properties", lambda: self.show_attribute_properties(name))
        return menu

    def _tree_menu(self, pos):
        node = self.tree.itemAt(pos)
        name = node.data(0, Qt.ItemDataRole.UserRole + 1) if node is not None else None
        menu = self.item_menu(name) if name else self.build_menu()
        menu.exec(self.tree.viewport().mapToGlobal(pos))
        menu.deleteLater()

    def eventFilter(self, obj, event):
        # Drop of attribute names (text) on the selection tree
        et = event.type()
        if et in (QtCore.QEvent.Type.DragEnter, QtCore.QEvent.Type.DragMove):
            if event.mimeData().hasText():
                event.acceptProposedAction()
                return True
        elif et == QtCore.QEvent.Type.Drop and event.mimeData().hasText():
            self.drop_text(event.mimeData().text())
            event.acceptProposedAction()
            return True
        return QtWidgets.QWidget.eventFilter(self, obj, event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.drop_text(event.mimeData().text())
        event.acceptProposedAction()

    def drop_text(self, text):
        """ Add every "dev/attr" in a dropped text (one per line or space separated) """
        added = []
        for word in re.split(r"[\s,;]+", text or ""):
            if word.count("/") >= 3:
                added.append(self.add_attribute(word))
        return added

    # -- Dialog hooks ----------------------------------------------------------
    def ask_text(self, title, label, value=""):
        text, ok = QtWidgets.QInputDialog.getText(self, title, label, text=value)
        return text if ok else None

    def ask_open_path(self, title):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, title, "", "Trend settings (*.trend.json *.json *.txt);;"
                                                        "All files (*)")
        return path or None

    def ask_save_path(self, title):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, title, self._last_config or "",
                                                        "Trend settings (*.trend.json)")
        return path or None

    def error(self, text):
        QtWidgets.QMessageBox.critical(self, "Error", text)

    def add_attribute_dialog(self):
        text = self.ask_text("Add new attribute", "Attribute name (domain/family/member/attribute)")
        if not text:
            return None
        if text.strip().count("/") < 3:
            self.error("Invalid attribute name: " + text)
            return None
        return self.add_attribute(text.strip())

    def ask_refresh_interval(self):
        text = self.ask_text("Set refresh interval", "Enter refresh interval (ms)", str(self._refresh_ms))
        if text is None:
            return None
        try:
            self.set_refresh_interval(int(text))
        except ValueError:
            self.error("Invalid number !")
            return None
        return self._refresh_ms

    def show_global_settings(self):
        return self.chart.show_chart_properties()

    def show_graphic_properties(self, name):
        it = self.item(name)
        # Edit the item's own view: an item on no axis has no curve to edit
        return self.chart.show_view_properties(self.curve_key(it), view=it.view)

    def show_attribute_properties(self, name):
        from .attrprops import QAttributePropertyDialog
        it = self.item(name)
        dlg = QAttributePropertyDialog(it.model or it.base, self, read_only=self.read_only_properties)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.show()
        return dlg

    read_only_properties = False

    def show_errors(self):
        from .errors import QErrorHistory
        return self._single("errors", lambda: QErrorHistory())

    def show_diagnostic(self):
        from .diagnostic import QRefresherDiagnostic
        dlg = self._single("diagnostic", lambda: QRefresherDiagnostic(models=[it.base for it in self._items]))
        dlg.set_models([it.base for it in self._items])
        return dlg

    def _single(self, key, factory):
        w = self._dialogs.get(key)
        try:
            if w is not None:
                w.isVisible()
        except RuntimeError:
            w = None
        if w is None:
            w = factory()
            w.setWindowFlag(Qt.WindowType.Window, True)
            self._dialogs[key] = w
        w.show()
        w.raise_()
        return w

    # -- Settings --------------------------------------------------------------
    def settings(self):
        win = self.window()
        return {"format": "pyqtango-trend", "version": 1, "boolean": self.boolean, "title": self._title,
                "refresh_ms": self._refresh_ms, "source": int(self.source()),
                "display_duration": None if math.isinf(self.chart.display_duration) else self.chart.display_duration,
                "show_device_name": self._show_device, "toolbar_visible": self.is_toolbar_visible(),
                "tree_visible": not self.tree.isHidden(), "chart": self.chart.settings(),
                "window": {"pos": [win.x(), win.y()], "size": [win.width(), win.height()]},
                "items": [it.to_dict() for it in self._items]}

    def apply_settings(self, d):
        """ Replace the configuration (attributes included) with ``d`` """
        self.clear()
        self.chart.clear()
        if "chart" in d:
            self.chart.apply_settings(d["chart"])
        self.chart.set_time_axis(True)
        self._title = d.get("title", "")
        if "refresh_ms" in d:
            self.set_refresh_interval(d["refresh_ms"])
        if "source" in d:
            self.set_source(tango.DevSource(int(d["source"])))
        if "display_duration" in d:
            self.chart.display_duration = math.inf if d["display_duration"] is None else float(d["display_duration"])
        if "show_device_name" in d:
            self._show_device = bool(d["show_device_name"])
        if "toolbar_visible" in d:
            self.set_toolbar_visible(d["toolbar_visible"])
        if "tree_visible" in d:
            self.tree.setVisible(bool(d["tree_visible"]))
        for item in d.get("items", []):
            view = DataView.from_dict(item["view"]) if "view" in item else None
            it = self.add_attribute(item["name"], int(item.get("selected", SEL_Y1)), view)
            it.show_min_alarm = bool(item.get("show_min_alarm", False))
            it.show_max_alarm = bool(item.get("show_max_alarm", False))
        win = d.get("window")
        if win and self.window() is not self and self.window().isWindow() and win.get("size"):
            self.window().resize(*win["size"])
        self.redraw()

    def save_configuration(self, path):
        with open(path, "w") as f:
            json.dump(self.settings(), f, indent=1)
        self._last_config = path
        return path

    def load_configuration(self, path):
        d = load_settings_file(path)
        self.apply_settings(d)
        self._last_config = path
        return d

    def save_configuration_dialog(self):
        path = self.ask_save_path("Save configuration")
        if not path:
            return None
        if not path.endswith(".json"):
            path += ".trend.json"
        try:
            return self.save_configuration(path)
        except OSError as e:
            self.error("Failed to write {0}\n{1}".format(path, e))
            return None

    def load_configuration_dialog(self):
        path = self.ask_open_path("Load configuration")
        if not path:
            return None
        try:
            return self.load_configuration(path)
        except (OSError, ValueError, KeyError) as e:
            self.error("Failed to read {0}\n{1}".format(path, e))
            return None

    # -- Data files ------------------------------------------------------------
    def save_data(self, path):
        """ CSV of the whole buffers: one time column and one value column per attribute """
        from .plot import save_csv
        save_csv(path, {it.name: it.buffer.data() for it in self._items})
        return path

    def load_data(self, path):
        """ Load a data file written by :meth:`save_data` (goes off line, keeps the data browsable) """
        from .plot import load_csv
        data = load_csv(path)
        self.set_offline(True)
        for name, (t, v) in data.items():
            it = self.item(name) or self.add_attribute(name)
            it.buffer.clear()
            it.buffer.extend(t, v)
        self.redraw()
        return path

    def closeEvent(self, event):
        self.clear()
        QtWidgets.QWidget.closeEvent(self, event)


class QBooleanTrend(QTrend):
    """ Boolean attributes as stepped lanes sharing one time axis """

    boolean = True
    LANE = 1.5

    def __init__(self, parent=None, refresh_ms=DEFAULT_REFRESH_MS, toolbar=True):
        QTrend.__init__(self, parent, refresh_ms, toolbar)
        self.tree.setHeaderLabels(["Attribute", "Shown", "Value", "Quality"])
        self.chart.axes["y1"].autoscale = True
        self.chart.legend.setVisible(False)
        self.itemsChanged.connect(self._update_lanes)

    def labels_changed(self):
        self._update_lanes()

    def add_attribute(self, name, selected=SEL_Y1, view=None):
        if selected == SEL_Y2 or selected == SEL_X:
            selected = SEL_Y1
        return QTrend.add_attribute(self, name, selected, view)

    def set_selected(self, name, selected):
        QTrend.set_selected(self, name, SEL_Y1 if selected in (SEL_X, SEL_Y2) else selected)

    def next_selection(self, selected):
        return SEL_NONE if selected != SEL_NONE else SEL_Y1

    def axis_text(self, it):
        return "Yes" if it.selected != SEL_NONE else "No"

    def lanes(self):
        return [it for it in self._items if it.selected != SEL_NONE]

    def curve_values(self, it, values):
        lanes = self.lanes()
        i = lanes.index(it) if it in lanes else 0
        return (len(lanes) - 1 - i) * self.LANE + np.asarray(values, dtype=float)

    def _update_lanes(self):
        lanes = self.lanes()
        ticks = []
        for i, it in enumerate(lanes):
            base = (len(lanes) - 1 - i) * self.LANE
            ticks.append((base + 0.5, self.curve_key(it)))
        self.chart.plot_item.getAxis("left").setTicks([ticks, []])

    def item_menu(self, name):
        menu = QtWidgets.QMenu(self)
        it = self.item(name)
        menu.addAction("Hide" if it.selected != SEL_NONE else "Show",
                       lambda: self.set_selected(name, self.next_selection(it.selected)))
        menu.addAction("Remove", lambda: self.remove_attribute(name))
        menu.addSeparator()
        menu.addAction("Graphic properties", lambda: self.show_graphic_properties(name))
        menu.addAction("Attribute properties", lambda: self.show_attribute_properties(name))
        return menu


# -- Settings files ------------------------------------------------------------
def _atk_values(text):
    """ Values of one ATK key:value line: comma separated, '...' quoted """
    out, cur, quoted, i = [], "", False, 0
    while i < len(text):
        ch = text[i]
        if ch == "'":
            quoted = not quoted
        elif ch == "," and not quoted:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    out.append(cur.strip())
    return out


def _atk_color(vals):
    try:
        r, g, b = (int(v) for v in vals[:3])
        return "#{0:02x}{1:02x}{2:02x}".format(r, g, b)
    except (ValueError, TypeError):
        return None


def _bool(v):
    return str(v).strip().lower() in ("true", "1", "yes")


def parse_atk_settings(text):
    """ Settings dict (as :meth:`QTrend.settings`) from an ATK Trend key:value file """
    p = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        p[key.strip().lower()] = _atk_values(value)

    def get(key, default=None):
        v = p.get(key.lower())
        return v if v is not None else default

    def num(key, default, cast=float):
        v = get(key)
        try:
            return cast(v[0]) if v else default
        except (ValueError, TypeError):
            return default

    d = {"format": "pyqtango-trend", "version": 1, "imported_from": "atk"}
    if get("refresh_time"):
        d["refresh_ms"] = num("refresh_time", DEFAULT_REFRESH_MS, int)
    if get("source"):
        d["source"] = num("source", 2, int)
    if get("display_duration"):
        ms = num("display_duration", DEFAULT_DURATION_S * 1000)
        d["display_duration"] = None if (math.isinf(ms) or ms <= 0 or ms > 1e15) else ms / 1000.0
    for key, out in (("show_device_name", "show_device_name"), ("toolbar_visible", "toolbar_visible"),
                     ("tree_visible", "tree_visible")):
        if get(key):
            d[out] = _bool(get(key)[0])
    if get("frame_title"):
        d["title"] = get("frame_title")[0]
    if get("window_size"):
        try:
            d["window"] = {"size": [int(get("window_size")[0]), int(get("window_size")[1])]}
            if get("window_pos"):
                d["window"]["pos"] = [int(get("window_pos")[0]), int(get("window_pos")[1])]
        except (ValueError, IndexError):
            pass
    axes = {}
    for a in ("x", "y1", "y2"):
        s = AxisSettings(visible=a != "y2")
        found = False
        for sep in ("", "_"):
            pre = a + sep
            if get(pre + "visible"):
                s.visible = _bool(get(pre + "visible")[0])
                found = True
            if get(pre + "grid"):
                s.grid = _bool(get(pre + "grid")[0])
            if get(pre + "autoscale"):
                s.autoscale = _bool(get(pre + "autoscale")[0])
                found = True
            if get(pre + "min"):
                s.minimum = num(pre + "min", s.minimum)
            if get(pre + "max"):
                s.maximum = num(pre + "max", s.maximum)
            if get(pre + "scale"):
                s.log = num(pre + "scale", 0, int) == 1
            if get(pre + "autoscalemargin"):
                m = num(pre + "autoscalemargin", 0.0)
                s.margin = m / 100.0 if m > 1 else m
            if get(pre + "title"):
                s.title = get(pre + "title")[0]
        if found:
            axes[a] = s.to_dict()
    chart = {"axes": axes}
    if get("graph_title"):
        chart["title"] = get("graph_title")[0]
    if get("label_visible"):
        chart["legend"] = _bool(get("label_visible")[0])
    d["chart"] = chart
    items = []
    n = num("dv_number", 0, int)
    for i in range(n):
        name = get("dv{0}_name".format(i))
        if not name:
            continue
        pre = "dv{0}_".format(i)
        view = DataView(name=name[0])
        c = _atk_color(get(pre + "linecolor", []))
        if c:
            view.color = c
        view.width = num(pre + "linewidth", view.width, int)
        view.line_style = num(pre + "linestyle", 0, int) % 5
        view.view_type = num(pre + "viewtype", 0, int)
        bw = num(pre + "barwidth", 10, float)
        view.bar_width = 0.0 if bw > 1 else bw
        view.fill = num(pre + "fillstyle", 0, int) != 0
        fc = _atk_color(get(pre + "fillcolor", []))
        if fc and fc != view.color:
            view.fill_color = fc
        view.marker = num(pre + "markerstyle", 0, int) % 11
        view.marker_size = num(pre + "markersize", 6, int)
        mc = _atk_color(get(pre + "markercolor", []))
        if mc and mc != view.color:
            view.marker_color = mc
        view.a0 = num(pre + "a0", 0.0)
        view.a1 = num(pre + "a1", 1.0)
        view.a2 = num(pre + "a2", 0.0)
        selected = num(pre + "selected", SEL_Y1, int)
        view.axis = "y2" if selected == SEL_Y2 else "y1"
        items.append({"name": name[0], "selected": selected,
                      "show_min_alarm": _bool((get(pre + "showminalarm") or ["false"])[0]),
                      "show_max_alarm": _bool((get(pre + "showmaxalarm") or ["false"])[0]),
                      "view": view.to_dict()})
    d["items"] = items
    return d


def load_settings_file(path):
    """ Trend settings from a JSON file or an ATK key:value file """
    with open(path) as f:
        text = f.read()
    stripped = text.lstrip()
    if stripped.startswith("{"):
        d = json.loads(text)
        if not isinstance(d, dict) or "items" not in d:
            raise ValueError("{0}: not a trend configuration".format(path))
        return d
    d = parse_atk_settings(text)
    if not d["items"] and "dv_number" not in text:
        raise ValueError("{0}: not a trend configuration".format(path))
    return d
