# -*- coding: utf-8 -*-
"""
QConsole: append-only monospace log (Jive's Test Device console).
"""

from ..qt import QtGui, QtWidgets, Signal


class QConsole(QtWidgets.QWidget):
    """ Read-only text log with "Clear history" and optional "Dismiss".

    ``print(text)`` appends text as is (add ``\\n`` yourself, as Jive does);
    ``separator()`` prints Jive's dashed line. ``maximumBlockCount`` bounds memory.
    """

    dismissed = Signal()

    def __init__(self, parent=None, dismiss_button=False, max_lines=10000):
        QtWidgets.QWidget.__init__(self, parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.text = QtWidgets.QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(max_lines)
        self.text.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont))
        self.text.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.text)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        self.clear_button = QtWidgets.QPushButton("Clear history", self)
        self.clear_button.clicked.connect(self.clear)
        row.addWidget(self.clear_button)
        self.dismiss_button = QtWidgets.QPushButton("Dismiss", self)
        self.dismiss_button.clicked.connect(self.dismissed.emit)
        self.dismiss_button.setVisible(dismiss_button)
        row.addWidget(self.dismiss_button)
        layout.addLayout(row)

    def print(self, text):
        cursor = self.text.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.text.setTextCursor(cursor)
        self.text.ensureCursorVisible()

    def separator(self):
        self.print("-" * 52 + "\n")

    def clear(self):
        self.text.clear()

    def contents(self):
        return self.text.toPlainText()
