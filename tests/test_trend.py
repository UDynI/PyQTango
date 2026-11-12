# -*- coding: utf-8 -*-
""" TrendBuffer, QTrend and QBooleanTrend (7.3) on the test device """

import json
import math
import time

import numpy as np
import pytest
import tango

pytest.importorskip("pyqtgraph")

from PyQTango.models import AttrValue
from PyQTango.widgets.trend import (TrendBuffer, QTrend, QBooleanTrend, numeric_value, parse_atk_settings,
                                    load_settings_file, split_index, SEL_NONE, SEL_X, SEL_Y1, SEL_Y2)
from conftest import attr, wait


def short(name):
    """ Curve name of an attribute: without tango://host:port/ """
    return name.split("/", 3)[3] if name.startswith("tango://") else name

pytestmark = pytest.mark.usefixtures("no_tango_in_gui_thread")


def test_buffer():
    b = TrendBuffer(5)
    assert len(b) == 0 and b.last() is None
    for i in range(8):
        assert b.append(float(i), i * 10.0)
    assert not b.append(7.0, 0)                       # not after the last sample: dropped
    t, v = b.data()
    assert list(t) == [3, 4, 5, 6, 7] and list(v) == [30, 40, 50, 60, 70]
    t, v = b.window(4.5, 6.2, extra=0)
    assert list(t) == [5, 6]
    t, v = b.window(4.5, 6.2)                          # one more sample on each side
    assert list(t) == [4, 5, 6, 7]
    b.resize(3)
    assert list(b.data()[0]) == [5, 6, 7]
    b.clear()
    assert len(b) == 0
    assert TrendBuffer(10).nbytes == 160


def test_numeric_value_and_index():
    V = tango.AttrQuality
    def val(v, q=V.ATTR_VALID):
        return AttrValue(v, None, q, 0.0)
    assert numeric_value(val(2.5)) == 2.5
    assert numeric_value(val(True)) == 1.0
    assert numeric_value(val(tango.DevState.FAULT)) == float(int(tango.DevState.FAULT))
    assert math.isnan(numeric_value(val(1.0, V.ATTR_INVALID)))
    assert numeric_value(val([1, 2, 3]), 1) == 2
    assert math.isnan(numeric_value(val([1]), 5))
    assert math.isnan(numeric_value(val("text")))
    assert split_index("a/b/c/d[3]") == ("a/b/c/d", 3) and split_index("a/b/c/d") == ("a/b/c/d", None)
    assert split_index("a/b/c/d[3]#dbase=no") == ("a/b/c/d#dbase=no", 3)


ATK_FILE = """graph_title:'Power supplies'
label_visible:true
display_duration:600000.0
toolbar_visible:false
tree_visible:true
show_device_name:false
refresh_time:500
source:0
xvisible:true
y1visible:true
y1autoscale:false
y1min:-1.5
y1max:12.0
y1scale:1
y1title:'Current'
y2visible:true
y2autoscale:true
dv_number:2
dv0_name:'lab/power/ps1/current'
dv0_selected:2
dv0_showminalarm:false
dv0_showmaxalarm:true
dv0_linecolor:255,0,0
dv0_linewidth:2
dv0_linestyle:2
dv0_markerstyle:3
dv0_markersize:5
dv0_A0:0.0
dv0_A1:2.0
dv1_name:'lab/power/ps2/voltage'
dv1_selected:3
dv1_linecolor:0,0,255
"""


def test_atk_import(tmp_path):
    d = parse_atk_settings(ATK_FILE)
    assert d["refresh_ms"] == 500 and d["source"] == 0 and d["display_duration"] == 600
    assert d["toolbar_visible"] is False and d["show_device_name"] is False
    assert d["chart"]["title"] == "Power supplies"
    y1 = d["chart"]["axes"]["y1"]
    assert y1["autoscale"] is False and y1["minimum"] == -1.5 and y1["maximum"] == 12 and y1["log"]
    assert y1["title"] == "Current"
    a, b = d["items"]
    assert a["name"] == "lab/power/ps1/current" and a["selected"] == SEL_Y1 and a["show_max_alarm"]
    assert a["view"]["color"] == "#ff0000" and a["view"]["width"] == 2 and a["view"]["line_style"] == 2
    assert a["view"]["marker"] == 3 and a["view"]["a1"] == 2.0
    assert b["selected"] == SEL_Y2 and b["view"]["axis"] == "y2" and b["view"]["color"] == "#0000ff"
    p = tmp_path / "old.txt"
    p.write_text(ATK_FILE)
    assert load_settings_file(str(p))["items"][1]["name"] == "lab/power/ps2/voltage"
    bad = tmp_path / "bad.txt"
    bad.write_text("hello\n")
    with pytest.raises(ValueError):
        load_settings_file(str(bad))


