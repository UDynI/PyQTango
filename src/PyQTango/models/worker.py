# -*- coding: utf-8 -*-
"""
Background execution for Tango calls.

The GUI thread must never call Tango directly: a dead device blocks for the
whole client timeout. Use :func:`run_async` for short calls and :class:`Job` for
long operations that report progress and can be cancelled.

Results are delivered through Qt signals, so slots run in the thread that owns
the receiver (normally the GUI thread).
"""

import logging
import threading

from ..qt import QtCore, Signal
from ..core.errors import error_from_exception

log = logging.getLogger(__name__)

_pool = None
_live = set()
_live_lock = threading.Lock()


def thread_pool():
    """ Dedicated pool for PyQTango work (8 threads by default) """
    global _pool
    if _pool is None:
        _pool = QtCore.QThreadPool()
        _pool.setMaxThreadCount(8)
    return _pool


def _keep(obj):
    with _live_lock:
        _live.add(obj)


def _drop(obj):
    with _live_lock:
        _live.discard(obj)


class Task(QtCore.QObject):
    """ Handle on a background call.

    Signals:
        done(object):   return value of the function
        failed(object): :class:`PyQTango.core.ErrorRecord`
        finished():     emitted after done or failed
    """

    done = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, source=""):
        QtCore.QObject.__init__(self)
        self.source = source
        self.result = None
        self.error = None
        self.is_finished = False


class _Runnable(QtCore.QRunnable):

    def __init__(self, task, fn, args, kwargs):
        QtCore.QRunnable.__init__(self)
        self.setAutoDelete(True)
        self.task = task
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        task = self.task
        try:
            task.result = self.fn(*self.args, **self.kwargs)
            ok = True
        except Exception as e:  # noqa: BLE001 - every error must reach the GUI
            task.error = error_from_exception(e, task.source)
            ok = False
        task.is_finished = True
        try:
            if ok:
                task.done.emit(task.result)
            else:
                task.failed.emit(task.error)
            task.finished.emit()
        except RuntimeError:
            # The task object was deleted while running
            pass
        finally:
            _drop(task)


def run_async(fn, *args, on_done=None, on_error=None, source="", **kwargs):
    """ Run ``fn(*args, **kwargs)`` in the PyQTango thread pool.

    ``on_done(result)`` and ``on_error(ErrorRecord)`` are called in the thread
    that called ``run_async`` (connections are queued). Returns the :class:`Task`;
    in a thread with an event loop the call starts on the next loop turn, so
    connecting to the task's signals right after ``run_async`` returns is safe.
    """
    task = Task(source)
    if on_done is not None:
        task.done.connect(on_done)
    if on_error is not None:
        task.failed.connect(on_error)
    _keep(task)
    runnable = _Runnable(task, fn, args, kwargs)
    if QtCore.QCoreApplication.instance() is not None and QtCore.QThread.currentThread().eventDispatcher() is not None:
        # Start on the next event-loop turn, so that callers can still connect
        # to the returned task's signals without racing a fast call.
        QtCore.QTimer.singleShot(0, lambda: thread_pool().start(runnable))
    else:
        thread_pool().start(runnable)
    return task


class Job(QtCore.QObject):
    """ Long operation with progress and cancellation.

    ``fn(job, *args, **kwargs)`` runs in a worker thread and may call
    ``job.set_progress(percent, text)``, ``job.add_error(record_or_exc, source)``
    and check ``job.cancelled``.

    Signals: progress(int, str), done(object), failed(object), finished().
    Non-fatal errors collected with ``add_error`` are in ``job.errors``.
    """

    progress = Signal(int, str)
    done = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, fn, *args, title="", **kwargs):
        QtCore.QObject.__init__(self)
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.title = title
        self.errors = []
        self._cancel = threading.Event()

    @property
    def cancelled(self):
        return self._cancel.is_set()

    def cancel(self):
        self._cancel.set()

    def set_progress(self, percent, text=""):
        self.progress.emit(int(percent), text)

    def add_error(self, error, source=""):
        if not hasattr(error, "items"):
            error = error_from_exception(error, source)
        self.errors.append(error)

    def start(self):
        def body():
            return self.fn(self, *self.args, **self.kwargs)
        # Keep the job alive until it finishes, even if the caller drops it
        _keep(self)
        task = run_async(body, source=self.title)
        task.done.connect(self._relay_done)
        task.failed.connect(self._relay_failed)
        task.finished.connect(self._relay_finished)
        self._task = task
        return self

    def _relay_done(self, result):
        self.done.emit(result)

    def _relay_failed(self, err):
        self.failed.emit(err)

    def _relay_finished(self):
        self.finished.emit()
        _drop(self)
