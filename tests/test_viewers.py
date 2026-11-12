# -*- coding: utf-8 -*-
""" Phase 4 viewers and tools: spectrum, list and image viewers, combo setters, QCommandCombo,
QAttributePropertyDialog, QRefresherDiagnostic, freezing and pausing hidden widgets """

import numpy as np
import pytest
import tango

pytest.importorskip("pyqtgraph")

from PyQTango.qt import QtWidgets, Qt
from PyQTango.models import attribute_model, device_model
from PyQTango.widgets import (QCommandCombo, QAttributePropertyDialog, QRefresherDiagnostic, QValueLabel,
                              QNumberComboSetter, QStringComboSetter, QScalarListViewer, create_setter,
                              freeze_widgets)
from PyQTango.widgets.setters import parse_values_list
from PyQTango.widgets.spectrum import (QSpectrumViewer, QStringSpectrumViewer, QStateSpectrumViewer,
                                       QBooleanSpectrumViewer)
from PyQTango.widgets.image import QImageViewer, QStringImageViewer, QRawImageViewer, decode_encoded, \
    EncodedImageError
from PyQTango.widgets.diagnostic import diagnostic_rows
from conftest import attr, wait

pytestmark = pytest.mark.usefixtures("no_tango_in_gui_thread")


def test_spectrum_viewer(qtbot, device_name):
    v = QSpectrumViewer()
    qtbot.addWidget(v)
    name = attr(device_name, "rw_spectrum")
    v.setModel(name)
    wait(qtbot, lambda: v.curve_names(), 5000)
    read = v.curve_names()[0]
    assert read == "rw_spectrum" and list(v.curve_data(read)[1]) == [0.5, 1.5]
    assert len(v.curve_names()) == 1                         # set point not valid yet
    with qtbot.waitSignal(v.model().writeDone, timeout=5000):
        v.model().write([3.0, 4.0, 5.0])
    wait(qtbot, lambda: len(v.curve_names()) == 2, 5000)
    assert list(v.curve_data("rw_spectrum (set point)")[1]) == [3.0, 4.0, 5.0]
    # Constant X range: x[i] = xmin + i * (xmax - xmin) / n
    v.setXRange(0, 30)
    assert list(v.curve_data(read)[0]) == [0, 10, 20]
    assert not v.axes["x"].autoscale and v.axes["x"].maximum == 30
    v.setXRange(None, None)
    assert list(v.curve_data(read)[0]) == [0, 1, 2]
    # X range from two scalar attributes
    v.setXModels(attr(device_name, "expert_double"), attr(device_name, "alarm_double"))
    wait(qtbot, lambda: v.xRange() == (3.0, 10.0), 5000)
    assert list(v.curve_data(read)[0]) == pytest.approx([3, 3 + 7 / 3, 3 + 14 / 3])
    v.setModel(None)
    assert v.curve_names() == []


def test_list_viewers(qtbot, device_name):
    s = QStringSpectrumViewer()
    st = QStateSpectrumViewer()
    b = QBooleanSpectrumViewer()
    for w, a in ((s, "str_spectrum"), (st, "state_spectrum"), (b, "bool_spectrum")):
        qtbot.addWidget(w)
        w.setModel(attr(device_name, a))
    wait(qtbot, lambda: s.rowCount() == 2 and st.rowCount() == 3 and b.rowCount() == 3, 5000)
    assert s.values() == ["alpha", "beta"] and s.item(1, 0).text() == "1"
    assert st.values() == ["ON", "FAULT", "ALARM"]
    assert st.item(1, 1).background().color().name() == "#ff0000"
    assert b.values() == [True, False, True]


