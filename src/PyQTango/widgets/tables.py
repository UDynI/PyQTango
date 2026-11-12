# -*- coding: utf-8 -*-
"""
Property tables with multi-line values (Jive's JiveTable, MultiLineCellEditor).

Tango property values are string arrays; the table shows one item per line.
"""

from ..qt import QtCore, QtGui, QtWidgets, Qt, Signal

#: Background of values edited but not applied (same as the configuration tables)
MODIFIED_BACKGROUND = "#fff1b8"


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
    """ Name / value rows; a row is modified while its value differs from the loaded one.

    ``set_properties([(name, value_or_list), ...])`` loads rows (lists are joined
    with new lines); ``changed()`` returns the modified rows as ``{name: [lines]}``.
    Modified values are bold on a tinted background, with the stored value as tooltip.
    """

    modifiedChanged = Signal(bool)

    def __init__(self, headers=("Property name", "Value"), parent=None, names_editable=False):
        QtCore.QAbstractTableModel.__init__(self, parent)
        self.headers = list(headers)
        self.names_editable = names_editable
        self.read_only = False
        #: Optional ``callable(name) -> bool``: rows whose value can be edited
        self.row_editable = None
        self._rows = []        # [name, value_text, stored_text]

    @staticmethod
    def _text(value):
        if isinstance(value, (list, tuple)):
            return "\n".join(str(v) for v in value)
        return str(value)

    def set_properties(self, props):
        self.beginResetModel()
        self._rows = [[name, self._text(value), self._text(value)] for name, value in props]
        self.endResetModel()
        self.modifiedChanged.emit(False)

    def properties(self):
        return [(r[0], r[1].split("\n")) for r in self._rows]

    def changed(self):
        return {r[0]: r[1].split("\n") for r in self._rows if r[1] != r[2]}

    def is_modified(self):
        return any(r[1] != r[2] for r in self._rows)

    def is_row_modified(self, row):
        return self._rows[row][1] != self._rows[row][2]

    def mark_clean(self):
        """ The current values are now the stored ones (after a write) """
        for r in self._rows:
            r[2] = r[1]
        if self._rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, 1))
        self.modifiedChanged.emit(False)

    def revert(self):
        """ Drop the edits not applied yet """
        for r in self._rows:
            r[1] = r[2]
        if self._rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, 1))
        self.modifiedChanged.emit(False)

    def name(self, row):
        return self._rows[row][0]

    def names(self):
        return [r[0] for r in self._rows]

    def value(self, row):
        return self._rows[row][1]

    def stored(self, row):
        return self._rows[row][2]

    def row_of(self, name, case_sensitive=True):
        key = name if case_sensitive else name.lower()
        for i, r in enumerate(self._rows):
            if (r[0] if case_sensitive else r[0].lower()) == key:
                return i
        return -1

    def set_value(self, row, value):
        """ Change a value (pending until written); True when it changed """
        value = self._text(value)
        r = self._rows[row]
        if r[1] == value:
            return False
        was = self.is_modified()
        r[1] = value
        self.dataChanged.emit(self.index(row, 0), self.index(row, 1))
        if was != self.is_modified() or self.is_modified():
            self.modifiedChanged.emit(self.is_modified())
        return True

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else 2

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return None

    def _can_edit(self, index):
        if self.read_only or not index.isValid():
            return False
        if index.column() == 0:
            return self.names_editable
        return self.row_editable is None or bool(self.row_editable(self._rows[index.row()][0]))

    def flags(self, index):
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self._can_edit(index):
            f |= Qt.ItemFlag.ItemIsEditable
        return f

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return row[index.column()]
        if row[1] != row[2] and index.column() == 1:
            if role == Qt.ItemDataRole.FontRole:
                f = QtGui.QFont()
                f.setBold(True)
                return f
            if role == Qt.ItemDataRole.BackgroundRole:
                return QtGui.QBrush(QtGui.QColor(MODIFIED_BACKGROUND))
            if role == Qt.ItemDataRole.ForegroundRole:
                return QtGui.QBrush(QtGui.QColor("#000000"))
            if role == Qt.ItemDataRole.ToolTipRole:
                return "Not applied yet. Stored value:\n" + (row[2] or "(empty)")
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not self._can_edit(index):
            return False
        if index.column() == 1:
            return self.set_value(index.row(), str(value))
        row = self._rows[index.row()]
        if row[0] == value:
            return False
        row[0] = value
        self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), 1))
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
        # Row heights follow the column widths: a name that wrapped while its column was
        # narrow (before resizeColumnToContents, or while the user drags) must shrink back
        self._row_timer = QtCore.QTimer(self)
        self._row_timer.setSingleShot(True)
        self._row_timer.setInterval(0)
        self._row_timer.timeout.connect(self.resizeRowsToContents)
        self.horizontalHeader().sectionResized.connect(lambda *a: self._row_timer.start())

    def selected_rows(self):
        return sorted({i.row() for i in self.selectionModel().selectedRows()})
