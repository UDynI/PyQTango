# -*- coding: utf-8 -*-
"""
Spectrum viewers (ATK ``NumberSpectrumViewer`` and the string, state and boolean lists).

* :class:`QSpectrumViewer` plots a numeric spectrum (read value, and the set
  point of a writable attribute) on a :class:`QTangoChart`. The X axis runs
  from ``Xmin`` to ``Xmax`` as in ATK: ``x[i] = xmin + i * (xmax - xmin) / n``.
  The range comes from :meth:`setXRange` (constants), from two scalar
  attributes (:meth:`setXModels`) or from the database attribute properties
  ``XminAttribute`` / ``XmaxAttribute`` or ``Xmin`` / ``Xmax``
  (:meth:`load_x_axis_properties`, as ATKPanel does).
* :class:`QStringSpectrumViewer`, :class:`QStateSpectrumViewer` and
  :class:`QBooleanSpectrumViewer` list the elements with their index; states in
  ATK colours, booleans as check marks.

@author: Michele Devetta <michele.devetta@cnr.it>
"""

import numpy as np

from ..qt import QtWidgets, Qt, Signal, connect_destroyed
from ..core.proxies import proxy_cache
from ..core.formatting import state_name
from ..models.worker import run_async
from ..models.registry import attribute_model
from .base import TangoAttributeWidget, model_name_property
from .colors import state_qcolors
from .plot import QTangoChart

__all__ = ["QSpectrumViewer", "QStringSpectrumViewer", "QStateSpectrumViewer", "QBooleanSpectrumViewer",
           "read_x_axis_properties", "XMIN_ATT_PROP", "XMAX_ATT_PROP", "XMIN_PROP", "XMAX_PROP"]

XMIN_ATT_PROP = "XminAttribute"
XMAX_ATT_PROP = "XmaxAttribute"
XMIN_PROP = "Xmin"
XMAX_PROP = "Xmax"

_UNITS_NONE = ("", "No unit", "Not specified", None)


def read_x_axis_properties(attribute_name):
    """ Blocking (worker thread): {"XminAttribute": ..., "XmaxAttribute": ..., "Xmin": ..., "Xmax": ...}
    from the database attribute properties; missing ones are left out """
    from ..core.names import split_attribute_name
    device, attr = split_attribute_name(attribute_name)
    if "#dbase=no" in device.lower():
        return {}
    proxy = proxy_cache.get(device)
    db = proxy.get_device_db()
    props = db.get_device_attribute_property(proxy.dev_name(), [attr]).get(attr, {})
    out = {}
    for key in (XMIN_ATT_PROP, XMAX_ATT_PROP, XMIN_PROP, XMAX_PROP):
        for k, v in props.items():
            if k.lower() == key.lower() and len(v):
                out[key] = v[0]
    return out


