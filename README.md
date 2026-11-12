# PyQTango

Library of event-aware Tango widgets for Python and Qt. Version 0.2 runs on
**PyQt5** (default, compatible with the existing lab GUIs) and **PyQt6**.

## Install

```
pip install .            # PyQt5 (default)
pip install .[pyqt6]     # also install PyQt6
pip install .[plot]      # pyqtgraph, for QTangoChart and QImageViewer
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

A widget can stop following its model without unbinding: `setFrozen(True)`
(a window's "Stop refreshing"; `refreshOnce()` lets one value through, and a
model whose users are all frozen is no longer polled) or
`setPauseWhenHidden(True)` (a tab reads its attribute only while shown).
`freeze_widgets(window, on)` applies the first to every Tango widget of a window.
Reads of one device never overlap, and when a grouped read times out because of
one slow attribute, that attribute is polled on its own (at most every 10 s)
while the others keep their group.
Subscriptions are set up at most 16 at a time (`subscription_limiter()`, with
progress), so a window following hundreds of devices opens at once and fills in.
A model can use its own timeout (`timeout_ms`; Starters use 1 s) without
changing the shared proxy's.

Setters show the set point when it is meaningful (memorized attribute, write-only
attribute, or already written by this process) and the read value otherwise;
set `setPointMode = "always"` for the ATK behaviour. `setNeedsConfirmation(True)`
asks before each write, and a failed write puts the setter back to the device value.

## Widgets

| Widget | Purpose |
| --- | --- |
| `QValueLabel` | Formatted value with unit, quality marker, tooltip with the configuration |
| `QStateLabel`, `QStatusViewer`, `QStateStatusViewer` | State (ATK colours) and status |
| `QWheelEditor`, `QAttributeWheelEditor` | Compact per-digit wheel editor (mouse, wheel, keyboard) |
| `QBooleanSetter`, `QEnumSetter`, `QStringSetter`, `QNumberSetter`, `QArraySetter` | Setters; `create_viewer()` / `create_setter()` pick one from a configuration |
| `QBooleanLabel`, `QSwitchButton`, `QSwitchSetter` | Boolean label / tick viewer, on/off switch and switch setter with optional confirmation (ATK 10) |
| `QScalarListViewer` | Label / value / setter / unit / property button grid for a device (operator/expert view, read-only); a combo setter when the attribute property `values` lists the allowed values |
| `QNumberComboSetter`, `QStringComboSetter` | Setters choosing among allowed values (ATK combo editors) |
| `QCommandCombo` | Run any command of a device: void commands at once, others with an argument prompt (Jive syntax), result popup |
| `QAttributePropertyDialog` | ATK's attribute property editor: label, range, alarms, warnings, delta t/val, format, unit; read-only flag |
| `QRefresherDiagnostic` | What every live model does: events or polling, period, source, last update, counts, last error |
| `QAttribute`, `QCommandExecuter` | 0.1 widgets, now on the shared models (same API) |
| `QErrorDialog`, `QErrorHistory`, `QJobProgressDialog` | Errors and long operations |
| `QConsole`, `QNavigationBar`, `NavigationHistory` | Test-panel console, back/forward/search bar |
| `QTangoChart` (`PyQTango.widgets.plot`, needs pyqtgraph) | ATK JLChart: Y1/Y2 axes, index, numeric or time X axis with display duration, per-curve style (colour, width, line style, 11 markers, bars, fill, transform), autoscale or fixed, log, zoom and Zoom back, and the JLChart menu: Chart properties, Data View properties, Save/Load data File (CSV), Show table, Show statistics, Print Chart, Save a snapshot (PNG/SVG) |
| `QTrend`, `QBooleanTrend`, `TrendBuffer` (`.trend`) | ATK Trend and BooleanTrend: selection tree (none/X/Y1/Y2), one-day ring buffers, 5-minute display, refresh period and source, start/stop, off line mode, reset, min/max alarm lines, XY mode, JSON settings with ATK key:value import |
| `QSpectrumViewer`, `QStringSpectrumViewer`, `QStateSpectrumViewer`, `QBooleanSpectrumViewer` (`.spectrum`) | Spectra: chart (read and set point; X axis from XminAttribute/XmaxAttribute or Xmin/Xmax) or lists |
| `QImageViewer`, `QStringImageViewer`, `QRawImageViewer` (`.image`) | Images: colour maps, levels, histogram, profiles, value under the cursor, Save as PNG/TIFF/CSV; string images as a table; DevEncoded JPEG, GRAY8, GRAY16, RGB24 |
| `QBlackBoxView`, `QBlackBoxDialog` (`.blackbox`) | A device's black box: filter, auto-update, Top counts |
| `QPollingProfiler`, `QPollingProfilerDialog` (`.profiler`) | Polling profile from `DevPollStatus`: duration, drift and history charts |
| `QTableDialog`, `QTextDialog` (`.dialogs`) | Result tables (filter, numeric sort, copy, save) and long texts (loaded in chunks, find, save) |
| `QStartupLevelDialog`, `QServerPickerDialog`, `QLevelWalkerDialog` (`.levels`) | Starter dialogs: startup level and controlled flag, servers to start on a host, start/stop by level with a confirm per level and a results table |
| `state_icon`, `host_icon`, `ball_icon` (`.icons`) | Device and host state icons |
| `LazyTreeModel`, `TreeNode` | Asynchronous lazy tree model |
| `QPropertyTable`, `PropertyTableModel`, `QMultiLineDelegate` | Property tables with multi-line values |
| `QCodeEditor`, `QSearchableEditor`, `QCompleterLineEdit` | Editors |
| `QDigitDial`, `QStatusLed`, `QDeviceTree`, `QAttributeTree` | 0.1 widgets, ported |

Qt-free helpers live in `PyQTango.core`: Jive's argument parser
(`parse_command_argin`, `parse_attribute_value`), Tango name and wildcard
helpers, value formatting, ATK colours, `ErrorRecord`, `ProxyCache`, the
Starter formats (`core.starter`) and start/stop by level (`core.levels.LevelWalker`).
`PyQTango.models.StarterModel` follows a Starter (state, servers, commands).

Run `python examples/gallery.py sys/tg_test/1` for a demo.

## Application name on macOS

The macOS menu bar takes the application's name from the process's bundle, so a script shows
"Python" there whatever `setApplicationName` says. `make_application(argv, name="My app")`
writes the name into the bundle's information before Qt starts, so the menu bar, the Dock and
the About and Quit items show it.

## Finding GUI stalls

While the GUI thread is busy Qt cannot repaint, so a window keeps showing old content (for
instance the controls of the tab just left) and ignores clicks. Set `PYQTANGO_STALL_MS` to report
every stall longer than that many milliseconds on standard error, with the GUI thread's stack at
that moment (any application made with `PyQTango.qt.make_application`):

```
PYQTANGO_STALL_MS=200 pyjive
```

No report while old content stays on screen means the GUI thread was free and the display did
not show what Qt painted (a compositor or remote-display problem rather than PyQTango's).

## Tests

The tests start a real device server (`tango.test_context`) and run on both bindings:

```
PYQTANGO_QT_API=pyqt5 PYTEST_QT_API=pyqt5 QT_QPA_PLATFORM=offscreen pytest -o qt_api=pyqt5
PYQTANGO_QT_API=pyqt6 PYTEST_QT_API=pyqt6 QT_QPA_PLATFORM=offscreen pytest -o qt_api=pyqt6
```

or `tox` (environments `pyqt5` and `pyqt6`). A fixture fails any test in which a
Tango proxy is requested from the GUI thread.

See `CHANGELOG.md` for the changes from 0.1.
