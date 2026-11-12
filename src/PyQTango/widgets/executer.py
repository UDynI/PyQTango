# -*- coding: utf-8 -*-
"""
QCommandExecuter: run any command of a device.

Version 0.2 keeps the 0.1 API (``setDevice``, ``device``) and layout, but:

* accepts every argument type through :mod:`PyQTango.core.argparser`
  (Jive syntax: arrays, ``[1,2][a,b]``, ``"fmt",[bytes]``, states, enums...);
* never blocks the GUI thread;
* shows the full Tango error stack.

Created on Tue May 12 11:13:29 2020

@author: Michele Devetta <michele.devetta@cnr.it>
"""

import logging

import tango as PT

from ..qt import QtGui, QtWidgets, Signal, Slot, is_deleted
from .icons import get_image_path
from ..core.argparser import parse_command_argin, argin_example, ArgParserError
from ..core.formatting import format_value
from ..models.registry import device_model

log = logging.getLogger(__name__)


class QCommandExecuter(QtWidgets.QWidget):

    #: command, result, duration (ms)
    executed = Signal(str, object, float)

    def __init__(self, parent=None):
        QtWidgets.QWidget.__init__(self, parent)

        self.selector = QtWidgets.QComboBox(self)
        self.selector.setObjectName("executor_selector")
        self.selector.currentIndexChanged.connect(self.on_index_changed)
        self.arg = QtWidgets.QLineEdit(self)
        self.arg.setObjectName("executor_arg")
        self.arg.setDisabled(True)
        self.arg.returnPressed.connect(self.on_released)
        self.execute = QtWidgets.QPushButton(self)
        self.execute.setObjectName("executor_button")
        icon = QtGui.QIcon()
        icon.addPixmap(QtGui.QPixmap(get_image_path("execute.png")), QtGui.QIcon.Mode.Normal, QtGui.QIcon.State.Off)
        self.execute.setIcon(icon)
        self.execute.setDisabled(True)
        self.execute.released.connect(self.on_released)
        self.desc = QtWidgets.QLabel(self)
        self.desc.setObjectName("executor_desc")
        self.desc.setWordWrap(True)
        self.results = QtWidgets.QTextEdit(self)
        self.results.setObjectName("executor_results")
        self.results.setReadOnly(True)

        hlayout = QtWidgets.QHBoxLayout()
        hlayout.addWidget(self.selector)
        hlayout.addWidget(self.arg)
        hlayout.addWidget(self.execute)
        vlayout = QtWidgets.QVBoxLayout()
        vlayout.addLayout(hlayout)
        vlayout.addWidget(self.desc)
        vlayout.addWidget(self.results)
        self.setLayout(vlayout)

        sz = self.execute.size()
        self.execute.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)
        self.execute.resize(sz.height(), sz.height())

        self.__dev = None
        self.__cmds = []
        self.__cmd_info = None

    def device(self):
        return self.__dev.name if self.__dev is not None else None

    def __cleanWidget(self):
        self.selector.blockSignals(True)
        self.selector.clear()
        self.selector.blockSignals(False)
        self.__cmds = []
        self.__cmd_info = None
        self.execute.setDisabled(True)
        self.arg.setDisabled(True)

    def setDevice(self, device):
        self.__cleanWidget()
        if self.__dev is not None:
            for sig, slot in self.__connections(self.__dev):
                try:
                    sig.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
        self.__dev = device_model(device) if device else None
        if self.__dev is None:
            return
        for sig, slot in self.__connections(self.__dev):
            sig.connect(slot)
        self.__dev.load_commands()

    def __connections(self, dev):
        return [(dev.commandsChanged, self.__on_commands), (dev.errorChanged, self.__on_device_error)]

    def __on_commands(self, cmds):
        self.__cmds = list(cmds)
        self.selector.blockSignals(True)
        self.selector.clear()
        self.selector.addItems([c.cmd_name for c in self.__cmds])
        self.selector.blockSignals(False)
        self.execute.setDisabled(not self.__cmds)
        self.on_index_changed(self.selector.currentIndex())

    def __on_device_error(self, err):
        log.warning("Device not available: %s", err)
        self.results.setPlainText(err.text())
        self.execute.setDisabled(True)
        self.arg.setDisabled(True)

    @Slot(int)
    def on_index_changed(self, index):
        if index < 0 or index >= len(self.__cmds):
            self.__cmd_info = None
            return
        info = self.__cmd_info = self.__cmds[index]
        idesc = info.in_type_desc if info.in_type_desc != 'Uninitialised' else 'None'
        odesc = info.out_type_desc if info.out_type_desc != 'Uninitialised' else 'None'
        msg = "Input: {0} (type: {1!s})\nOutput: {2} (type: {3!s})".format(idesc, info.in_type, odesc, info.out_type)
        self.desc.setText(msg)
        void = info.in_type == PT.CmdArgType.DevVoid
        self.arg.setDisabled(void)
        self.arg.setPlaceholderText(argin_example(info.in_type))

    @Slot()
    def on_released(self):
        info = self.__cmd_info
        if info is None or self.__dev is None or not self.execute.isEnabled():
            return
        argin = None
        if info.in_type != PT.CmdArgType.DevVoid:
            try:
                argin = parse_command_argin(self.arg.text(), info.in_type)
            except ArgParserError as e:
                QtWidgets.QMessageBox.critical(self, "Bad argument", str(e))
                return
        self.execute.setDisabled(True)
        cmd = info.cmd_name
        # Use this call's own task, so other widgets running commands on the
        # same device do not update this one
        task = self.__dev.execute(cmd, argin)
        # The widget can be deleted, or its device cleared, before the command ends
        dev_name = self.__dev.name
        task.done.connect(lambda res, c=cmd: None if is_deleted(self) else
                          self.__on_done(dev_name, c, res[0], res[1]))
        task.failed.connect(lambda err, c=cmd: None if is_deleted(self) else self.__on_failed(c, err))

    def __on_done(self, dev_name, cmd, result, duration_ms):
        self.execute.setDisabled(False)
        text = format_value(result) if result is not None else "Command OK"
        self.results.setPlainText("Command: {0}/{1}\nDuration: {2:d} msec\nResult: {3}".format(
            dev_name, cmd, int(duration_ms), text))
        self.executed.emit(cmd, result, duration_ms)

    def __on_failed(self, cmd, err):
        self.execute.setDisabled(False)
        self.results.setPlainText(err.text())
