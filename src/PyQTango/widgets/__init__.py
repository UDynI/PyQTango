# -*- coding: utf-8 -*-
"""
PyQTango.widgets: reusable, event-aware Tango widgets.

Attribute widgets (bind with ``setModel("dom/fam/mem/attr")``):
    QValueLabel, QStateLabel, QStatusViewer, QWheelEditor, QAttributeWheelEditor,
    QBooleanSetter, QEnumSetter, QStringSetter, QNumberSetter, QArraySetter,
    QBooleanLabel, QSwitchSetter

    QNumberComboSetter, QStringComboSetter

Device widgets (bind with ``setDevice("dom/fam/mem")``):
    QStateStatusViewer, QScalarListViewer, QCommandCombo

Dialogs and tools:
    QAttributePropertyDialog, QRefresherDiagnostic, QBlackBoxView, QBlackBoxDialog,
    QTableDialog, QTextDialog

Charts, trends, spectrum and image viewers need pyqtgraph (the ``plot`` extra)
and are imported from their modules: PyQTango.widgets.plot (QTangoChart),
.chartdialogs, .trend (QTrend, QBooleanTrend), .spectrum (QSpectrumViewer and
the list viewers), .image (QImageViewer, QStringImageViewer, QRawImageViewer) and
.profiler (QPollingProfiler, QPollingProfilerDialog).

Legacy widgets (0.1 API, built on the shared models):
    QAttribute, QCommandExecuter, QDigitDial, QStatusLed, QTangoMainWindow, QTangoDialog,
    QDeviceTree, QAttributeTree and their tree items (TreeItem, DeviceItem, AttributeItem,
    ServerItem); window mix-ins TangoEvents2Qt and WindowScaling

Generic building blocks:
    QSwitchButton, QErrorDialog, QErrorHistory, QConsole, QJobProgressDialog, QNavigationBar,
    NavigationHistory, LazyTreeModel, TreeNode, QMultiLineDelegate,
    PropertyTableModel, QPropertyTable, ConfigTableModel, QConfigPanel, QPollingPanel, QCodeEditor, QSearchableEditor,
    QCompleterLineEdit
"""

from .base import (TangoAttributeWidget, TangoDeviceWidget, model_name_property, device_name_property)
from .colors import state_style, state_qcolors, quality_qcolor
from .value import QValueLabel
from .state import QStateLabel, QStatusViewer, QStateStatusViewer
from .wheel import QWheelEditor, QAttributeWheelEditor
from .setters import (QBooleanSetter, QEnumSetter, QStringSetter, QNumberSetter, QArraySetter,
                      QNumberComboSetter, QStringComboSetter, create_viewer, create_setter)
from .boolean import QBooleanLabel, QSwitchButton, QSwitchSetter
from .scalar_list import QScalarListViewer
from .errors import QErrorDialog, QErrorHistory, show_error
from .console import QConsole
from .blackbox import QBlackBoxView, QBlackBoxDialog
from .progress import QJobProgressDialog
from .navigation import QNavigationBar, NavigationHistory
from .lazytree import LazyTreeModel, TreeNode
from .tables import QMultiLineDelegate, PropertyTableModel, QPropertyTable
from .configtables import ConfigColumn, ConfigAction, ConfigTab, ConfigTableModel, QConfigPanel
from .polling import QPollingPanel
from .editors import QCodeEditor, QSearchableEditor, QCompleterLineEdit
from .commands import QCommandCombo
from .attrprops import QAttributePropertyDialog
from .diagnostic import QRefresherDiagnostic
from .dialogs import QTableDialog, QTextDialog
from .base import tango_widgets, freeze_widgets
# Legacy widgets
from .attribute import QAttribute
from .executer import QCommandExecuter
from .digitdial import QDigitDial
from .led import QStatusLed
from .windows import QTangoMainWindow, QTangoDialog, TangoEvents2Qt, WindowScaling
from .treeitems import TreeItem, DeviceItem, AttributeItem, ServerItem
from .devicetree import QDeviceTree
from .attributetree import QAttributeTree

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
    "ConfigColumn", "ConfigAction", "ConfigTab", "ConfigTableModel", "QConfigPanel", "QPollingPanel",
    "QCodeEditor", "QSearchableEditor", "QCompleterLineEdit",
    "QNumberComboSetter", "QStringComboSetter", "QCommandCombo", "QAttributePropertyDialog",
    "QRefresherDiagnostic", "QTableDialog", "QTextDialog", "tango_widgets", "freeze_widgets",
    "QAttribute", "QCommandExecuter", "QDigitDial", "QStatusLed", "QTangoMainWindow", "QTangoDialog",
    "TangoEvents2Qt", "WindowScaling", "TreeItem", "DeviceItem", "AttributeItem", "ServerItem",
    "QDeviceTree", "QAttributeTree",
]
