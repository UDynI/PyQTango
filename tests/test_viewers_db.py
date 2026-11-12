# -*- coding: utf-8 -*-
""" Viewers that read database attribute properties: spectrum X axis and allowed values lists """

import pytest
import tango

pytest.importorskip("pyqtgraph")

from PyQTango.widgets import QScalarListViewer, QNumberComboSetter, QStringComboSetter
from PyQTango.widgets.spectrum import QSpectrumViewer, read_x_axis_properties
from test_polling import tango_host, in_thread, DEV  # noqa: F401 (fixture)
from conftest import wait

pytestmark = pytest.mark.usefixtures("no_tango_in_gui_thread")


def fq(th, name):
    return "tango://{0}/{1}".format(th, name)


def test_x_axis_from_attribute_properties(qtbot, tango_host):
    db = in_thread(lambda: tango.Database(*tango_host.split(":")))
    in_thread(db.put_device_attribute_property, DEV, {"wave": {"XminAttribute": ["xstart"],
                                                               "XmaxAttribute": ["xend"]}})
    name = fq(tango_host, DEV + "/wave")
    assert in_thread(read_x_axis_properties, name) == {"XminAttribute": "xstart", "XmaxAttribute": "xend"}
    v = QSpectrumViewer()
    qtbot.addWidget(v)
    v.setModel(name)
    with qtbot.waitSignal(v.xAxisLoaded, timeout=10000):
        v.load_x_axis_properties()
    wait(qtbot, lambda: v.xRange() == (10.0, 20.0), 5000)
    wait(qtbot, lambda: v.curve_names(), 5000)
    assert list(v.curve_data(v.curve_names()[0])[0]) == [10.0, 12.5, 15.0, 17.5]
    # Constant Xmin / Xmax
    in_thread(db.delete_device_attribute_property, DEV, {"wave": ["XminAttribute", "XmaxAttribute"]})
    in_thread(db.put_device_attribute_property, DEV, {"wave": {"Xmin": ["0"], "Xmax": ["8"]}})
    with qtbot.waitSignal(v.xAxisLoaded, timeout=10000):
        v.load_x_axis_properties()
    assert v.xRange() == (0.0, 8.0)
    in_thread(db.delete_device_attribute_property, DEV, {"wave": ["Xmin", "Xmax"]})


def test_values_lists_make_combos(qtbot, tango_host):
    db = in_thread(lambda: tango.Database(*tango_host.split(":")))
    in_thread(db.put_device_attribute_property, DEV, {"gain": {"values": ["1", "2", "5"]},
                                                      "mode_name": {"Values": ["slow,fast"]}})
    w = QScalarListViewer()
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.valuesLoaded, timeout=10000) as blocker:
        w.setDevice(fq(tango_host, DEV))
    assert blocker.args == [2]
    setters = {r[0].split("/")[-1]: r[2][2] for r in w._rows}
    assert isinstance(setters["gain"], QNumberComboSetter) and setters["gain"].valuesList() == [1.0, 2.0, 5.0]
    assert isinstance(setters["mode_name"], QStringComboSetter)
    assert setters["mode_name"].valuesList() == ["slow", "fast"]
    wait(qtbot, lambda: setters["mode_name"].currentIndex() == 0, 5000)
    in_thread(db.delete_device_attribute_property, DEV, {"gain": ["values"], "mode_name": ["Values"]})
