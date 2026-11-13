# -*- coding: utf-8 -*-
"""
QTangoChart: the chart PyQTango ships, on pyqtgraph (ATK ``JLChart``).

* Named curves (``set_curve``), each with a :class:`DataView` style: colour,
  width, line style, marker, line or bar, fill, a0 + a1*y + a2*y^2 transform,
  and the Y axis it belongs to (``y1`` on the left, ``y2`` on the right).
* An index, numeric or time X axis. In time mode ``display_duration`` keeps the
  last N seconds in view, as JLChart does for trends.
* Per-axis :class:`AxisSettings`: visible, autoscale or fixed min/max with an
  autoscale margin, log scale, grid, title.
* Zoom with the mouse (wheel, drag, rectangle) and Zoom back, which steps back
  through the zoom history and then returns to autoscale.
* The JLChart context menu: Chart properties, Data View properties, Save data
  File (CSV), Load data File, Show table, Show statistics, Zoom back, Print
  Chart, Save a snapshot of this chart (PNG or SVG).

pyqtgraph is imported here only (and in the modules built on this one), so
applications that never plot do not need it. It follows the binding PyQTango
selected, because :mod:`PyQTango.qt` imports it first.

QImageViewer moved to :mod:`PyQTango.widgets.image`; it is re-exported here.

@author: Michele Devetta <michele.devetta@cnr.it>
"""

import csv
import math
import time
from dataclasses import dataclass, field, asdict

import numpy as np

from ..qt import QtCore, QtGui, QtWidgets, Qt, Signal
import pyqtgraph as pg

__all__ = ["QTangoChart", "DataView", "AxisSettings", "PALETTE", "LINE_STYLES", "MARKERS",
           "QImageViewer", "statistics", "merge_table", "save_csv", "load_csv"]

# Curve colours, in order of creation (ATK's default data-view colours)
PALETTE = ("#c00000", "#0050c0", "#008000", "#c08000", "#8000c0", "#008080", "#404040",
           "#ff6000", "#0090ff", "#80a000")

#: JLDataView line styles (index = ATK STYLE_* value)
LINE_STYLES = ("Solid", "Dot", "Dash", "Long Dash", "Dash + Dot")
_PEN_STYLES = (Qt.PenStyle.SolidLine, Qt.PenStyle.DotLine, Qt.PenStyle.DashLine,
               Qt.PenStyle.CustomDashLine, Qt.PenStyle.DashDotLine)

#: JLDataView markers (index = ATK MARKER_* value): (label, pyqtgraph symbol, filled)
MARKERS = (("None", None, True), ("Dot", "o", True), ("Box", "s", True), ("Triangle", "t1", True),
           ("Diamond", "d", True), ("Star", "star", True), ("Vertical line", "|", True),
           ("Horizontal line", "_", True), ("Cross", "x", True), ("Circle", "o", False),
           ("Square", "s", False))

VIEW_LINE = 0
VIEW_BAR = 1

AXES = ("x", "y1", "y2")


@dataclass
class DataView:
    """ Style of one curve (ATK ``JLDataView``) """
    name: str = ""
    axis: str = "y1"
    color: str = "#c00000"
    width: int = 1
    line_style: int = 0
    marker: int = 0
    marker_size: int = 6
    marker_color: str = ""          # "" = curve colour
    view_type: int = VIEW_LINE
    bar_width: float = 0.8          # in X units; 0 = automatic
    fill: bool = False
    fill_color: str = ""            # "" = curve colour
    a0: float = 0.0
    a1: float = 1.0
    a2: float = 0.0
    visible: bool = True
    step: bool = False

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    def transform(self, y):
        if self.a0 == 0.0 and self.a1 == 1.0 and self.a2 == 0.0:
            return y
        return self.a0 + self.a1 * y + self.a2 * y * y


