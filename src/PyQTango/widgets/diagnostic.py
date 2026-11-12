# -*- coding: utf-8 -*-
"""
QRefresherDiagnostic: what every live attribute model is doing (ATK ``ATKDiagnostic``).

One row per model: mode (events or polling), users, polling period, source,
whether every user is suspended, last update, event and update counts, error
count and last error. ``models`` limits the table to some attributes (a window's
own ones); the table refreshes every second while visible.

@author: Michele Devetta <michele.devetta@cnr.it>
"""

import time

from ..qt import QtCore, QtWidgets, Qt
from ..core.names import normalize_name
from ..models.registry import registry
from ..models.refresher import refresher

__all__ = ["QRefresherDiagnostic", "diagnostic_rows", "COLUMNS"]

COLUMNS = ("Attribute", "Mode", "Users", "Period (ms)", "Source", "Suspended", "Last update",
           "Events", "Updates", "Errors", "Last error")


def _source_name(source):
    if source is None:
        return "Default"
    return {0: "Device", 1: "Cache", 2: "Cache-Device"}.get(int(source), str(source))


def diagnostic_rows(names=None):
    """ Rows (tuples, in :data:`COLUMNS` order) for the live models, or those in ``names`` """
    polled = {d["attribute"]: d for d in refresher().diagnostics()}
    keys = None if names is None else {normalize_name(n) for n in names}
    rows = []
    for m in sorted(registry().attributes(), key=lambda m: m.name.lower()):
        if keys is not None and normalize_name(m.name) not in keys:
            continue
        p = polled.get(m.name)
        last = "" if m.last_update is None else time.strftime("%H:%M:%S", time.localtime(m.last_update))
        err = m.last_error()
        rows.append((m.name, m.mode(), m.ref_count(), "" if p is None else p["period_ms"],
                     _source_name(getattr(m, "source", None)), "yes" if m.is_suspended() else "",
                     last, m.n_events, m.n_updates, m.n_errors, "" if err is None else err.message))
    return rows


class QRefresherDiagnostic(QtWidgets.QWidget):
    """ Table of subscriptions and polled attributes """

    def __init__(self, parent=None, models=None, period_ms=1000):
        QtWidgets.QWidget.__init__(self, parent)
        self.setWindowTitle("Diagnostic")
        self._names = None if models is None else [getattr(m, "name", m) for m in models]
        layout = QtWidgets.QVBoxLayout(self)
        self.summary = QtWidgets.QLabel(self)
        layout.addWidget(self.summary)
        self.table = QtWidgets.QTableWidget(0, len(COLUMNS), self)
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        row = QtWidgets.QHBoxLayout()
        self.refresh_button = QtWidgets.QPushButton("Refresh", self)
        self.refresh_button.clicked.connect(self.update_table)
        self.auto = QtWidgets.QCheckBox("Auto refresh", self)
        self.auto.setChecked(True)
        row.addWidget(self.refresh_button)
        row.addWidget(self.auto)
        row.addStretch(1)
        close = QtWidgets.QPushButton("Dismiss", self)
        close.clicked.connect(self.close)
        row.addWidget(close)
        layout.addLayout(row)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(period_ms)
        self._timer.timeout.connect(self._tick)
        self.resize(900, 400)
        self.update_table()

    def set_models(self, models):
        self._names = None if models is None else [getattr(m, "name", m) for m in models]
        self.update_table()

    def rows(self):
        return diagnostic_rows(self._names)

    def update_table(self):
        rows = self.rows()
        self.table.setRowCount(len(rows))
        for r, values in enumerate(rows):
            for c, v in enumerate(values):
                item = self.table.item(r, c)
                if item is None:
                    item = QtWidgets.QTableWidgetItem()
                    if c in (2, 3, 7, 8, 9):
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table.setItem(r, c, item)
                item.setText(str(v))
        n_ev = sum(1 for r in rows if r[1] == "events")
        n_poll = sum(1 for r in rows if r[1] == "polling")
        self.summary.setText("{0} attribute(s): {1} on events, {2} polled{3}".format(
            len(rows), n_ev, n_poll, " (refresher paused)" if refresher().is_paused() else ""))
        self.table.resizeColumnsToContents()

    def _tick(self):
        if self.auto.isChecked() and self.isVisible():
            self.update_table()

    def showEvent(self, event):
        QtWidgets.QWidget.showEvent(self, event)
        self._timer.start()
        self.update_table()

    def hideEvent(self, event):
        QtWidgets.QWidget.hideEvent(self, event)
        self._timer.stop()
