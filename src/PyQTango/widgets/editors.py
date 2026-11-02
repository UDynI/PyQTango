# -*- coding: utf-8 -*-
"""
Text editors: QCodeEditor with line numbers and search (Jive's JTextEditor and
PropertyEditorDlg) and QCompleterLineEdit (Jive's JTextTips).
"""

from ..qt import QtCore, QtGui, QtWidgets, Qt, Signal


class _LineNumberArea(QtWidgets.QWidget):

    def __init__(self, editor):
        QtWidgets.QWidget.__init__(self, editor)
        self.editor = editor

    def sizeHint(self):
        return QtCore.QSize(self.editor.line_number_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_line_numbers(event)


class QCodeEditor(QtWidgets.QPlainTextEdit):
    """ Plain-text editor with a line-number gutter and a find helper """

    def __init__(self, parent=None):
        QtWidgets.QPlainTextEdit.__init__(self, parent)
        self.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont))
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self._gutter = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_margin)
        self.updateRequest.connect(self._update_gutter)
        self._update_margin()

    def line_number_width(self):
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 8 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margin(self, *_):
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _update_gutter(self, rect, dy):
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())

    def resizeEvent(self, event):
        QtWidgets.QPlainTextEdit.resizeEvent(self, event)
        cr = self.contentsRect()
        self._gutter.setGeometry(QtCore.QRect(cr.left(), cr.top(), self.line_number_width(), cr.height()))

    def paint_line_numbers(self, event):
        p = QtGui.QPainter(self._gutter)
        pal = self.palette()
        p.fillRect(event.rect(), pal.color(QtGui.QPalette.ColorRole.Window))
        p.setPen(pal.color(QtGui.QPalette.ColorRole.PlaceholderText) if hasattr(QtGui.QPalette.ColorRole, "PlaceholderText")
                 else pal.color(QtGui.QPalette.ColorRole.Mid))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        h = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                p.drawText(0, top, self._gutter.width() - 4, h, Qt.AlignmentFlag.AlignRight, "%03d" % (number + 1))
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            number += 1
        p.end()

    def find_text(self, text, match_case=False, from_start=False):
        """ Select the next occurrence of ``text``; wraps around once. Returns True if found. """
        if not text:
            return False
        flags = QtGui.QTextDocument.FindFlag(0)
        if match_case:
            flags |= QtGui.QTextDocument.FindFlag.FindCaseSensitively
        if from_start:
            self.moveCursor(QtGui.QTextCursor.MoveOperation.Start)
        if self.find(text, flags):
            return True
        self.moveCursor(QtGui.QTextCursor.MoveOperation.Start)
        return self.find(text, flags)


class QSearchableEditor(QtWidgets.QWidget):
    """ QCodeEditor with a search row: text, Match case, Search, Search Next """

    def __init__(self, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.editor = QCodeEditor(self)
        layout.addWidget(self.editor)
        row = QtWidgets.QHBoxLayout()
        self.search_text = QtWidgets.QLineEdit(self)
        self.search_text.setPlaceholderText("Find")
        self.match_case = QtWidgets.QCheckBox("Match case", self)
        self.search_button = QtWidgets.QPushButton("Search", self)
        self.next_button = QtWidgets.QPushButton("Search Next", self)
        row.addWidget(self.search_text, 1)
        row.addWidget(self.match_case)
        row.addWidget(self.search_button)
        row.addWidget(self.next_button)
        layout.addLayout(row)
        self.search_button.clicked.connect(lambda: self._find(True))
        self.next_button.clicked.connect(lambda: self._find(False))
        self.search_text.returnPressed.connect(lambda: self._find(False))

    def _find(self, from_start):
        found = self.editor.find_text(self.search_text.text(), self.match_case.isChecked(), from_start)
        self.search_text.setStyleSheet("" if found or not self.search_text.text() else "background-color: #ffd0d0;")

    def text(self):
        return self.editor.toPlainText()

    def setText(self, text):
        self.editor.setPlainText(text)


class QCompleterLineEdit(QtWidgets.QLineEdit):
    """ Line edit with a popup of matching items (case-insensitive).

    ``match="contains"`` (default) or ``"prefix"``. Signal ``itemChosen(str)``.
    """

    itemChosen = Signal(str)

    def __init__(self, parent=None, items=None, match="contains"):
        QtWidgets.QLineEdit.__init__(self, parent)
        self._model = QtCore.QStringListModel(list(items or []), self)
        self._completer = QtWidgets.QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains if match == "contains" else Qt.MatchFlag.MatchStartsWith)
        self._completer.setMaxVisibleItems(15)
        self._completer.activated.connect(self.itemChosen.emit)
        self.setCompleter(self._completer)

    def setItems(self, items):
        self._model.setStringList(list(items))

    def items(self):
        return self._model.stringList()