@dataclass
class AxisSettings:
    """ One axis (ATK ``JLAxis``) """
    visible: bool = True
    autoscale: bool = True
    minimum: float = 0.0
    maximum: float = 100.0
    margin: float = 0.0             # autoscale margin, fraction of the range
    log: bool = False
    grid: bool = True
    title: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class _Curve:
    view: DataView
    item: object
    bar: object = None
    x: np.ndarray = field(default_factory=lambda: np.zeros(0))
    y: np.ndarray = field(default_factory=lambda: np.zeros(0))
    style: dict = None          # view.to_dict() when the curve was last styled


def statistics(y):
    """ dict(count, min, max, mean, std) of the finite values of ``y`` """
    y = np.asarray(y, dtype=float)
    y = y[np.isfinite(y)]
    if len(y) == 0:
        return {"count": 0, "min": math.nan, "max": math.nan, "mean": math.nan, "std": math.nan}
    return {"count": int(len(y)), "min": float(y.min()), "max": float(y.max()),
            "mean": float(y.mean()), "std": float(y.std())}


def merge_table(curves):
    """ Rows (x, v1, v2, ...) over the union of the X values of ``[(x, y), ...]`` (None where missing) """
    xs = sorted(set().union(*[set(np.asarray(x, dtype=float).tolist()) for x, _ in curves])) if curves else []
    lookups = [dict(zip(np.asarray(x, dtype=float).tolist(), np.asarray(y, dtype=float).tolist()))
               for x, y in curves]
    return [[x] + [lk.get(x) for lk in lookups] for x in xs]


def save_csv(path, curves):
    """ Write ``{name: (x, y)}`` as CSV: one "name X" column and one "name" column per curve """
    names = list(curves)
    columns = []
    header = []
    for n in names:
        x, y = curves[n]
        header += [n + " X", n]
        columns += [list(np.asarray(x, dtype=float)), list(np.asarray(y, dtype=float))]
    rows = max((len(c) for c in columns), default=0)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for i in range(rows):
            w.writerow(["" if i >= len(c) or not np.isfinite(c[i]) else repr(float(c[i])) for c in columns])


def load_csv(path):
    """ Read a file written by :func:`save_csv`: ``{name: (x, y)}`` (NaN for empty cells) """
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return {}
    header = rows[0]
    if len(header) % 2:
        raise ValueError("{0}: expected pairs of X and value columns".format(path))
    out = {}
    for j in range(0, len(header), 2):
        name = header[j + 1]
        xs, ys = [], []
        for r in rows[1:]:
            if j + 1 >= len(r) or r[j] == "":
                continue
            xs.append(float(r[j]))
            ys.append(float(r[j + 1]) if r[j + 1] != "" else math.nan)
        out[name] = (np.array(xs), np.array(ys))
    return out


def _qcolor(c):
    return QtGui.QColor(c)