@pytest.fixture
def trend(qtbot):
    t = QTrend(refresh_ms=100)
    qtbot.addWidget(t)
    t.resize(800, 400)
    t.show()
    yield t
    t.close()


def test_live_trend(qtbot, trend, device_name, tmp_path):
    rw = attr(device_name, "rw_double")
    ev = attr(device_name, "ev_double")
    alarm = attr(device_name, "alarm_double")
    trend.add_attribute([rw, ev])
    it = trend.add_attribute(alarm, SEL_Y2)
    assert [i.name for i in trend.items()] == [rw, ev, alarm]
    wait(qtbot, lambda: len(trend.item(rw).buffer) >= 3, 8000)
    # ev_double only changes on Push: its value is held at each period
    wait(qtbot, lambda: len(trend.item(ev).buffer) >= 3, 8000)
    wait(qtbot, lambda: short(rw) in trend.chart.curve_names(), 3000)
    assert trend.chart.view(short(alarm)).axis == "y2"
    # Tree: device node, attribute rows with axis, value and quality
    node = trend.item(rw).tree_item
    assert node.parent().toolTip(0) == device_name and node.text(1) == "Y1"
    wait(qtbot, lambda: node.text(2) != "", 3000)
    assert node.text(3) == "VALID" and it.tree_item.text(3) == "ALARM"
    # Max alarm overlay
    trend.set_show_alarm(alarm, "max", True)
    assert short(alarm) + " max alarm" in trend.chart.curve_names()
    assert list(trend.chart.curve_data(short(alarm) + " max alarm")[1]) == [5.0, 5.0]
    # Axis column click cycles none -> Y1 -> Y2 -> none
    trend.tree.itemClicked.emit(node, 1)
    assert trend.item(rw).selected == SEL_Y2 and node.text(1) == "Y2"
    trend.tree.itemClicked.emit(node, 1)
    assert trend.item(rw).selected == SEL_NONE and short(rw) not in trend.chart.curve_names()
    trend.set_selected(rw, SEL_Y1)
    # Stop monitoring: no new samples, models suspended
    trend.stop()
    assert trend.actions["start_stop"].text() == "Start monitoring"
    assert trend.item(rw).model.is_suspended()
    n = len(trend.item(rw).buffer)
    qtbot.wait(400)
    assert len(trend.item(rw).buffer) == n
    trend.start()
    wait(qtbot, lambda: len(trend.item(rw).buffer) > n, 5000)
    # Off line: data kept, no new samples
    trend.set_offline(True)
    n = len(trend.item(rw).buffer)
    qtbot.wait(400)
    assert len(trend.item(rw).buffer) == n and trend.actions["offline"].isChecked()
    trend.set_offline(False)
    # Save the whole buffers, reset, load back (goes off line)
    path = str(tmp_path / "data.csv")
    trend.save_data(path)
    trend.reset()
    assert len(trend.item(rw).buffer) <= 1
    trend.load_data(path)
    assert trend.is_offline() and len(trend.item(rw).buffer) >= n
    trend.set_offline(False)
    # XY mode: rw_double against ev_double
    trend.set_selected(ev, SEL_X)
    assert not trend.chart.is_time_axis() and trend.item(ev).tree_item.text(1) == "X"
    trend.set_selected(ev, SEL_Y1)
    assert trend.chart.is_time_axis()
    # Settings round trip
    cfg = str(tmp_path / "t.trend.json")
    trend.set_refresh_interval(200)
    trend.set_source(tango.DevSource.DEV)
    trend.item(rw).view.color = "#123456"
    trend.save_configuration(cfg)
    d = json.load(open(cfg))
    assert d["refresh_ms"] == 200 and d["source"] == 0 and len(d["items"]) == 3
    other = QTrend()
    qtbot.addWidget(other)
    other.load_configuration(cfg)
    assert [i.name for i in other.items()] == [rw, ev, alarm]
    assert other.refresh_interval() == 200 and other.source() == tango.DevSource.DEV
    assert other.item(rw).view.color == "#123456" and other.item(alarm).show_max_alarm
    assert other.item(rw).model.source == tango.DevSource.DEV
    other.close()
    # Remove
    trend.remove_attribute(alarm)
    assert trend.item(alarm) is None and short(alarm) not in trend.chart.curve_names()


