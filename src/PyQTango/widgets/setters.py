# -*- coding: utf-8 -*-
"""
Attribute setters (ATK *Editor / *Setter widgets) and viewer/setter factories.

Every setter shows the attribute set point, writes asynchronously, and turns its
frame red with the error in the tooltip when a write fails; it then shows the
device value again (ATK 10 "set error" behaviour). ``setNeedsConfirmation(True)``
asks before each write (ATK ``needsConfirmation`` / ``hasConfirmWindow``).
"""

import tango

from ..qt import QtWidgets, Qt
from ..core.formatting import format_scalar, is_float_type, is_int_type, is_numeric_type
from ..core.argparser import parse_attribute_value, ArgParserError
from .base import TangoAttributeWidget, model_name_property
from .value import QValueLabel
from .state import QStateLabel
from .wheel import QAttributeWheelEditor
from .boolean import ask_yes_no

_WRITABLE = (tango.AttrWriteType.READ_WRITE, tango.AttrWriteType.READ_WITH_WRITE, tango.AttrWriteType.WRITE)
_ERROR_STYLE = "border: 1px solid red;"
_EDIT_STYLE = "color: darkgreen;"


class _SetterMixin(TangoAttributeWidget):
    """ Common setter behaviour. ``setPointMode``: "auto" (default), "always", "never";
    see :meth:`TangoAttributeWidget.set_point`. """

    setPointMode = "auto"
    _needs_confirmation = False
    _confirm_message = "Change {attribute} from {current} to {new}?"

    # -- Confirmation ------------------------------------------------------------------
    def setNeedsConfirmation(self, b):
        """ Ask "Change <attr> from <current> to <new>?" before each write """
        self._needs_confirmation = bool(b)

    def needsConfirmation(self):
        return self._needs_confirmation

    def setConfirmMessage(self, text):
        """ Question text; ``{attribute}``, ``{current}`` and ``{new}`` are replaced """
        self._confirm_message = text or _SetterMixin._confirm_message

    def ask_confirmation(self, message):
        """ Override (or replace on the instance) to change how confirmation is asked """
        return ask_yes_no(self, "Confirm", message)

    def confirm_write(self, new_text):
        """ True when the write may go ahead """
        if not self._needs_confirmation:
            return True
        cfg = self.attributeConfig()
        name = cfg.label if (cfg is not None and cfg.label) else (self.model().attr_name if self.model() else "")
        value = self.attributeValue()
        current = self.text_of(self.set_point(value, self.setPointMode)) if value is not None else "?"
        return bool(self.ask_confirmation(self._confirm_message.format(attribute=name, current=current, new=new_text)))

    def text_of(self, value):
        return str(value)

    def revert(self):
        """ Show the device value again (after a refused or failed write) """
        if self.attributeValue() is not None:
            self.on_value(self.attributeValue())

    def on_write_done(self, err):
        if not self.writing():
            return      # another widget's write on the shared model: keep this one's edit
        if err is None:
            self.setStyleSheet("")
            self.setToolTip(self.tooltip_text())
        else:
            self.setStyleSheet(_ERROR_STYLE)
            self.setToolTip(self.tooltip_text() + "<br/><font color='red'>Write failed: {0}</font>".format(err.message))
            self._editing = False
            self.revert()

    def on_model_cleared(self):
        """ Unbound: nothing to write to, nothing to show """
        self.setEnabled(False)
        self.setStyleSheet("")
        self._tnext = None
        self.blockSignals(True)
        try:
            if isinstance(self, QtWidgets.QLineEdit):
                self._editing = False
                self.clear()
            elif isinstance(self, QtWidgets.QComboBox):
                self.setCurrentIndex(-1)
            elif isinstance(self, QtWidgets.QAbstractButton):
                self.setChecked(False)
        finally:
            self.blockSignals(False)

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
        if not self.confirm_write(self.text_of(bool(checked))):
            self.revert()
            return
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

    def text_of(self, value):
        try:
            return self.itemText(int(value))
        except (TypeError, ValueError):
            return str(value)

    def _on_activated(self, index):
        if not self.confirm_write(self.itemText(index)):
            self.revert()
            return
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
        if not self._editing:
            return      # Enter on unedited text would write the rounded, displayed value
        try:
            value = self.parse(self.text())
        except (ValueError, ArgParserError) as e:
            self.setStyleSheet(_ERROR_STYLE)
            self.setToolTip(self.tooltip_text() + "<br/><font color='red'>{0}</font>".format(e))
            return
        refused = not self.confirm_write(self.text_of(value))
        self._editing = False
        self.setStyleSheet("")
        if refused:
            self.revert()
            return
        self.write(value)

    def on_value(self, value):
        if self._editing:
            return
        self.setText(self.display(self.set_point(value, self.setPointMode)))

    def parse(self, text):
        return text

    def display(self, value):
        return str(value)

    def text_of(self, value):
        return self.display(value)


