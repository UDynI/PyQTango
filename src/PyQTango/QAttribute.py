# -*- coding: utf-8 -*-
"""
QAttribute: one-line read/write widget for a scalar attribute.

Version 0.2 keeps the 0.1 API (``setTangoAttribute``, ``tangoAttribute``,
``label``, ``updated``, ``shutdown``) and look, but is built on the shared,
event-aware :class:`PyQTango.models.TangoAttributeModel`:

* works whether or not the server pushes change events (polling fallback);
* supports READ, READ_WRITE, READ_WITH_WRITE and WRITE attributes;
* shows spectrum and image attributes as read-only text;
* never blocks the GUI thread (configuration, reads and writes are asynchronous).

Created on Tue May 12 11:13:29 2020

@author: Michele Devetta <michele.devetta@cnr.it>
"""

import logging

import tango as PT

from .qt import QtCore, QtGui, QtWidgets, Signal, Slot, Property
from .config import get_image_path
from .core.formatting import format_scalar, format_value, is_float_type, is_int_type, is_numeric_type
from .widgets.base import TangoAttributeWidget
from .widgets.colors import state_style

log = logging.getLogger(__name__)

_WRITABLE = (PT.AttrWriteType.READ_WRITE, PT.AttrWriteType.READ_WITH_WRITE, PT.AttrWriteType.WRITE)


def _limit(text, data_type):
    """ Numeric min/max from an AttributeInfoEx string, or None """
    if text in (None, "", "Not specified"):
        return None
    try:
        return int(text) if is_int_type(data_type) else float(text)
    except ValueError:
        return None


