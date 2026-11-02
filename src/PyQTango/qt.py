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
    "make_application", "load_ui", "is_qt6",
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


def make_application(argv=None):
    """ Return the running QApplication or create one.

    On Qt5 HiDPI scaling and HiDPI pixmaps are enabled before creation, as
    they are by default on Qt6.
    """
    app = QtWidgets.QApplication.instance()
    if app is not None:
        return app
    if not is_qt6():
        QtWidgets.QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        QtWidgets.QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    return QtWidgets.QApplication(list(argv) if argv is not None else sys.argv)


def load_ui(path, baseinstance=None):
    """ Load a Qt Designer .ui file at runtime with the active binding's uic """
    uic = importlib.import_module(API + ".uic")
    return uic.loadUi(path, baseinstance)
