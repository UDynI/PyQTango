# -*- coding: utf-8 -*-
"""
PyQTango.widgets: reusable, event-aware Tango widgets.

Attribute widgets (bind with ``setModel("dom/fam/mem/attr")``):
    QValueLabel, QStateLabel, QStatusViewer, QWheelEditor, QAttributeWheelEditor,
    QBooleanSetter, QEnumSetter, QStringSetter, QNumberSetter, QArraySetter,
    QBooleanLabel, QSwitchSetter

Device widgets (bind with ``setDevice("dom/fam/mem")``):
    QStateStatusViewer, QScalarListViewer

Generic building blocks:
    QSwitchButton, QErrorDialog, QErrorHistory, QConsole, QJobProgressDialog, QNavigationBar,
    NavigationHistory, LazyTreeModel, TreeNode, QMultiLineDelegate,
    PropertyTableModel, QPropertyTable, QCodeEditor, QSearchableEditor,
    QCompleterLineEdit
"""

from .base import (TangoAttributeWidget, TangoDeviceWidget, model_name_property, device_name_property)
from .colors import state_style, state_qcolors, quality_qcolor
from .value import QValueLabel
from .state import QStateLabel, QStatusViewer, QStateStatusViewer
from .wheel import QWheelEditor, QAttributeWheelEditor
from .setters import (QBooleanSetter, QEnumSetter, QStringSetter, QNumberSetter, QArraySetter,
                      create_viewer, create_setter)
from .boolean import QBooleanLabel, QSwitchButton, QSwitchSetter
from .scalar_list import QScalarListViewer
from .errors import QErrorDialog, QErrorHistory, show_error
from .console import QConsole
from .progress import QJobProgressDialog
from .navigation import QNavigationBar, NavigationHistory
from .lazytree import LazyTreeModel, TreeNode
from .tables import QMultiLineDelegate, PropertyTableModel, QPropertyTable
from .editors import QCodeEditor, QSearchableEditor, QCompleterLineEdit

__all__ = [
    "TangoAttributeWidget", "TangoDeviceWidget", "model_name_property", "device_name_property",
    "state_style", "state_qcolors", "quality_qcolor",
    "QValueLabel", "QStateLabel", "QStatusViewer", "QStateStatusViewer",
    "QWheelEditor", "QAttributeWheelEditor",
    "QBooleanSetter", "QEnumSetter", "QStringSetter", "QNumberSetter", "QArraySetter",
    "create_viewer", "create_setter", "QScalarListViewer",
    "QBooleanLabel", "QSwitchButton", "QSwitchSetter",
    "QErrorDialog", "QErrorHistory", "show_error", "QConsole", "QJobProgressDialog",
    "QNavigationBar", "NavigationHistory", "LazyTreeModel", "TreeNode",
    "QMultiLineDelegate", "PropertyTableModel", "QPropertyTable",
    "QCodeEditor", "QSearchableEditor", "QCompleterLineEdit",
]
