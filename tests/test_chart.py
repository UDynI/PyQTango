# -*- coding: utf-8 -*-
""" QTangoChart (7.3): axes, styles, zoom back, menu, data files, table, statistics, snapshot, print """

import math
import time

import numpy as np
import pytest

pg = pytest.importorskip("pyqtgraph")

from PyQTango.qt import QtCore, QtGui, QtWidgets
from PyQTango.widgets.plot import (QTangoChart, DataView, AxisSettings, statistics, merge_table, save_csv,
                                   load_csv, MARKERS, LINE_STYLES)
from PyQTango.widgets.chartdialogs import (QChartPropertiesDialog, QDataViewDialog, QChartTableDialog,
                                           QChartStatisticsDialog)


@pytest.fixture
def chart(qtbot):
    c = QTangoChart(title="Test")
    qtbot.addWidget(c)
    c.resize(500, 350)
    c.show()
    qtbot.waitExposed(c)
    return c


def menu_texts(menu):
    out = []
    for a in menu.actions():
        if a.isSeparator():
            continue
        out.append(a.text())
    return out


def test_helpers(tmp_path):
    s = statistics([1, 2, 3, np.nan])
    assert s["count"] == 3 and s["min"] == 1 and s["max"] == 3 and s["mean"] == 2
    assert statistics([])["count"] == 0
    assert merge_table([([0, 1], [5, 6]), ([1, 2], [7, 8])]) == [[0, 5, None], [1, 6, 7], [2, None, 8]]
    path = str(tmp_path / "d.csv")
    save_csv(path, {"a": ([0, 1, 2], [1.5, np.nan, 3]), "b": ([10], [4])})
    data = load_csv(path)
    assert list(data) == ["a", "b"]
    assert list(data["a"][0]) == [0, 1, 2] and math.isnan(data["a"][1][1]) and list(data["b"][1]) == [4]
    assert DataView.from_dict(DataView(name="x", marker=3).to_dict()).marker == 3
    assert AxisSettings.from_dict({"log": True, "unknown": 1}).log
    assert len(MARKERS) == 11 and len(LINE_STYLES) == 5


def test_two_axes_styles_and_transform(qtbot, chart):
    chart.set_curve("a", [1, 2, 3])
    chart.set_curve("b", [10, 20, 30], axis="y2")
    assert chart.axes["y2"].visible
    assert chart.curve_item("b").getViewBox() is chart.vb2
    assert chart.curve_item("a").getViewBox() is chart.plot_item.vb
    v = chart.view("a")
    v.a0, v.a1 = 1.0, 2.0
    v.marker, v.line_style, v.width = 2, 2, 3
    chart.refresh_view("a")
    _, y = chart.curve_item("a").getData()
    assert list(y) == [3, 5, 7]                          # drawn with the transform
    assert list(chart.curve_data("a")[1]) == [1, 2, 3]   # data kept as given
    assert chart.curve_item("a").opts["symbol"] == "s"
    # Move a curve between axes
    v.axis = "y2"
    chart.refresh_view("a")
    assert chart.curve_item("a").getViewBox() is chart.vb2
    # Bar view
    chart.view("b").view_type = 1
    chart.refresh_view("b")
    assert chart._curves["b"].bar is not None
    chart.view("b").view_type = 0
    chart.refresh_view("b")
    assert chart._curves["b"].bar is None
    # Fixed and log axes
    chart.axes["y1"] = AxisSettings(autoscale=False, minimum=0, maximum=50)
    chart.apply_axes()
    assert chart.view_range()[1] == pytest.approx((0, 50))
    chart.axes["y2"].log = True
    chart.apply_axes()
    assert chart.curve_item("b").opts["logMode"][1]
    assert chart.autoscale_once("y2")
    assert not chart.axes["y2"].autoscale


def test_time_axis_and_display_duration(qtbot, chart):
    chart.set_time_axis(True)
    assert isinstance(chart.plot_item.getAxis("bottom"), pg.DateAxisItem)
    now = time.time()
    t = now - np.arange(100)[::-1]
    chart.set_display_duration(10)
    chart.set_curve("t", np.arange(100), x=t)
    x0, x1 = chart.visible_x_range()
    assert x1 == pytest.approx(now) and x1 - x0 == pytest.approx(10)
    assert "/" in chart.format_x(now)
    chart.set_time_axis(False)
    assert not isinstance(chart.plot_item.getAxis("bottom"), pg.DateAxisItem)


def test_zoom_back(qtbot, chart):
    chart.set_curve("a", np.arange(100))

    chart.zoom_to(x=(10, 20), y1=(10, 20))
    assert chart.is_zoomed() and chart.visible_x_range() == pytest.approx((10, 20))
    chart.zoom_to(x=(12, 14))
    chart.zoom_back()
    assert chart.visible_x_range() == pytest.approx((10, 20))
    chart.zoom_back()
    assert not chart.is_zoomed()
    qtbot.wait(50)
    assert chart.visible_x_range()[1] >= 99
    # A mouse-wheel zoom is recorded too
    vb = chart.plot_item.vb
    vb.sigRangeChangedManually.emit([True, True])
    assert chart.is_zoomed()
    chart.set_rect_zoom(True)
    assert vb.state["mouseMode"] == pg.ViewBox.RectMode