class QSpectrumViewer(TangoAttributeWidget, QTangoChart):
    """ Chart of one numeric spectrum attribute.

    Signals:
        xAxisLoaded(dict): the X axis properties read from the database
    """

    xAxisLoaded = Signal(object)
    modelName = model_name_property()

    READ = "read"
    SET_POINT = "set point"

    def __init__(self, parent=None, show_set_point=True):
        QTangoChart.__init__(self, parent)
        TangoAttributeWidget.__init__(self)
        self._show_set_point = show_set_point
        self._xrange = None
        self._xmodels = []          # [(model, slot)]: edited in place, the destroy handler shares it
        connect_destroyed(self, _release_on_destroy(self._xmodels))
        self._user_title = ""
        self._error_text = ""
        self._xvalues = [None, None]
        self._names = (self.READ, self.SET_POINT)

    # -- X axis ----------------------------------------------------------------
    def setXRange(self, xmin, xmax):
        """ Constant X range (None to go back to the index) """
        self._clear_xmodels()
        self._xrange = None if xmin is None or xmax is None or float(xmax) <= float(xmin) \
            else (float(xmin), float(xmax))
        self._fix_x_axis()
        self._redraw()

    def xRange(self):
        return self._xrange

    def setXModels(self, xmin_name, xmax_name):
        """ X range from two scalar attributes (followed live) """
        self._clear_xmodels()
        if not xmin_name or not xmax_name:
            return
        for i, name in enumerate((xmin_name, xmax_name)):
            m = attribute_model(name) if isinstance(name, str) else name
            slot = (lambda v, i=i: self._x_value(i, v))
            m.valueChanged.connect(slot)
            m.attach()
            self._xmodels.append((m, slot))
            if m.last_value() is not None:
                self._x_value(i, m.last_value())

    def _clear_xmodels(self):
        _release_xmodels(self._xmodels)
        self._xvalues = [None, None]

    def setModel(self, model):
        old = self.model()
        TangoAttributeWidget.setModel(self, model)
        if self.model() is not old and self.model() is not None and self._xmodels:
            # The X range came from attributes of the previous spectrum
            self._clear_xmodels()
            self._xrange = None
            self._fix_x_axis()

    def _x_value(self, i, value):
        try:
            self._xvalues[i] = float(value.value)
        except (TypeError, ValueError):
            self._xvalues[i] = None
        lo, hi = self._xvalues
        if lo is not None and hi is not None and hi > lo:
            if self._xrange != (lo, hi):
                self._xrange = (lo, hi)
                self._fix_x_axis()
                self._redraw()

    def _fix_x_axis(self):
        s = self.axes["x"]
        if self._xrange is None:
            s.autoscale = True
        else:
            s.autoscale = False
            s.minimum, s.maximum = self._xrange
        self.apply_axes()

    def x_of(self, n):
        if self._xrange is None:
            return np.arange(n, dtype=float)
        lo, hi = self._xrange
        return lo + np.arange(n, dtype=float) * (hi - lo) / max(n, 1)

    def load_x_axis_properties(self):
        """ Read XminAttribute/XmaxAttribute (or Xmin/Xmax) and apply them (asynchronous) """
        m = self.model()
        if m is None:
            return None
        name, device = m.name, m.device_name

        def done(props):
            if self.model() is not m:
                return
            if XMIN_ATT_PROP in props and XMAX_ATT_PROP in props:
                self.setXModels(_full(device, props[XMIN_ATT_PROP]), _full(device, props[XMAX_ATT_PROP]))
            elif XMIN_PROP in props and XMAX_PROP in props:
                try:
                    self.setXRange(float(props[XMIN_PROP]), float(props[XMAX_PROP]))
                except ValueError:
                    pass
            self.xAxisLoaded.emit(props)

        return run_async(read_x_axis_properties, name, on_done=done, on_error=lambda e: self.xAxisLoaded.emit({}),
                         source=name, owner=self)

    # -- Model hooks -------------------------------------------------------------
    def on_config(self, cfg):
        unit = "" if cfg.unit in _UNITS_NONE else cfg.unit
        self._names = (cfg.label or self.model().attr_name, (cfg.label or self.model().attr_name) + " (set point)")
        for old, new in zip((self.READ, self.SET_POINT), self._names):
            if old in self.curve_names() and old != new:
                self.remove_curve(old)
        self.READ, self.SET_POINT = self._names
        # Only the label: apply_axes() would reset the user's zoom at every configuration event
        self.axes["y1"].title = unit
        self.plot_item.getAxis("left").setLabel(unit or None)

    def on_value(self, value):
        self._redraw()

    def _redraw(self):
        value = self.attributeValue()
        if value is None or value.value is None:
            return
        y = np.asarray(value.value, dtype=float).ravel()
        self.set_curve(self.READ, y, x=self.x_of(len(y)))
        m = self.model()
        if self._show_set_point and m is not None and m.is_writable() and m.has_valid_set_point() \
                and value.w_value is not None:
            w = np.asarray(value.w_value, dtype=float).ravel()
            self.set_curve(self.SET_POINT, w, x=self.x_of(len(w)))
        elif self.SET_POINT in self.curve_names():
            self.remove_curve(self.SET_POINT)

    # The error is shown after the user's title, never instead of it
    def set_title(self, title):
        self._user_title = title or ""
        self._show_title()

    def title(self):
        return self._user_title

    def _show_title(self):
        text = self._user_title
        if self._error_text:
            err = "<font color='red'>{0}</font>".format(self._error_text)
            text = text + " " + err if text else err
        QTangoChart.set_title(self, text)
        self._title = self._user_title      # settings() saves the user's title only

    def on_error(self, err):
        self._error_text = "" if err is None else err.message
        self._show_title()

    def on_model_cleared(self):
        self.clear()
        self._clear_xmodels()


