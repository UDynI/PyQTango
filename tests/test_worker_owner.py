# -*- coding: utf-8 -*-
""" run_async(owner=...) and LazyTreeModel.ensure_loaded on failures """

import time

from PyQTango.qt import QtWidgets, is_deleted
from PyQTango.models.worker import run_async
from PyQTango.widgets.lazytree import LazyTreeModel, TreeNode
from conftest import wait


def test_owner_drops_late_results(qtbot):
    w = QtWidgets.QLabel()
    got = []
    run_async(lambda: (time.sleep(0.2), "late")[1], on_done=got.append, owner=w)
    w.deleteLater()
    qtbot.wait(50)
    assert is_deleted(w)
    qtbot.wait(400)
    assert got == []
    keep = QtWidgets.QLabel()
    qtbot.addWidget(keep)
    run_async(lambda: "ok", on_done=got.append, owner=keep)
    wait(qtbot, lambda: got == ["ok"])


class Failing(TreeNode):
    def populate(self, ctx):
        raise RuntimeError("cannot list")


def test_ensure_loaded_ends_on_failure(qtbot):
    m = LazyTreeModel(Failing("root"))
    called = []
    m.ensure_loaded(m.index(-1, 0), called.append)
    wait(qtbot, lambda: called)
    assert m.root.error is not None
