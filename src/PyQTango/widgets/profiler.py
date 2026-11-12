# -*- coding: utf-8 -*-
"""
Polling profiler (Astor's PollingProfiler).

``QPollingProfiler(devices)`` reads the admin device's ``DevPollStatus`` for
each device in the background and shows every polled object: its period, the
time its last reading took, the time since the last update and the deltas
between its last records. The chart shows, as Astor's:

* Duration: the last reading time of each object (bars), against its period;
* Polling drift: delta minus period for each recorded delta;
* History: when each object was last read, on a time line (one row per object).

Objects whose last delta exceeds 1.5 x the period, or whose reading takes
longer than the period, are FAULT (red). Auto update reads again every 2 s.
"""

import time

import numpy as np
import pyqtgraph as pg

from ..qt import QtCore, QtWidgets, Qt, Signal
from ..core.pollstatus import read_poll_status
from ..core.proxies import proxy_cache
from ..models.worker import run_async
from .dialogs import TableModel, _SortProxy

__all__ = ["QPollingProfiler", "QPollingProfilerDialog", "MODES"]

MODES = ("Duration", "Polling Drift", "History")
UPDATE_MS = 2000
_HEADERS = ["Device", "Object", "Type", "State", "Period (ms)", "Duration (ms)", "Updated", "Deltas (ms)",
            "Drifts (ms)"]
_FAULT = "#ff8080"
_ON = "#00b000"


def _admin_of(device):
    p = proxy_cache.get(device)
    return proxy_cache.get(p.adm_name())