def _release_xmodels(xmodels):
    for m, slot in xmodels:
        try:
            m.valueChanged.disconnect(slot)
        except (TypeError, RuntimeError):
            pass
        try:
            m.release()
        except RuntimeError:
            pass
    del xmodels[:]


def _release_on_destroy(xmodels):
    # Must not capture the viewer (it is being destroyed)
    def release(*_):
        _release_xmodels(xmodels)
    return release


def _full(device, attr):
    """ Full name of ``attr`` (an attribute of ``device`` unless it has slashes) """
    if attr.count("/") >= 3:
        return attr
    if "#" in device:
        dev, frag = device.split("#", 1)
        return "{0}/{1}#{2}".format(dev, attr, frag)
    return device + "/" + attr


class _ListViewer(TangoAttributeWidget, QtWidgets.QTableWidget):
    """ Index | value table for one spectrum attribute """

    modelName = model_name_property()

    def __init__(self, parent=None):
        QtWidgets.QTableWidget.__init__(self, 0, 2, parent)
        TangoAttributeWidget.__init__(self)
        self.setHorizontalHeaderLabels(["Index", "Value"])
        self.verticalHeader().hide()
        self.horizontalHeader().setStretchLastSection(True)
        self.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

    def on_config(self, cfg):
        self.setHorizontalHeaderLabels(["Index", cfg.label or self.model().attr_name])

    def set_values(self, values):
        values = list(values if values is not None else [])
        self.setRowCount(len(values))
        for i, v in enumerate(values):
            idx = self.item(i, 0)
            if idx is None:
                idx = QtWidgets.QTableWidgetItem(str(i))
                idx.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.setItem(i, 0, idx)
            item = self.item(i, 1)
            if item is None:
                item = QtWidgets.QTableWidgetItem()
                self.setItem(i, 1, item)
            self.show_item(item, v)

    def show_item(self, item, v):
        item.setText(str(v))

    def values(self):
        return [self.item(i, 1).text() for i in range(self.rowCount())]

    def on_value(self, value):
        self.set_values(value.value)
        self.setStyleSheet("")

    def on_error(self, err):
        self.setStyleSheet("" if err is None else "QTableWidget { border: 2px solid red; }")
        self.setToolTip("" if err is None else err.message)


class QStringSpectrumViewer(_ListViewer):
    """ String spectrum: one row per element """


class QStateSpectrumViewer(_ListViewer):
    """ DevState spectrum: state names in ATK colours """

    def show_item(self, item, v):
        item.setText(state_name(v))
        bg, fg = state_qcolors(v)
        item.setBackground(bg)
        item.setForeground(fg)


class QBooleanSpectrumViewer(_ListViewer):
    """ Boolean spectrum: check marks (read only) """

    def show_item(self, item, v):
        item.setText("")
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setCheckState(Qt.CheckState.Checked if bool(v) else Qt.CheckState.Unchecked)

    def values(self):
        return [self.item(i, 1).checkState() == Qt.CheckState.Checked for i in range(self.rowCount())]