def test_menus_and_dialog_hooks(qtbot, trend, device_name):
    menu = trend.build_menu()
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts == ["Load configuration", "Save configuration", "Global settings", "Zoom", "Stop monitoring",
                     "Set refresh interval", "Source", "Add new attribute", "Reset trend", "Hide toolbar",
                     "Off line mode", "View errors", "Diagnostic"]
    toolbar = [a.toolTip() for a in trend.toolbar.actions()]
    assert toolbar == ["Load configuration", "Save configuration", "Global settings", "Zoom", "Stop monitoring",
                       "Set refresh interval", "Add new attribute", "Reset trend"]
    rw = attr(device_name, "rw_double")
    trend.ask_text = lambda title, label, value="": rw
    assert trend.add_attribute_dialog().name == rw
    item_menu = [a.text() for a in trend.item_menu(rw).actions() if not a.isSeparator()]
    assert item_menu == ["Set to X", "Add to Y1", "Add to Y2", "Remove", "Show min alarm", "Show max alarm",
                         "Graphic properties", "Attribute properties"]
    errors = []
    trend.error = errors.append
    trend.ask_text = lambda title, label, value="": "abc"
    assert trend.ask_refresh_interval() is None and errors == ["Invalid number !"]
    trend.ask_text = lambda title, label, value="": "250"
    assert trend.ask_refresh_interval() == 250
    trend.ask_text = lambda title, label, value="": "not/an/attribute"
    assert trend.add_attribute_dialog() is None
    assert trend.show_graphic_properties(rw).windowTitle().startswith("Data View properties")
    assert trend.show_diagnostic().rows()[0][0] == rw
    trend.toggle_toolbar()
    assert not trend.is_toolbar_visible() and trend.actions["toolbar"].text() == "Show toolbar"
    assert trend.drop_text("x " + attr(device_name, "rw_long"))[0].name.endswith("rw_long#dbase=no")
    # Strings are rejected with a message in the tree
    s = trend.add_attribute(attr(device_name, "rw_string"))
    wait(qtbot, lambda: s.error, 5000)
    assert "Not a numeric" in s.error


def test_spectrum_element(qtbot, trend, device_name):
    dev, frag = device_name.split("#", 1)
    element = trend.add_attribute("{0}/spectrum[1]#{1}".format(dev, frag))
    assert element.index == 1 and element.base == attr(device_name, "spectrum")
    assert element.tree_item.text(0) == "spectrum[1]"
    wait(qtbot, lambda: len(element.buffer) >= 1, 5000)
    assert element.buffer.last()[1] == 2.0
    whole = trend.add_attribute(attr(device_name, "rw_spectrum"))
    wait(qtbot, lambda: whole.error, 5000)
    assert "dev/attr[index]" in whole.error


def test_boolean_trend(qtbot, device_name):
    t = QBooleanTrend(refresh_ms=100)
    qtbot.addWidget(t)
    t.show()
    b1, b2 = attr(device_name, "rw_bool"), attr(device_name, "rw_switch")
    t.add_attribute([b1, b2], SEL_Y2)
    assert all(i.selected == SEL_Y1 and i.view.step for i in t.items())
    wait(qtbot, lambda: len(t.item(b2).buffer) >= 2, 8000)
    t.redraw()
    _, y1 = t.chart.curve_item(short(b1)).getData()
    _, y2 = t.chart.curve_item(short(b2)).getData()
    assert set(np.unique(y1)) <= {1.5, 2.5} and set(np.unique(y2)) <= {0.0, 1.0}   # lanes
    ticks = t.chart.plot_item.getAxis("left")._tickLevels[0]
    assert [name for _, name in ticks] == [short(b1), short(b2)]
    assert t.item(b1).tree_item.text(1) == "Yes"
    t.tree.itemClicked.emit(t.item(b1).tree_item, 1)
    assert t.item(b1).selected == SEL_NONE and t.item(b1).tree_item.text(1) == "No"
    d = t.add_attribute(attr(device_name, "rw_double"))
    wait(qtbot, lambda: d.error, 5000)
    assert d.error == "Boolean scalars only"
    t.close()


