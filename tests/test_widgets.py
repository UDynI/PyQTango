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
    n.textEdited.emit("500")
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
    # A failed write of this widget shows the device value again
    wait(qtbot, lambda: abs(w.attributeValue().value - 100.0) < 1e-9 and not w.write_pending(), timeout=5000)
    expected = float(w.set_point(w.attributeValue(), w.setPointMode))
    w.setValue(55.0)
    assert w.value() != expected
    with qtbot.waitSignal(m.writeDone, timeout=5000) as blocker:
        w.write(1000.0)                               # above max_value: refused by the device
    assert blocker.args[0] is not None and w.value() == expected


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
    assert m.data(m.index(1, 1), Qt.ItemDataRole.FontRole).bold()
    assert "Stored value:\nx" in m.data(m.index(1, 1), Qt.ItemDataRole.ToolTipRole)
    m.set_value(1, "x")                      # back to the stored value: not modified
    assert not m.is_modified() and m.changed() == {}
    m.set_value(0, ["3"])
    assert m.row_of("A", case_sensitive=False) == 0 and m.stored(0) == "1\n2"
    m.revert()
    assert m.value(0) == "1\n2" and not m.is_modified()
    m.set_value(1, "y")
    m.mark_clean()
    assert not m.is_modified() and m.stored(1) == "y"


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


def test_multi_change_dialog(qtbot):
    from PyQTango.widgets.confirm import QMultiChangeDialog, change_sentence
    assert change_sentence(1, 2) == "You are going to modify 1 property on 2 devices.\nDo you want to proceed ?"
    assert change_sentence(3, 1, " for attribute x", "Attribute") == \
        "You are going to write 3 attributes on 1 device for attribute x.\nDo you want to proceed ?"
    d = QMultiChangeDialog([("a/b/c/Cmd", "1,2")], 5, item="command")
    qtbot.addWidget(d)
    assert d.windowTitle() == "Multiple change confirmation"
    assert d.text.text().startswith("You are going to execute 1 command on 5 devices.")
    assert [d.table.horizontalHeaderItem(i).text() for i in range(2)] == ["Command", "Input parameters"]
    assert d.table.item(0, 1).text() == "1,2"
    d.proceed_button.click()
    from PyQTango.qt import QtWidgets
    assert d.result() == QtWidgets.QDialog.DialogCode.Accepted


def test_attribute_tree_uses_dbhost_and_port(qtbot, monkeypatch):
    import PyQTango.widgets.attributetree as AT
    calls = []
    monkeypatch.setattr(AT, "getAllLiveAttributes", lambda *a: calls.append(a) or [])
    t = AT.QAttributeTree(dbhost="h", port=123)
    qtbot.addWidget(t)
    assert calls == [("h", 123)]


def test_destroying_a_frozen_widget_resumes_its_model(qtbot, device_name):
    from PyQTango.qt import sip
    name = attr(device_name, "rw_long")
    a, b = W.QValueLabel(), W.QValueLabel()
    qtbot.addWidget(b)
    a.setModel(name)
    b.setModel(name)
    m = b.model()
    a.setFrozen(True)
    assert m.ref_count() == 2 and not m.is_suspended()
    sip.delete(a)                                     # window A closed while frozen
    assert m.ref_count() == 1 and not m.is_suspended()


def test_paused_widget_rejoins_the_shared_model(qtbot, device_name):
    from PyQTango.models.registry import registry
    name = attr(device_name, "tab_a")
    w = W.QValueLabel()
    qtbot.addWidget(w)
    w.setPauseWhenHidden(True)
    w.setModel(name)
    w.show()
    first = w.model()
    wait(qtbot, lambda: first.last_value() is not None, timeout=5000)
    w.hide()
    wait(qtbot, lambda: registry().lookup(name) is None, timeout=3000)     # forgotten while hidden
    w.show()
    assert registry().lookup(name) is first                                  # shared again
    w.hide()
    wait(qtbot, lambda: registry().lookup(name) is None, timeout=3000)
    other = attribute_model(name)                     # meanwhile another widget made a new model
    w.show()
    assert w.model() is other and w.isAttached() and other.ref_count() == 1 and first.ref_count() == 0
    w.setModel(None)


# -- Crashes in slots (review round 2) ----------------------------------------------------------------

def test_qattribute_invalid_value_and_wide_int_range(qtbot, device_name):
    from PyQTango.models.attribute import AttrValue
    w = QAttribute()
    qtbot.addWidget(w)
    w.setTangoAttribute(attr(device_name, "rw_double"))
    wait(qtbot, lambda: isinstance(w.w_value, QtWidgets.QDoubleSpinBox) and w.attributeValue() is not None, 5000)
    w.on_value(AttrValue(None, None, tango.AttrQuality.ATTR_INVALID, 0.0))    # used to raise TypeError
    assert "gray" in w.w_value.styleSheet()
    lm = attribute_model(attr(device_name, "rw_long"))
    lm.attach()
    wait(qtbot, lambda: lm.config() is not None, 5000)
    import types
    real = lm.config()                                # shared: change a copy
    cfg = types.SimpleNamespace(**{k: getattr(real, k) for k in dir(real) if not k.startswith("_")})
    cfg.data_type, cfg.min_value, cfg.max_value = tango.CmdArgType.DevULong, "0", "4294967295"
    w.on_config(cfg)                                  # used to raise OverflowError in QSpinBox.setRange
    assert isinstance(w.w_value, QtWidgets.QLineEdit)
    lm.release()
    w.shutdown()


