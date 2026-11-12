# -*- coding: utf-8 -*-
"""
QTangoChart option dialogs (JLChart's chart and data view properties, table, statistics).

Every edit applies to the chart at once, as in JLChart; Close only hides the dialog.

@author: Michele Devetta <michele.devetta@cnr.it>
"""

import math

from ..qt import QtGui, QtWidgets, Qt
from .plot import LINE_STYLES, MARKERS, VIEW_LINE, VIEW_BAR, merge_table

__all__ = ["QChartPropertiesDialog", "QDataViewDialog", "QChartTableDialog", "QChartStatisticsDialog",
           "QColorButton"]


class QColorButton(QtWidgets.QPushButton):
    """ Push button showing a colour; click opens a colour chooser """

    def __init__(self, color="#000000", parent=None, on_change=None):
        QtWidgets.QPushButton.__init__(self, parent)
        self._color = color
        self._on_change = on_change
        self.setFixedWidth(60)
        self.clicked.connect(self._choose)
        self._paint()

    def color(self):
        return self._color

    def set_color(self, color, notify=True):
        self._color = color
        self._paint()
        if notify and self._on_change is not None:
            self._on_change(color)

    def ask_color(self):
        c = QtWidgets.QColorDialog.getColor(QtGui.QColor(self._color), self, "Choose colour")
        return c.name() if c.isValid() else None

    def _choose(self):
        c = self.ask_color()
        if c:
            self.set_color(c)

    def _paint(self):
        self.setStyleSheet("background-color: {0}; border: 1px solid #404040;".format(self._color))


def _number(text, default):
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


class _AxisTab(QtWidgets.QWidget):

    def __init__(self, chart, axis, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.chart, self.axis = chart, axis
        s = chart.axes[axis]
        form = QtWidgets.QFormLayout(self)
        self.visible = QtWidgets.QCheckBox("Visible", self)
        self.visible.setChecked(s.visible)
        self.grid = QtWidgets.QCheckBox("Show grid", self)
        self.grid.setChecked(s.grid)
        self.autoscale = QtWidgets.QCheckBox("Auto scale", self)
        self.autoscale.setChecked(s.autoscale)
        self.minimum = QtWidgets.QLineEdit(repr(s.minimum), self)
        self.maximum = QtWidgets.QLineEdit(repr(s.maximum), self)
        self.margin = QtWidgets.QDoubleSpinBox(self)
        self.margin.setRange(0, 50)
        self.margin.setSuffix(" %")
        self.margin.setValue(s.margin * 100)
        self.scale = QtWidgets.QComboBox(self)
        self.scale.addItems(["Linear", "Logarithmic"])
        self.scale.setCurrentIndex(1 if s.log else 0)
        self.title = QtWidgets.QLineEdit(s.title, self)
        self.once = QtWidgets.QPushButton("Autoscale once", self)
        form.addRow(self.visible)
        form.addRow(self.grid)
        form.addRow(self.autoscale)
        form.addRow("Autoscale margin", self.margin)
        form.addRow("Min", self.minimum)
        form.addRow("Max", self.maximum)
        form.addRow("Scale", self.scale)
        form.addRow("Title", self.title)
        form.addRow(self.once)
        for w in (self.visible, self.grid, self.autoscale):
            w.toggled.connect(self.apply)
        self.margin.valueChanged.connect(self.apply)
        self.scale.currentIndexChanged.connect(self.apply)
        for w in (self.minimum, self.maximum, self.title):
            w.editingFinished.connect(self.apply)
        self.once.clicked.connect(self._once)
        self._enable()

    def _enable(self):
        fixed = not self.autoscale.isChecked()
        self.minimum.setEnabled(fixed)
        self.maximum.setEnabled(fixed)

    def apply(self, *_):
        s = self.chart.axes[self.axis]
        s.visible = self.visible.isChecked()
        s.grid = self.grid.isChecked()
        s.autoscale = self.autoscale.isChecked()
        s.margin = self.margin.value() / 100.0
        lo = _number(self.minimum.text(), s.minimum)
        hi = _number(self.maximum.text(), s.maximum)
        log = self.scale.currentIndex() == 1
        if lo < hi and not (log and lo <= 0):
            s.minimum, s.maximum = lo, hi
        else:
            # Invalid fixed range (min >= max, or min <= 0 on a log scale): keep the previous one
            self.minimum.setText(repr(s.minimum))
            self.maximum.setText(repr(s.maximum))
        s.log = log
        s.title = self.title.text()
        self._enable()
        self.chart.apply_axes()

    def _once(self):
        lo, hi = self.chart.autoscale_once(self.axis)
        s = self.chart.axes[self.axis]
        for w, v in ((self.autoscale, False),):
            w.blockSignals(True)
            w.setChecked(v)
            w.blockSignals(False)
        self.minimum.setText(repr(s.minimum))
        self.maximum.setText(repr(s.maximum))
        self._enable()


class QChartPropertiesDialog(QtWidgets.QDialog):
    """ Chart properties: title, legend, display duration and one tab per axis """

    def __init__(self, chart, parent=None):
        QtWidgets.QDialog.__init__(self, parent)
        self.chart = chart
        self.setWindowTitle("Chart properties")
        layout = QtWidgets.QVBoxLayout(self)
        general = QtWidgets.QFormLayout()
        self.title = QtWidgets.QLineEdit(chart.title(), self)
        self.title.editingFinished.connect(lambda: chart.set_title(self.title.text()))
        general.addRow("Title", self.title)
        self.legend = QtWidgets.QCheckBox("Show legend", self)
        self.legend.setChecked(chart.legend is not None and chart.legend.isVisible())
        self.legend.setEnabled(chart.legend is not None)
        self.legend.toggled.connect(lambda on: chart.legend.setVisible(on) if chart.legend is not None else None)
        general.addRow(self.legend)
        self.duration = QtWidgets.QLineEdit(self)
        self.duration.setPlaceholderText("Infinite")
        if math.isfinite(chart.display_duration):
            self.duration.setText("{0:g}".format(chart.display_duration))
        self.duration.editingFinished.connect(self._duration)
        self.duration.setEnabled(chart.is_time_axis())
        general.addRow("Display duration (s)", self.duration)
        layout.addLayout(general)
        self.tabs = QtWidgets.QTabWidget(self)
        self.axis_tabs = {}
        for axis, label in (("x", "X axis"), ("y1", "Y1 axis"), ("y2", "Y2 axis")):
            tab = _AxisTab(chart, axis, self)
            self.axis_tabs[axis] = tab
            self.tabs.addTab(tab, label)
        layout.addWidget(self.tabs)
        close = QtWidgets.QPushButton("Close", self)
        close.clicked.connect(self.close)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)

    def _duration(self):
        text = self.duration.text().strip()
        value = _number(text, -1.0) if text else None
        if value is not None and (value < 0 or math.isnan(value)):
            # Not a duration: show the current one again
            d = self.chart.display_duration
            self.duration.setText("{0:g}".format(d) if math.isfinite(d) else "")
            return
        self.chart.set_display_duration(value)