def test_image_viewers(qtbot, device_name, tmp_path):
    v = QImageViewer()
    qtbot.addWidget(v)
    v.setModel(attr(device_name, "image"))
    wait(qtbot, lambda: v.data() is not None, 5000)
    assert v.data().shape == (2, 3) and v.levels() == (1.0, 6.0)
    assert v.value_at(2, 1) == 6.0 and v.value_at(5, 5) is None
    v.set_colormap("Gray")
    assert v.colormap_name() == "Gray"
    with pytest.raises(ValueError):
        v.set_colormap("Nope")
    v.set_levels(0, 10)
    assert v.levels() == (0.0, 10.0) and not v.auto_levels.isChecked()
    v.show()
    v.show_profiles(True)
    r, row, c, col = v.profile_data()
    assert (r, c) == (1, 1) and list(row) == [4, 5, 6] and list(col) == [2, 5]
    v.set_profile_position(2, 0)
    assert v.profile_data()[0] == 0 and v.profile_data()[2] == 2
    for ext in ("png", "tif", "csv"):
        p = str(tmp_path / ("img." + ext))
        v.ask_save_path = lambda p=p: p
        assert v.save_dialog() == p
    assert np.loadtxt(str(tmp_path / "img.csv"), delimiter=",").tolist() == [[1, 2, 3], [4, 5, 6]]
    s = QStringImageViewer()
    qtbot.addWidget(s)
    s.setModel(attr(device_name, "str_image"))
    wait(qtbot, lambda: s.rowCount() == 2, 5000)
    assert s.data() == [["a", "b"], ["c", "d"]]
    raw = QRawImageViewer()
    qtbot.addWidget(raw)
    raw.setModel(attr(device_name, "gray8"))
    wait(qtbot, lambda: raw.data() is not None, 5000)
    assert raw.data().tolist() == [[0, 64, 128], [192, 255, 10]] and "GRAY8 3x2" in raw.position.text()


def test_decode_encoded():
    assert decode_encoded(("GRAY8", bytes([0, 2, 0, 1, 7, 9]))).tolist() == [[7, 9]]
    g16 = decode_encoded(("GRAY16", bytes([0, 1, 0, 1, 1, 2])))
    assert g16.tolist() == [[258]]
    rgb = decode_encoded(("RGB24", bytes([0, 1, 0, 1, 10, 20, 30])))
    assert rgb.shape == (1, 1, 3) and rgb[0, 0].tolist() == [10, 20, 30]
    from PyQTango.qt import QtCore, QtGui
    img = QtGui.QImage(4, 2, QtGui.QImage.Format.Format_RGB888)
    img.fill(QtGui.QColor(255, 0, 0))
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "JPEG")
    jpeg = decode_encoded(("JPEG_RGB", bytes(buf.data())))
    assert jpeg.shape == (2, 4, 3) and jpeg[0, 0, 0] > 200
    for bad in (("GRAY8", b"\x00"), ("GRAY8", bytes([0, 9, 0, 9, 1])), ("XYZ", b""), ("JPEG", b"no")):
        with pytest.raises(EncodedImageError):
            decode_encoded(bad)


def test_combo_setters(qtbot, device_name):
    assert parse_values_list(["1, 2", "3"]) == ["1", "2", "3"]
    n = QNumberComboSetter(values=["1", "2.5", "10"])
    qtbot.addWidget(n)
    n.setModel(attr(device_name, "rw_double"))
    with qtbot.waitSignal(n.model().writeDone, timeout=5000):
        n.model().write(10.0)
    wait(qtbot, lambda: n.attributeValue() is not None and n.attributeValue().value == 10.0, 5000)
    assert n.valuesList() == [1.0, 2.5, 10.0] and n.currentIndex() == 2
    with qtbot.waitSignal(n.model().writeDone, timeout=5000):
        n.activated.emit(1)
    wait(qtbot, lambda: n.attributeValue().value == 2.5, 5000)
    assert n.currentIndex() == 1
    s = QStringComboSetter(values=["hello", "world"])
    qtbot.addWidget(s)
    s.setModel(attr(device_name, "rw_string"))
    with qtbot.waitSignal(s.model().writeDone, timeout=5000):
        s.model().write("hello")
    wait(qtbot, lambda: s.currentIndex() == 0, 5000)
    rm = attribute_model(attr(device_name, "rw_double"))
    rm.attach()                                       # do not rely on an earlier test for the configuration
    wait(qtbot, lambda: rm.config() is not None, 5000)
    cfg = rm.config()
    rm.release()
    assert isinstance(create_setter(cfg, values=["1"]), QNumberComboSetter)
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    other = create_setter(cfg, parent, values=["a"])                 # not numeric: usual setter, no orphan combo
    assert other is not None and not isinstance(other, QNumberComboSetter)
    assert parent.findChildren(QNumberComboSetter) == []
    with qtbot.waitSignal(n.model().writeDone, timeout=5000):
        n.model().write(10.0)


