# -*- coding: utf-8 -*-
"""
QMultiChangeDialog: Jive's MultiChangeConfirmDlg.

Shown before a change that touches several devices: a warning icon, the
sentence "You are going to modify 3 properties on 12 devices.", a read-only
table of what will be written, and Proceed / Cancel. The verb and the value
column follow the kind of item: properties are modified ("New value"),
attributes written ("New value"), commands executed ("Input parameters").

``confirm_changes(parent, rows, n_devices, extra="", item="property")``
returns True when the user chooses Proceed.
"""

from ..qt import QtWidgets, Qt

__all__ = ["QMultiChangeDialog", "confirm_changes", "change_sentence"]


def _plural(word, n):
    if n == 1:
        return word
    return word[:-1] + "ies" if word.endswith("y") else word + "s"


def change_sentence(n_items, n_devices, extra="", item="property"):
    """ Jive's sentence, with the counts and the verb for ``item`` """
    item = item.lower()
    verb = {"attribute": "write", "command": "execute"}.get(item, "modify")
    return "You are going to {0} {1} {2} on {3} device{4}{5}.\nDo you want to proceed ?".format(
        verb, n_items, _plural(item, n_items), n_devices, "" if n_devices == 1 else "s", extra)


class QMultiChangeDialog(QtWidgets.QDialog):

    def __init__(self, rows, n_devices, extra="", item="property", parent=None):
        QtWidgets.QDialog.__init__(self, parent)
        self.setWindowTitle("Multiple change confirmation")
        self.rows = [(str(a), str(b)) for a, b in rows]
        layout = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        icon = QtWidgets.QLabel(self)
        icon.setPixmap(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MessageBoxWarning).pixmap(32, 32))
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        top.addWidget(icon)
        self.text = QtWidgets.QLabel(change_sentence(len(self.rows), n_devices, extra, item), self)
        self.text.setWordWrap(True)
        top.addWidget(self.text, 1)
        layout.addLayout(top)
        value_header = "Input parameters" if item.lower() == "command" else "New value"
        self.table = QtWidgets.QTableWidget(len(self.rows), 2, self)
        self.table.setHorizontalHeaderLabels([item[:1].upper() + item[1:], value_header])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        for r, (name, value) in enumerate(self.rows):
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(name))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(value))
        self.table.resizeColumnToContents(0)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.resizeRowsToContents()
        layout.addWidget(self.table, 1)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        self.proceed_button = QtWidgets.QPushButton("Proceed", self)
        self.proceed_button.clicked.connect(self.accept)
        self.cancel_button = QtWidgets.QPushButton("Cancel", self)
        self.cancel_button.clicked.connect(self.reject)
        self.cancel_button.setDefault(True)
        buttons.addWidget(self.proceed_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)
        self.resize(520, 360)


def confirm_changes(parent, rows, n_devices, extra="", item="property"):
    dlg = QMultiChangeDialog(rows, n_devices, extra, item, parent)
    return dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted
