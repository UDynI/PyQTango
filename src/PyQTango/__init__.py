# -*- coding: utf-8 -*-
"""
PyQTango: Tango widgets for PyQt5 and PyQt6.

Qt is imported through :mod:`PyQTango.qt`; see that module for the rules that
keep code portable between PyQt5 and PyQt6.
"""

__version__ = "0.2.1"

from . import qt

# Existing widgets (0.1 API, now built on the shared models)
from .DeviceTree import QDeviceTree
from .AttributeTree import QArchivedAttributeTree, QAttributeTree
from .QStatusLed import QStatusLed
from .QAttribute import QAttribute
from .QCommandExecuter import QCommandExecuter
from .QTangoMainWindow import QTangoMainWindow, QTangoDialog

# QDigitDial
from .QDigitDial import QDigitDial

# Node types
from .CommonTree import TreeItem, DeviceItem, AttributeItem, ServerItem

# TangoUtil
from . import TangoUtil
from . import TangoWindows

# New in 0.2
from . import core
from . import models
from . import widgets
from .models import attribute_model, device_model, run_async, Job
from .widgets import *  # noqa: F401,F403
