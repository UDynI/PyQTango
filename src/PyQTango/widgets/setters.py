# -*- coding: utf-8 -*-
"""
Attribute setters (ATK *Editor / *Setter widgets) and viewer/setter factories.

Every setter shows the attribute set point, writes asynchronously, and turns its
frame red with the error in the tooltip when a write fails.
"""

import tango

from ..qt import QtWidgets, Qt
from ..core.formatting import format_scalar, is_float_type, is_int_type, is_numeric_type
from ..core.argparser import parse_attribute_value, ArgParserError
from .base import TangoAttributeWidget, model_name_property
from .value import QValueLabel
from .state import QStateLabel
from .wheel import QAttributeWheelEditor

_WRITABLE = (tango.AttrWriteType.READ_WRITE, tango.AttrWriteType.READ_WITH_WRITE, tango.AttrWriteType.WRITE)
_ERROR_STYLE = "border: 1px solid red;"
_EDIT_STYLE = "color: darkgreen;"


class _SetterMixin(TangoAttributeWidget):
    """ Common setter behaviour. ``setPointMode``: "auto" (default), "always", "never";
    see :meth:`TangoAttributeWidget.set_point`. """

    setPointMode = "auto"

    def on_write_done(self, err):
        if err is None:
            self.setStyleSheet("")
            self.setToolTip(self.tooltip_text())
        else:
            self.setStyleSheet(_ERROR_STYLE)
            self.setToolTip(self.tooltip_text() + "<br/><font color='red'>Write failed: {0}</font>".format(err.message))

    def on_config(self, cfg):
        self.setEnabled(cfg.writable in _WRITABLE)
        self.setToolTip(self.tooltip_text())
        self.on_setter_config(cfg)
        if self.attributeValue() is not None:
            self.on_value(self.attributeValue())

    def on_setter_config(self, cfg):
        pass


class QBooleanSetter(_SetterMixin, QtWidgets.QCheckBox):
    """ Check box writing a DevBoolean attribute on toggle """

    modelName = model_name_property()

    def __init__(self, parent=None):
        QtWidgets.QCheckBox.__init__(self, parent)
        TangoAttributeWidget.__init__(self)
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self, checked):
        self.write(bool(checked))

    def on_value(self, value):
        self.blockSignals(True)
        self.setChecked(bool(self.set_point(value, self.setPointMode)))
        self.blockSignals(False)


class QEnumSetter(_SetterMixin, QtWidgets.QComboBox):
    """ Combo box writing a DevEnum attribute (labels from the configuration) """

    modelName = model_name_property()

    def __init__(self, parent=None):
        QtWidgets.QComboBox.__init__(self, parent)
        TangoAttributeWidget.__init__(self)
        self.activated.connect(self._on_activated)

    def on_setter_config(self, cfg):
        labels = list(cfg.enum_labels or [])
        if [self.itemText(i) for i in range(self.count())] != labels:
            self.blockSignals(True)
            self.clear()
            self.addItems(labels)
            self.blockSignals(False)

    def _on_activated(self, index):
        self.write(int(index))

    def on_value(self, value):
        try:
            idx = int(self.set_point(value, self.setPointMode))
        except (TypeError, ValueError):
            return
        self.blockSignals(True)
        self.setCurrentIndex(idx)
        self.blockSignals(False)


class _LineSetter(_SetterMixin, QtWidgets.QLineEdit):
    """ Line edit: Enter writes, Esc reverts, edits are shown in dark green """

    def __init__(self, parent=None):
        QtWidgets.QLineEdit.__init__(self, parent)
        TangoAttributeWidget.__init__(self)
        self._editing = False
        self.textEdited.connect(self._on_edited)
        self.returnPressed.connect(self._commit)

    def _on_edited(self, _):
        self._editing = True
        self.setStyleSheet(_EDIT_STYLE)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._editing = False
            self.setStyleSheet("")
            if self.attributeValue() is not None:
                self.on_value(self.attributeValue())
            return
        QtWidgets.QLineEdit.keyPressEvent(self, event)

    def _commit(self):
        try:
            value = self.parse(self.text())
        except (ValueError, ArgParserError) as e:
            self.setStyleSheet(_ERROR_STYLE)
            self.setToolTip(self.tooltip_text() + "<br/><font color='red'>{0}</font>".format(e))
            return
        self._editing = False
        self.setStyleSheet("")
        self.write(value)

    def on_value(self, value):
        if self._editing:
            return
        self.setText(self.display(self.set_point(value, self.setPointMode)))

    def parse(self, text):
        return text

    def display(self, value):
        return str(value)


class QStringSetter(_LineSetter):
    """ Line edit writing a DevString attribute on Enter """

    modelName = model_name_property()


class QNumberSetter(_LineSetter):
    """ Line edit writing a numeric attribute on Enter (accepts hex and exponents) """

    modelName = model_name_property()

    def parse(self, text):
        cfg = self.attributeConfig()
        text = text.strip()
        if cfg is not None:
            unit = cfg.unit if cfg.unit not in ("", "No unit", "Not specified") else ""
            if unit and text.endswith(unit):
                text = text[:-len(unit)].strip()
            value = parse_attribute_value(text, cfg.data_type)
            lo, hi = cfg.min_value, cfg.max_value
            try:
                if lo not in ("", "Not specified") and float(value) < float(lo):
                    raise ValueError("Value below minimum {0}".format(lo))
                if hi not in ("", "Not specified") and float(value) > float(hi):
                    raise ValueError("Value above maximum {0}".format(hi))
            except TypeError:
                pass
            return value
        return float(text)

    def display(self, value):
        cfg = self.attributeConfig()
        if cfg is None:
            return str(value)
        return format_scalar(value, cfg.format, cfg.data_type).strip()


class QArraySetter(_LineSetter):
    """ Line edit writing a spectrum or image with the Jive syntax (``1,2,3`` / ``[1,2][3,4]``) """

    modelName = model_name_property()

    def parse(self, text):
        cfg = self.attributeConfig()
        if cfg is None:
            raise ValueError("Attribute configuration not available yet")
        return parse_attribute_value(text, cfg.data_type, cfg.data_format, list(cfg.enum_labels or []))

    def display(self, value):
        try:
            import numpy as np
            arr = np.asarray(value)
            if arr.ndim == 2:
                return "".join("[" + ",".join(str(v) for v in row) + "]" for row in arr)
            return ",".join(str(v) for v in arr.ravel())
        except Exception:  # noqa: BLE001
            return str(value)


def create_viewer(cfg, parent=None):
    """ Best read-only widget for an attribute configuration """
    if cfg.data_format == tango.AttrDataFormat.SCALAR and cfg.data_type == tango.CmdArgType.DevState:
        return QStateLabel(parent)
    return QValueLabel(parent)


def create_setter(cfg, parent=None, wheel=True):
    """ Best setter for an attribute configuration, or None when not writable """
    if cfg.writable not in _WRITABLE:
        return None
    if cfg.data_format != tango.AttrDataFormat.SCALAR:
        return QArraySetter(parent)
    dt = cfg.data_type
    if dt == tango.CmdArgType.DevBoolean:
        return QBooleanSetter(parent)
    if dt == tango.CmdArgType.DevEnum:
        return QEnumSetter(parent)
    if dt == tango.CmdArgType.DevString:
        return QStringSetter(parent)
    if is_numeric_type(dt):
        fmt = (cfg.format or "").lower()
        if wheel and ("e" not in fmt or is_int_type(dt)) and not (is_float_type(dt) and "g" in fmt):
            return QAttributeWheelEditor(parent)
        return QNumberSetter(parent)
    return None
