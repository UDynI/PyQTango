# -*- coding: utf-8 -*-
""" Icons, table/text dialogs, startup level, server picker and level walker dialogs (plan 7.6) """

import pytest

from PyQTango.qt import QtWidgets, Qt
from PyQTango.widgets.icons import state_icon, host_icon, ball_icon, HOST_COLORS
from PyQTango.widgets.dialogs import QTableDialog, QTextDialog
from PyQTango.widgets.levels import (QStartupLevelDialog, QServerPickerDialog, QLevelWalkerDialog)
from PyQTango.core.levels import START, STOP
from conftest import wait


def test_icons(qtbot):
    import tango
    a = state_icon(tango.DevState.ON)
    assert a is state_icon("ON") and not a.isNull()            # cached, names accepted
    assert state_icon("FAULT") is not a
    for s in HOST_COLORS:
        assert not host_icon(s).isNull()
    assert host_icon("running") is host_icon("running") and ball_icon("#123456").availableSizes()


def test_table_dialog(qtbot, tmp_path):
    d = QTableDialog("Servers", ["Name", "Uptime (s)"], [["b/1", 10], ["a/1", 200], ["c/2", 3]], info="three")
    qtbot.addWidget(d)
    from PyQTango.qt import Qt
    d.view.sortByColumn(1, Qt.SortOrder.AscendingOrder)
    assert [r[0] for r in d.visible_rows()] == ["c/2", "b/1", "a/1"]       # numbers sort as numbers
    d.filter.setText("/1")
    assert sorted(r[0] for r in d.visible_rows()) == ["a/1", "b/1"] and d.count.text() == "2 / 3"
    assert d.text().splitlines()[0] == "Name\tUptime (s)"
    path = str(tmp_path / "t.csv")
    d.ask_save_path = lambda: path
    assert d.save_dialog() == path and open(path).read().startswith("Name,Uptime (s)")
    d.copy()
    assert QtWidgets.QApplication.clipboard().text().startswith("Name\t")
    d.set_rows([["x", 1]])
    d.filter.clear()
    assert d.visible_rows() == [["x", 1]]


def test_text_dialog(qtbot, tmp_path):
    big = "".join("line {0}\n".format(i) for i in range(10000))
    d = QTextDialog("Log", big)
    qtbot.addWidget(d)
    assert d.is_loading()
    wait(qtbot, lambda: not d.is_loading(), 5000)
    assert d.text() == big
    d.find_edit.setText("line 9999")
    assert d.find_next()
    path = str(tmp_path / "log.txt")
    d.ask_save_path = lambda: path
    d.save_dialog()
    assert open(path).read() == big
    h = QTextDialog("Help", "<b>bold</b>", html=True)
    qtbot.addWidget(h)
    assert h.text() == "bold"


def test_startup_level_and_picker(qtbot):
    d = QStartupLevelDialog(["A/1", "B/1"], nb_levels=5, level=3)
    qtbot.addWidget(d)
    assert d.values() == (True, 3) and "2 servers" in d.label.text()
    d.controlled.setChecked(False)
    assert d.values() == (False, 0) and not d.level.isEnabled()
    p = QServerPickerDialog(["Motion/axis", "PowerSupply/lab", "TangoTest/test1"],
                            host_servers={"hostb": ["TangoTest/test1"]})
    qtbot.addWidget(p)
    assert p.names() == ["Motion/axis", "PowerSupply/lab", "TangoTest/test1"]
    p.filter.setText("power")
    assert p.names() == ["PowerSupply/lab"]
    p.filter.clear()
    p.source.setCurrentText("hostb")
    assert p.names() == ["TangoTest/test1"]
    p.select(["tangotest/test1"])
    assert p.selected() == ["TangoTest/test1"]
    with qtbot.waitSignal(p.createRequested):
        p.create_button.click()