class QAttribute(TangoAttributeWidget, QtWidgets.QWidget):

    # On Update signal (raw tango.DeviceAttribute, as in 0.1)
    updated = Signal(PT.DeviceAttribute)

    def __init__(self, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        TangoAttributeWidget.__init__(self)

        self.layout = QtWidgets.QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.w_value = None
        self.w_value_c = False
        self.c_button = None
        self.r_button = None
        self.__cfg = None
        self.__shape = None

    # -- 0.1 API -----------------------------------------------------------------
    def shutdown(self):
        """ Detach from the attribute (kept for compatibility) """
        self.setModel(None)

    def label(self):
        return self.__cfg.label if self.__cfg is not None else ""

    def tangoAttribute(self):
        return self.model().name if self.model() is not None else None

    def setTangoAttribute(self, attr_name):
        if not attr_name:
            self.setModel(None)
        else:
            log.debug("Setting up attribute %s", attr_name)
            self.setModel(attr_name)

    modelName = Property(str, TangoAttributeWidget.getModelName, TangoAttributeWidget.setModelName,
                         TangoAttributeWidget.resetModel)

    def event_callback(self, event):
        """ Kept for compatibility: events now arrive through the shared model """

    # -- Model hooks ---------------------------------------------------------------
    def on_model_cleared(self):
        self.__cleanWidget()
        self.__cfg = None
        self.__shape = None

    def on_config(self, cfg):
        self.__cfg = cfg
        shape = (cfg.data_format, cfg.data_type, cfg.writable)
        if shape != self.__shape:
            self.__shape = shape
            self.setupWidget()
        else:
            self.__apply_limits()
        self.setToolTip(self.tooltip_text())

    def on_error(self, err):
        self.setToolTip(self.tooltip_text())
        if err is not None and self.w_value is not None and not self.w_value_c:
            self.w_value.setStyleSheet("color: gray;")

    def on_value(self, value):
        if self.__cfg is None or self.w_value is None:
            return
        cfg = self.__cfg
        if cfg.data_format != PT.AttrDataFormat.SCALAR:
            self.w_value.setText(format_value(value.value, cfg.format, cfg.data_type, cfg.enum_labels,
                                              cfg.unit, max_items=20))
            if value.raw is not None:
                self.updated.emit(value.raw)
            return

        if cfg.writable in _WRITABLE and self.w_value_c:
            # The user is editing: do not overwrite, flag the change
            self.w_value.setStyleSheet("color: red;")
            return

        shown = value.value
        if cfg.writable == PT.AttrWriteType.WRITE:
            shown = value.w_value if value.w_value is not None else value.value

        w = self.w_value
        w.blockSignals(True)
        try:
            if isinstance(w, QtWidgets.QLineEdit):
                w.setText(self.__format_value(shown))
                w.setStyleSheet("")
            elif isinstance(w, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                w.setValue(shown)
                w.setStyleSheet("")
            elif isinstance(w, QtWidgets.QCheckBox):
                w.setChecked(bool(shown))
            elif isinstance(w, QtWidgets.QComboBox):
                w.setCurrentIndex(int(shown))
            elif isinstance(w, QtWidgets.QLabel) and cfg.data_type == PT.CmdArgType.DevState:
                w.setText(str(shown))
                w.setStyleSheet(state_style(shown))
        finally:
            w.blockSignals(False)
        if value.raw is not None:
            self.updated.emit(value.raw)

    def on_write_done(self, err):
        if err is None:
            return
        QtWidgets.QMessageBox.critical(self, "Failed to set attribute", err.message)

    # -- Widget construction ---------------------------------------------------------
    def __cleanWidget(self):
        for w in (self.w_value, self.c_button, self.r_button):
            if w is not None:
                self.layout.removeWidget(w)
                w.deleteLater()
        self.w_value = None
        self.w_value_c = False
        self.c_button = None
        self.r_button = None

    def setupWidget(self):
        self.__cleanWidget()
        cfg = self.__cfg
        if cfg is None:
            return
        dtype = cfg.data_type

        if cfg.data_format != PT.AttrDataFormat.SCALAR:
            # Spectrum / image: read-only text summary
            self.w_value = QtWidgets.QLineEdit(self)
            self.w_value.setReadOnly(True)

        elif cfg.writable == PT.AttrWriteType.READ:
            if is_numeric_type(dtype) or dtype in (PT.CmdArgType.DevString, PT.CmdArgType.DevEnum):
                self.w_value = QtWidgets.QLineEdit(self)
                self.w_value.setReadOnly(True)
            elif dtype == PT.CmdArgType.DevBoolean:
                self.w_value = QtWidgets.QCheckBox(self)
                self.w_value.setText("")
                self.w_value.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                self.w_value.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            elif dtype == PT.CmdArgType.DevState:
                self.w_value = QtWidgets.QLabel(self)
                self.w_value.setText(str(PT.DevState.UNKNOWN))
                self.w_value.setStyleSheet(state_style(PT.DevState.UNKNOWN))
            else:
                self.w_value = QtWidgets.QLineEdit(self)
                self.w_value.setReadOnly(True)

        else:
            minimum = _limit(cfg.min_value, dtype)
            maximum = _limit(cfg.max_value, dtype)
            if is_numeric_type(dtype):
                if minimum is not None and maximum is not None:
                    if is_float_type(dtype):
                        self.w_value = QtWidgets.QDoubleSpinBox(self)
                    else:
                        self.w_value = QtWidgets.QSpinBox(self)
                        self.w_value.setSingleStep(1)
                else:
                    self.w_value = QtWidgets.QLineEdit(self)
                self.__add_buttons()
            elif dtype == PT.CmdArgType.DevBoolean:
                self.w_value = QtWidgets.QCheckBox(self)
                self.w_value.setText("")
            elif dtype == PT.CmdArgType.DevEnum:
                self.w_value = QtWidgets.QComboBox(self)
                self.w_value.addItems(list(cfg.enum_labels))
                self.__add_buttons()
            elif dtype == PT.CmdArgType.DevString:
                self.w_value = QtWidgets.QLineEdit(self)
                self.__add_buttons()
            else:
                # e.g. writable DevState: show it, writes are not supported here
                self.w_value = QtWidgets.QLineEdit(self)
                self.w_value.setReadOnly(True)
            self.__apply_limits()
            self.__connect_editor()

        self.w_value.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.w_value.setObjectName(cfg.name)
        self.layout.addWidget(self.w_value)
        if self.c_button is not None:
            self.c_button.released.connect(self.on_pb_c_released)
            self.layout.addWidget(self.c_button)
        if self.r_button is not None:
            self.r_button.released.connect(self.on_pb_r_released)
            self.layout.addWidget(self.r_button)
        # Show the last value at once
        if self.attributeValue() is not None:
            self.on_value(self.attributeValue())

    def __add_buttons(self):
        name = self.__cfg.name
        self.c_button = self.__create_pushbutton(name, self, 'c', self.size().height())
        self.r_button = self.__create_pushbutton(name, self, 'r', self.size().height())

    def __apply_limits(self):
        cfg, w = self.__cfg, self.w_value
        if cfg is None or w is None:
            return
        if isinstance(w, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
            minimum = _limit(cfg.min_value, cfg.data_type)
            maximum = _limit(cfg.max_value, cfg.data_type)
            if isinstance(w, QtWidgets.QDoubleSpinBox):
                decimals = 2
                fmt = cfg.format or ""
                if "." in fmt:
                    try:
                        decimals = int(fmt.split(".")[1].rstrip("fFeEgG"))
                    except ValueError:
                        pass
                w.setDecimals(decimals)
                w.setSingleStep(10 ** -decimals if decimals > 0 else 1.0)
            if minimum is not None and maximum is not None:
                w.setRange(minimum, maximum)
            unit = cfg.unit if cfg.unit not in ("", "No unit", "Not specified") else ""
            w.setSuffix(" " + unit if unit else "")

    def __connect_editor(self):
        w = self.w_value
        if isinstance(w, QtWidgets.QLineEdit):
            w.textChanged.connect(self.on_textChanged)
        elif isinstance(w, QtWidgets.QCheckBox):
            w.toggled.connect(self.on_toggled)
        elif isinstance(w, QtWidgets.QSpinBox):
            w.valueChanged.connect(self.on_valueChanged_int)
        elif isinstance(w, QtWidgets.QDoubleSpinBox):
            w.valueChanged.connect(self.on_valueChanged_float)
        elif isinstance(w, QtWidgets.QComboBox):
            w.currentIndexChanged.connect(self.on_currentIndexChanged)

    # -- Formatting / parsing ----------------------------------------------------------
    def __format_value(self, value):
        cfg = self.__cfg
        unit = cfg.unit if cfg.unit not in ("", "No unit", "Not specified") else ""
        if cfg.data_type == PT.CmdArgType.DevEnum or not is_numeric_type(cfg.data_type):
            return format_scalar(value, "", cfg.data_type, cfg.enum_labels)
        return format_scalar(value, cfg.format, cfg.data_type, unit=unit)

    def __check_value(self, text):
        cfg = self.__cfg
        dtype = cfg.data_type
        unit = cfg.unit if cfg.unit not in ("", "No unit", "Not specified") else ""
        if unit:
            text = text.replace(unit, "")
        text = text.strip()
        if dtype == PT.CmdArgType.DevString:
            return text
        try:
            if is_float_type(dtype):
                return float(text)
            if is_int_type(dtype):
                return int(text, 0)
        except ValueError:
            return None
        return None

    def __create_pushbutton(self, name, parent, action, sz):
        pb = QtWidgets.QPushButton(parent)
        pb.setEnabled(False)
        pb.setGeometry(QtCore.QRect(0, 0, sz, sz))
        pb.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)
        pb.setText("")
        icon = QtGui.QIcon()
        image = "confirm.png" if action == 'c' else "reject.png"
        icon.addPixmap(QtGui.QPixmap(get_image_path(image)), QtGui.QIcon.Mode.Normal, QtGui.QIcon.State.Off)
        pb.setIcon(icon)
        pb.setObjectName(name + "_" + action)
        return pb

    # -- Slots ---------------------------------------------------------------------------
    def __set_editing(self, editing):
        self.w_value_c = editing
        if self.c_button is not None:
            self.c_button.setEnabled(editing)
            self.r_button.setEnabled(editing)
        self.w_value.setStyleSheet("color: darkgreen;" if editing else "")

    @Slot()
    def on_pb_c_released(self):
        # Confirm
        w = self.w_value
        if isinstance(w, QtWidgets.QLineEdit):
            val = self.__check_value(w.text())
            if val is None:
                QtWidgets.QMessageBox.critical(self, "Value error", "Failed to convert value")
                return
        elif isinstance(w, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
            val = w.value()
        elif isinstance(w, QtWidgets.QComboBox):
            val = w.currentIndex()
        else:
            return
        self.write(val)
        self.__set_editing(False)

    @Slot()
    def on_pb_r_released(self):
        # Reject: show the last value again
        self.__set_editing(False)
        if self.attributeValue() is not None:
            self.on_value(self.attributeValue())
        elif self.model() is not None:
            self.model().refresh()

    @Slot(str)
    def on_textChanged(self, text):
        self.__set_editing(True)

    @Slot(bool)
    def on_toggled(self, checked):
        self.write(bool(checked))

    # Kept for compatibility with 0.1 subclasses
    def on_stateChanged(self, state):
        self.write(bool(state))

    @Slot(int)
    def on_valueChanged_int(self, value):
        self.__set_editing(True)

    @Slot(float)
    def on_valueChanged_float(self, value):
        self.__set_editing(True)

    @Slot(int)
    def on_currentIndexChanged(self, index):
        self.__set_editing(True)