class QTangoChart(QtWidgets.QWidget):
    """ Chart of named curves on one or two Y axes.

    ``set_curve(name, y, x=None)`` creates or replaces the curve ``name``;
    without ``x`` points are drawn at 0, 1, 2... (``x_offset`` shifts them).

    Signals:
        zoomed(): the user zoomed (or the zoom history changed)
        curvesChanged(): a curve was added or removed
    """

    zoomed = Signal()
    curvesChanged = Signal()
    viewChanged = Signal(str)       # a DataView was edited (curve name)
    durationChanged = Signal(float)  # display duration (seconds, inf = everything)

    def __init__(self, parent=None, title=None, legend=True, time_axis=False):
        QtWidgets.QWidget.__init__(self, parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        axis_items = {"bottom": pg.DateAxisItem(orientation="bottom")} if time_axis else None
        self.plot_widget = pg.PlotWidget(self, background="w", axisItems=axis_items)
        self.plot_item = self.plot_widget.getPlotItem()
        self.plot_item.setMenuEnabled(False)
        self.plot_item.vb.setMenuEnabled(False)
        self.plot_item.hideButtons()
        self._time_axis = bool(time_axis)
        self.display_duration = math.inf     # seconds, time axis only
        # Second Y axis: its own ViewBox, X linked to the main one
        self.vb2 = pg.ViewBox(enableMenu=False)
        self.plot_item.scene().addItem(self.vb2)
        self.plot_item.getAxis("right").linkToView(self.vb2)
        self.vb2.setXLink(self.plot_item.vb)
        self.plot_item.vb.sigResized.connect(self._sync_views)
        for axis in ("left", "bottom", "right"):
            self.plot_item.getAxis(axis).setPen(pg.mkPen("#404040"))
            self.plot_item.getAxis(axis).setTextPen(pg.mkPen("#202020"))
            # Show the values as they are (JLChart): no "(x0.001)" rescaling of small ranges
            self.plot_item.getAxis(axis).enableAutoSIPrefix(False)
        self._title = ""
        if title:
            self.set_title(title)
        self.legend = self.plot_item.addLegend(labelTextColor="#202020") if legend else None
        self._curves = {}
        self._color_index = 0
        self.axes = {a: AxisSettings() for a in AXES}
        self.axes["y2"].visible = False
        self._zoom_stack = []
        self._prev_range = self._cur_range = None
        self._gesture = QtCore.QTimer(self)
        self._gesture.setSingleShot(True)
        self._gesture.setInterval(400)
        self.plot_item.vb.sigRangeChanged.connect(self._range_changed)
        self.vb2.sigRangeChanged.connect(self._range_changed)
        self.plot_item.vb.sigRangeChangedManually.connect(self._manual_zoom)
        self.vb2.sigRangeChangedManually.connect(self._manual_zoom)
        layout.addWidget(self.plot_widget)
        self.plot_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.plot_widget.customContextMenuRequested.connect(self._show_menu)
        self.setMinimumSize(320, 240)
        self._dialogs = {}
        self.apply_axes()

    # -- Curves ----------------------------------------------------------------
    def set_curve(self, name, y, x=None, x_offset=0, color=None, view=None, axis=None):
        """ Create or update a curve; returns its pyqtgraph PlotDataItem """
        y = np.asarray(y, dtype=float).ravel()
        if x is None:
            x = np.arange(len(y), dtype=float) + x_offset
        else:
            x = np.asarray(x, dtype=float).ravel()
        c = self._curves.get(name)
        if c is None:
            if view is None:
                view = DataView(name=name, color=color or self.next_color())
            else:
                view.name = name
            if axis is not None:
                view.axis = axis
            item = pg.PlotDataItem(name=name)
            c = _Curve(view=view, item=item)
            self._curves[name] = c
            self._style(c)          # before the legend takes its sample
            c.style = view.to_dict()
            self._attach(c)
            self.curvesChanged.emit()
        else:
            if view is not None:
                view.name = name
                snap = view.to_dict()
                if snap != c.style:
                    self.set_view(name, view)       # restyle only when the look changed
                else:
                    c.view = view
            elif axis is not None and axis != c.view.axis:
                c.view.axis = axis
                self._detach(c)
                self._attach(c)
        c.x, c.y = x, y
        self._draw(c)
        self._autoscale()
        return c.item

    def next_color(self):
        color = PALETTE[self._color_index % len(PALETTE)]
        self._color_index += 1
        return color

    def remove_curve(self, name):
        c = self._curves.pop(name, None)
        if c is not None:
            self._detach(c)
            self.curvesChanged.emit()

    def clear(self):
        for name in list(self._curves):
            self.remove_curve(name)
        self._color_index = 0
        self.reset_zoom()

    def curve_names(self):
        return list(self._curves)

    def curve_data(self, name):
        """ (x, y) arrays of a curve, as given (before the DataView transform) """
        c = self._curves[name]
        return c.x, c.y

    def curve_item(self, name):
        return self._curves[name].item

    def view(self, name):
        """ The DataView of a curve (edit it, then call :meth:`set_view` or :meth:`refresh_view`) """
        return self._curves[name].view

    def set_view(self, name, view):
        c = self._curves[name]
        moved = view.axis != c.view.axis
        if moved:
            self._detach(c)
        c.view = view
        if moved:
            self._attach(c)
        self.refresh_view(name)

    def refresh_view(self, name):
        c = self._curves[name]
        if c.view.axis not in ("y1", "y2"):
            c.view.axis = "y1"
        self._detach(c)
        self._style(c)
        c.style = c.view.to_dict()
        self._attach(c)
        self._draw(c)
        self._autoscale()
        self.viewChanged.emit(name)

    def _box(self, axis):
        return self.vb2 if axis == "y2" else self.plot_item.vb

    def _attach(self, c):
        box = self._box(c.view.axis)
        box.addItem(c.item)
        if c.view.axis == "y2" and not self.axes["y2"].visible:
            self.axes["y2"].visible = True
            self.apply_axes()
        if self.legend is not None:
            self.legend.addItem(c.item, c.view.name)

    def _detach(self, c):
        for item in (c.item, c.bar):
            if item is None:
                continue
            vb = item.getViewBox()
            if vb is not None:
                vb.removeItem(item)
        c.bar = None
        if self.legend is not None:
            self.legend.removeItem(c.item)

    def _style(self, c):
        v = c.view
        pen = pg.mkPen(_qcolor(v.color), width=max(0, v.width))
        pen.setStyle(_PEN_STYLES[v.line_style % len(_PEN_STYLES)])
        if v.line_style == 3:
            pen.setDashPattern([8, 4])
        line = v.width > 0 and v.view_type == VIEW_LINE
        _, symbol, filled = MARKERS[v.marker % len(MARKERS)]
        mcolor = _qcolor(v.marker_color or v.color)
        c.item.setPen(pen if line else None)
        c.item.setSymbol(symbol)
        if symbol is not None:
            c.item.setSymbolSize(v.marker_size)
            c.item.setSymbolPen(pg.mkPen(mcolor))
            c.item.setSymbolBrush(pg.mkBrush(mcolor) if filled else None)
        if v.fill and v.view_type == VIEW_LINE:
            fc = _qcolor(v.fill_color or v.color)
            fc.setAlpha(80)
            c.item.setFillLevel(0.0)
            c.item.setBrush(pg.mkBrush(fc))
        else:
            c.item.setFillLevel(None)
            c.item.setBrush(None)
        c.item.setVisible(v.visible)

    def _draw(self, c):
        v = c.view
        y = v.transform(c.y)
        log = self.axes[v.axis].log
        xlog = self.axes["x"].log
        c.item.setLogMode(xlog, log)
        if v.step and len(c.x) > 1:
            # Hold each value until the next sample (boolean lanes, states)
            c.item.setData(np.repeat(c.x, 2)[1:], np.repeat(y, 2)[:-1], connect="finite")
        else:
            c.item.setData(c.x, y, connect="finite")
        if v.view_type == VIEW_BAR and v.visible:
            width = v.bar_width
            if width <= 0:
                width = float(np.min(np.diff(c.x))) * 0.8 if len(c.x) > 1 else 0.8
            fc = _qcolor(v.fill_color or v.color)
            ok = np.isfinite(y)
            if c.bar is None:
                c.bar = pg.BarGraphItem(x=c.x[ok], height=y[ok], width=width, brush=fc,
                                        pen=pg.mkPen(_qcolor(v.color)))
                self._box(v.axis).addItem(c.bar)
            else:
                c.bar.setOpts(x=c.x[ok], height=y[ok], width=width, brush=fc, pen=pg.mkPen(_qcolor(v.color)))
        elif c.bar is not None:
            vb = c.bar.getViewBox()
            if vb is not None:
                vb.removeItem(c.bar)
            c.bar = None

    # -- Axes ------------------------------------------------------------------
    def set_title(self, title):
        self._title = title or ""
        self.plot_item.setTitle(self._title or None, color="#202020")

    def title(self):
        return self._title

    def set_axis_labels(self, x=None, y=None, y2=None):
        if x is not None:
            self.axes["x"].title = x
        if y is not None:
            self.axes["y1"].title = y
        if y2 is not None:
            self.axes["y2"].title = y2
        self.apply_axes()

    def is_time_axis(self):
        return self._time_axis

    def set_time_axis(self, on):
        on = bool(on)
        if on == self._time_axis:
            return
        self._time_axis = on
        axis = pg.DateAxisItem(orientation="bottom") if on else pg.AxisItem(orientation="bottom")
        self.plot_item.setAxisItems({"bottom": axis})
        axis.enableAutoSIPrefix(False)
        axis.setPen(pg.mkPen("#404040"))
        axis.setTextPen(pg.mkPen("#202020"))
        self.apply_axes()

    def set_display_duration(self, seconds):
        """ Time axis: seconds kept in view while X autoscales (None, 0 or inf = everything) """
        seconds = float(seconds) if seconds else math.inf
        if seconds < 0 or math.isnan(seconds):
            raise ValueError("Invalid display duration: {0}".format(seconds))
        self.display_duration = seconds
        self._autoscale()
        self.durationChanged.emit(seconds)

    def apply_axes(self):
        """ Apply :attr:`axes` (call after editing them) """
        pi = self.plot_item
        names = {"x": "bottom", "y1": "left", "y2": "right"}
        for a, side in names.items():
            s = self.axes[a]
            pi.getAxis(side).setLabel(s.title or None)   # PlotItem.setLabel would show the axis
            if s.visible:
                pi.showAxis(side)
            else:
                pi.hideAxis(side)
            pi.getAxis(side).setLogMode(s.log)
            pi.getAxis(side).setGrid(80 if s.grid and s.visible else False)
        for c in self._curves.values():
            self._draw(c)
        self._apply_ranges()

    def _apply_ranges(self):
        sx, s1, s2 = self.axes["x"], self.axes["y1"], self.axes["y2"]
        vb = self.plot_item.vb

        def rng(s):
            lo, hi = s.minimum, s.maximum
            if s.log:
                # A log axis cannot reach 0: keep six decades below the maximum
                hi = hi if hi > 0 else 1.0
                lo = lo if 0 < lo < hi else hi / 1e6
                lo, hi = math.log10(lo), math.log10(hi)
            return lo, hi

        if not sx.autoscale:
            vb.disableAutoRange(pg.ViewBox.XAxis)
            vb.setXRange(*rng(sx), padding=0)
        if s1.autoscale:
            vb.enableAutoRange(pg.ViewBox.YAxis)
            vb.setAutoPan(y=False)
        else:
            vb.disableAutoRange(pg.ViewBox.YAxis)
            vb.setYRange(*rng(s1), padding=0)
        if s2.autoscale:
            self.vb2.enableAutoRange(pg.ViewBox.YAxis)
        else:
            self.vb2.disableAutoRange(pg.ViewBox.YAxis)
            self.vb2.setYRange(*rng(s2), padding=0)
        vb.setDefaultPadding(max(0.0, s1.margin) if s1.autoscale else 0.02)
        self.vb2.setDefaultPadding(max(0.0, s2.margin) if s2.autoscale else 0.02)
        self._autoscale()

    def _autoscale(self):
        """ X autoscale, honouring the display duration on a time axis """
        if not self.axes["x"].autoscale or self._zoom_stack:
            return
        vb = self.plot_item.vb
        if self._time_axis and math.isfinite(self.display_duration):
            last = self.last_x()
            if last is None:
                return
            vb.disableAutoRange(pg.ViewBox.XAxis)
            vb.setXRange(last - self.display_duration, last, padding=0)
            # Y autoscale over the visible window only
            vb.setAutoVisible(y=True)
            self.vb2.setAutoVisible(y=True)
        else:
            vb.enableAutoRange(pg.ViewBox.XAxis)

    def last_x(self):
        last = None
        for c in self._curves.values():
            if len(c.x):
                m = np.nanmax(c.x)
                if np.isfinite(m) and (last is None or m > last):
                    last = float(m)
        return last

    def autoscale_once(self, axis):
        """ Fit one axis ("x", "y1" or "y2") to the data now, then keep it fixed (ATK 10) """
        box = self.vb2 if axis == "y2" else self.plot_item.vb
        which = pg.ViewBox.XAxis if axis == "x" else pg.ViewBox.YAxis
        box.enableAutoRange(which)
        box.updateAutoRange()
        rng = box.viewRange()[0 if axis == "x" else 1]
        box.disableAutoRange(which)
        s = self.axes[axis]
        s.autoscale = False
        s.minimum, s.maximum = (10 ** rng[0], 10 ** rng[1]) if s.log else (rng[0], rng[1])
        return tuple(rng)

    # -- Views and zoom --------------------------------------------------------
    def _sync_views(self):
        self.vb2.setGeometry(self.plot_item.vb.sceneBoundingRect())
        self.vb2.linkedViewChanged(self.plot_item.vb, self.vb2.XAxis)

    def view_range(self):
        """ ((x0, x1), (y1_0, y1_1), (y2_0, y2_1)) """
        (x, y1) = self.plot_item.vb.viewRange()
        y2 = self.vb2.viewRange()[1]
        return (tuple(x), tuple(y1), tuple(y2))

    def _range_changed(self, *_):
        # Both view boxes report one change (X is linked): keep only real changes,
        # or the range before the zoom is lost
        new = self.view_range()
        if new != self._cur_range:
            self._prev_range, self._cur_range = self._cur_range, new

    def _manual_zoom(self, *_):
        if not self._gesture.isActive():
            self._zoom_stack.append(self._prev_range or self.view_range())
            self.zoomed.emit()
        self._gesture.start()

    def zoom_to(self, x=None, y1=None, y2=None):
        """ Zoom programmatically, recorded in the zoom history like a mouse zoom """
        self._zoom_stack.append(self.view_range())
        vb = self.plot_item.vb
        if x is not None:
            vb.setXRange(*x, padding=0)
        if y1 is not None:
            vb.setYRange(*y1, padding=0)
        if y2 is not None:
            self.vb2.setYRange(*y2, padding=0)
        self.zoomed.emit()

    def is_zoomed(self):
        return bool(self._zoom_stack)

    def reset_zoom(self):
        """ Forget the zoom history and apply the axis settings again (autoscale included) """
        had = bool(self._zoom_stack)
        self._zoom_stack = []
        self._apply_ranges()
        if had:
            self.zoomed.emit()

    def zoom_back(self):
        """ Previous zoom level; after the first one, back to the axis settings """
        if not self._zoom_stack:
            return
        prev = self._zoom_stack.pop()
        if self._zoom_stack:
            x, y1, y2 = prev
            self.plot_item.vb.setRange(xRange=x, yRange=y1, padding=0)
            self.vb2.setYRange(*y2, padding=0)
        else:
            self._apply_ranges()
        self.zoomed.emit()

    def set_rect_zoom(self, on):
        """ Left drag draws a zoom rectangle (ATK Zoom button) instead of panning """
        mode = pg.ViewBox.RectMode if on else pg.ViewBox.PanMode
        self.plot_item.vb.setMouseMode(mode)

    def visible_x_range(self):
        vb = self.plot_item.vb
        if any(vb.autoRangeEnabled()):
            vb.updateAutoRange()      # autoscale is lazy (applied at the next paint)
        return tuple(vb.viewRange()[0])

    # -- Data operations -------------------------------------------------------
    def curves_data(self, names=None):
        return {n: (self._curves[n].x, self._curves[n].y) for n in (names or self._curves)}

    def statistics(self, names=None, visible_only=True):
        """ {name: statistics} over the visible X window (or all data) """
        x0, x1 = self.visible_x_range()
        if self.axes["x"].log:
            x0, x1 = 10 ** x0, 10 ** x1
        out = {}
        for n in (names or list(self._curves)):
            c = self._curves[n]
            y = c.view.transform(c.y)
            if visible_only and len(c.x):
                y = y[(c.x >= x0) & (c.x <= x1)]
            out[n] = statistics(y)
        return out

    def save_data(self, path):
        """ CSV of the curves as given (before the A0/A1/A2 transform, which load_data applies again) """
        save_csv(path, {n: (c.x, c.y) for n, c in self._curves.items()})
        return path

    def load_data(self, path):
        for name, (x, y) in load_csv(path).items():
            self.set_curve(name, y, x=x)
        return path

    def snapshot(self, path):
        """ Save the chart as PNG (or any Qt image format) or SVG, chosen by extension """
        if str(path).lower().endswith(".svg"):
            QtSvg = __import__(QtCore.__name__.split(".")[0] + ".QtSvg", fromlist=["x"])
            gen = QtSvg.QSvgGenerator()
            gen.setFileName(str(path))
            size = self.plot_widget.size()
            gen.setSize(size)
            gen.setViewBox(QtCore.QRect(0, 0, size.width(), size.height()))
            gen.setTitle(self._title or "Chart")
            painter = QtGui.QPainter(gen)
            try:
                self.plot_widget.render(painter)
            finally:
                painter.end()
        else:
            pix = self.plot_widget.grab()
            if not pix.save(str(path)):
                raise IOError("Cannot save " + str(path))
        return path

    def print_chart(self, printer=None):
        """ Print through a print dialog, or to ``printer`` when given (QPrinter) """
        QtPrintSupport = __import__(QtCore.__name__.split(".")[0] + ".QtPrintSupport", fromlist=["x"])
        if printer is None:
            printer = QtPrintSupport.QPrinter()
            dlg = QtPrintSupport.QPrintDialog(printer, self)
            if not dlg.exec():
                return False
        painter = QtGui.QPainter(printer)
        try:
            pix = self.plot_widget.grab()
            rect = painter.viewport()
            size = pix.size()
            size.scale(rect.size(), Qt.AspectRatioMode.KeepAspectRatio)
            painter.setViewport(rect.x(), rect.y(), size.width(), size.height())
            painter.setWindow(pix.rect())
            painter.drawPixmap(0, 0, pix)
        finally:
            painter.end()
        return True

    # -- Settings --------------------------------------------------------------
    def settings(self):
        return {"title": self._title, "time_axis": self._time_axis,
                "display_duration": None if math.isinf(self.display_duration) else self.display_duration,
                "legend": self.legend is not None and self.legend.isVisible(),
                "axes": {a: s.to_dict() for a, s in self.axes.items()}}

    def apply_settings(self, d):
        if "title" in d:
            self.set_title(d["title"])
        if "time_axis" in d:
            self.set_time_axis(d["time_axis"])
        if "display_duration" in d:
            self.display_duration = math.inf if d["display_duration"] is None else float(d["display_duration"])
        if "legend" in d and self.legend is not None:
            self.legend.setVisible(bool(d["legend"]))
        for a, s in d.get("axes", {}).items():
            if a in self.axes:
                self.axes[a] = AxisSettings.from_dict(s)
        self._zoom_stack = []
        self.apply_axes()
        self.durationChanged.emit(self.display_duration)

    # -- Context menu ----------------------------------------------------------
    #: Hooks replaced by tests (file choosers and dialogs)
    def ask_save_path(self, title, filters):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, title, "", filters)
        return path or None

    def ask_open_path(self, title, filters):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, title, "", filters)
        return path or None

    def error(self, text):
        QtWidgets.QMessageBox.critical(self, "Error", text)

    def build_menu(self, menu=None):
        """ The JLChart context menu (``menu`` to add to an existing one) """
        menu = menu or QtWidgets.QMenu(self)
        menu.addAction("Chart properties", self.show_chart_properties)
        dv = menu.addMenu("Data View properties")
        table = QtWidgets.QMenu("Show table", menu)
        stats = QtWidgets.QMenu("Show statistics", menu)
        table.addAction("All", lambda: self.show_table())
        stats.addAction("All", lambda: self.show_statistics())
        for n in self._curves:
            dv.addAction(n, lambda n=n: self.show_view_properties(n))
            table.addAction(n, lambda n=n: self.show_table([n]))
            stats.addAction(n, lambda n=n: self.show_statistics([n]))
        dv.setEnabled(bool(self._curves))
        menu.addAction("Save data File", self.save_data_file)
        menu.addAction("Load data File", self.load_data_file)
        menu.addMenu(table)
        menu.addMenu(stats)
        zb = menu.addAction("Zoom back", self.zoom_back)
        zb.setEnabled(self.is_zoomed())
        menu.addAction("Print Chart", self.print_chart)
        menu.addAction("Save a snapshot of this chart", self.save_snapshot)
        return menu

    def _show_menu(self, pos):
        menu = self.build_menu()
        menu.exec(self.plot_widget.mapToGlobal(pos))
        menu.deleteLater()

    def save_data_file(self):
        path = self.ask_save_path("Save data File", "CSV files (*.csv);;All files (*)")
        if path:
            try:
                return self.save_data(path)
            except OSError as e:
                self.error("Failed to write {0}\n{1}".format(path, e))
        return None

    def load_data_file(self):
        path = self.ask_open_path("Load data File", "CSV files (*.csv);;All files (*)")
        if path:
            try:
                return self.load_data(path)
            except (OSError, ValueError) as e:
                self.error("Failed to read {0}\n{1}".format(path, e))
        return None

    def save_snapshot(self):
        path = self.ask_save_path("Save a snapshot of this chart", "PNG image (*.png);;SVG drawing (*.svg)")
        if path:
            if not path.lower().endswith((".png", ".svg", ".jpg", ".jpeg", ".bmp")):
                path += ".png"
            try:
                return self.snapshot(path)
            except (IOError, OSError) as e:
                self.error(str(e))
        return None

    def _dialog(self, key, factory):
        dlg = self._dialogs.get(key)
        try:
            if dlg is not None and not dlg.isVisible():
                # Closed: build it again so it shows the current settings
                dlg.deleteLater()
                dlg = None
        except RuntimeError:
            dlg = None
        if dlg is None:
            dlg = factory()
            self._dialogs[key] = dlg
        dlg.show()
        dlg.raise_()
        return dlg

    def show_chart_properties(self):
        from .chartdialogs import QChartPropertiesDialog
        return self._dialog("chart", lambda: QChartPropertiesDialog(self, self))

    def show_view_properties(self, name, view=None):
        """ ``view``: edit this DataView (see :class:`QDataViewDialog`) """
        from .chartdialogs import QDataViewDialog
        return self._dialog(("dv", name), lambda: QDataViewDialog(self, name, self, view=view))

    def show_table(self, names=None):
        from .chartdialogs import QChartTableDialog
        dlg = QChartTableDialog(self, names, self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.show()
        return dlg

    def show_statistics(self, names=None):
        from .chartdialogs import QChartStatisticsDialog
        dlg = QChartStatisticsDialog(self, names, self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.show()
        return dlg

    def format_x(self, x):
        """ X value as text (date and time on a time axis) """
        if self._time_axis:
            return time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(x)) + ".{0:03d}".format(int((x % 1) * 1000))
        return "{0:g}".format(x)


from .image import QImageViewer  # noqa: E402  (backward compatibility)