def test_command_combo(qtbot, device_name):
    c = QCommandCombo()
    qtbot.addWidget(c)
    with qtbot.waitSignal(c.loaded, timeout=5000):
        c.setDevice(device_name)
    assert "ExpertCmd" in c.command_names() and c.itemText(0) == "Commands..."
    c.setOperatorView(True)
    assert "ExpertCmd" not in c.command_names()
    results, failures, asked = [], [], []
    c.show_result = lambda cmd, text: results.append((cmd, text))
    c.show_failure = lambda cmd, err: failures.append((cmd, err if isinstance(err, str) else err.message))
    c.ask_argin = lambda info: asked.append(info.cmd_name) or "hi there"
    with qtbot.waitSignal(c.executed, timeout=5000):
        c.activated.emit(c.findText("Echo"))
    assert asked == ["Echo"] and results == [("Echo", "hi there")] and c.currentIndex() == 0
    with qtbot.waitSignal(c.executed, timeout=5000):
        c.run("Values")
    assert results[-1] == ("Values", "1.0\n2.5")
    with qtbot.waitSignal(c.executed, timeout=5000):
        c.run("Push")                                   # void in, void out: no popup
    assert len(results) == 2
    with qtbot.waitSignal(c.failed, timeout=5000):
        c.run("Fail")
    assert failures[-1][0] == "Fail" and "Fail on purpose" in failures[-1][1]
    c.ask_argin = lambda info: "1,x"
    assert c.run("Sum") is None and failures[-1][0] == "Sum"
    c.ask_argin = lambda info: None
    assert c.run("Echo") is None
    with qtbot.waitSignal(c.executed, timeout=5000):
        c.run("echo", "hi")                             # other case than the device's "Echo"
    assert results[-1] == ("Echo", "hi")
    i = c.findText("Echo")
    assert c.itemData(i, Qt.ItemDataRole.ToolTipRole) == c.info("Echo").in_type_desc


def test_attribute_property_dialog(qtbot, device_name):
    name = attr(device_name, "rw_double")
    followed = attribute_model(name)
    followed.attach()                                 # the model reports the new label: it must be running
    wait(qtbot, lambda: followed.mode() != "idle", 5000)
    d = QAttributePropertyDialog(name)
    qtbot.addWidget(d)
    with qtbot.waitSignal(d.loaded, timeout=5000):
        pass
    assert d.windowTitle() == "Attribute property editor"
    assert d.fields["label"].text() == "RW double" and d.fields["unit"].text() == "mm"
    assert d.fields["max_value"].text() == "100" and not d.apply_button.isEnabled()
    d.fields["label"].setText("Position")
    d.fields["label"].textEdited.emit("Position")
    d.fields["max_alarm"].setText("90")
    assert d.apply_button.isEnabled()
    with qtbot.waitSignal(d.applied, timeout=5000) as blocker:
        d.apply()
    assert blocker.args == [None]
    wait(qtbot, lambda: attribute_model(name).config() is not None and attribute_model(name).label() == "Position",
         5000)
    assert "Description" in d.information_text()
    # Restore
    d.fields["label"].setText("RW double")
    d.fields["max_alarm"].setText("")
    with qtbot.waitSignal(d.applied, timeout=5000):
        d.apply()
    assert d.fields["max_alarm"].text() == "Not specified"
    ro = QAttributePropertyDialog(name, read_only=True)
    qtbot.addWidget(ro)
    assert ro.apply_button.isHidden() and ro.fields["label"].isReadOnly() and ro.apply() is None
    followed.release()


