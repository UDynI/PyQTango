# -*- coding: utf-8 -*-
"""
Black box of a device (Astor's BlackBoxTable and TopDialog).

``QBlackBoxView(device)`` reads ``black_box(depth)`` in the background and
shows date, operation, name, source, host and process, newest first. Auto
update reads again every second and keeps the records the device has already
dropped from its ring; a warning shows when reads stopped overlapping (records
lost). A filter keeps the rows whose chosen column contains a text, and Top
counts operations, names, sources, hosts and processes over the time span of
the records.
"""

from ..qt import QtCore, QtWidgets, Qt, Signal
from ..core.blackbox import BlackBox, COLUMNS, top, span_seconds, span_text
from ..core.proxies import proxy_cache
from ..models.worker import run_async
from .dialogs import TableModel, _SortProxy

__all__ = ["QBlackBoxView", "QBlackBoxDialog", "QTopDialog"]

DEFAULT_DEPTH = 100
UPDATE_MS = 1000


class _ColumnProxy(_SortProxy):
    column = -1             # -1: any column

    def filterAcceptsRow(self, row, parent):
        if not self.text:
            return True
        values = self.sourceModel().rows[row]
        cols = range(len(values)) if self.column < 0 else [self.column]
        return any(self.text.lower() in str(values[c]).lower() for c in cols)