class QDataViewDialog(QtWidgets.QDialog):
    """ Data View properties of one curve """

    def __init__(self, chart, name, parent=None, view=None):
        """ ``view``: the DataView to edit, for a curve that may not be drawn yet
        (a trend item on no axis); by default the view of the curve ``name`` """
        QtWidgets.QDialog.__init__(self, parent)
        self.chart, self.name = chart, name
        self._view = view
        v = view if view is not None else chart.view(name)
        self._last_line = v.color
        self.setWindowTitle("Data View properties [{0}]".format(name))
        form = QtWidgets.QFormLayout(self)
        self.axis = QtWidgets.QComboBox(self)
        self.axis.addItems(["Y1", "Y2"])
        self.axis.setCurrentIndex(1 if v.axis == "y2" else 0)
        self.color = QColorButton(v.color, self, on_change=self._line_color)
        self.width = QtWidgets.QSpinBox(self)
        self.width.setRange(0, 10)
        self.width.setValue(v.width)
        self.line_style = QtWidgets.QComboBox(self)
        self.line_style.addItems(LINE_STYLES)
        self.line_style.setCurrentIndex(v.line_style)
        self.view_type = QtWidgets.QComboBox(self)
        self.view_type.addItems(["Line", "Bar graph"])
        self.view_type.setCurrentIndex(1 if v.view_type == VIEW_BAR else 0)
        self.bar_width = QtWidgets.QDoubleSpinBox(self)
        self.bar_width.setRange(0, 1e9)
        self.bar_width.setDecimals(3)
        self.bar_width.setValue(v.bar_width)
        self.fill = QtWidgets.QCheckBox("Fill area", self)
        self.fill.setChecked(v.fill)
        self.fill_color = QColorButton(v.fill_color or v.color, self, on_change=lambda _: self.apply())
        self.marker = QtWidgets.QComboBox(self)
        self.marker.addItems([m[0] for m in MARKERS])
        self.marker.setCurrentIndex(v.marker)
        self.marker_size = QtWidgets.QSpinBox(self)
        self.marker_size.setRange(1, 40)
        self.marker_size.setValue(v.marker_size)
        self.marker_color = QColorButton(v.marker_color or v.color, self, on_change=lambda _: self.apply())
        self.a0 = QtWidgets.QLineEdit(repr(v.a0), self)
        self.a1 = QtWidgets.QLineEdit(repr(v.a1), self)
        self.a2 = QtWidgets.QLineEdit(repr(v.a2), self)
        self.visible = QtWidgets.QCheckBox("Visible", self)
        self.visible.setChecked(v.visible)
        form.addRow("Axis", self.axis)
        form.addRow("Line colour", self.color)
        form.addRow("Line width", self.width)
        form.addRow("Line style", self.line_style)
        form.addRow("View type", self.view_type)
        form.addRow("Bar width", self.bar_width)
        form.addRow(self.fill)
        form.addRow("Fill colour", self.fill_color)
        form.addRow("Marker", self.marker)
        form.addRow("Marker size", self.marker_size)
        form.addRow("Marker colour", self.marker_color)
        form.addRow(QtWidgets.QLabel("Transform: y' = A0 + A1*y + A2*y²", self))
        form.addRow("A0", self.a0)
        form.addRow("A1", self.a1)
        form.addRow("A2", self.a2)
        form.addRow(self.visible)
        for w in (self.axis, self.line_style, self.view_type, self.marker):
            w.currentIndexChanged.connect(self.apply)
        for w in (self.width, self.marker_size):
            w.valueChanged.connect(self.apply)
        self.bar_width.valueChanged.connect(self.apply)
        for w in (self.fill, self.visible):
            w.toggled.connect(self.apply)
        for w in (self.a0, self.a1, self.a2):
            w.editingFinished.connect(self.apply)
        close = QtWidgets.QPushButton("Close", self)
        close.clicked.connect(self.close)
        form.addRow(close)

    def _line_color(self, color):
        # Marker and fill colours that followed the line colour keep following it
        for b in (self.fill_color, self.marker_color):
            if b.color() == self._last_line:
                b.set_color(color, notify=False)
        self._last_line = color
        self.apply()

    def apply(self, *_):
        drawn = self.name in self.chart.curve_names()
        if self._view is not None:
            v = self._view
        elif drawn:
            v = self.chart.view(self.name)
        else:
            return
        v.axis = "y2" if self.axis.currentIndex() == 1 else "y1"
        v.color = self.color.color()
        v.width = self.width.value()
        v.line_style = self.line_style.currentIndex()
        v.view_type = VIEW_BAR if self.view_type.currentIndex() == 1 else VIEW_LINE
        v.bar_width = self.bar_width.value()
        v.fill = self.fill.isChecked()
        v.fill_color = self.fill_color.color() if self.fill_color.color() != v.color else ""
        v.marker = self.marker.currentIndex()
        v.marker_size = self.marker_size.value()
        v.marker_color = self.marker_color.color() if self.marker_color.color() != v.color else ""
        v.a0 = _number(self.a0.text(), v.a0)
        v.a1 = _number(self.a1.text(), v.a1)
        v.a2 = _number(self.a2.text(), v.a2)
        v.visible = self.visible.isChecked()
        if drawn and self.chart.view(self.name) is v:
            self.chart.refresh_view(self.name)


class QChartTableDialog(QtWidgets.QDialog):
    """ Show table: one X column and one column per curve, rows merged on X """

    def __init__(self, chart, names=None, parent=None):
        QtWidgets.QDialog.__init__(self, parent)
        names = list(names or chart.curve_names())
        self.setWindowTitle("Table [{0}]".format(", ".join(names)) if len(names) == 1 else "Table")
        layout = QtWidgets.QVBoxLayout(self)
        data = chart.curves_data(names)
        rows = merge_table([(x, chart.view(n).transform(y)) for n, (x, y) in data.items()])
        self.table = QtWidgets.QTableWidget(len(rows), len(names) + 1, self)
        self.table.setHorizontalHeaderLabels(["Time" if chart.is_time_axis() else "X"] + names)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        for r, row in enumerate(rows):
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(chart.format_x(row[0])))
            for c, v in enumerate(row[1:], start=1):
                text = "" if v is None or (isinstance(v, float) and math.isnan(v)) else "{0:g}".format(v)
                self.table.setItem(r, c, QtWidgets.QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)
        self.resize(480, 400)


class QChartStatisticsDialog(QtWidgets.QDialog):
    """ Show statistics: count, min, max, mean and standard deviation over the visible window """

    COLUMNS = ("Curve", "Count", "Min", "Max", "Mean", "Std dev")

    def __init__(self, chart, names=None, parent=None):
        QtWidgets.QDialog.__init__(self, parent)
        self.setWindowTitle("Statistics")
        layout = QtWidgets.QVBoxLayout(self)
        stats = chart.statistics(names)
        self.stats = stats
        x0, x1 = chart.visible_x_range()
        layout.addWidget(QtWidgets.QLabel("From {0} to {1}".format(chart.format_x(x0), chart.format_x(x1)), self))
        self.table = QtWidgets.QTableWidget(len(stats), len(self.COLUMNS), self)
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        for r, (n, s) in enumerate(stats.items()):
            values = [n, str(s["count"])] + ["{0:g}".format(s[k]) for k in ("min", "max", "mean", "std")]
            for c, v in enumerate(values):
                item = QtWidgets.QTableWidgetItem(v)
                if c:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)
        self.resize(520, 200)