def test_level_walker_dialog(qtbot):
    calls = []

    def command(host, level):
        calls.append((host, level))
        if level == 2:
            raise RuntimeError("level 2 failed")

    d = QLevelWalkerDialog(START, {"hosta": [1, 2], "hostb": [1]}, command, pause_start=0)
    qtbot.addWidget(d)
    d.show()
    with qtbot.waitSignal(d.finished_walk, timeout=10000) as blocker:
        d.start()
        wait(qtbot, lambda: d.question.isVisible(), 5000)
        assert d.question_label.text() == "Start level 1 ?"
        d.for_all.setChecked(True)
        d.yes_button.click()
    assert calls == [("hosta", 1), ("hostb", 1), ("hosta", 2)]
    assert [(r.host, r.level, r.ok) for r in blocker.args[0]] == [
        ("hosta", 1, True), ("hostb", 1, True), ("hosta", 2, False)]
    assert d.results.rowCount() == 3 and d.results.item(2, 2).text() == "level 2 failed"
    assert d.stop_button.text() == "Dismiss"
    calls.clear()
    s = QLevelWalkerDialog(STOP, {"hosta": [1, 2]}, command, pause_stop=0)
    qtbot.addWidget(s)
    s.auto_answer = "no"
    with qtbot.waitSignal(s.finished_walk, timeout=10000) as blocker:
        s.start()
    assert calls == [] and all(r.skipped for r in blocker.args[0])
    c = QLevelWalkerDialog(STOP, {"hosta": [1, 2]}, command, pause_stop=0)
    qtbot.addWidget(c)
    c.show()
    with qtbot.waitSignal(c.finished_walk, timeout=10000):
        c.start()
        wait(qtbot, lambda: c.question.isVisible(), 5000)
        assert c.question_label.text() == "Stop level 2 ?"
        c.cancel_button.click()
    assert c.walker.was_cancelled and c.status.text() == "Cancelled"
    e = QLevelWalkerDialog(STOP, {"hosta": [1, 2]}, command, pause_stop=0)
    qtbot.addWidget(e)
    e.show()
    with qtbot.waitSignal(e.finished_walk, timeout=10000):
        e.start()
        wait(qtbot, lambda: e.question.isVisible(), 5000)
        qtbot.keyClick(e, Qt.Key.Key_Escape)        # Esc -> reject(), must not leave the worker blocked
    assert e.walker.was_cancelled


def test_job_progress_dialog_outlives_its_window(qtbot):
    """ Closing the window of a running job deletes its progress dialog; the job still ends quietly """
    import threading
    from PyQTango.qt import QtWidgets
    from PyQTango.models.worker import Job
    from PyQTango.widgets.progress import QJobProgressDialog
    gate = threading.Event()

    def body(job, _arg):
        gate.wait(5)
        job.set_progress(50, "half")
        return 1
    parent = QtWidgets.QWidget()
    job = Job(body, None, title="Slow")
    finished = []
    job.finished.connect(lambda: finished.append(1))
    dlg = QJobProgressDialog.run(job, parent, show_errors=True)
    parent.deleteLater()
    qtbot.wait(50)
    gate.set()
    qtbot.waitUntil(lambda: bool(finished), timeout=5000)
    assert dlg is not None


def test_text_dialog_set_text_drops_pending_chunks(qtbot):
    d = QTextDialog("Log", "A" * (QTextDialog.CHUNK * 3))
    qtbot.addWidget(d)
    d.set_text("short")
    qtbot.wait(200)
    assert d.text() == "short"


def test_dialog_save_failure_is_reported(qtbot, tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda *a: errors.append(a[-1]))
    for d in (QTextDialog("Log", "x"), QTableDialog("T", ["a"], [["1"]])):
        qtbot.addWidget(d)
        d.ask_save_path = lambda: str(tmp_path)       # a directory: OSError
        assert d.save_dialog() is None
    assert len(errors) == 2


def test_level_walker_dialog_deleted_while_asking(qtbot):
    from PyQTango.qt import sip
    d = QLevelWalkerDialog(STOP, {"hosta": [1, 2]}, lambda h, l: None, pause_stop=0)
    d.show()
    walker = d.walker
    d.start()
    wait(qtbot, lambda: d.question.isVisible(), 5000)
    sip.delete(d)                                     # deleted with its window: no reject, no close
    wait(qtbot, lambda: walker.was_cancelled, 3000)   # the worker stopped waiting


def test_job_progress_dialog_deletes_itself(qtbot):
    from PyQTango.qt import QtCore, is_deleted
    from PyQTango.models.worker import Job
    from PyQTango.widgets.progress import QJobProgressDialog
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    job = Job(lambda job, _a: 1, None, title="Quick")
    dlg = QJobProgressDialog.run(job, parent, show_errors=False)
    with qtbot.waitSignal(job.finished, timeout=5000):
        pass
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    assert is_deleted(dlg)