def test_scalar_list_property_buttons(qtbot, device_name):
    w = QScalarListViewer()
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.loaded, timeout=5000):
        w.setDevice(device_name)
    row = [r for r in w._rows if "rw_double" in r[0]][0]
    assert row[2][4].text() == "..."
    w.setReadOnly(True)
    assert not row[2][4].isVisibleTo(w) and not row[2][2].isVisibleTo(w)
    dlg = w.show_properties(row[0])
    assert dlg.read_only
    w.setReadOnly(False)
    assert not w.show_properties(row[0]).read_only


def test_scalar_list_set_models_twice(qtbot, device_name):
    w = QScalarListViewer()
    qtbot.addWidget(w)
    a, b, c = (attr(device_name, n) for n in ("rw_double", "rw_long", "rw_string"))
    w.setModels([a, b])
    assert w.models() == [a, b]
    w.setModels([c])
    assert w.models() == [c]


def test_freeze_refresh_once_and_diagnostic(qtbot, device_name):
    host = QtWidgets.QWidget()
    qtbot.addWidget(host)
    label = QValueLabel(host)
    name = attr(device_name, "counter")         # used by this test only
    label.setModel(name)
    m = label.model()
    wait(qtbot, lambda: label.attributeValue() is not None, 5000)
    assert freeze_widgets(host, True) == [label]
    assert label.isFrozen() and m.is_suspended()
    first = label.attributeValue().value
    with qtbot.waitSignal(m.writeDone, timeout=5000):
        m.write(first + 1)
    qtbot.wait(300)
    assert label.attributeValue().value == first          # frozen
    with qtbot.waitSignal(m.valueChanged, timeout=5000):
        label.refreshOnce()
    assert label.attributeValue().value == first + 1      # one value let through
    freeze_widgets(host, False)
    assert not m.is_suspended()
    rows = diagnostic_rows([name])
    assert rows[0][0] == name and rows[0][1] in ("polling", "events") and rows[0][8] >= 2
    d = QRefresherDiagnostic(models=[name])
    qtbot.addWidget(d)
    assert d.table.rowCount() == 1 and d.table.item(0, 0).text() == name and "1 attribute(s)" in d.summary.text()
    with qtbot.waitSignal(m.writeDone, timeout=5000):
        m.write(first)


def test_pause_when_hidden(qtbot, device_name):
    tabs = QtWidgets.QTabWidget()
    qtbot.addWidget(tabs)
    a, b = QValueLabel(), QValueLabel()
    for w in (a, b):
        w.setPauseWhenHidden(True)
    tabs.addTab(a, "a")
    tabs.addTab(b, "b")
    a.setModel(attr(device_name, "tab_a"))      # used by this test only
    b.setModel(attr(device_name, "tab_b"))
    assert not a.isAttached() and not b.isAttached()      # nothing attaches before being shown
    tabs.show()
    qtbot.waitExposed(tabs)
    assert a.isAttached() and not b.isAttached()
    wait(qtbot, lambda: a.attributeValue() is not None, 5000)
    tabs.setCurrentIndex(1)
    assert b.isAttached() and not a.isAttached()
    wait(qtbot, lambda: b.attributeValue() is not None, 5000)
    assert b.model().ref_count() == 1 and a.model().ref_count() == 0



def test_slow_attribute_is_polled_apart(qtbot, device_name):
    """ A grouped read that times out because of one slow attribute: the others keep their values """
    from concurrent.futures import ThreadPoolExecutor
    from PyQTango.core.proxies import proxy_cache
    from PyQTango.models import refresher
    dev = device_name

    def set_timeout(ms):
        with ThreadPoolExecutor(1) as ex:
            ex.submit(lambda: proxy_cache.get(dev).set_timeout_millis(ms)).result()
    set_timeout(400)
    try:
        fast, slow = QValueLabel(), QValueLabel()
        for w in (fast, slow):
            qtbot.addWidget(w)
        fast.setModel(attr(device_name, "expert_double"))
        slow.setModel(attr(device_name, "slow"))
        wait(qtbot, lambda: refresher().is_solo(slow.model()), 10000)
        assert not refresher().is_solo(fast.model())
        n = fast.model().n_updates
        wait(qtbot, lambda: fast.model().n_updates > n + 1, 10000)
        assert any(d["solo"] for d in refresher().diagnostics() if d["attribute"] == slow.model().name)
        slow.setModel(None)
        fast.setModel(None)
        qtbot.wait(200)
        assert not refresher().is_solo(slow.model())
    finally:
        set_timeout(3000)


