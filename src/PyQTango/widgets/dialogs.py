# -*- coding: utf-8 -*-
"""
Generic result dialogs (Astor's PopupTable, PopupText and PopupHtml).

* :class:`QTableDialog` - a sortable table with a filter box, Copy and Save as
  CSV. Rows are lists of values; numbers sort as numbers.
* :class:`QTextDialog` - plain text or HTML with Find, Copy and Save. Large
  texts are appended in chunks, so a 64 KB log does not freeze the window.

@author: Michele Devetta <michele.devetta@cnr.it>
"""

import csv
import io

from ..qt import QtCore, QtGui, QtWidgets, Qt, Signal
from ..qt import fixed_font

__all__ = ["QTableDialog", "QTextDialog", "TableModel"]


class TableModel(QtCore.QAbstractTableModel):
    """ Rows of values with headers; sorts numbers as numbers """

    def __init__(self, headers, rows, parent=None):
        QtCore.QAbstractTableModel.__init__(self, parent)
        self.headers = list(headers)
        self.rows = [list(r) for r in rows]
        self.colors = {}         # (row, column) -> QColor background

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        v = self.rows[index.row()][index.column()] if index.column() < len(self.rows[index.row()]) else ""
        if role == Qt.ItemDataRole.DisplayRole:
            return "" if v is None else str(v)
        if role == Qt.ItemDataRole.UserRole:
            return v
        if role == Qt.ItemDataRole.TextAlignmentRole and isinstance(v, (int, float)) and not isinstance(v, bool):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.BackgroundRole:
            c = self.colors.get((index.row(), index.column()))
            return QtGui.QBrush(QtGui.QColor(c)) if c else None
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section] if section < len(self.headers) else ""
        return None


class _SortProxy(QtCore.QSortFilterProxyModel):

    text = ""

    def lessThan(self, left, right):
        a = left.data(Qt.ItemDataRole.UserRole)
        b = right.data(Qt.ItemDataRole.UserRole)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return a < b
        return str("" if a is None else a).lower() < str("" if b is None else b).lower()

    def filterAcceptsRow(self, row, parent):
        text = self.text
        if not text:
            return True
        m = self.sourceModel()
        return any(text.lower() in str(v).lower() for v in m.rows[row])


