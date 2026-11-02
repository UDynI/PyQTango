# -*- coding: utf-8 -*-
""" Widgets on a live device server (both bindings) """

import pytest
import tango

from PyQTango.qt import QtCore, QtWidgets, Qt, QAction, enum_value, API
from PyQTango import widgets as W
from PyQTango import QAttribute, QCommandExecuter, QDigitDial, QStatusLed, QDeviceTree
from PyQTango.models import attribute_model
from conftest import attr, wait, value_of

pytestmark = pytest.mark.usefixtures("no_tango_in_gui_thread")


def test_shim():
    assert API in ("PyQt5", "PyQt6")
    assert enum_value(Qt.CheckState.Checked) == 2
    assert QAction is not None


def test_value_label(qtbot, device_name):
    w = W.QValueLabel()
    qtbot.addWidget(w)
    w.setModel(attr(device_name, "rw_double"))
    wait(qtbot, lambda: w.text().endswith("mm"), timeout=5000)
    assert "." in w.text()
    w.setShowUnit(False)
    assert not w.text().endswith("mm")
    alarm = W.QValueLabel()
    qtbot.addWidget(alarm)
    alarm.setModel(attr(device_name, "alarm_double"))
    wait(qtbot, lambda: alarm.attributeValue() is not None, timeout=5000)
    assert alarm.attributeValue().quality == tango.AttrQuality.ATTR_ALARM
    assert "rgba" in alarm.styleSheet()


def test_state_status(qtbot, device_name):
    w = W.QStateStatusViewer()
    qtbot.addWidget(w)
    w.setDevice(device_name)
    wait(qtbot, lambda: w.state.text() == "ALARM" and "Device is ON" in w.status.toPlainText(), timeout=5000)
    assert "#ff8c00" in w.state.styleSheet()   # ATK alarm orange


def test_qattribute_compat_roundtrip(qtbot, device_name):
    w = QAttribute()
    qtbot.addWidget(w)
    received = []
    w.updated.connect(received.append)
    w.setTangoAttribute(attr(device_name, "rw_double"))
    wait(qtbot, lambda: isinstance(w.w_value, QtWidgets.QDoubleSpinBox) and received, timeout=5000)
    assert isinstance(received[-1], tango.DeviceAttribute)
    assert w.label() == "RW double"
    w.w_value.setValue(12.25)
    assert w.w_value_c and w.c_button.isEnabled()
    w.on_pb_c_released()
    wait(qtbot, lambda: value_of(attr(device_name, "rw_double")) == 12.25,
                    timeout=5000)
    assert not w.w_value_c
    w.shutdown()


def test_qattribute_string_and_spectrum(qtbot, device_name):
    s = QAttribute()
    qtbot.addWidget(s)
    s.setTangoAttribute(attr(device_name, "rw_string"))
    wait(qtbot, lambda: isinstance(s.w_value, QtWidgets.QLineEdit) and s.w_value.text(), timeout=5000)
    sp = QAttribute()
    qtbot.addWidget(sp)
    sp.setTangoAttribute(attr(device_name, "spectrum"))
    wait(qtbot, lambda: sp.w_value is not None and sp.w_value.text().startswith("["), timeout=5000)


def test_setters(qtbot, device_name):
    b = W.QBooleanSetter()
    e = W.QEnumSetter()
    s = W.QStringSetter()
    n = W.QNumberSetter()
    for w in (b, e, s, n):
        qtbot.addWidget(w)
    b.setModel(attr(device_name, "rw_bool"))
    e.setModel(attr(device_name, "rw_enum"))
    s.setModel(attr(device_name, "rw_string"))
    n.setModel(attr(device_name, "rw_double"))
    # Setters show the set point; for a never written string Tango has none
    wait(qtbot, lambda: e.count() == 3 and s.text() == "hello" and n.text(), timeout=5000)
    assert [e.itemText(i) for i in range(3)] == ["Red", "Green", "Blue"]
    b.click()
    wait(qtbot, lambda: value_of(attr(device_name, "rw_bool")) == True, timeout=5000)  # noqa: E712 (numpy.bool_)
    e.setCurrentIndex(2)
    e.activated.emit(2)
    wait(qtbot, lambda: value_of(attr(device_name, "rw_enum")) == 2, timeout=5000)
    s.setText("world")
    s.textEdited.emit("world")
    s.returnPressed.emit()
    wait(qtbot, lambda: value_of(attr(device_name, "rw_string")) == "world",
                    timeout=5000)
    n.setText("500")
    n.returnPressed.emit()
    assert "red" in n.styleSheet()      # rejected: above max_value, nothing written


def test_wheel_editor(qtbot, device_name):
    w = W.QAttributeWheelEditor()
    qtbot.addWidget(w)
    w.show()
    w.setModel(attr(device_name, "rw_double"))
    wait(qtbot, lambda: w.attributeValue() is not None and w.decimals() == 2, timeout=5000)
    assert w.integerDigits() == 3          # "%6.2f"
    start = w.value()
    w.setFocus()
    cells = w._digit_cells()
    w._sel = cells[w.integerDigits() - 1]  # units digit
    qtbot.keyClick(w, Qt.Key.Key_Up)
    m = attribute_model(attr(device_name, "rw_double"))
    wait(qtbot, lambda: abs(m.last_value().value - (start + 1)) < 1e-9, timeout=5000)
    # Clamped to max_value = 100
    w.setValue(99.5)
    qtbot.keyClick(w, Qt.Key.Key_Up)
    assert w.value() == 100.0


