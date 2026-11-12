# -*- coding: utf-8 -*-
"""
Error display: QErrorDialog (ATK ErrorPane) and QErrorHistory (ATK ErrorHistory).
"""

from ..qt import QtWidgets, Qt
from ..core.errors import error_from_exception
from ..models.history import error_history


class QErrorDialog(QtWidgets.QDialog):
    """ Shows the first error description, with the full Tango stack under "Details" """

    def __init__(self, record, title="Error", parent=None):
        QtWidgets.QDialog.__init__(self, parent)
        if not hasattr(record, "items"):
            record = error_from_exception(record)
        self.record = record
        self.setWindowTitle(title)
        layout = QtWidgets.QVBoxLayout(self)

        top = QtWidgets.QHBoxLayout()
        icon = QtWidgets.QLabel(self)
        icon.setPixmap(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MessageBoxCritical).pixmap(32, 32))
        top.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        message = record.message or ""
        if len(message) > 600 or message.count("\n") > 8:
            # Very long or multi-line errors: scrollable, capped (ATK 10 ErrorPane caps at 800x600)
            head = QtWidgets.QVBoxLayout()
            title = QtWidgets.QLabel("<b>{0}</b>".format(record.source or record.reason), self)
            title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            head.addWidget(title)
            msg = QtWidgets.QPlainTextEdit(self)
            msg.setReadOnly(True)
            msg.setPlainText(message)
            msg.setMaximumHeight(300)
            head.addWidget(msg)
            top.addLayout(head, 1)
        else:
            msg = QtWidgets.QLabel(self)
            msg.setWordWrap(True)
            msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            msg.setText("<b>{0}</b><br/>{1}".format(record.source or record.reason, message))
            top.addWidget(msg, 1)
        self.message_widget = msg
        layout.addLayout(top)

        self.details = QtWidgets.QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setPlainText(record.text())
        self.details.setVisible(False)
        self.details.setMinimumHeight(160)
        self.details.setMaximumHeight(400)
        layout.addWidget(self.details)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok, parent=self)
        self.details_button = buttons.addButton("Details", QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self.details.setVisible)
        copy = buttons.addButton("Copy", QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(record.text()))
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self.setMaximumWidth(800)
        self.resize(480, 160)


def show_error(parent, error, title="Error"):
    """ Modal error dialog for a DevFailed, any exception or an ErrorRecord """
    dlg = QErrorDialog(error, title, parent)
    dlg.exec()
    return dlg


class QErrorHistory(QtWidgets.QWidget):
    """ Table of all errors collected by PyQTango models, with Clear and Save """

    def __init__(self, parent=None, model=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.model = model or error_history()
        layout = QtWidgets.QVBoxLayout(self)
        self.view = QtWidgets.QTableView(self)
        self.view.setModel(self.model)
        self.view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.view.verticalHeader().setVisible(False)
        self.view.doubleClicked.connect(self._show_details)
        layout.addWidget(self.view)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        clear = QtWidgets.QPushButton("Clear", self)
        clear.clicked.connect(self.model.clear)
        save = QtWidgets.QPushButton("Save...", self)
        save.clicked.connect(self.save)
        row.addWidget(clear)
        row.addWidget(save)
        layout.addLayout(row)
        self.setWindowTitle("Error history")
        self.resize(700, 300)

    def _show_details(self, index):
        QErrorDialog(self.model.record(index.row()), "Error details", self).exec()

    def save(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save errors", "errors.txt")
        if not path:
            return
        with open(path, "w") as f:
            for rec in reversed(self.model.records()):
                f.write(rec.text() + "\n\n")
