# -*- coding: utf-8 -*-
""" QTangoChart and QImageViewer (pyqtgraph), both bindings """

import numpy as np
import pytest

pg = pytest.importorskip("pyqtgraph")

from PyQTango.qt import API
from PyQTango.widgets.plot import QTangoChart, QImageViewer


def test_pyqtgraph_follows_binding():
    assert pg.Qt.QT_LIB == API


def test_chart_curves(qtbot):
    c = QTangoChart(title="t")
    qtbot.addWidget(c)
    c.set_curve("a", [1, 2, 3])
    c.set_curve("b", [5, 6], x=[10, 20])
    assert c.curve_names() == ["a", "b"]
    x, y = c.curve_data("a")
    assert list(x) == [0, 1, 2] and list(y) == [1, 2, 3]
    c.set_curve("a", [4, 5], x_offset=3)            # replaced, not added
    x, y = c.curve_data("a")
    assert list(x) == [3, 4] and list(y) == [4, 5] and len(c.curve_names()) == 2
    c.remove_curve("b")
    assert c.curve_names() == ["a"]
    c.clear()
    assert c.curve_names() == []


def test_image_viewer(qtbot):
    v = QImageViewer()
    qtbot.addWidget(v)
    data = np.arange(6).reshape(2, 3)
    v.set_data(data)
    assert v.data().shape == (2, 3)
    lo, hi = v.levels()
    assert lo == 0 and hi == 5
    v.set_data([1, 2, 3])                            # 1D: one row
    assert v.data().shape == (1, 3)
