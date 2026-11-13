# PyQTango widget documentation

PyQTango is a library of Tango widgets for PyQt5 and PyQt6. Each widget binds to
an attribute or a device by name and keeps itself up to date: it follows Tango
change events when the server pushes them and is polled otherwise, it never
blocks the GUI, and every widget showing the same attribute shares one
subscription.

These pages describe each widget with an example and a screenshot. For installing,
choosing the Qt binding and the PyQt5/PyQt6 coding rules, see the
[main README](../README.md).

## Quick start

```python
import sys
from PyQTango.qt import QtWidgets, make_application
from PyQTango.widgets import QStateStatusViewer, QValueLabel, QAttributeWheelEditor

app = make_application(sys.argv, name="Laser")

window = QtWidgets.QWidget()
layout = QtWidgets.QFormLayout(window)

header = QStateStatusViewer()
header.setDevice("lab/laser/1")                  # State and Status of a device
layout.addRow(header)

power = QValueLabel()
power.setModel("lab/laser/1/power")              # read value, unit and quality
layout.addRow("Power", power)

current = QAttributeWheelEditor()
current.setModel("lab/laser/1/current")          # writes on every click
layout.addRow("Current", current)

window.show()
sys.exit(app.exec())
```

## Binding widgets

* **Attribute widgets** take a full attribute name with `setModel("dom/fam/mem/attr")`.
  `setModel(None)` unbinds the widget. In Qt Designer, set the `modelName` property instead.
  A name can carry a host, as in `tango://host:10000/dom/fam/mem/attr`.
* **Device widgets** take a device name with `setDevice("dom/fam/mem")`, or the
  `deviceName` property in Designer.
* **Charts, trends and tools** are built with the names they show (see their pages).

Behind every attribute widget is one shared `TangoAttributeModel` per attribute
(`PyQTango.models.attribute_model(name)`). The model reads the configuration,
subscribes to events, falls back to polling, and unsubscribes 2 s after the last
widget lets go. Widgets react to it through four hooks: `on_config`, `on_value`,
`on_error` and `on_write_done`.

Two switches stop a widget from following its model without unbinding it:

```python
from PyQTango.widgets import freeze_widgets

freeze_widgets(window, True)        # "Stop refreshing": values are kept, not shown
label.refreshOnce()                 # let one fresh value through
freeze_widgets(window, False)

tab_label.setPauseWhenHidden(True)  # read only while the tab is visible
```

Every attribute widget shows a tooltip with the attribute name, label,
description, unit, limits, quality and the last error.

## Pages

| Page | Widgets |
| --- | --- |
| [Attribute viewers](attribute-viewers.md) | `QValueLabel`, `QStateLabel`, `QStatusViewer`, `QStateStatusViewer`, `QBooleanLabel`, `create_viewer` |
| [Setters](setters.md) | `QNumberSetter`, `QStringSetter`, `QBooleanSetter`, `QEnumSetter`, `QArraySetter`, `QNumberComboSetter`, `QStringComboSetter`, `QWheelEditor`, `QAttributeWheelEditor`, `QSwitchButton`, `QSwitchSetter`, `create_setter` |
| [Device widgets](device-widgets.md) | `QScalarListViewer`, `QCommandCombo` |
| [Charts, trends, spectra and images](charts.md) | `QTangoChart` and its dialogs, `QTrend`, `QBooleanTrend`, `QSpectrumViewer`, `QStringSpectrumViewer`, `QStateSpectrumViewer`, `QBooleanSpectrumViewer`, `QImageViewer`, `QStringImageViewer`, `QRawImageViewer` |
| [Dialogs and tools](tools.md) | `QAttributePropertyDialog`, `QRefresherDiagnostic`, `QErrorDialog`, `QErrorHistory`, `QBlackBoxView`, `QPollingProfiler`, `QPollingPanel`, `QConfigPanel`, `QJobProgressDialog`, `QTableDialog`, `QTextDialog`, `QMultiChangeDialog`, `QStartupLevelDialog`, `QServerPickerDialog`, `QLevelWalkerDialog` |
| [Building blocks](building-blocks.md) | `QConsole`, `QNavigationBar`, `LazyTreeModel`, `QPropertyTable`, `QCodeEditor`, `QSearchableEditor`, `QCompleterLineEdit`, icons and colours, writing your own Tango widget |
| [Legacy widgets](legacy.md) | `QAttribute`, `QCommandExecuter`, `QDigitDial`, `QStatusLed`, `QTangoMainWindow`, `QTangoDialog`, `QDeviceTree`, `QAttributeTree` |

## Imports

Most widgets come from `PyQTango.widgets` (and from `PyQTango` itself). The
widgets that need pyqtgraph (`pip install .[plot]`) are imported from their
modules, so that applications without charts do not need it:

```python
from PyQTango.widgets import QValueLabel, QScalarListViewer      # no pyqtgraph needed
from PyQTango.widgets.plot import QTangoChart, DataView           # pyqtgraph
from PyQTango.widgets.trend import QTrend, QBooleanTrend
from PyQTango.widgets.spectrum import QSpectrumViewer
from PyQTango.widgets.image import QImageViewer
from PyQTango.widgets.profiler import QPollingProfilerDialog
```

## Screenshots

The images were rendered by [`make_screenshots.py`](make_screenshots.py) from a
small "laser" device (`lab/laser/1`, defined in that script) running against the
test database of `tests/`. They use the Qt Fusion style; on your desktop the
widgets take your platform style. To render them again:

```
PYQTANGO_QT_API=pyqt6 QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=2 python docs/make_screenshots.py
python docs/make_screenshots.py trend image      # only some of them
```
