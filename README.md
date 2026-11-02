# PyQTango

Library of event-aware Tango widgets for Python and Qt. Version 0.2 runs on
**PyQt5** (default, compatible with the existing lab GUIs) and **PyQt6**.

## Install

```
pip install .            # PyQt5 (default)
pip install .[pyqt6]     # also install PyQt6
```

Requires Python ≥ 3.7, PyTango ≥ 9.5 and numpy.

## Choosing the Qt binding

PyQTango imports Qt only through `PyQTango.qt`. The binding is chosen, in order:

1. the binding your application already imported (`PyQt5` or `PyQt6`);
2. the `PYQTANGO_QT_API` environment variable (`pyqt5` or `pyqt6`);
3. PyQt5 if installed, otherwise PyQt6.

An existing PyQt5 GUI therefore keeps working unchanged, and only one binding is
ever loaded in a process.

## Writing code that also runs on PyQt6

Use these rules in PyQTango and in applications built on it. Code that follows
them runs unchanged on both bindings; moving a GUI to PyQt6 then only needs
regenerating its `.ui` files with `pyuic6` (or loading them with
`PyQTango.qt.load_ui`).

| Do | Instead of |
| --- | --- |
| `from PyQTango.qt import QtCore, QtGui, QtWidgets, Qt, Signal, Slot, Property` | `from PyQt5 import ...`, `pyqtSignal`, `pyqtSlot`, `pyqtProperty` |
| Scoped enums: `Qt.AlignmentFlag.AlignLeft`, `QtWidgets.QSizePolicy.Policy.Expanding`, `QtGui.QIcon.Mode.Normal` | `Qt.AlignLeft`, `QSizePolicy.Expanding`, `QIcon.Normal` |
| `dialog.exec()`, `app.exec()`, `menu.exec()` | `exec_()` |
| `from PyQTango.qt import QAction, QActionGroup, QShortcut` | `QtWidgets.QAction` (moved to `QtGui` in Qt6) |
| `event_pos(event)`, `event_global_pos(event)` | `event.pos()`, `event.globalPos()` |
| `checkbox.isChecked()` | comparing `state == Qt.Checked` (an int in Qt5, an enum in Qt6) |
| `enum_value(flag)` when an int is needed | `int(flag)` |
| `no_window_flags()` | `Qt.WindowFlags()` (removed in Qt6) |
| `make_application(argv)` (enables HiDPI on Qt5 as Qt6 does) | `QApplication(argv)` |
| `QRegularExpression`, `QScreen`, `fontMetrics().horizontalAdvance()` | `QRegExp`, `QDesktopWidget`, `fontMetrics().width()` |

`import tango` replaces the deprecated `import PyTango`.

## Event-aware models

Widgets never call Tango themselves. They bind to shared models that subscribe
to Tango events and fall back to polling when the server does not push events:

```python
from PyQTango.qt import make_application
from PyQTango.widgets import QValueLabel, QAttributeWheelEditor, QStateStatusViewer

app = make_application()
value = QValueLabel()
value.setModel("sys/tg_test/1/double_scalar")        # read + quality + unit
wheel = QAttributeWheelEditor()
wheel.setModel("sys/tg_test/1/double_scalar_w")      # writes on each click
header = QStateStatusViewer()
header.setDevice("sys/tg_test/1")
```

* One `TangoAttributeModel` per attribute is shared by all widgets
  (`PyQTango.models.attribute_model(name)`).
* It subscribes to `CHANGE_EVENT` and `ATTR_CONF_EVENT` (stateless). Without
  change events it is read by the shared `AttributeRefresher` (default 1 s, one
  `read_attributes` per device), and switches back to events as soon as they
  arrive. Configuration changes (label, unit, format, limits) update the widgets live.
* The last widget to detach unsubscribes after a 2 s grace period.
* Tango calls run in a worker pool (`run_async`, `Job`); the GUI never blocks.
* Errors are collected in `PyQTango.models.error_history()` and shown by
  `QErrorHistory`; `QErrorDialog` shows a full `DevFailed` stack.

Setters show the set point when it is meaningful (memorized attribute, write-only
attribute, or already written by this process) and the read value otherwise;
set `setPointMode = "always"` for the ATK behaviour.

## Widgets

| Widget | Purpose |
| --- | --- |
| `QValueLabel` | Formatted value with unit, quality marker, tooltip with the configuration |
| `QStateLabel`, `QStatusViewer`, `QStateStatusViewer` | State (ATK colours) and status |
| `QWheelEditor`, `QAttributeWheelEditor` | Compact per-digit wheel editor (mouse, wheel, keyboard) |
| `QBooleanSetter`, `QEnumSetter`, `QStringSetter`, `QNumberSetter`, `QArraySetter` | Setters; `create_viewer()` / `create_setter()` pick one from a configuration |
| `QScalarListViewer` | Label / value / setter / unit grid for a device (operator/expert view) |
| `QAttribute`, `QCommandExecuter` | 0.1 widgets, now on the shared models (same API) |
| `QErrorDialog`, `QErrorHistory`, `QJobProgressDialog` | Errors and long operations |
| `QConsole`, `QNavigationBar`, `NavigationHistory` | Test-panel console, back/forward/search bar |
| `LazyTreeModel`, `TreeNode` | Asynchronous lazy tree model |
| `QPropertyTable`, `PropertyTableModel`, `QMultiLineDelegate` | Property tables with multi-line values |
| `QCodeEditor`, `QSearchableEditor`, `QCompleterLineEdit` | Editors |
| `QDigitDial`, `QStatusLed`, `QDeviceTree`, `QAttributeTree` | 0.1 widgets, ported |

Qt-free helpers live in `PyQTango.core`: Jive's argument parser
(`parse_command_argin`, `parse_attribute_value`), Tango name and wildcard
helpers, value formatting, ATK colours, `ErrorRecord`, `ProxyCache`.

Run `python examples/gallery.py sys/tg_test/1` for a demo.

## Tests

The tests start a real device server (`tango.test_context`) and run on both bindings:

```
PYQTANGO_QT_API=pyqt5 PYTEST_QT_API=pyqt5 QT_QPA_PLATFORM=offscreen pytest -o qt_api=pyqt5
PYQTANGO_QT_API=pyqt6 PYTEST_QT_API=pyqt6 QT_QPA_PLATFORM=offscreen pytest -o qt_api=pyqt6
```

or `tox` (environments `pyqt5` and `pyqt6`). A fixture fails any test in which a
Tango proxy is requested from the GUI thread.

See `CHANGELOG.md` for the changes from 0.1.
