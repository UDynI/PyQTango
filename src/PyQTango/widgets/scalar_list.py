# -*- coding: utf-8 -*-
"""
QScalarListViewer: label | value | setter | unit rows (ATK ScalarListViewer).
"""

import logging

import tango

from ..qt import QtWidgets, Qt, Signal, Property
from ..core.proxies import proxy_cache
from ..models.worker import run_async
from ..models.registry import attribute_model
from .base import TangoDeviceWidget, device_name_property
from .setters import create_viewer, create_setter
from .value import QValueLabel

log = logging.getLogger(__name__)

_SKIP = ("state", "status")


class QScalarListViewer(TangoDeviceWidget, QtWidgets.QWidget):
    """ Grid of scalar attributes with viewers and setters.

    ``setDevice(name)`` lists every scalar attribute of a device except State and
    Status (asynchronously); ``setModels([...])`` shows an explicit list.
    ``operatorView`` hides EXPERT attributes, ``settersVisible`` hides the
    setter column (read-only panels).

    Signal ``loaded(int)`` gives the number of rows once built.
    """

    loaded = Signal(int)
    deviceName = device_name_property()

    def __init__(self, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        TangoDeviceWidget.__init__(self)
        self._grid = QtWidgets.QGridLayout(self)
        self._grid.setColumnStretch(1, 1)
        self._grid.setColumnStretch(2, 1)
        self._grid.setHorizontalSpacing(8)
        self._rows = []             # list of (name, disp_level, [widgets])
        self._operator_view = False
        self._setters_visible = True
        self._configs = {}
        self._message = QtWidgets.QLabel(self)
        self._grid.addWidget(self._message, 0, 0, 1, 4)

    # -- Properties ---------------------------------------------------------------
    def getOperatorView(self):
        return self._operator_view

    def setOperatorView(self, on):
        self._operator_view = bool(on)
        self._apply_visibility()

    operatorView = Property(bool, getOperatorView, setOperatorView)

    def getSettersVisible(self):
        return self._setters_visible

    def setSettersVisible(self, on):
        self._setters_visible = bool(on)
        self._apply_visibility()

    settersVisible = Property(bool, getSettersVisible, setSettersVisible)

    # -- Content ------------------------------------------------------------------
    def on_device_changed(self, device):
        self._clear()
        if device is None:
            return
        self._message.setText("Loading attributes of {0}...".format(device.name))
        self._message.show()
        name = device.name

        def query():
            return proxy_cache.get(name).attribute_list_query_ex()

        def done(cfgs):
            if self.device() is not device:
                return
            names = []
            for cfg in sorted(cfgs, key=lambda c: c.name.lower()):
                if cfg.data_format != tango.AttrDataFormat.SCALAR or cfg.name.lower() in _SKIP:
                    continue
                full = device._attr(cfg.name)
                self._configs[full] = cfg
                names.append(full)
            self._build(names)

        def failed(err):
            self._message.setText("<font color='red'>{0}</font>".format(err.message))

        run_async(query, on_done=done, on_error=failed, source=name)

    def setModels(self, names):
        """ Show an explicit list of full attribute names (configurations read asynchronously) """
        self.setDevice(None)
        self._build(list(names))

    def models(self):
        return [r[0] for r in self._rows]

    def _clear(self):
        for _, _, widgets in self._rows:
            for w in widgets:
                if w is not None:
                    self._grid.removeWidget(w)
                    if hasattr(w, "setModel"):
                        w.setModel(None)
                    w.deleteLater()
        self._rows = []
        self._configs = {}
        self._message.hide()

    def _build(self, names):
        self._message.hide()
        for row, name in enumerate(names, start=1):
            model = attribute_model(name)
            cfg = self._configs.get(name) or model.config()
            label = QtWidgets.QLabel(cfg.label if cfg is not None else model.attr_name, self)
            label.setToolTip(name)
            viewer = create_viewer(cfg, self) if cfg is not None else QValueLabel(self)
            if isinstance(viewer, QValueLabel):
                viewer.setShowUnit(False)
            viewer.setModel(model)
            setter = create_setter(cfg, self) if cfg is not None else None
            if setter is not None:
                setter.setModel(model)
            unit = QtWidgets.QLabel(self)
            if cfg is not None and cfg.unit not in ("", "No unit", "Not specified"):
                unit.setText(cfg.unit)
            self._grid.addWidget(label, row, 0, Qt.AlignmentFlag.AlignRight)
            self._grid.addWidget(viewer, row, 1)
            if setter is not None:
                self._grid.addWidget(setter, row, 2)
            self._grid.addWidget(unit, row, 3)
            level = cfg.disp_level if cfg is not None else tango.DispLevel.OPERATOR
            self._rows.append((name, level, [label, viewer, setter, unit]))
            if cfg is None:
                # Explicit list: complete the row once the configuration arrives
                model.configChanged.connect(lambda c, lb=label, u=unit: self._late_config(c, lb, u))
        self._grid.setRowStretch(len(names) + 1, 1)
        self._apply_visibility()
        self.loaded.emit(len(self._rows))

    def _late_config(self, cfg, label, unit):
        try:
            label.setText(cfg.label)
            if cfg.unit not in ("", "No unit", "Not specified"):
                unit.setText(cfg.unit)
        except RuntimeError:
            pass

    def _apply_visibility(self):
        for _, level, widgets in self._rows:
            visible = not (self._operator_view and level == tango.DispLevel.EXPERT)
            for i, w in enumerate(widgets):
                if w is None:
                    continue
                w.setVisible(visible and (i != 2 or self._setters_visible))
