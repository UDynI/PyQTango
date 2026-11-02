# -*- coding: utf-8 -*-
"""
State and Status viewers (ATK StateViewer / StatusViewer).
"""

import tango

from ..qt import QtWidgets, Qt
from ..core.formatting import state_name
from .base import TangoAttributeWidget, TangoDeviceWidget, model_name_property, device_name_property
from .colors import state_style


class QStateLabel(TangoAttributeWidget, QtWidgets.QLabel):
    """ DevState shown as text on the ATK state colour.

    Bind with ``setModel("dom/fam/mem/State")`` or ``setDevice("dom/fam/mem")``.
    """

    modelName = model_name_property()

    def __init__(self, parent=None):
        QtWidgets.QLabel.__init__(self, parent)
        TangoAttributeWidget.__init__(self)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(70)
        self.show_state(tango.DevState.UNKNOWN)

    def setDevice(self, device):
        """ Convenience: bind to the State attribute of a device """
        if not device:
            self.setModel(None)
        elif "#" in device:
            dev, frag = device.split("#", 1)
            self.setModel(dev + "/State#" + frag)
        else:
            self.setModel(device + "/State")

    def show_state(self, state):
        self.setText(state_name(state))
        self.setStyleSheet(state_style(state))

    def on_value(self, value):
        self.show_state(value.value)
        self.setToolTip(self.tooltip_text())

    def on_error(self, err):
        if err is not None:
            self.show_state(tango.DevState.UNKNOWN)
        self.setToolTip(self.tooltip_text())

    def on_model_cleared(self):
        self.show_state(tango.DevState.UNKNOWN)


class QStatusViewer(TangoAttributeWidget, QtWidgets.QPlainTextEdit):
    """ Read-only, wrapping view of a Status (or any string) attribute """

    modelName = model_name_property()

    def __init__(self, parent=None):
        QtWidgets.QPlainTextEdit.__init__(self, parent)
        TangoAttributeWidget.__init__(self)
        self.setReadOnly(True)
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth)

    def setDevice(self, device):
        if not device:
            self.setModel(None)
        elif "#" in device:
            dev, frag = device.split("#", 1)
            self.setModel(dev + "/Status#" + frag)
        else:
            self.setModel(device + "/Status")

    def on_value(self, value):
        text = str(value.value)
        if text != self.toPlainText():
            self.setPlainText(text)

    def on_error(self, err):
        if err is not None:
            self.setPlainText(err.message)

    def on_model_cleared(self):
        self.clear()


class QStateStatusViewer(TangoDeviceWidget, QtWidgets.QWidget):
    """ Device header as in ATKPanel: state box next to the status text """

    deviceName = device_name_property()

    def __init__(self, parent=None, orientation=Qt.Orientation.Horizontal):
        QtWidgets.QWidget.__init__(self, parent)
        TangoDeviceWidget.__init__(self)
        if orientation == Qt.Orientation.Horizontal:
            layout = QtWidgets.QHBoxLayout(self)
        else:
            layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.state = QStateLabel(self)
        self.status = QStatusViewer(self)
        self.status.setMaximumHeight(80)
        layout.addWidget(self.state)
        layout.addWidget(self.status, 1)

    def on_device_changed(self, device):
        if device is None:
            self.state.setModel(None)
            self.status.setModel(None)
        else:
            self.state.setModel(device.state_model)
            self.status.setModel(device.status_model)