# -- Review round 2 -------------------------------------------------------------------------------------

def test_embedded_trend_releases_models(qtbot, device_name):
    from PyQTango.qt import sip, QtWidgets
    from PyQTango.models import attribute_model
    parent = QtWidgets.QWidget()
    t = QTrend(parent, refresh_ms=100)
    name = attr(device_name, "tab_b")
    t.add_attribute(name)
    m = attribute_model(name)
    refs = m.ref_count()
    t.stop()                                          # stopped: the model is suspended too
    sip.delete(parent)                                # the window goes: no closeEvent for the trend
    assert m.ref_count() == refs - 1 and not m.is_suspended()
    assert getattr(m, "_period_requests", {}) == {}


def test_trend_does_not_slow_other_widgets(qtbot, trend, device_name):
    from PyQTango.widgets import QValueLabel
    name = attr(device_name, "tab_a")
    label = QValueLabel()
    qtbot.addWidget(label)
    label.setModel(name)
    m = label.model()
    base = m.polling_period
    trend.add_attribute(name)
    trend.set_refresh_interval(60000)
    assert m.polling_period == base                   # the label still gets the default rate
    trend.remove_attribute(name)
    assert m.polling_period == base
    label.setModel(None)


def test_xy_trend_keeps_points_when_zoomed(qtbot, trend, device_name):
    y, x = attr(device_name, "tab_a"), attr(device_name, "tab_b")
    trend.add_attribute(y)
    trend.add_attribute(x, SEL_X)
    trend.set_offline(True)
    yi, xi = trend.item(y), trend.item(x)
    yi.buffer.clear()
    xi.buffer.clear()
    t0 = time.time() - 1000
    for i in range(100):
        yi.buffer.append(t0 + i, float(i))
        xi.buffer.append(t0 + i, i / 10.0)
    trend.redraw()
    curve = [n for n in trend.chart.curve_names() if "tab_a" in n][0]
    assert len(trend.chart.curve_data(curve)[0]) == 100
    trend.chart.zoom_to(x=(2, 5))                     # X-attribute units, not times
    trend.redraw()
    assert len(trend.chart.curve_data(curve)[0]) == 100


def test_trend_errors_on_device_clock(qtbot, trend):
    from PyQTango.widgets.trend import TrendItem
    from PyQTango.core.errors import error_from_exception
    it = TrendItem("a/b/c/d")
    now = time.time()
    trend._on_value(it, AttrValue(1.0, None, tango.AttrQuality.ATTR_VALID, now - 30))   # device 30 s late
    trend._on_error(it, error_from_exception(RuntimeError("x")))
    trend._on_value(it, AttrValue(2.0, None, tango.AttrQuality.ATTR_VALID, now - 29))
    assert len(it.buffer) == 3                        # the value after the error is kept


def test_same_attribute_on_two_devices_gets_two_curves(qtbot, trend):
    from PyQTango.widgets.trend import TrendItem
    a, b = TrendItem("x/y/z/current"), TrendItem("x/y/w/current")
    trend._items += [a, b]
    try:
        trend.set_offline(True)
        trend.set_show_device_names(False)
        for i, it in enumerate((a, b)):
            it.buffer.append(time.time(), float(i))
        trend.redraw()
        assert len([n for n in trend.chart.curve_names() if n.startswith("current")]) == 2
    finally:
        trend._items.remove(a)
        trend._items.remove(b)


def test_graphic_properties_of_unplotted_item(qtbot, trend, device_name):
    name = attr(device_name, "tab_a")
    trend.add_attribute(name, SEL_NONE)
    it = trend.item(name)
    dlg = trend.show_graphic_properties(name)
    trend.redraw()                                    # the item is on no axis: nothing drawn
    dlg.color.set_color("#123456")
    assert it.view.color == "#123456"


def test_boolean_lane_labels_follow_device_names(qtbot, device_name):
    b = QBooleanTrend(refresh_ms=100)
    qtbot.addWidget(b)
    b.add_attribute(attr(device_name, "rw_bool"))
    b.set_show_device_names(False)
    assert b.chart.plot_item.getAxis("left")._tickLevels[0][0][1] == "rw_bool"
    b.clear()