class QTableDialog(QtWidgets.QDialog):
    """ Table of results: ``QTableDialog(title, headers, rows, parent)`` """

    activated = Signal(object)       # the row (list) double-clicked

    def __init__(self, title, headers, rows, parent=None, info=""):
        QtWidgets.QDialog.__init__(self, parent)
        self.setWindowTitle(title)
        layout = QtWidgets.QVBoxLayout(self)
        if info:
            self.info = QtWidgets.QLabel(info, self)
            self.info.setWordWrap(True)
            layout.addWidget(self.info)
        top = QtWidgets.QHBoxLayout()
        self.filter = QtWidgets.QLineEdit(self)
        self.filter.setPlaceholderText("Filter")
        self.filter.setClearButtonEnabled(True)
        self.count = QtWidgets.QLabel(self)
        top.addWidget(self.filter, 1)
        top.addWidget(self.count)
        layout.addLayout(top)
        self.model = TableModel(headers, rows, self)
        self.proxy = _SortProxy(self)
        self.proxy.setSourceModel(self.model)
        self.view = QtWidgets.QTableView(self)
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        self.view.verticalHeader().hide()
        self.view.horizontalHeader().setStretchLastSection(True)
        self.view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.doubleClicked.connect(lambda idx: self.activated.emit(self.row_at(idx)))
        layout.addWidget(self.view, 1)
        buttons = QtWidgets.QHBoxLayout()
        self.copy_button = QtWidgets.QPushButton("Copy", self)
        self.save_button = QtWidgets.QPushButton("Save...", self)
        close = QtWidgets.QPushButton("Dismiss", self)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.save_button)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.copy_button.clicked.connect(self.copy)
        self.save_button.clicked.connect(self.save_dialog)
        close.clicked.connect(self.close)
        self.filter.textChanged.connect(self.set_filter)
        self.view.resizeColumnsToContents()
        self._count()
        self.resize(min(900, 120 + 140 * len(self.model.headers)), 420)

    def set_rows(self, rows):
        self.model.beginResetModel()
        self.model.rows = [list(r) for r in rows]
        self.model.endResetModel()
        self.view.resizeColumnsToContents()
        self._count()

    def set_filter(self, text):
        self.proxy.text = text or ""
        self.proxy.invalidateFilter()
        self._count()

    def _count(self):
        self.count.setText("{0} / {1}".format(self.proxy.rowCount(), self.model.rowCount()))

    def row_at(self, proxy_index):
        return self.model.rows[self.proxy.mapToSource(proxy_index).row()]

    def visible_rows(self):
        return [self.model.rows[self.proxy.mapToSource(self.proxy.index(r, 0)).row()]
                for r in range(self.proxy.rowCount())]

    def text(self, rows=None):
        """ Tab-separated text of the visible rows, headers first """
        out = ["\t".join(self.model.headers)]
        for r in (self.visible_rows() if rows is None else rows):
            out.append("\t".join("" if v is None else str(v) for v in r))
        return "\n".join(out)

    def copy(self):
        sel = sorted({self.proxy.mapToSource(i).row() for i in self.view.selectionModel().selectedRows()})
        rows = [self.model.rows[r] for r in sel] if sel else None
        QtWidgets.QApplication.clipboard().setText(self.text(rows))

    def ask_save_path(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save", "", "CSV files (*.csv);;All files (*)")
        return path or None

    def save(self, path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(self.model.headers)
            for r in self.visible_rows():
                w.writerow(["" if v is None else v for v in r])
        return path

    def save_dialog(self):
        path = self.ask_save_path()
        if not path:
            return None
        try:
            return self.save(path)
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "Save", str(e))
            return None


class QTextDialog(QtWidgets.QDialog):
    """ Text or HTML viewer with Find, Copy and Save """

    CHUNK = 16384

    def __init__(self, title, text="", parent=None, html=False):
        QtWidgets.QDialog.__init__(self, parent)
        self.setWindowTitle(title)
        layout = QtWidgets.QVBoxLayout(self)
        find = QtWidgets.QHBoxLayout()
        self.find_edit = QtWidgets.QLineEdit(self)
        self.find_edit.setPlaceholderText("Find")
        self.find_edit.returnPressed.connect(self.find_next)
        self.match_case = QtWidgets.QCheckBox("Match case", self)
        next_b = QtWidgets.QPushButton("Find next", self)
        next_b.clicked.connect(self.find_next)
        find.addWidget(self.find_edit, 1)
        find.addWidget(self.match_case)
        find.addWidget(next_b)
        layout.addLayout(find)
        self.edit = QtWidgets.QTextEdit(self)
        self.edit.setReadOnly(True)
        if not html:
            self.edit.setFont(fixed_font())
            self.edit.setLineWrapMode(QtWidgets.QTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.edit, 1)
        buttons = QtWidgets.QHBoxLayout()
        copy = QtWidgets.QPushButton("Copy", self)
        save = QtWidgets.QPushButton("Save...", self)
        close = QtWidgets.QPushButton("Dismiss", self)
        copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(self.text()))
        save.clicked.connect(self.save_dialog)
        close.clicked.connect(self.close)
        buttons.addWidget(copy)
        buttons.addWidget(save)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._html = html
        self._pending = ""
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._append_chunk)
        self.resize(760, 520)
        self.set_text(text)

    def set_text(self, text):
        self._timer.stop()          # drop what is left of the previous text
        self._pending = ""
        self.edit.clear()
        if self._html:
            self.edit.setHtml(text or "")
            return
        text = text or ""
        if len(text) <= self.CHUNK:
            self.edit.setPlainText(text)
        else:
            self.edit.setPlainText(text[:self.CHUNK])
            self._pending = text[self.CHUNK:]
            self._timer.start()

    def _append_chunk(self):
        if not self._pending:
            self._timer.stop()
            return
        chunk, self._pending = self._pending[:self.CHUNK], self._pending[self.CHUNK:]
        cursor = self.edit.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        cursor.insertText(chunk)
        if not self._pending:
            self._timer.stop()
            self.edit.moveCursor(QtGui.QTextCursor.MoveOperation.Start)

    def is_loading(self):
        return bool(self._pending)

    def text(self):
        return self.edit.toPlainText() + self._pending

    def find_next(self):
        text = self.find_edit.text()
        if not text:
            return False
        flags = QtGui.QTextDocument.FindFlag.FindCaseSensitively if self.match_case.isChecked() else \
            QtGui.QTextDocument.FindFlag(0)
        if self.edit.find(text, flags):
            return True
        self.edit.moveCursor(QtGui.QTextCursor.MoveOperation.Start)
        return self.edit.find(text, flags)

    def ask_save_path(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save", "", "Text files (*.txt);;All files (*)")
        return path or None

    def save(self, path):
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(self.edit.toHtml() if self._html else self.text())
        return path

    def save_dialog(self):
        path = self.ask_save_path()
        if not path:
            return None
        try:
            return self.save(path)
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "Save", str(e))
            return None