class QPollingProfiler(QtWidgets.QWidget):
    """ Polling profile of ``devices`` (all served by one admin device, or one each) """

    updated = Signal(list)          # [PolledElement]
    failed = Signal(str)

    def __init__(self, devices, parent=None, reader=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.devices = list(devices)
        #: reader(devices) -> [PolledElement] (blocking; tests replace it)
        self.reader = reader or self._read_devices
        self.elements = []
        self._busy = False
        self._read_at = 0.0
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = QtWidgets.QHBoxLayout()
        self.title = QtWidgets.QLabel(self)
        self.title.setStyleSheet("font-weight: bold;")
        bar.addWidget(self.title, 1)
        self.mode = QtWidgets.QComboBox(self)
        self.mode.addItems(MODES)
        self.mode.currentIndexChanged.connect(lambda _i: self._draw())
        bar.addWidget(self.mode)
        self.update_button = QtWidgets.QPushButton("Update", self)
        self.update_button.clicked.connect(lambda _c=False: self.update_now())
        bar.addWidget(self.update_button)
        self.auto = QtWidgets.QCheckBox("Auto Update", self)
        self.auto.toggled.connect(self.set_auto_update)
        bar.addWidget(self.auto)
        layout.addLayout(bar)
        self.warning = QtWidgets.QLabel(self)
        self.warning.setStyleSheet("color: #c00000;")
        layout.addWidget(self.warning)
        split = QtWidgets.QSplitter(Qt.Orientation.Vertical, self)
        self.plot = pg.PlotWidget(split, background="w")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        for axis in ("left", "bottom"):
            self.plot.getPlotItem().getAxis(axis).enableAutoSIPrefix(False)     # values are already in ms
        split.addWidget(self.plot)
        self.model = TableModel(_HEADERS, [], self)
        self.proxy = _SortProxy(self)
        self.proxy.setSourceModel(self.model)
        self.table = QtWidgets.QTableView(split)
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        split.addWidget(self.table)
        split.setSizes([300, 200])
        layout.addWidget(split, 1)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(UPDATE_MS)
        self.timer.timeout.connect(self.update_now)
        self._set_title()

    def _set_title(self):
        if len(self.devices) == 1:
            self.title.setText("Polling on:  " + self.devices[0])
        else:
            self.title.setText("Polling on:  {0} devices".format(len(self.devices)))

    @staticmethod
    def _read_devices(devices):
        out = []
        for dev in devices:
            plain = dev.split("#", 1)[0]
            if plain.startswith("tango://"):
                plain = plain.split("://", 1)[1].split("/", 1)[1]
            out += read_poll_status(_admin_of(dev), [plain])
        return out

    # -- Reading -----------------------------------------------------------------------------
    def update_now(self):
        if self._busy:
            return None
        self._busy = True
        return run_async(self.reader, self.devices, owner=self, source="Polling profiler",
                         on_done=self._read, on_error=self._failed)

    def _read(self, elements):
        self._busy = False
        self._read_at = time.time()
        self.elements = list(elements)
        faults = [e for e in self.elements if e.state == "FAULT"]
        polled = [e for e in self.elements if e.polled]
        text = "{0} polled, {1} externally triggered".format(len(polled), len(self.elements) - len(polled))
        if faults:
            text += " - {0} late or too slow: {1}".format(len(faults), ", ".join(e.name for e in faults[:5]))
        self.warning.setText(text if self.elements else "Nothing is polled.")
        self.warning.setStyleSheet("color: #c00000;" if faults else "color: #202020;")
        self._fill()
        self._draw()
        self.updated.emit(self.elements)

    def _failed(self, err):
        self._busy = False
        self.auto.setChecked(False)
        self.warning.setText(err.message)
        self.failed.emit(err.message)

    def set_auto_update(self, on):
        if on:
            self.update_now()
            self.timer.start()
        else:
            self.timer.stop()

    # -- Display -----------------------------------------------------------------------------
    def rows(self):
        return [list(r) for r in self.model.rows]

    def _fill(self):
        rows, colors = [], {}
        for i, e in enumerate(self.elements):
            rows.append([e.device, e.name, e.kind, e.state, e.period if e.polled else "triggered",
                         e.duration, e.last_update_text, ", ".join(str(d) for d in e.deltas),
                         ", ".join(str(d) for d in e.drifts())])
            if e.state == "FAULT":
                colors[(i, 3)] = _FAULT
        self.model.beginResetModel()
        self.model.rows = rows
        self.model.colors = colors
        self.model.endResetModel()
        self.table.resizeColumnsToContents()

    def _labels(self):
        multi = len({e.device for e in self.elements}) > 1
        return [e.full_name if multi else e.name for e in self.elements]

    def _draw(self):
        p = self.plot.getPlotItem()
        p.clear()
        if not self.elements:
            return
        mode = self.mode.currentText()
        labels = self._labels()
        n = len(self.elements)
        x = np.arange(n)
        axis = p.getAxis("bottom")
        left = p.getAxis("left")
        if mode == "History":
            # one row per object, a dot at each recorded reading, time 0 = now
            for i, e in enumerate(self.elements):
                if e.last_update < 0:
                    continue
                t = [-e.last_update / 1000.0]
                for d in e.deltas:
                    t.append(t[-1] - d / 1000.0)
                color = _FAULT if e.state == "FAULT" else _ON
                p.addItem(pg.ScatterPlotItem(x=t, y=[i] * len(t), size=7, brush=pg.mkBrush(color),
                                             pen=pg.mkPen("#404040")))
            left.setTicks([list(enumerate(labels))])
            axis.setTicks(None)
            p.setLabel("bottom", "Time before the last read (s)")
            p.setLabel("left", "")
            return
        left.setTicks(None)
        axis.setTicks([list(enumerate(labels))])
        if mode == "Duration":
            heights = [max(0.0, e.duration) for e in self.elements]
            brushes = [pg.mkBrush(_FAULT if e.state == "FAULT" else "#6fa8dc") for e in self.elements]
            p.addItem(pg.BarGraphItem(x=x, height=heights, width=0.6, brushes=brushes, pen=pg.mkPen("#404040")))
            p.setLabel("left", "Duration (ms)")
        else:
            for i, e in enumerate(self.elements):
                d = e.drifts()
                if d:
                    color = _FAULT if e.state == "FAULT" else "#3060c0"
                    p.addItem(pg.ScatterPlotItem(x=[i] * len(d), y=d, size=7, brush=pg.mkBrush(color),
                                                 pen=pg.mkPen("#404040")))
            p.addItem(pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen("#808080", style=Qt.PenStyle.DashLine)))
            p.setLabel("left", "Polling Drift (ms)")
        p.setLabel("bottom", "")
        p.setXRange(-0.5, n - 0.5, padding=0.02)

    def hideEvent(self, event):
        self.auto.setChecked(False)
        QtWidgets.QWidget.hideEvent(self, event)


class QPollingProfilerDialog(QtWidgets.QDialog):

    def __init__(self, devices, parent=None, reader=None):
        QtWidgets.QDialog.__init__(self, parent)
        self.setWindowTitle("Polling Profiler")
        layout = QtWidgets.QVBoxLayout(self)
        self.profiler = QPollingProfiler(devices, self, reader)
        layout.addWidget(self.profiler)
        close = QtWidgets.QPushButton("Dismiss", self)
        close.clicked.connect(self.close)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        self.resize(900, 620)
        self.profiler.update_now()