class QBlackBoxView(QtWidgets.QWidget):
    """ Black box table of ``device`` (a full or plain device name) """

    updated = Signal(int)            # records added by the last read
    failed = Signal(str)

    def __init__(self, device, parent=None, depth=DEFAULT_DEPTH, proxy_getter=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.device = device
        self._proxy_getter = proxy_getter or (lambda: proxy_cache.get(device))
        self.box = BlackBox()
        self._busy = False
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = QtWidgets.QHBoxLayout()
        bar.addWidget(QtWidgets.QLabel("Records:", self))
        self.depth = QtWidgets.QSpinBox(self)
        self.depth.setRange(1, 10000)
        self.depth.setValue(depth)
        bar.addWidget(self.depth)
        self.update_button = QtWidgets.QPushButton("Update", self)
        self.update_button.clicked.connect(lambda _c=False: self.update_now())
        bar.addWidget(self.update_button)
        self.auto = QtWidgets.QCheckBox("Auto update", self)
        self.auto.toggled.connect(self.set_auto_update)
        bar.addWidget(self.auto)
        self.clear_button = QtWidgets.QPushButton("Clear", self)
        self.clear_button.setToolTip("Forget the records read so far")
        self.clear_button.clicked.connect(self.clear)
        bar.addWidget(self.clear_button)
        self.top_button = QtWidgets.QPushButton("Top...", self)
        self.top_button.clicked.connect(lambda _c=False: self.show_top())
        bar.addWidget(self.top_button)
        bar.addStretch(1)
        layout.addLayout(bar)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Filter:", self))
        self.column = QtWidgets.QComboBox(self)
        self.column.addItems(["Any column"] + list(COLUMNS))
        row.addWidget(self.column)
        self.filter = QtWidgets.QLineEdit(self)
        self.filter.setClearButtonEnabled(True)
        self.filter.setPlaceholderText("contains...")
        row.addWidget(self.filter, 1)
        layout.addLayout(row)
        self.model = TableModel(COLUMNS, [], self)
        self.proxy = _ColumnProxy(self)
        self.proxy.setSourceModel(self.model)
        self.view = QtWidgets.QTableView(self)
        self.view.setModel(self.proxy)
        self.view.verticalHeader().hide()
        self.view.horizontalHeader().setStretchLastSection(True)
        self.view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.doubleClicked.connect(self._show_line)
        layout.addWidget(self.view, 1)
        self.info = QtWidgets.QLabel(self)
        self.warning = QtWidgets.QLabel("Some records were lost between two reads "
                                        "(raise the number of records or update more often).", self)
        self.warning.setStyleSheet("color: #b05000;")
        self.warning.hide()
        layout.addWidget(self.warning)
        layout.addWidget(self.info)
        self.filter.textChanged.connect(self._filter)
        self.column.currentIndexChanged.connect(lambda _i: self._filter(self.filter.text()))
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(UPDATE_MS)
        self.timer.timeout.connect(self.update_now)
        self._top = None

    # -- Reading ---------------------------------------------------------------------------
    def update_now(self):
        """ Read the black box in the background; skipped while a read is running """
        if self._busy:
            return None
        self._busy = True
        n = self.depth.value()
        return run_async(lambda: list(self._proxy_getter().black_box(n)), owner=self, source=self.device,
                         on_done=self._read, on_error=self._failed)

    def _read(self, lines):
        self._busy = False
        added = self.box.update(lines)
        self.warning.setVisible(not self.box.contiguous)
        self._fill()
        self.updated.emit(added)

    def _failed(self, err):
        self._busy = False
        self.auto.setChecked(False)
        self.info.setText(err.message)
        self.failed.emit(err.message)

    def set_auto_update(self, on):
        if on:
            self.update_now()
            self.timer.start()
        else:
            self.timer.stop()

    def clear(self):
        self.box.clear()
        self.warning.hide()
        self._fill()

    # -- Display -----------------------------------------------------------------------------
    def records(self):
        return list(self.box.records)

    def visible_rows(self):
        return [self.model.rows[self.proxy.mapToSource(self.proxy.index(r, 0)).row()]
                for r in range(self.proxy.rowCount())]

    def visible_records(self):
        return [self.box.records[self.proxy.mapToSource(self.proxy.index(r, 0)).row()]
                for r in range(self.proxy.rowCount())]

    def _fill(self):
        self.model.beginResetModel()
        self.model.rows = [list(r.values()) for r in self.box.records]
        self.model.endResetModel()
        if self.model.rows:
            self.view.resizeColumnsToContents()
        self._count()
        if self._top is not None and self._top.isVisible():
            self._top.refresh()

    def _filter(self, text):
        self.proxy.text = text or ""
        self.proxy.column = self.column.currentIndex() - 1
        self.proxy.invalidateFilter()
        self._count()

    def _count(self):
        recs = self.visible_records()
        self.info.setText("{0} record(s) shown, {1} read, during {2}".format(
            len(recs), len(self.box.records), span_text(span_seconds(recs))))

    def _show_line(self, index):
        rec = self.box.records[self.proxy.mapToSource(index).row()]
        self.show_line(rec.line)

    def show_line(self, line):
        """ The raw black box line (tests replace this) """
        QtWidgets.QMessageBox.information(self, self.device, line)

    def show_top(self):
        if self._top is None:
            self._top = QTopDialog(self)
        self._top.refresh()
        self._top.show()
        self._top.raise_()
        return self._top

    def hideEvent(self, event):
        self.auto.setChecked(False)
        QtWidgets.QWidget.hideEvent(self, event)


class QTopDialog(QtWidgets.QDialog):
    """ Most frequent operations, names, sources, hosts and processes of the shown records """

    def __init__(self, view):
        QtWidgets.QDialog.__init__(self, view)
        self.view_ = view
        layout = QtWidgets.QVBoxLayout(self)
        self.title = QtWidgets.QLabel(self)
        self.title.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.title)
        grid = QtWidgets.QHBoxLayout()
        self.lists = {}
        for col in COLUMNS[1:]:
            box = QtWidgets.QVBoxLayout()
            box.addWidget(QtWidgets.QLabel(col, self))
            t = QtWidgets.QPlainTextEdit(self)
            t.setReadOnly(True)
            box.addWidget(t)
            grid.addLayout(box)
            self.lists[col] = t
        layout.addLayout(grid, 1)
        close = QtWidgets.QPushButton("Dismiss", self)
        close.clicked.connect(self.close)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        self.resize(900, 360)

    def counts(self):
        recs = self.view_.visible_records()
        return {col: top(recs, col) for col in COLUMNS[1:]}

    def refresh(self):
        recs = self.view_.visible_records()
        self.setWindowTitle("Top on " + self.view_.device)
        self.title.setText("Top on {0} during {1}".format(self.view_.device, span_text(span_seconds(recs))))
        for col, rows in self.counts().items():
            self.lists[col].setPlainText("\n".join("{0:5d}  {1}".format(n, v) for v, n in rows))


class QBlackBoxDialog(QtWidgets.QDialog):
    """ A black box view in its own window, read when shown """

    def __init__(self, device, parent=None, depth=DEFAULT_DEPTH, proxy_getter=None):
        QtWidgets.QDialog.__init__(self, parent)
        self.setWindowTitle("Black Box " + device)
        layout = QtWidgets.QVBoxLayout(self)
        self.view = QBlackBoxView(device, self, depth, proxy_getter)
        layout.addWidget(self.view)
        close = QtWidgets.QPushButton("Dismiss", self)
        close.clicked.connect(self.close)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        self.resize(980, 460)
        self.view.update_now()