def test_scalar_list_drops_stale_and_late_replies(qtbot, device_name):
    from PyQTango.qt import sip
    w = QScalarListViewer()
    qtbot.addWidget(w)
    w.setDevice(device_name)
    w.setDevice(None)
    with qtbot.waitSignal(w.loaded, timeout=5000):
        w.setDevice(device_name)                      # A -> None -> A: the first reply is stale
    qtbot.wait(300)
    assert len(w.models()) == len(set(w.models()))
    d = QScalarListViewer()
    d.setDevice(device_name)
    sip.delete(d)                                     # deleted before the reply
    qtbot.wait(500)


def test_scalar_list_completes_rows_on_late_config(qtbot, device_name):
    from PyQTango.models.registry import registry
    name = attr(device_name, "rw_long")
    wait(qtbot, lambda: all(m.name != name for m in registry().attributes()), 3000)   # no configuration yet
    w = QScalarListViewer()
    qtbot.addWidget(w)
    w.setModels([name])
    assert w._rows[0][2][2] is None
    wait(qtbot, lambda: w._rows[0][2][2] is not None, 5000)          # setter built once configured
    assert w._rows[0][2][0].text() == attribute_model(name).config().label
    w.setModels([])
    assert w._late == []


@pytest.mark.filterwarnings("ignore:All-NaN slice")
def test_image_viewer_bad_values(qtbot):
    v = QImageViewer()
    qtbot.addWidget(v)
    v.profiles.setChecked(True)
    v.show()
    for data in (np.array([[0.0, 1.0], [np.inf, 2.0]]), np.full((3, 3), np.nan), np.zeros((0, 0)),
                 np.zeros((3, 0))):
        v.set_data(data)
    v.set_data(np.arange(6.0).reshape(2, 3))
    assert v.profile_data() is not None and v.view.getLevels() == (0.0, 5.0)


def test_spectrum_viewer_releases_x_models(qtbot, device_name):
    from PyQTango.qt import sip
    v = QSpectrumViewer()
    v.setModel(attr(device_name, "rw_spectrum"))
    xa, xb = attr(device_name, "tab_a"), attr(device_name, "tab_b")
    v.setXModels(xa, xb)
    ma, mb = attribute_model(xa), attribute_model(xb)
    assert ma.ref_count() == 1 and mb.ref_count() == 1
    v.setModel(attr(device_name, "spectrum"))         # another spectrum: the X attributes do not apply
    assert ma.ref_count() == 0 and mb.ref_count() == 0 and v.xRange() is None
    v.setXModels(xa, xb)
    ma, mb = attribute_model(xa), attribute_model(xb)
    sip.delete(v)                                     # destroyed without setModel(None)
    assert ma.ref_count() == 0 and mb.ref_count() == 0


def test_spectrum_viewer_keeps_zoom_and_title(qtbot, device_name):
    from PyQTango.core.errors import error_from_exception
    v = QSpectrumViewer()
    qtbot.addWidget(v)
    v.set_title("Mine")
    v.setModel(attr(device_name, "rw_spectrum"))
    wait(qtbot, lambda: v.model().config() is not None and v.curve_names(), 5000)
    v.zoom_to(y1=(0.2, 0.8))
    v.on_config(v.model().config())                   # a configuration event
    assert v.is_zoomed() and np.allclose(v.view_range()[1], (0.2, 0.8))
    v.on_error(error_from_exception(RuntimeError("down")))
    assert v.title() == "Mine" and "down" in v.plot_item.titleLabel.text
    v.on_error(None)
    assert "Mine" in v.plot_item.titleLabel.text and "down" not in v.plot_item.titleLabel.text
