# -*- coding: utf-8 -*-
"""
QCommandCombo: run any command of a device from a combo box (ATK ``CommandComboViewer``).

Choosing a command runs it at once when it takes no argument; otherwise the
argument is asked for with Jive's syntax (:mod:`PyQTango.core.argparser`). A
command that returns something shows its result in a popup, and a failure shows
the full error stack.

@author: Michele Devetta <michele.devetta@cnr.it>
"""

import tango

from ..qt import QtWidgets, Qt, Signal, Property
from ..core.argparser import parse_command_argin, argin_example, ArgParserError
from ..core.formatting import format_value
from .base import TangoDeviceWidget, device_name_property
from .errors import show_error

__all__ = ["QCommandCombo", "command_result_text"]

T = tango.CmdArgType


def command_result_text(result, out_type=None):
    """ Command output as text (arrays one element per line, as ATK's result popup) """
    if result is None:
        return ""
    if isinstance(result, (list, tuple)) and len(result) == 2 and out_type in (
            T.DevVarLongStringArray, T.DevVarDoubleStringArray):
        nums, strs = result
        return "\n".join([str(v) for v in nums] + [str(v) for v in strs])
    if out_type == T.DevState:
        return str(result)
    if isinstance(result, (str, bytes)):
        return result if isinstance(result, str) else repr(result)
    try:
        import numpy as np
        if isinstance(result, (list, tuple, np.ndarray)):
            return "\n".join(str(v) for v in np.asarray(result).ravel())
    except Exception:  # noqa: BLE001
        pass
    return format_value(result)


class QCommandCombo(TangoDeviceWidget, QtWidgets.QComboBox):
    """ Command combo of one device.

    ``operatorView`` hides EXPERT commands. The hooks :meth:`ask_argin`,
    :meth:`show_result` and :meth:`show_failure` can be replaced (tests,
    embedding).

    Signals:
        loaded(int): number of commands listed
        executed(str, object): command, result (after a successful run)
        failed(str, object): command, ErrorRecord
    """

    loaded = Signal(int)
    executed = Signal(str, object)
    failed = Signal(str, object)
    deviceName = device_name_property()

    PROMPT = "Commands..."

    def __init__(self, parent=None):
        QtWidgets.QComboBox.__init__(self, parent)
        TangoDeviceWidget.__init__(self)
        self._commands = []
        self._operator_view = False
        self._pending = {}
        self.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.activated.connect(self._on_activated)
        self._fill()

    # -- Properties ------------------------------------------------------------
    def getOperatorView(self):
        return self._operator_view

    def setOperatorView(self, on):
        self._operator_view = bool(on)
        self._fill()

    operatorView = Property(bool, getOperatorView, setOperatorView)

    # -- Device ------------------------------------------------------------------
    def on_device_changed(self, device):
        for sig, slot in getattr(self, "_conns", []):
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._conns = []
        self._commands = []
        self._fill()
        if device is None:
            return
        self._conns = [(device.commandsChanged, self._on_commands),
                       (device.commandDone, self._on_done),
                       (device.commandFailed, self._on_failed)]
        for sig, slot in self._conns:
            sig.connect(slot)
        if device.commands() is not None:
            self._on_commands(device.commands())
        else:
            device.load_commands()

    def _on_commands(self, cmds):
        self._commands = list(cmds)
        self._fill()
        self.loaded.emit(len(self.commands()))

    def commands(self):
        """ CommandInfo of the listed commands """
        return [c for c in self._commands
                if not (self._operator_view and c.disp_level == tango.DispLevel.EXPERT)]

    def command_names(self):
        return [c.cmd_name for c in self.commands()]

    def _fill(self):
        self.blockSignals(True)
        self.clear()
        self.addItem(self.PROMPT)
        for c in self.commands():
            self.addItem(c.cmd_name)
            self.setItemData(self.count() - 1, c.in_type_desc if c.in_type != T.DevVoid else "No argument",
                             Qt.ItemDataRole.ToolTipRole)
        self.setCurrentIndex(0)
        self.blockSignals(False)

    # -- Execution ---------------------------------------------------------------
    def _on_activated(self, index):
        self.setCurrentIndex(0)
        if index <= 0:
            return
        cmds = self.commands()
        if index - 1 < len(cmds):
            self.run(cmds[index - 1].cmd_name)

    def info(self, command):
        for c in self._commands:
            if c.cmd_name.lower() == command.lower():
                return c
        return None

    def run(self, command, text=None):
        """ Run ``command``; ``text`` is the argument (asked for when None and needed) """
        dev = self.device()
        info = self.info(command)
        if dev is None or info is None:
            return None
        argin = None
        if info.in_type != T.DevVoid:
            if text is None:
                text = self.ask_argin(info)
                if text is None:
                    return None
            try:
                argin = parse_command_argin(text, info.in_type)
            except (ArgParserError, ValueError) as e:
                self.show_failure(command, str(e))
                return None
        self._pending[info.cmd_name] = info      # the device model reports the device's spelling
        return dev.execute(info.cmd_name, argin)

    def _on_done(self, command, result, _ms):
        info = self._pending.pop(command, None)
        if info is None:
            return
        self.executed.emit(command, result)
        if info.out_type != T.DevVoid:
            self.show_result(command, command_result_text(result, info.out_type))

    def _on_failed(self, command, err):
        if self._pending.pop(command, None) is None:
            return
        self.failed.emit(command, err)
        self.show_failure(command, err)

    # -- Hooks -------------------------------------------------------------------
    def ask_argin(self, info):
        """ Argument text for ``info`` (tango.CommandInfo), or None to cancel """
        hint = argin_example(info.in_type)
        label = "{0}\n{1}".format(info.in_type_desc if info.in_type_desc not in ("", "Uninitialised") else
                                  str(info.in_type), hint).strip()
        text, ok = QtWidgets.QInputDialog.getText(self, "Command: " + info.cmd_name, label)
        return text if ok else None

    def show_result(self, command, text):
        QtWidgets.QMessageBox.information(self, "Command: " + command, text or "(empty)")

    def show_failure(self, command, err):
        if isinstance(err, str):
            QtWidgets.QMessageBox.critical(self, "Command: " + command, err)
        else:
            show_error(self, err, "Command: " + command)
