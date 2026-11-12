# -*- coding: utf-8 -*-
""" Boolean widgets from ATK 9.4/10.0 and the ATK 10 setter behaviour """

import pytest

from PyQTango.qt import QtCore, QtGui, Qt
from PyQTango import widgets as W
from PyQTango.widgets.boolean import text_color_for
from conftest import attr, wait, value_of

pytestmark = pytest.mark.usefixtures("no_tango_in_gui_thread")


def _bg(widget):
    style = widget.styleSheet()
    return style.split("background-color:")[1].split(";")[0].strip()


def test_text_color_rule():
    assert text_color_for("#00ff00").name() == "#000000"
    assert text_color_for("#007d00").name() == "#ffffff"


def test_boolean_label(qtbot, device_name):
    lab = W.QBooleanLabel()
    qtbot.addWidget(lab)
    lab.setModel(attr(device_name, "rw_switch"))
    wait(qtbot, lambda: lab.booleanValue() is not None)
    assert lab.text() == "Pump"                       # attribute label
    expected = "#00ff00" if lab.booleanValue() else "#ffffff"
    assert _bg(lab) == expected
    lab.trueText = "Running"
    lab.falseText = "Stopped"
    assert lab.text() in ("Running", "Stopped")
    lab.displayMode = "tick"
    assert lab.text() in (u"✔", u"✕")
    assert _bg(lab) in ("#ffffff", "#c0c0c0")
    lab.trueColor = QtGui.QColor("#123456")
    assert lab.trueColor.name() == "#123456"


def test_boolean_label_error(qtbot, device_name):
    lab = W.QBooleanLabel()
    qtbot.addWidget(lab)
    lab.hideUntilValid = True
    lab.setModel(attr(device_name, "no_such_attribute"))
    wait(qtbot, lambda: lab.attributeError() is not None, timeout=8000)
    assert lab.booleanValue() is None
    assert _bg(lab) == "#ff0000"
    assert lab.isHidden()


def test_switch_button_standalone(qtbot):
    sw = W.QSwitchButton(onText="OPEN", offText="CLOSED")
    qtbot.addWidget(sw)
    sw.show()
    seen = []
    sw.switched.connect(seen.append)
    qtbot.mouseClick(sw, Qt.MouseButton.LeftButton)
    assert sw.isChecked() and seen == [True]
    # Keyboard toggles too
    sw.setFocus()
    qtbot.keyClick(sw, Qt.Key.Key_Space)
    assert not sw.isChecked() and seen == [True, False]
    # Programmatic changes do not emit switched
    sw.setChecked(True)
    assert seen == [True, False]
    # Confirmation refused
    sw.setNeedsConfirmation(True)
    questions = []
    sw.ask_confirmation = lambda msg: questions.append(msg) or False
    qtbot.mouseClick(sw, Qt.MouseButton.LeftButton)
    assert sw.isChecked() and questions == ["Switch from OPEN to CLOSED?"]
    # State changed from outside while the question is open: the toggle is dropped
    def external_change(msg):
        sw.setChecked(not sw.isChecked())
        return True
    sw.ask_confirmation = external_change
    qtbot.mouseClick(sw, Qt.MouseButton.LeftButton)
    assert not sw.isChecked() and seen == [True, False]
    sw.ask_confirmation = lambda msg: True
    qtbot.mouseClick(sw, Qt.MouseButton.LeftButton)
    assert sw.isChecked() and seen == [True, False, True]
    sw.grab()   # paints without errors
    assert sw.sizeHint().width() > sw.sizeHint().height()


def test_switch_setter(qtbot, device_name):
    name = attr(device_name, "rw_switch")
    w = W.QSwitchSetter()
    qtbot.addWidget(w)
    w.show()
    w.setModel(name)
    wait(qtbot, lambda: w.switch.isEnabled() and w.attributeValue() is not None)
    assert w.label.text() == "Pump"
    start = bool(value_of(name))
    assert w.isChecked() == start
    qtbot.mouseClick(w.switch, Qt.MouseButton.LeftButton)
    wait(qtbot, lambda: bool(value_of(name)) == (not start))
    # Refused confirmation: nothing written
    w.setNeedsConfirmation(True)
    w.switch.ask_confirmation = lambda msg: False
    qtbot.mouseClick(w.switch, Qt.MouseButton.LeftButton)
    qtbot.wait(300)
    assert bool(value_of(name)) == (not start) and w.isChecked() == (not start)
    # Accepted confirmation
    w.switch.ask_confirmation = lambda msg: True
    qtbot.mouseClick(w.switch, Qt.MouseButton.LeftButton)
    wait(qtbot, lambda: bool(value_of(name)) == start)
    w.trueLabel = "Pump running"
    w.falseLabel = "Pump stopped"
    assert w.label.text() == ("Pump running" if w.isChecked() else "Pump stopped")
    w.showQuality = True
    assert "background-color" in w.label.styleSheet()


def test_switch_setter_write_failure(qtbot, device_name):
    w = W.QSwitchSetter()
    qtbot.addWidget(w)
    w.show()
    w.setModel(attr(device_name, "rw_locked"))
    wait(qtbot, lambda: w.switch.isEnabled() and w.attributeValue() is not None)
    qtbot.mouseClick(w.switch, Qt.MouseButton.LeftButton)
    wait(qtbot, lambda: "Write failed" in w.toolTip())
    assert not w.isChecked()            # put back to the device value


def test_setter_confirmation_and_revert(qtbot, device_name):
    e = W.QEnumSetter()
    qtbot.addWidget(e)
    e.setModel(attr(device_name, "rw_enum"))
    wait(qtbot, lambda: e.count() == 3 and e.attributeValue() is not None)
    before = e.currentIndex()
    other = (before + 1) % 3
    e.setNeedsConfirmation(True)
    asked = []
    e.ask_confirmation = lambda msg: asked.append(msg) or False
    e.setCurrentIndex(other)
    e.activated.emit(other)
    assert e.currentIndex() == before
    assert asked and asked[0].startswith("Change rw_enum from ") and asked[0].endswith(" to {0}?".format(e.itemText(other)))
    # Failed write puts the check box back
    b = W.QBooleanSetter()
    qtbot.addWidget(b)
    b.setModel(attr(device_name, "rw_locked"))
    wait(qtbot, lambda: b.isEnabled() and b.attributeValue() is not None)
    b.click()
    wait(qtbot, lambda: "red" in b.styleSheet())
    assert not b.isChecked()


def test_string_write_on_edit(qtbot, device_name):
    name = attr(device_name, "rw_string")
    s = W.QStringSetter()
    qtbot.addWidget(s)
    s.setModel(name)
    wait(qtbot, lambda: s.attributeValue() is not None)
    s.setWriteOnEdit(True)
    s.setText("abc")
    s.textEdited.emit("abc")
    wait(qtbot, lambda: value_of(name) == "abc")
    # Restore the shared device state for the other tests
    s.setText("hello")
    s.textEdited.emit("hello")
    wait(qtbot, lambda: value_of(name) == "hello")


def test_error_dialog_long_message(qtbot):
    import tango
    long_msg = "\n".join("{0} This is a multiline error".format(i) for i in range(100))
    err = tango.DevFailed(tango.DevError())
    try:
        tango.Except.throw_exception("Test_Error", long_msg, "test")
    except tango.DevFailed as e:
        err = e
    dlg = W.QErrorDialog(err)
    qtbot.addWidget(dlg)
    assert dlg.message_widget.maximumHeight() == 300
    assert dlg.maximumWidth() == 800
