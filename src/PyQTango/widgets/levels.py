# -*- coding: utf-8 -*-
"""
Dialogs for host control (Astor's PutServerInfoDialog, ListDialog and the
ServerCmdThread monitor).

* :class:`QStartupLevelDialog` - controlled flag and startup level (1 to N) for
  one or many servers; :func:`ask_levels_policy` asks how to set the levels
  when more than four servers start (Astor's three choices).
* :class:`QServerPickerDialog` - servers to start: filter, servers of another
  host, multi-selection and a "Create new server..." hook.
* :class:`QLevelWalkerDialog` - runs a :class:`PyQTango.core.levels.LevelWalker`
  in a worker: Yes / No / Cancel per level with "Do it for all levels",
  a progress bar, Cancel, and a result table per host at the end.

@author: Michele Devetta <michele.devetta@cnr.it>
"""

import threading

from ..qt import QtWidgets, Qt, Signal, is_deleted
from ..core.levels import LevelWalker, START
from ..models.worker import run_async

__all__ = ["QStartupLevelDialog", "QServerPickerDialog", "QLevelWalkerDialog", "ask_levels_policy",
           "POLICY_NONE", "POLICY_SAME", "POLICY_EACH"]

POLICY_NONE = "none"       # not controlled, don't ask
POLICY_SAME = "same"       # one level for all
POLICY_EACH = "each"       # ask for each server


class QStartupLevelDialog(QtWidgets.QDialog):
    """ Startup level of ``servers``: values() -> (controlled, level) """

    def __init__(self, servers, parent=None, nb_levels=5, level=1, controlled=True):
        QtWidgets.QDialog.__init__(self, parent)
        servers = list(servers)
        self.setWindowTitle("Startup level")
        layout = QtWidgets.QVBoxLayout(self)
        text = servers[0] if len(servers) == 1 else "{0} servers".format(len(servers))
        self.label = QtWidgets.QLabel("Startup level for " + text, self)
        if len(servers) > 1:
            self.label.setToolTip("\n".join(servers))
        layout.addWidget(self.label)
        self.controlled = QtWidgets.QCheckBox("Controlled by the Starter", self)
        self.controlled.setChecked(controlled)
        layout.addWidget(self.controlled)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Level", self))
        self.level = QtWidgets.QSpinBox(self)
        self.level.setRange(1, max(1, nb_levels))
        self.level.setValue(min(max(1, level or 1), max(1, nb_levels)))
        row.addWidget(self.level)
        row.addStretch(1)
        layout.addLayout(row)
        self.controlled.toggled.connect(self.level.setEnabled)
        self.level.setEnabled(controlled)
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                         QtWidgets.QDialogButtonBox.StandardButton.Cancel, parent=self)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def values(self):
        """ (controlled, level); level 0 when not controlled """
        on = self.controlled.isChecked()
        return on, (self.level.value() if on else 0)