def test_menu_and_data_operations(qtbot, chart, tmp_path):
    chart.set_curve("a", [1, 2, 3])
    chart.set_curve("b", [4, 5], x=[1, 2])
    menu = chart.build_menu()
    assert menu_texts(menu) == ["Chart properties", "Data View properties", "Save data File", "Load data File",
                                "Show table", "Show statistics", "Zoom back", "Print Chart",
                                "Save a snapshot of this chart"]
    sub = {a.text(): a.menu() for a in menu.actions() if a.menu()}
    assert menu_texts(sub["Data View properties"]) == ["a", "b"]
    assert menu_texts(sub["Show table"]) == ["All", "a", "b"]
    assert not [a for a in menu.actions() if a.text() == "Zoom back"][0].isEnabled()
    # Save / load data file
    path = str(tmp_path / "data.csv")
    chart.ask_save_path = lambda title, f: path
    assert chart.save_data_file() == path
    chart.clear()
    chart.ask_open_path = lambda title, f: path
    assert chart.load_data_file() == path
    assert chart.curve_names() == ["a", "b"] and list(chart.curve_data("b")[1]) == [4, 5]
    # Table and statistics
    table = chart.show_table()
    assert table.table.rowCount() == 3 and table.table.columnCount() == 3
    assert table.table.item(1, 2).text() == "4"
    stats = chart.show_statistics(["a"])
    assert stats.stats["a"]["count"] == 3 and stats.table.item(0, 3).text() == "3"
    # Snapshot (PNG and SVG) and print to a PDF file
    for ext in ("png", "svg"):
        p = str(tmp_path / ("snap." + ext))
        chart.ask_save_path = lambda title, f, p=p: p
        assert chart.save_snapshot() == p
        assert (tmp_path / ("snap." + ext)).stat().st_size > 100
    QtPrintSupport = __import__(QtCore.__name__.split(".")[0] + ".QtPrintSupport", fromlist=["x"])
    printer = QtPrintSupport.QPrinter()
    printer.setOutputFormat(QtPrintSupport.QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(tmp_path / "chart.pdf"))
    assert chart.print_chart(printer)
    assert (tmp_path / "chart.pdf").stat().st_size > 100
    # Errors go through the hook
    errors = []
    chart.error = errors.append
    chart.ask_open_path = lambda title, f: str(tmp_path / "missing.csv")
    assert chart.load_data_file() is None and "Failed to read" in errors[0]


def test_dialogs_apply_live(qtbot, chart):
    chart.set_curve("a", [1, 2, 3])
    dlg = chart.show_chart_properties()
    assert isinstance(dlg, QChartPropertiesDialog) and chart.show_chart_properties() is dlg
    tab = dlg.axis_tabs["y1"]
    tab.autoscale.setChecked(False)
    tab.minimum.setText("-5")
    tab.maximum.setText("5")
    tab.apply()
    assert chart.view_range()[1] == pytest.approx((-5, 5))
    dlg.title.setText("New title")
    dlg.title.editingFinished.emit()
    assert chart.title() == "New title"
    dv = chart.show_view_properties("a")
    assert isinstance(dv, QDataViewDialog) and dv.windowTitle() == "Data View properties [a]"
    dv.marker.setCurrentIndex(4)
    dv.color.set_color("#00ff00")
    dv.axis.setCurrentIndex(1)
    v = chart.view("a")
    assert v.marker == 4 and v.color == "#00ff00" and v.axis == "y2"
    assert chart.curve_item("a").getViewBox() is chart.vb2
    dv.a1.setText("10")
    dv.a1.editingFinished.emit()
    assert list(chart.curve_item("a").getData()[1]) == [10, 20, 30]
    assert QChartTableDialog(chart).table.columnCount() == 2
    assert QChartStatisticsDialog(chart).table.rowCount() == 1


def test_hidden_axis_stays_hidden_with_a_title(qtbot, chart):
    chart.set_axis_labels(y2="unit")
    assert not chart.plot_item.getAxis("right").isVisible()
    chart.set_curve("b", [1, 2], axis="y2")
    assert chart.plot_item.getAxis("right").isVisible()


def test_settings_round_trip(qtbot, chart):
    chart.set_title("T")
    chart.axes["y1"].log = True
    chart.set_time_axis(True)
    chart.display_duration = 60
    d = chart.settings()
    other = QTangoChart()
    qtbot.addWidget(other)
    other.apply_settings(d)
    assert other.title() == "T" and other.axes["y1"].log and other.is_time_axis() and other.display_duration == 60


def test_context_menu_policy(qtbot, chart):
    from PyQTango.qt import Qt
    assert chart.plot_widget.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    assert not chart.plot_item.vb.menuEnabled()


