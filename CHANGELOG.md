# Changelog

## 0.2.0

### Qt5/Qt6 portability
- New `PyQTango.qt` compatibility module: one import point for Qt, binding chosen from the
  already-loaded binding, `PYQTANGO_QT_API`, or what is installed; helpers for the APIs that
  differ (`QAction`/`QShortcut` location, mouse positions, enum values, window flags, HiDPI).
- All existing modules import Qt from `PyQTango.qt` and use scoped enums; they run unchanged on
  PyQt5 5.15 and PyQt6.
- `import tango` replaces the deprecated `import PyTango`; `print` diagnostics replaced by `logging`.
- `WindowScaling` no longer double-scales when Qt's own HiDPI scaling is active (Qt6, or Qt5 with
  `make_application`).

### New: event-aware models (`PyQTango.models`)
- `TangoAttributeModel` shared per attribute: stateless change/configuration event subscriptions,
  automatic polling fallback through `AttributeRefresher`, asynchronous writes, reference-counted
  release with a grace period, reconnection retries.
- `TangoDeviceModel` (State/Status models, command list, asynchronous `execute`, info).
- `run_async`, `Job` (progress, cancel, error collection), `error_history()`.

### New widgets (`PyQTango.widgets`)
- `QValueLabel`, `QStateLabel`, `QStatusViewer`, `QStateStatusViewer`, `QWheelEditor`,
  `QAttributeWheelEditor`, `QBooleanSetter`, `QEnumSetter`, `QStringSetter`, `QNumberSetter`,
  `QArraySetter`, `QScalarListViewer`, `QErrorDialog`, `QErrorHistory`, `QJobProgressDialog`,
  `QConsole`, `QNavigationBar`, `LazyTreeModel`, `QPropertyTable`, `QMultiLineDelegate`,
  `QCodeEditor`, `QSearchableEditor`, `QCompleterLineEdit`.
- `PyQTango.core`: port of Jive's argument parser (all Tango types, `zeros(n)`, images,
  `DevEncoded`, long/double-string arrays, pipe blobs), name/wildcard helpers, formatting,
  ATK colours, `ErrorRecord`, thread-safe `ProxyCache`.

### Changed existing widgets (same public API)
- `QAttribute` is built on the shared model: no blocking calls, works without change events,
  supports READ_WITH_WRITE and WRITE attributes, shows spectra/images as text, applies
  configuration changes live. It no longer unsubscribes in `__del__`; call `shutdown()` or
  delete the widget.
- `QCommandExecuter` accepts every argument type (Jive syntax), runs asynchronously, shows the
  full error stack and the argument syntax as a placeholder; new `executed` signal.
- `QDeviceTree` no longer opens the database when a device list is given.
- `TangoUtil.getAllRegisteredDevices` uses one query when the database allows it;
  liveness checks use threads instead of processes.

### Fixes
- `DeviceByClassTreeModel` duplicate check used the wrong dictionary.
- `AttributeTree` image icon branch tested `SPECTRUM` twice; missing `genattr.png` replaced.
- `QAttribute` read `self.__unit` before setting it when parsing limits.
- `QCommandExecuter` raised `UnboundLocalError` on unhandled argument types.

### Notes
- Pipes: the PyTango 10.3 used for testing no longer provides `read_pipe`/`write_pipe`; the pipe
  syntax in `core.argparser` is kept for older PyTango versions.