def test_command_executer_survives_delete_and_device_change(qtbot, device_name):
    from PyQTango.qt import sip
    w = QCommandExecuter()
    qtbot.addWidget(w)
    w.setDevice(device_name)
    wait(qtbot, lambda: w.selector.count() > 0, timeout=5000)
    w.selector.setCurrentIndex(w.selector.findText("Echo"))
    w.arg.setText("hello")
    w.on_released()
    w.setDevice(None)                                 # cleared while the command runs
    wait(qtbot, lambda: "Result: hello" in w.results.toPlainText(), timeout=5000)
    assert device_name.split("#")[0].split("/")[-1] in w.results.toPlainText()
    d = QCommandExecuter()
    d.setDevice(device_name)
    wait(qtbot, lambda: d.selector.count() > 0, timeout=5000)
    d.selector.setCurrentIndex(d.selector.findText("Echo"))
    d.arg.setText("bye")
    d.on_released()
    sip.delete(d)                                     # deleted while the command runs
    qtbot.wait(500)


def test_lazy_tree_drops_stale_loads(qtbot):
    import threading
    calls = []

    class Slow(W.TreeNode):
        def populate(self, ctx):
            ev = threading.Event()
            calls.append(ev)
            n = len(calls)
            ev.wait(5)
            return [W.TreeNode("{0}-{1}".format(self.label, n), leaf=True)]

    class Root(W.TreeNode):
        def populate(self, ctx):
            return [Slow("a")]

    model = W.LazyTreeModel(Root("root"))
    view = QtWidgets.QTreeView()
    qtbot.addWidget(view)
    view.setModel(model)
    wait(qtbot, lambda: model.rowCount() == 1 and not model.node(model.index(0, 0)).leaf, 5000)
    ia = model.index(0, 0)
    model.fetchMore(ia)
    wait(qtbot, lambda: len(calls) == 1, 5000)
    model.refresh(ia)                                 # a second load while the first runs
    wait(qtbot, lambda: len(calls) == 2, 5000)
    calls[1].set()
    wait(qtbot, lambda: model.data(model.index(0, 0, ia)) == "a-2", 5000)
    calls[0].set()                                    # the older, slower load ends last
    qtbot.wait(300)
    assert model.data(model.index(0, 0, ia)) == "a-2"
    model.refresh(ia)
    wait(qtbot, lambda: len(calls) == 3, 5000)
    model.refresh()                                   # the loading node leaves the tree
    wait(qtbot, lambda: model.rowCount() == 1, 5000)
    calls[2].set()                                    # used to raise ValueError in row()
    qtbot.wait(300)


def test_error_history_save_failure_is_reported(qtbot, tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path), ""))
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *a: errors.append(a[-1]))
    h = W.QErrorHistory()
    qtbot.addWidget(h)
    h.save()                                          # a directory: OSError
    assert errors


# -- Wrong values written (review round 2) ------------------------------------------------------------

def test_wheel_widens_for_wide_values(qtbot):
    w = W.QWheelEditor(integer_digits=3, decimals=2)
    qtbot.addWidget(w)
    w.setWriteOnChange(True)
    w.setValue(1500.0)                                # "%6.2f" gives 3 digits, the device says 1500
    assert w.integerDigits() == 4 and "".join(w._text_cells()) == "+1500.00"
    committed = []
    w.valueCommitted.connect(committed.append)
    w.step(w._digit_cells()[-1], +1)                  # used to write 999.99
    assert committed == [1500.01]


def test_wheel_writes_one_at_a_time(qtbot, device_name):
    w = W.QAttributeWheelEditor()
    qtbot.addWidget(w)
    w.setModel(attr(device_name, "rw_double"))
    wait(qtbot, lambda: w.attributeValue() is not None, timeout=5000)
    m = w.model()
    done = []
    m.writeDone.connect(done.append)
    for v in (1.0, 2.0, 3.0, 4.0):                    # four fast clicks
        w._write_value(v)
    wait(qtbot, lambda: len(done) >= 2 and value_of(attr(device_name, "rw_double")) == 4.0, 5000)
    qtbot.wait(300)
    assert done == [None, None]                       # the first, then only the latest


