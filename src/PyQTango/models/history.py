# -*- coding: utf-8 -*-
"""
Process-wide error history (replacement for ATK's ErrorHistory model).
"""

import time

from ..qt import QtCore, Qt, Signal

COLUMNS = ("Time", "Source", "Reason", "Description")


class ErrorHistoryModel(QtCore.QAbstractTableModel):
    """ Table of :class:`PyQTango.core.ErrorRecord`, newest first """

    errorAdded = Signal(object)

    def __init__(self, max_rows=1000, parent=None):
        QtCore.QAbstractTableModel.__init__(self, parent)
        self.max_rows = max_rows
        self._rows = []

    def add(self, record):
        if record is None:
            return
        self.beginInsertRows(QtCore.QModelIndex(), 0, 0)
        self._rows.insert(0, record)
        self.endInsertRows()
        if len(self._rows) > self.max_rows:
            n = len(self._rows)
            self.beginRemoveRows(QtCore.QModelIndex(), self.max_rows, n - 1)
            del self._rows[self.max_rows:]
            self.endRemoveRows()
        self.errorAdded.emit(record)

    def clear(self):
        self.beginResetModel()
        self._rows = []
        self.endResetModel()

    def record(self, row):
        return self._rows[row]

    def records(self):
        return list(self._rows)

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        rec = self._rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return time.strftime("%H:%M:%S", time.localtime(rec.timestamp))
            if col == 1:
                return rec.source
            if col == 2:
                return rec.reason
            return rec.message
        if role == Qt.ItemDataRole.ToolTipRole:
            return rec.text()
        return None


_history = None


def error_history():
    """ The shared error history model """
    global _history
    if _history is None:
        _history = ErrorHistoryModel()
    return _history