class QStringSetter(_LineSetter):
    """ Line edit writing a DevString attribute on Enter.

    ``setWriteOnEdit(True)`` writes on every keystroke instead (ATK
    ``StringScalarEditor`` ``updateImmediately``; confirmation is then not asked).
    """

    modelName = model_name_property()
    _write_on_edit = False

    def setWriteOnEdit(self, b):
        self._write_on_edit = bool(b)

    def writeOnEdit(self):
        return self._write_on_edit

    def _on_edited(self, text):
        if self._write_on_edit:
            self._editing = False
            self.setStyleSheet("")
            self.write_latest(text)     # one write at a time, in order
            return
        _LineSetter._on_edited(self, text)

    def on_value(self, value):
        if self._write_on_edit and self.hasFocus():
            return  # do not move the cursor under the user's fingers
        _LineSetter.on_value(self, value)


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


class _ComboSetter(_SetterMixin, QtWidgets.QComboBox):
    """ Combo of allowed values (ATK *ScalarComboEditor); write on selection """

    modelName = model_name_property()

    def __init__(self, parent=None, values=None):
        QtWidgets.QComboBox.__init__(self, parent)
        _SetterMixin.__init__(self)
        self._values = []
        self.activated.connect(self._on_activated)
        if values:
            self.setValuesList(values)

    def setValuesList(self, values):
        """ Allowed values (numbers or strings) """
        self._values = [self.convert(v) for v in values]
        self.blockSignals(True)
        self.clear()
        for v in self._values:
            self.addItem(self.text_of(v))
        self.setCurrentIndex(-1)
        self.blockSignals(False)
        if self.attributeValue() is not None:
            self.on_value(self.attributeValue())

    def valuesList(self):
        return list(self._values)

    def convert(self, v):
        return v

    def _on_activated(self, index):
        if not (0 <= index < len(self._values)):
            return
        value = self._values[index]
        if not self.confirm_write(self.text_of(value)):
            self.revert()
            return
        self.write(value)

    def on_value(self, value):
        v = self.set_point(value, self.setPointMode)
        self.blockSignals(True)
        try:
            # A value outside the list leaves the combo empty
            self.setCurrentIndex(self._index_of(v))
        finally:
            self.blockSignals(False)

    def _index_of(self, v):
        for i, x in enumerate(self._values):
            try:
                if x == self.convert(v):
                    return i
            except (TypeError, ValueError):
                pass
        return -1


class QNumberComboSetter(_ComboSetter):
    """ Numeric scalar with a list of allowed values (ATK NumberScalarComboEditor) """

    def convert(self, v):
        return float(v)

    def text_of(self, value):
        cfg = self.attributeConfig()
        try:
            if cfg is not None:
                return format_scalar(value, cfg.format, cfg.data_type)
            return "{0:g}".format(float(value))
        except (TypeError, ValueError):
            return str(value)

    def _on_activated(self, index):
        if 0 <= index < len(self._values):
            cfg = self.attributeConfig()
            if cfg is not None and is_int_type(cfg.data_type):
                self._values[index] = int(self._values[index])
        _ComboSetter._on_activated(self, index)


class QStringComboSetter(_ComboSetter):
    """ String scalar with a list of allowed values (ATK StringScalarComboEditor) """

    def convert(self, v):
        return str(v)


def parse_values_list(values):
    """ Allowed values from an attribute property: one per line, or comma separated """
    out = []
    for v in values or []:
        for part in str(v).split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out


def create_viewer(cfg, parent=None):
    """ Best read-only widget for an attribute configuration """
    if cfg.data_format == tango.AttrDataFormat.SCALAR and cfg.data_type == tango.CmdArgType.DevState:
        return QStateLabel(parent)
    return QValueLabel(parent)


def create_setter(cfg, parent=None, wheel=True, values=None):
    """ Best setter for an attribute configuration, or None when not writable.

    ``values``: allowed values; a numeric or string scalar then gets a combo.
    """
    if cfg.writable not in _WRITABLE:
        return None
    if cfg.data_format != tango.AttrDataFormat.SCALAR:
        return QArraySetter(parent)
    dt = cfg.data_type
    if values:
        if dt == tango.CmdArgType.DevString:
            return QStringComboSetter(parent, values)
        if is_numeric_type(dt):
            # Check before building: a combo that fails half-way stays a child of parent
            try:
                [float(v) for v in values]
            except (TypeError, ValueError):
                pass
            else:
                return QNumberComboSetter(parent, values)
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