def test_line_setter_enter_without_edit_and_foreign_writes(qtbot, device_name):
    a, b = W.QNumberSetter(), W.QNumberSetter()
    for x in (a, b):
        qtbot.addWidget(x)
        x.setModel(attr(device_name, "rw_double"))
    wait(qtbot, lambda: a.text() and b.text(), timeout=5000)
    m = a.model()
    done = []
    m.writeDone.connect(done.append)
    a.returnPressed.emit()                            # Enter on unedited text: nothing written
    qtbot.wait(300)
    assert done == []
    a.setText("12")
    a.textEdited.emit("12")                           # a is being edited...
    with qtbot.waitSignal(m.writeDone, timeout=5000):
        b.write(1000.0)                               # ...when b's write fails
    assert a.text() == "12" and a._editing and "red" not in a.styleSheet()
    assert "red" in b.styleSheet()


# -- Remaining items (review round 2) -----------------------------------------------------------------

def test_navigation_enter_emits_once(qtbot):
    n = W.QNavigationBar()
    qtbot.addWidget(n)
    n.show()
    seen = []
    n.searchRequested.connect(seen.append)
    n.search.lineEdit().setText("foo")
    qtbot.keyClick(n.search.lineEdit(), Qt.Key.Key_Return)
    qtbot.wait(50)
    assert seen == ["foo"]


def test_digit_dial_negative_value(qtbot):
    d = QDigitDial("3.2f")
    qtbot.addWidget(d)
    d.setValue(123.0)
    d.setValue(-1.5)
    assert d.value() == -1.5


def test_setters_disabled_when_unbound(qtbot, device_name):
    s, w = W.QNumberSetter(), W.QAttributeWheelEditor()
    for x in (s, w):
        qtbot.addWidget(x)
        x.setModel(attr(device_name, "rw_double"))
    wait(qtbot, lambda: s.isEnabled() and s.text() and w.isEnabled(), timeout=5000)
    s.setModel(None)
    w.setModel(None)
    assert not s.isEnabled() and s.text() == "" and not w.isEnabled() and w.value() == 0


def test_boolean_label_hidden_until_valid_stays_attached(qtbot, device_name):
    w = W.QBooleanLabel()
    qtbot.addWidget(w)
    w.setPauseWhenHidden(True)
    w.setHideUntilValid(True)
    w.show()
    w.setModel(attr(device_name, "no_such_boolean"))
    wait(qtbot, lambda: w.attributeError() is not None, timeout=5000)
    assert not w.isVisible() and w.isAttached()      # hidden by itself: still follows its model
    w.setModel(None)


def test_qattribute_config_event_and_value_parsing(qtbot, device_name):
    import types
    w = QAttribute()
    qtbot.addWidget(w)
    w.setTangoAttribute(attr(device_name, "rw_double"))
    wait(qtbot, lambda: isinstance(w.w_value, QtWidgets.QDoubleSpinBox) and w.attributeValue() is not None, 5000)
    w.w_value.blockSignals(True)
    w.w_value.setValue(50.0)
    w.w_value.blockSignals(False)
    real = w.model().config()
    cfg = types.SimpleNamespace(**{k: getattr(real, k) for k in dir(real) if not k.startswith("_")})
    cfg.max_value = "10"                              # new limits clamp the shown value
    w.on_config(cfg)
    assert not w.w_value_c                            # not taken as a user edit
    check = w._QAttribute__check_value
    assert check("1e-3 mm") == 0.001 and check(" 12 mm ") == 12.0
    i = QAttribute()
    qtbot.addWidget(i)
    i.setTangoAttribute(attr(device_name, "rw_long"))
    wait(qtbot, lambda: i.w_value is not None, 5000)
    assert i._QAttribute__check_value("010") == 10 and i._QAttribute__check_value("0x10") == 16
    w.shutdown()
    i.shutdown()


def test_legacy_trees_names_and_async_load(qtbot, monkeypatch):
    import PyQTango.widgets.attributetree as AT
    import PyQTango.widgets.devicetree as DT
    m = AT.AttributeTreeModel([{"attribute": "tango://h:10000/a/b/c/d"}, {"attribute": "a/b/c/e#dbase=no"},
                               {"attribute": "not/valid"}])
    assert m.rowCount(QtCore.QModelIndex()) == 1      # one "a" domain; the invalid name is skipped
    monkeypatch.setattr(AT, "getAllLiveAttributes", lambda *a: [{"attribute": "x/y/z/w"}])
    t = AT.QAttributeTree(load_async=True)
    qtbot.addWidget(t)
    with qtbot.waitSignal(t.loaded, timeout=5000):
        pass
    assert t.model.rowCount(QtCore.QModelIndex()) == 1
    monkeypatch.setattr(DT.PT, "Database", lambda *a: "db")
    monkeypatch.setattr(DT, "getAllRegisteredDevices", lambda *a: [])
    d = DT.QDeviceTree(load_async=True)
    qtbot.addWidget(d)
    with qtbot.waitSignal(d.loaded, timeout=5000):
        pass
    assert d.db == "db"


def test_status_led_get_state(qtbot):
    led = QStatusLed()
    qtbot.addWidget(led)
    led.setState(QStatusLed.On)
    assert led.getState() == QStatusLed.On and led.state == QStatusLed.On
