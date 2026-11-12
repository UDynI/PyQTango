# -*- coding: utf-8 -*-
""" The GUI stall watchdog (PYQTANGO_STALL_MS) """

import io
import time

from PyQTango.core.stalls import StallWatchdog, start_from_environment


def test_reports_a_busy_gui_thread(qtbot):
    out = io.StringIO()
    w = StallWatchdog(100, out=out).start()
    try:
        qtbot.wait(200)
        assert w.stalls == []
        time.sleep(0.4)                     # the GUI thread is busy: nothing repaints
        qtbot.waitUntil(lambda: len(w.stalls) == 1, timeout=2000)
        length, stack = w.stalls[0]
        assert 0.3 < length < 1.5
        assert "test_reports_a_busy_gui_thread" in stack
        text = out.getvalue()
        assert "GUI thread busy for" in text and "GUI thread was busy for" in text
    finally:
        w.stop()


def test_environment(qtbot):
    assert start_from_environment(environ={}) is None
    w = start_from_environment(environ={"PYQTANGO_STALL_MS": "150"})
    try:
        assert abs(w.threshold - 0.15) < 1e-9
    finally:
        w.stop()