# -- Review round 2 -------------------------------------------------------------------------------------

def _manual_zoom(chart, factor):
    vb = chart.plot_item.vb
    vb.scaleBy((factor, factor))
    vb.sigRangeChangedManually.emit([True, True])


def test_zoom_back_restores_previous_level(qtbot, chart):
    chart.set_curve("a", [1, 5, 2, 8, 3])
    qtbot.wait(50)
    _manual_zoom(chart, 0.5)
    r1 = chart.view_range()
    qtbot.wait(500)                                   # a new gesture
    _manual_zoom(chart, 0.5)
    assert chart.view_range() != r1
    chart.zoom_back()
    assert np.allclose(chart.view_range()[0], r1[0]) and np.allclose(chart.view_range()[1], r1[1])


def test_reset_zoom_and_settings_clear_zoom(qtbot, chart):
    chart.set_curve("a", [1, 5, 2])
    chart.zoom_to(y1=(0, 1))
    chart.reset_zoom()
    assert not chart.is_zoomed() and chart.plot_item.vb.autoRangeEnabled()[1]
    chart.zoom_to(y1=(0, 1))
    chart.apply_settings(chart.settings())
    assert not chart.is_zoomed()


def test_csv_round_trip_keeps_raw_values(qtbot, chart, tmp_path):
    chart.set_curve("a", [1.0, 2.0, 3.0])
    chart.view("a").a1 = 10.0
    chart.refresh_view("a")
    path = str(tmp_path / "d.csv")
    chart.save_data(path)
    chart.load_data(path)                             # into the same chart: the transform applies once
    assert list(chart.curve_data("a")[1]) == [1.0, 2.0, 3.0]


def test_set_curve_does_not_restyle_unchanged_views(qtbot, chart):
    v = DataView(name="a", color="#ff0000")
    chart.set_curve("a", [1, 2], view=v)
    changed = []
    chart.viewChanged.connect(changed.append)
    for i in range(5):
        chart.set_curve("a", [i, i + 1], view=v)
    assert changed == []
    v.color = "#00ff00"
    chart.set_curve("a", [1, 2], view=v)
    assert changed == ["a"]


def test_marker_and_fill_follow_line_colour(qtbot, chart):
    chart.set_curve("a", [1, 2, 3], color="#ff0000")
    chart.view("a").marker = 1
    chart.refresh_view("a")
    d = QDataViewDialog(chart, "a")
    qtbot.addWidget(d)
    d.color.set_color("#0000ff")
    v = chart.view("a")
    assert v.color == "#0000ff" and d.marker_color.color() == "#0000ff" and v.marker_color == ""


def test_reopened_dialog_shows_current_settings(qtbot, chart):
    d = chart.show_chart_properties()
    d.close()
    chart.set_title("New title")
    d2 = chart.show_chart_properties()
    assert d2.title.text() == "New title"


def test_invalid_duration_and_log_range(qtbot, chart):
    chart.set_time_axis(True)
    seen = []
    chart.durationChanged.connect(seen.append)
    d = QChartPropertiesDialog(chart)
    qtbot.addWidget(d)
    d.duration.setText("-5")
    d.duration.editingFinished.emit()
    assert math.isinf(chart.display_duration) and seen == []
    d.duration.setText("60")
    d.duration.editingFinished.emit()
    assert chart.display_duration == 60.0 and seen == [60.0]
    chart.set_time_axis(False)
    chart.set_curve("a", [1, 10, 100])
    s = chart.axes["y1"]
    s.log, s.autoscale, s.minimum, s.maximum = True, False, 0.0, 1000.0
    chart.apply_axes()                                # min 0 on a log axis: six decades below the max
    lo, hi = chart.plot_item.vb.viewRange()[1]
    assert abs(lo - (-3.0)) < 1e-6 and abs(hi - 3.0) < 1e-6
    tab = d.axis_tabs["y1"]
    tab.minimum.setText("5")
    tab.maximum.setText("1")
    tab.apply()                                       # min >= max: refused
    assert (s.minimum, s.maximum) == (0.0, 1000.0) and tab.minimum.text() == repr(0.0)


def test_context_menus_are_deleted(qtbot, chart, monkeypatch):
    monkeypatch.setattr(QtWidgets.QMenu, "exec", lambda self, *a: None)
    for _ in range(3):
        chart._show_menu(QtCore.QPoint(10, 10))
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    assert chart.findChildren(QtWidgets.QMenu) == []


def test_axes_show_values_as_they_are(qtbot, chart):
    chart.set_curve("a", [0.0, 0.35, 0.7])
    chart.set_axis_labels(x="Position", y="Signal (V)")
    chart.set_time_axis(True)
    chart.set_time_axis(False)
    qtbot.wait(50)
    for side in ("left", "bottom", "right"):
        axis = chart.plot_item.getAxis(side)
        assert not axis.autoSIPrefix and "(x" not in axis.labelString()
