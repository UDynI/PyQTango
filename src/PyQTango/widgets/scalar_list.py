# -*- coding: utf-8 -*-
"""
QScalarListViewer: label | value | setter | unit rows (ATK ScalarListViewer).
"""

import logging
import functools

import tango

from ..qt import QtWidgets, Qt, Signal, Property, is_deleted
from ..core.proxies import proxy_cache
from ..models.worker import run_async
from ..models.registry import attribute_model
from .base import TangoDeviceWidget, device_name_property
from ..core.formatting import is_numeric_type
from ..core.names import split_attribute_name
from .setters import create_viewer, create_setter, parse_values_list
from .value import QValueLabel

log = logging.getLogger(__name__)

_SKIP = ("state", "status")


class QScalarListViewer(TangoDeviceWidget, QtWidgets.QWidget):
    """ Grid of scalar attributes with viewers and setters.

    ``setDevice(name)`` lists every scalar attribute of a device except State and
    Status (asynchronously); ``setModels([...])`` shows an explicit list.
    ``operatorView`` hides EXPERT attributes, ``settersVisible`` hides the
    setter column and ``propertyButtonsVisible`` the "..." buttons that open
    :class:`QAttributePropertyDialog` (read-only panels hide both).
    ``propertiesEditable`` (ATK ``modifProp``) lets that dialog write.

    Numeric and string scalars whose database attribute property ``values``
    lists allowed values (one per line or comma separated) get a combo setter.

    Signals: ``loaded(int)`` (rows built), ``valuesLoaded(int)`` (combos made).
    """

    loaded = Signal(int)
    valuesLoaded = Signal(int)
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
        self._props_visible = True
        self._props_editable = True
        self._dialogs = {}
        self._configs = {}
        self._load_id = 0           # attribute-list request in progress (older replies are dropped)
        self._late = []             # (model, slot) waiting for a configuration (explicit lists)
        self._stretch_row = None
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

    def getPropertyButtonsVisible(self):
        return self._props_visible

    def setPropertyButtonsVisible(self, on):
        self._props_visible = bool(on)
        self._apply_visibility()

    propertyButtonsVisible = Property(bool, getPropertyButtonsVisible, setPropertyButtonsVisible)

    def getPropertiesEditable(self):
        return self._props_editable

    def setPropertiesEditable(self, on):
        self._props_editable = bool(on)

    propertiesEditable = Property(bool, getPropertiesEditable, setPropertiesEditable)

    def setReadOnly(self, on):
        """ Hide setters and property buttons (ATKPanel -ro) """
        self.setSettersVisible(not on)
        self.setPropertyButtonsVisible(not on)
        self.setPropertiesEditable(not on)

    # -- Content ------------------------------------------------------------------
    def on_device_changed(self, device):
        self._clear()
        if device is None:
            return
        self._message.setText("Loading attributes of {0}...".format(device.name))
        self._message.show()
        name = device.name
        token = self._load_id

        def query():
            return proxy_cache.get(name).attribute_list_query_ex()

        def done(cfgs):
            if token != self._load_id or self.device() is not device:
                return
            names = []
            for cfg in sorted(cfgs, key=lambda c: c.name.lower()):
                if cfg.data_format != tango.AttrDataFormat.SCALAR or cfg.name.lower() in _SKIP \
                        or cfg.data_type == tango.CmdArgType.DevEncoded:
                    continue      # DevEncoded scalars are images (QRawImageViewer)
                full = device._attr(cfg.name)
                self._configs[full] = cfg
                names.append(full)
            self._build(names)

        def failed(err):
            if token != self._load_id:
                return
            self._message.setText("<font color='red'>{0}</font>".format(err.message))

        run_async(query, on_done=done, on_error=failed, source=name, owner=self)

    def setModels(self, names):
        """ Show an explicit list of full attribute names (configurations read asynchronously) """
        self.setDevice(None)
        self._clear()        # setDevice(None) does nothing when there was no device
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
        self._load_id += 1
        for model, slot in self._late:
            try:
                model.configChanged.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._late = []
        if self._stretch_row is not None:
            self._grid.setRowStretch(self._stretch_row, 0)
            self._stretch_row = None
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
            button = QtWidgets.QToolButton(self)
            button.setText("...")
            button.setToolTip("Attribute properties")
            button.clicked.connect(lambda _=False, n=name: self.show_properties(n))
            self._grid.addWidget(label, row, 0, Qt.AlignmentFlag.AlignRight)
            self._grid.addWidget(viewer, row, 1)
            if setter is not None:
                self._grid.addWidget(setter, row, 2)
            self._grid.addWidget(unit, row, 3)
            self._grid.addWidget(button, row, 4)
            level = cfg.disp_level if cfg is not None else tango.DispLevel.OPERATOR
            self._rows.append((name, level, [label, viewer, setter, unit, button]))
            if cfg is None:
                # Explicit list: complete the row once the configuration arrives
                slot = functools.partial(self._late_config, name)
                model.configChanged.connect(slot)
                self._late.append((model, slot))
        self._stretch_row = len(names) + 1
        self._grid.setRowStretch(self._stretch_row, 1)
        self._apply_visibility()
        self.loaded.emit(len(self._rows))
        self._load_values_lists()

    # -- Allowed values ----------------------------------------------------------
    def _load_values_lists(self, only=None):
        rows = [(i, r[0]) for i, r in enumerate(self._rows) if r[2][2] is not None and (only is None or r[0] in only)]
        cfgs = {n: self._configs.get(n) or attribute_model(n).config() for _, n in rows}
        rows = [(i, n) for i, n in rows if cfgs[n] is not None and cfgs[n].data_format == tango.AttrDataFormat.SCALAR
                and (is_numeric_type(cfgs[n].data_type) or cfgs[n].data_type == tango.CmdArgType.DevString)]
        if not rows:
            return None
        names = [n for _, n in rows]
        built = self._rows

        def query():
            return read_values_lists(names)

        def done(lists):
            if self._rows is not built:
                return
            made = 0
            for i, n in rows:
                values = lists.get(n)
                if not values:
                    continue
                setter = create_setter(cfgs[n], self, values=values)
                if setter is None or not hasattr(setter, "setValuesList"):
                    continue
                old = self._rows[i][2][2]
                self._grid.removeWidget(old)
                old.setModel(None)
                old.deleteLater()
                setter.setModel(attribute_model(n))
                self._grid.addWidget(setter, i + 1, 2)
                self._rows[i][2][2] = setter
                made += 1
            self._apply_visibility()
            self.valuesLoaded.emit(made)

        return run_async(query, on_done=done, on_error=lambda e: self.valuesLoaded.emit(0),
                         source=self.getDeviceName(), owner=self)

    # -- Property dialog ---------------------------------------------------------
    def show_properties(self, name):
        """ Open (or raise) the property dialog of one attribute """
        from .attrprops import QAttributePropertyDialog
        dlg = self._dialogs.get(name)
        try:
            if dlg is not None:
                dlg.isVisible()
        except RuntimeError:
            dlg = None
        if dlg is None or dlg.read_only != (not self._props_editable):
            dlg = QAttributePropertyDialog(attribute_model(name), self, read_only=not self._props_editable)
            self._dialogs[name] = dlg
        dlg.show()
        dlg.raise_()
        return dlg

    def _late_config(self, name, cfg):
        if is_deleted(self):
            return      # the viewer went away without _clear(): nothing to complete
        for i, (n, _, widgets) in enumerate(self._rows):
            if n != name:
                continue
            label, unit = widgets[0], widgets[3]
            label.setText(cfg.label)
            if cfg.unit not in ("", "No unit", "Not specified"):
                unit.setText(cfg.unit)
            new_setter = False
            if widgets[2] is None:
                setter = create_setter(cfg, self)
                if setter is not None:
                    setter.setModel(attribute_model(name))
                    self._grid.addWidget(setter, i + 1, 2)
                    widgets[2] = setter
                    new_setter = True
            self._rows[i] = (n, cfg.disp_level, widgets)
            self._apply_visibility()
            if new_setter:
                self._load_values_lists(only=[name])
            return

    def _apply_visibility(self):
        for _, level, widgets in self._rows:
            visible = not (self._operator_view and level == tango.DispLevel.EXPERT)
            for i, w in enumerate(widgets):
                if w is None:
                    continue
                w.setVisible(visible and (i != 2 or self._setters_visible) and (i != 4 or self._props_visible))


def read_values_lists(names):
    """ Blocking (worker thread): {full name: [allowed values]} from the database
    attribute property ``values`` of each attribute (devices without a database are skipped) """
    by_device = {}
    for n in names:
        dev, attr = split_attribute_name(n)
        by_device.setdefault(dev, []).append((attr, n))
    out = {}
    for dev, items in by_device.items():
        if "#dbase=no" in dev.lower():
            continue
        proxy = proxy_cache.get(dev)
        db = proxy.get_device_db()
        props = db.get_device_attribute_property(proxy.dev_name(), [a for a, _ in items])
        for attr, full in items:
            for key, val in props.get(attr, {}).items():
                if key.lower() == "values":
                    values = parse_values_list(val)
                    if values:
                        out[full] = values
    return out
