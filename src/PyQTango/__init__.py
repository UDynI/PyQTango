# -*- coding: utf-8 -*-
"""
PyQTango: Tango widgets for PyQt5 and PyQt6.

Qt is imported through :mod:`PyQTango.qt`; see that module for the rules that
keep code portable between PyQt5 and PyQt6.
"""

__version__ = "0.3.2"

from . import qt

from . import core
from . import models
from . import widgets

# Legacy widgets (0.1 API, now in PyQTango.widgets and built on the shared models)
from .widgets import (QAttribute, QCommandExecuter, QDigitDial, QStatusLed, QTangoMainWindow, QTangoDialog,
                      QDeviceTree, QAttributeTree, TreeItem, DeviceItem, AttributeItem, ServerItem)

# Legacy modules, still reachable as PyQTango.TangoUtil and PyQTango.TangoWindows
from .core import tangoutil as TangoUtil
from .widgets import windows as TangoWindows

from .models import attribute_model, device_model, run_async, Job
from .widgets import *  # noqa: F401,F403
