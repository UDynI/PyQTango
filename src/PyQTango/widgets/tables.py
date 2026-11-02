# -*- coding: utf-8 -*-
"""
Property tables with multi-line values (Jive's JiveTable, MultiLineCellEditor).

Tango property values are string arrays; the table shows one item per line.
"""

from ..qt import QtCore, QtGui, QtWidgets, Qt, Signal


class QMultiLineDelegate(QtWidgets.QStyledItemDelegate):
    """ Edits a cell in a QPlainTextEdit. Enter adds a line, Ctrl+Enter commits,
    Esc cancels, leaving the cell commits. """

    def createEditor(self, parent, option, index):
        editor = QtWidgets.QPlainTextEdit(parent)
        editor.setTabChangesFocus(True)
        editor.installEventFilter(self)
        return editor

    def setEditorData(self, editor, index):
        editor.setPlainText(index.data(Qt.ItemDataRole.EditRole) or "")
        editor.moveCursor(QtGui.QTextCursor.MoveOperation.End)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.toPlainText(), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        rect = QtCore.QRect(option.rect)
        lines = max(3, (index.data(Qt.ItemDataRole.EditRole) or "").count("\n") + 2)
        rect.setHeight(max(rect.height(), min(300, lines * option.fontMetrics.height() + 8)))
        editor.setGeometry(rect)

    def eventFilter(self, editor, event):
        if event.type() == QtCore.QEvent.Type.KeyPress and isinstance(editor, QtWidgets.QPlainTextEdit):
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and \
                    event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.commitData.emit(editor)
                self.closeEditor.emit(editor, QtWidgets.QAbstractItemDelegate.EndEditHint.NoHint)
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.closeEditor.emit(editor, QtWidgets.QAbstractItemDelegate.EndEditHint.RevertModelCache)
                return True
            return False
        return QtWidgets.QStyledItemDelegate.eventFilter(self, editor, event)


class PropertyTableModel(QtCore.QAbstractTableModel):
    """ Name / value rows with per-row "modified" tracking.

    ``set_properties([(name, value_or_list), ...])`` loads rows (lists are joined
    with new lines); ``changed()`` returns the edited rows as ``{name: [lines]}``.
    """

    modifiedChanged = Signal(bool)

    def __init__(self, headers=("Property name", "Value"), parent=None, names_editable=False):
        QtCore.QAbstractTableModel.__init__(self, parent)
        self.headers = list(headers)
        self.names_editable = names_editable
        self.read_only = False
        self._rows = []        # [name, value_text, modified]

    def set_properties(self, props):
        self.beginResetModel()
        self._rows = []
        for name, value in props:
            if isinstance(value, (list, tuple)):
                value = "\n".join(str(v) for v in value)
            self._rows.append([name, str(value), False])
        self.endResetModel()
        self.modifiedChanged.emit(False)

    def properties(self):
        return [(r[0], r[1].split("\n")) for r in self._rows]

    def changed(self):
        return {r[0]: r[1].split("\n") for r in self._rows if r[2]}

    def is_modified(self):
        return any(r[2] for r in self._rows)

    def mark_clean(self):
        for r in self._rows:
            r[2] = False
        if self._rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, 1))
        self.modifiedChanged.emit(False)

    def name(self, row):
        return self._rows[row][0]

    def value(self, row):
        return self._rows[row][1]

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else 2

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return None

    def flags(self, index):
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if not self.read_only and (index.column() == 1 or self.names_editable):
            f |= Qt.ItemFlag.ItemIsEditable
        return f

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return row[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole and row[2]:
            return QtGui.QBrush(QtGui.QColor("darkgreen"))
        if role == Qt.ItemDataRole.FontRole and row[2]:
            f = QtGui.QFont()
            f.setBold(True)
            return f
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        row = self._rows[index.row()]
        col = index.column()
        if row[col] == value:
            return False
        row[col] = value
        row[2] = True
        self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), 1))
        self.modifiedChanged.emit(True)
        return True


class QPropertyTable(QtWidgets.QTableView):
    """ Table view for a :class:`PropertyTableModel` with multi-line cells """

    def __init__(self, parent=None, model=None):
        QtWidgets.QTableView.__init__(self, parent)
        self.setModel(model or PropertyTableModel(parent=self))
        self.setItemDelegate(QMultiLineDelegate(self))
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.setWordWrap(True)
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked |
                             QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed)
        self.model().modelReset.connect(self.resizeRowsToContents)
        self.model().dataChanged.connect(lambda *a: self.resizeRowsToContents())

    def selected_rows(self):
        return sorted({i.row() for i in self.selectionModel().selectedRows()})