def ask_levels_policy(parent, count):
    """ Astor's question when more than four servers start: POLICY_* or None (cancel) """
    box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Icon.Question, "Startup levels",
                                "{0} servers will be started.\nHow do you want to set their startup level?"
                                .format(count), parent=parent)
    none_b = box.addButton("Not controlled (don't ask)", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
    same_b = box.addButton("Same level for all", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
    each_b = box.addButton("Ask for each", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QtWidgets.QMessageBox.StandardButton.Cancel)
    box.exec()
    return {none_b: POLICY_NONE, same_b: POLICY_SAME, each_b: POLICY_EACH}.get(box.clickedButton())


class QServerPickerDialog(QtWidgets.QDialog):
    """ Pick servers to start.

    ``servers`` are all candidate names; ``host_servers`` maps other hosts to
    their servers (the "Servers of host" choice). ``createRequested`` asks the
    application to create a new server (wizard).
    """

    createRequested = Signal()

    ALL = "All registered servers"

    def __init__(self, servers, parent=None, host_servers=None, title="Start new servers"):
        QtWidgets.QDialog.__init__(self, parent)
        self.setWindowTitle(title)
        self._all = sorted(servers, key=str.lower)
        self._hosts = dict(host_servers or {})
        layout = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Servers of", self))
        self.source = QtWidgets.QComboBox(self)
        self.source.addItem(self.ALL)
        for h in sorted(self._hosts):
            self.source.addItem(h)
        row.addWidget(self.source, 1)
        layout.addLayout(row)
        self.filter = QtWidgets.QLineEdit(self)
        self.filter.setPlaceholderText("Filter (wildcards allowed)")
        self.filter.setClearButtonEnabled(True)
        layout.addWidget(self.filter)
        self.list = QtWidgets.QListWidget(self)
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())
        layout.addWidget(self.list, 1)
        buttons = QtWidgets.QHBoxLayout()
        self.create_button = QtWidgets.QPushButton("Create new server...", self)
        self.create_button.clicked.connect(self._create)
        buttons.addWidget(self.create_button)
        buttons.addStretch(1)
        self.ok_button = QtWidgets.QPushButton("Start", self)
        cancel = QtWidgets.QPushButton("Cancel", self)
        self.ok_button.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self.ok_button)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self.filter.textChanged.connect(self._fill)
        self.source.currentTextChanged.connect(self._fill)
        self._fill()
        self.resize(420, 480)

    def _candidates(self):
        src = self.source.currentText()
        return self._all if src == self.ALL else sorted(self._hosts.get(src, []), key=str.lower)

    def _fill(self, *_):
        from ..core.names import wildcard_to_regex
        pattern = self.filter.text().strip()
        if pattern and "*" not in pattern:
            pattern = "*" + pattern + "*"
        rx = wildcard_to_regex(pattern) if pattern else None
        self.list.clear()
        for s in self._candidates():
            if rx is None or rx.match(s):
                self.list.addItem(s)

    def names(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

    def select(self, names):
        wanted = {n.lower() for n in names}
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setSelected(it.text().lower() in wanted)

    def selected(self):
        return [it.text() for it in self.list.selectedItems()]

    def _create(self):
        self.createRequested.emit()
        self.reject()


class QLevelWalkerDialog(QtWidgets.QDialog):
    """ Run a start or stop by level.

    ``QLevelWalkerDialog(action, hosts_levels, command, parent)`` builds the
    LevelWalker; :meth:`start` runs it in a worker. Set ``auto_answer``
    ("yes", "all", "no" or "cancel") to skip the questions (tests, scripts).

    Signals: ``finished_walk(list)`` with the LevelResults.
    """

    finished_walk = Signal(object)
    _ask = Signal(str, int)
    _progress = Signal(int, int, str)

    def __init__(self, action, hosts_levels, command, parent=None, pause_start=0.5, pause_stop=0.05):
        QtWidgets.QDialog.__init__(self, parent)
        self.action = action
        verb = "Start" if action == START else "Stop"
        self.setWindowTitle("{0} servers".format(verb))
        self.auto_answer = None
        self._answer = None
        self._event = threading.Event()
        self._cancel = False
        self.walker = LevelWalker(action, hosts_levels, command, decide=self._decide,
                                  progress=self._progress.emit, cancelled=lambda: self._cancel,
                                  pause_start=pause_start, pause_stop=pause_stop)
        layout = QtWidgets.QVBoxLayout(self)
        hosts = sorted(hosts_levels)
        self.header = QtWidgets.QLabel("{0} servers on {1}".format(
            verb, hosts[0] if len(hosts) == 1 else "{0} hosts".format(len(hosts))), self)
        layout.addWidget(self.header)
        self.question = QtWidgets.QWidget(self)
        q = QtWidgets.QVBoxLayout(self.question)
        q.setContentsMargins(0, 0, 0, 0)
        self.question_label = QtWidgets.QLabel(self.question)
        q.addWidget(self.question_label)
        self.for_all = QtWidgets.QCheckBox("Do it for all levels", self.question)
        q.addWidget(self.for_all)
        qb = QtWidgets.QHBoxLayout()
        self.yes_button = QtWidgets.QPushButton("Yes", self.question)
        self.no_button = QtWidgets.QPushButton("No", self.question)
        self.cancel_button = QtWidgets.QPushButton("Cancel", self.question)
        for b, a in ((self.yes_button, "yes"), (self.no_button, "no"), (self.cancel_button, "cancel")):
            b.clicked.connect(lambda _c=False, a=a: self.answer(a))
            qb.addWidget(b)
        q.addLayout(qb)
        layout.addWidget(self.question)
        self.question.hide()
        self.progress = QtWidgets.QProgressBar(self)
        self.status = QtWidgets.QLabel(self)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        self.results = QtWidgets.QTableWidget(0, 3, self)
        self.results.setHorizontalHeaderLabels(["Host", "Level", "Result"])
        self.results.horizontalHeader().setStretchLastSection(True)
        self.results.verticalHeader().hide()
        self.results.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results.hide()
        layout.addWidget(self.results, 1)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        self.stop_button = QtWidgets.QPushButton("Cancel", self)
        self.stop_button.clicked.connect(self.cancel)
        row.addWidget(self.stop_button)
        layout.addLayout(row)
        self._ask.connect(self._show_question)
        self._progress.connect(self._show_progress)
        self.running = False
        self.resize(460, 220)

    # -- Running -------------------------------------------------------------------
    def start(self):
        self.running = True
        return run_async(self.walker.run, on_done=self._done, on_error=self._failed, source=self.windowTitle(),
                         owner=self)

    def cancel(self):
        if not self.running:
            self.close()
            return
        self._cancel = True
        self.answer("cancel")

    def _decide(self, action, level):
        """ Worker thread: ask the GUI and wait for the answer """
        if self._cancel:
            return "cancel"         # cancelled while a level was running: do not ask again
        if self.auto_answer is not None:
            return self.auto_answer
        self._event.clear()
        if is_deleted(self):
            return "cancel"
        self._ask.emit(action, level)
        # The dialog can be deleted with its window (no close, no reject): never wait for good
        while not self._event.wait(0.2):
            if is_deleted(self):
                return "cancel"
        return self._answer

    def _show_question(self, action, level):
        self.question_label.setText("{0} level {1} ?".format("Start" if action == START else "Stop", level))
        self.question.show()
        self.yes_button.setFocus()

    def answer(self, a):
        if a == "yes" and self.for_all.isChecked():
            a = "all"
        self._answer = a
        self.question.hide()
        self._event.set()

    def _show_progress(self, done, total, text):
        self.progress.setMaximum(max(1, total))
        self.progress.setValue(done)
        if text:
            self.status.setText(text)

    def _done(self, results):
        self.running = False
        self.question.hide()
        self.stop_button.setText("Dismiss")
        self.status.setText("Cancelled" if self.walker.was_cancelled else "Done")
        self.results.setRowCount(len(results))
        for r, res in enumerate(results):
            text = "skipped" if res.skipped else ("OK" if res.ok else res.message)
            for c, v in enumerate((res.host, str(res.level), text)):
                item = QtWidgets.QTableWidgetItem(v)
                if c == 2 and not res.ok:
                    item.setForeground(Qt.GlobalColor.red)
                self.results.setItem(r, c, item)
        self.results.resizeColumnsToContents()
        self.results.show()
        self.finished_walk.emit(results)

    def _failed(self, err):
        self.running = False
        self.status.setText("<font color='red'>{0}</font>".format(err.message))
        self.stop_button.setText("Dismiss")
        self.finished_walk.emit(list(self.walker.results))

    def _abort_wait(self):
        """ Cancel a running walk and release a worker waiting for an answer """
        if self.running:
            self._cancel = True
            self._answer = "cancel"
            self._event.set()

    def reject(self):
        # Esc and the window close button go through reject(), not closeEvent
        self._abort_wait()
        QtWidgets.QDialog.reject(self)

    def closeEvent(self, event):
        self._abort_wait()
        QtWidgets.QDialog.closeEvent(self, event)