def test_wheel_standalone_keyboard(qtbot):
    w = W.QWheelEditor(integer_digits=2, decimals=1)
    qtbot.addWidget(w)
    w.setRange(-10, 10)
    committed = []
    w.valueCommitted.connect(committed.append)
    w.setValue(1.5)
    w.setFocus()
    w._sel = w._digit_cells()[-1]
    qtbot.keyClick(w, Qt.Key.Key_Up)
    assert w.value() == 1.6 and w.isPending() and not committed
    qtbot.keyClick(w, Qt.Key.Key_Return)
    assert committed == [1.6]
    qtbot.keyClick(w, Qt.Key.Key_Minus)
    qtbot.keyClick(w, Qt.Key.Key_Escape)
    assert w.value() == 1.6


def test_scalar_list(qtbot, device_name):
    w = W.QScalarListViewer()
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.loaded, timeout=5000) as blocker:
        w.setDevice(device_name)
    names = [n.split("/")[-1].split("#")[0] for n in w.models()]
    assert "rw_double" in names and "expert_double" in names and "spectrum" not in names
    assert blocker.args[0] == len(names)
    w.setOperatorView(True)
    row = [r for r in w._rows if "expert_double" in r[0]][0]
    assert not row[2][0].isVisibleTo(w)


def test_command_executer(qtbot, device_name):
    w = QCommandExecuter()
    qtbot.addWidget(w)
    w.setDevice(device_name)
    wait(qtbot, lambda: w.selector.count() > 0, timeout=5000)
    w.selector.setCurrentIndex(w.selector.findText("Sum"))
    w.arg.setText("1,2,3.5")
    w.on_released()
    wait(qtbot, lambda: "Result: 6.5" in w.results.toPlainText(), timeout=5000)
    w.selector.setCurrentIndex(w.selector.findText("Fail"))
    w.on_released()
    wait(qtbot, lambda: "Fail on purpose" in w.results.toPlainText(), timeout=5000)


def test_lazy_tree(qtbot):
    class Node(W.TreeNode):
        def populate(self, ctx):
            depth = len(self.path())
            if depth >= 2:
                return [W.TreeNode("leaf", leaf=True)]
            return [Node("n%d" % i) for i in range(3)]

    model = W.LazyTreeModel(Node("root"))
    view = QtWidgets.QTreeView()
    qtbot.addWidget(view)
    view.setModel(model)
    found = []
    model.find_path(["n1", "n2", "leaf"], found.append)
    wait(qtbot, lambda: found, timeout=5000)
    assert found[0] is not None and model.node(found[0]).path() == ["n1", "n2", "leaf"]
    model.refresh(model.index(0, 0))
    assert model.data(model.index(0, 0, model.index(0, 0))) == model.LOADING_TEXT


def test_property_table():
    m = W.PropertyTableModel()
    m.set_properties([("a", ["1", "2"]), ("b", "x")])
    assert m.value(0) == "1\n2"
    m.setData(m.index(1, 1), "y\nz")
    assert m.changed() == {"b": ["y", "z"]} and m.is_modified()
    m.mark_clean()
    assert not m.is_modified()


def test_misc_widgets(qtbot):
    c = W.QConsole()
    qtbot.addWidget(c)
    c.separator()
    c.print("Command: a/b/c/Ping\n")
    assert "Ping" in c.contents()
    nav = W.QNavigationBar()
    qtbot.addWidget(nav)
    nav.search.setEditText("sys/tg_test/1")
    with qtbot.waitSignal(nav.searchRequested, timeout=1000):
        nav.search_action.trigger()
    hist = W.NavigationHistory()
    for p in ("a", "b", "c"):
        hist.record(p)
    assert hist.back() == "b" and hist.forward() == "c" and not hist.can_go_forward()
    ed = W.QSearchableEditor()
    qtbot.addWidget(ed)
    ed.setText("alpha\nbeta\ngamma")
    assert ed.editor.find_text("gam") and not ed.editor.find_text("zeta")
    comp = W.QCompleterLineEdit(items=["sys/tg_test/1", "sys/database/2"])
    qtbot.addWidget(comp)
    assert comp.items()[0] == "sys/tg_test/1"
    dlg = W.QErrorDialog(ValueError("boom"), "Test")
    qtbot.addWidget(dlg)
    assert "boom" in dlg.details.toPlainText()
    hist_w = W.QErrorHistory()
    qtbot.addWidget(hist_w)


def test_legacy_widgets(qtbot):
    d = QDigitDial("3.2f")
    qtbot.addWidget(d)
    d.setValue(12.34)
    assert abs(d.value() - 12.34) < 1e-9
    led = QStatusLed()
    qtbot.addWidget(led)
    led.setState(QStatusLed.Blinking)
    assert led.state == QStatusLed.Blinking
    tree = QDeviceTree(dev_list=[{"device": "a/b/c", "server": "S/i", "class": "C"}],
                       structure=QDeviceTree.ByClass)
    qtbot.addWidget(tree)
    assert tree.model.rowCount(QtCore.QModelIndex()) == 1
