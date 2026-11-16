# -*- coding: utf-8 -*-
"""
PyQTango.qt: single import point for Qt.

All PyQTango modules (and, ideally, the applications built on them) import Qt
from here instead of from PyQt5/PyQt6 directly::

    from PyQTango.qt import QtCore, QtGui, QtWidgets, Qt, Signal, Slot, Property

Binding selection, in order of priority:

1. A binding already imported by the application (``PyQt5`` or ``PyQt6`` in
   ``sys.modules``). This keeps PyQTango usable inside existing PyQt5 GUIs.
2. The ``PYQTANGO_QT_API`` environment variable (``pyqt5`` or ``pyqt6``).
3. PyQt5 if installed, else PyQt6.

Writing Qt6-ready code (works on both bindings):

* use scoped enums: ``Qt.AlignmentFlag.AlignLeft``, ``QtWidgets.QSizePolicy.Policy.Expanding``
* call ``exec()``, never ``exec_()``
* take ``QAction``, ``QActionGroup``, ``QShortcut`` from this module
* use :func:`event_pos` / :func:`event_global_pos` for mouse events
* use :func:`enum_value` when an enum must become an ``int``
* compare check boxes with ``isChecked()``, not with ``Qt.Checked``
* use :func:`make_application` to create the ``QApplication`` (HiDPI on Qt5)

@author: Michele Devetta <michele.devetta@cnr.it>
"""

import os
import sys
import importlib

__all__ = [
    "API", "QT_VERSION", "PYQT_VERSION", "QtCore", "QtGui", "QtWidgets", "Qt",
    "Signal", "Slot", "Property", "QAction", "QActionGroup", "QShortcut",
    "enum_value", "event_pos", "event_global_pos", "no_window_flags",
    "make_application", "load_ui", "is_qt6", "is_deleted", "sip", "fixed_font",
    "connect_destroyed", "disconnect_destroyed",
]

_SUPPORTED = ("PyQt5", "PyQt6")


def _select_api():
    # 1. Binding already loaded by the application
    for name in _SUPPORTED:
        if name in sys.modules:
            return name
    # 2. Environment
    env = os.environ.get("PYQTANGO_QT_API", "").strip().lower()
    if env:
        for name in _SUPPORTED:
            if env == name.lower():
                return name
        raise ImportError("PYQTANGO_QT_API='{0}' is not one of {1}".format(env, _SUPPORTED))
    # 3. First installed binding
    for name in _SUPPORTED:
        try:
            importlib.import_module(name + ".QtCore")
            return name
        except ImportError:
            continue
    raise ImportError("PyQTango needs PyQt5 or PyQt6")


API = _select_api()

QtCore = importlib.import_module(API + ".QtCore")
QtGui = importlib.import_module(API + ".QtGui")
QtWidgets = importlib.import_module(API + ".QtWidgets")

Qt = QtCore.Qt
Signal = QtCore.pyqtSignal
Slot = QtCore.pyqtSlot
Property = QtCore.pyqtProperty

sip = importlib.import_module(API + ".sip")


def is_deleted(obj):
    """ True when the C++ side of a Qt object is gone (a late callback must drop it) """
    try:
        return sip.isdeleted(obj)
    except TypeError:
        return False


# Handlers of connect_destroyed(), kept reachable from here. PyQt reports a slot's callable to the
# garbage collector as referenced by the sender's wrapper: when that wrapper is cyclic garbage while
# the C++ object lives on (owned by a C++ parent), the collector clears the callable (NULL closure
# and globals) and the slot proxy keeps it; ``destroyed`` then calls it and the process crashes.
_destroy_handlers = set()


def connect_destroyed(obj, callback):
    """ Call ``callback()`` once the C++ object of ``obj`` is destroyed (``callback`` must not
    reference ``obj``). Returns the handler, to pass to :func:`disconnect_destroyed`. """
    def handler(*_):
        _destroy_handlers.discard(handler)
        callback()
    _destroy_handlers.add(handler)
    obj.destroyed.connect(handler)
    return handler


def disconnect_destroyed(obj, handler):
    """ Undo :func:`connect_destroyed` """
    _destroy_handlers.discard(handler)
    try:
        obj.destroyed.disconnect(handler)
    except (TypeError, RuntimeError):
        pass


QT_VERSION = QtCore.QT_VERSION_STR
PYQT_VERSION = QtCore.PYQT_VERSION_STR


def is_qt6():
    """ True when running on a Qt6 binding """
    return API == "PyQt6"


# Classes that moved from QtWidgets (Qt5) to QtGui (Qt6)
if is_qt6():
    QAction = QtGui.QAction
    QActionGroup = QtGui.QActionGroup
    QShortcut = QtGui.QShortcut
else:
    QAction = QtWidgets.QAction
    QActionGroup = QtWidgets.QActionGroup
    QShortcut = QtWidgets.QShortcut


def enum_value(e):
    """ Integer value of a Qt enum or flag, on both bindings """
    if isinstance(e, int):
        return int(e)
    value = getattr(e, "value", None)
    if value is not None:
        return int(value)
    return int(e)


def event_pos(event):
    """ Mouse/wheel event position in widget coordinates, as QPoint """
    if hasattr(event, "position"):
        return event.position().toPoint()
    if hasattr(event, "pos"):
        return event.pos()
    return QtCore.QPoint()


def event_global_pos(event):
    """ Mouse/wheel event position in global coordinates, as QPoint """
    if hasattr(event, "globalPosition"):
        return event.globalPosition().toPoint()
    return event.globalPos()


def no_window_flags():
    """ Default (empty) window flags; replaces ``QtCore.Qt.WindowFlags()`` """
    return Qt.WindowType.Widget


def fixed_font():
    """ A fixed-pitch font for consoles and aligned text.

    ``QFontDatabase.systemFont(FixedFont)`` is not always fixed-pitch (the
    offscreen platform and some minimal desktops return the UI font): fall back
    to the font family the system matches to "monospace".
    """
    font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
    if QtGui.QFontInfo(font).fixedPitch():
        return font
    fallback = QtGui.QFont("monospace")
    fallback.setStyleHint(QtGui.QFont.StyleHint.TypeWriter)
    fallback.setFixedPitch(True)
    if font.pointSizeF() > 0:
        fallback.setPointSizeF(font.pointSizeF())
    return fallback


def make_application(argv=None, name=None):
    """ Return the running QApplication or create one.

    On Qt5 HiDPI scaling and HiDPI pixmaps are enabled before creation, as
    they are by default on Qt6. ``name`` sets the application name and, on
    macOS, the name shown in the menu bar and the Dock (instead of "Python").
    """
    app = QtWidgets.QApplication.instance()
    if app is not None:
        if name:
            app.setApplicationName(name)
        return app
    if name:
        # macOS takes the menu bar's name from the bundle, before Cocoa starts
        from .core.macos import set_app_name
        set_app_name(name)
    if not is_qt6():
        QtWidgets.QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        QtWidgets.QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    app = QtWidgets.QApplication(list(argv) if argv is not None else sys.argv)
    # PYQTANGO_STALL_MS: report the times the GUI thread is too busy to repaint
    from .core.stalls import start_from_environment
    app._stall_watchdog = start_from_environment(app)
    if name:
        app.setApplicationName(name)
    return app


def load_ui(path, baseinstance=None):
    """ Load a Qt Designer .ui file at runtime with the active binding's uic """
    uic = importlib.import_module(API + ".uic")
    return uic.loadUi(path, baseinstance)
