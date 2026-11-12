# -*- coding: utf-8 -*-
"""
GUI stall watchdog (a diagnostic, off by default).

While the GUI thread is busy, Qt cannot repaint: the window keeps showing
what it showed before (for instance the controls of the tab just left) and
does not react to clicks. ``StallWatchdog`` tells such stalls apart from
display problems: a timer on the GUI thread ticks every ``tick_ms``; a
watcher thread notices when no tick arrived for ``threshold_ms``, writes the
GUI thread's stack at that moment, then the stall's length once the GUI
thread is back.

Set ``PYQTANGO_STALL_MS`` (for example ``PYQTANGO_STALL_MS=200``) to start
it in every application made with :func:`PyQTango.qt.make_application`;
reports go to standard error.
"""

import os
import sys
import threading
import time
import traceback

__all__ = ["StallWatchdog", "start_from_environment", "ENV"]

ENV = "PYQTANGO_STALL_MS"


class StallWatchdog(object):

    def __init__(self, threshold_ms=200, tick_ms=20, out=None):
        self.threshold = max(20, int(threshold_ms)) / 1000.0
        self.tick_ms = int(tick_ms)
        self.out = out
        #: [(seconds, stack text)] of the stalls seen so far
        self.stalls = []
        self._last = time.monotonic()
        self._gui_ident = None
        self._stop = threading.Event()
        self._thread = None
        self._timer = None

    def _write(self, text):
        out = self.out or sys.stderr
        try:
            out.write(text)
            out.flush()
        except Exception:  # noqa: BLE001
            pass

    def _tick(self):
        self._last = time.monotonic()

    def start(self, parent=None):
        """ Start; call it on the GUI thread """
        from ..qt import QtCore
        self._gui_ident = threading.get_ident()
        self._last = time.monotonic()
        self._timer = QtCore.QTimer(parent)
        self._timer.setInterval(self.tick_ms)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._thread = threading.Thread(target=self._watch, name="PyQTango stall watchdog", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._timer is not None:
            self._timer.stop()

    def _stack(self):
        frame = sys._current_frames().get(self._gui_ident)
        return "".join(traceback.format_stack(frame)) if frame is not None else "(no stack)\n"

    def _watch(self):
        stalled_since, stack = None, ""
        step = min(self.threshold / 4.0, 0.05)
        while not self._stop.wait(step):
            last = self._last
            late = time.monotonic() - last
            if stalled_since is None:
                if late >= self.threshold:
                    stalled_since = last
                    stack = self._stack()
                    self._write("PyQTango: GUI thread busy for {0:.0f} ms, now in:\n{1}".format(late * 1000, stack))
            elif last != stalled_since:
                length = last - stalled_since
                self.stalls.append((length, stack))
                self._write("PyQTango: GUI thread was busy for {0:.0f} ms\n".format(length * 1000))
                stalled_since = None


def start_from_environment(parent=None, environ=None):
    """ Start a watchdog when ``PYQTANGO_STALL_MS`` is set; returns it (or None) """
    value = (environ if environ is not None else os.environ).get(ENV, "").strip()
    if not value:
        return None
    try:
        ms = int(value)
    except ValueError:
        ms = 200
    w = StallWatchdog(ms).start(parent)
    w._write("PyQTango: reporting GUI stalls longer than {0} ms\n".format(int(w.threshold * 1000)))
    return w
