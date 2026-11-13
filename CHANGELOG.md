# Changelog

## Unreleased

- Widget documentation in `docs/`: every widget with an example and a screenshot;
  `docs/make_screenshots.py` renders the images again.

## 0.3.1

- `TangoUtil.getAllLiveDevices()`, `getAllLiveAttributes()` and `getAllLiveDevicesByClass()`
  with a `dbhost`/`port` now check and read the devices on that database (they used the
  default `TANGO_HOST`, so every device looked dead and `QAttributeTree(dbhost, port)` was
  empty). `getAllLiveAttributes()` then returns fully qualified attribute names;
  `checkDevicesAreLive()` takes `dbhost`/`port` too.
- `QTangoChart` shows axis values as they are: pyqtgraph's automatic rescaling of small
  ranges ("Signal (x0.001)" with ticks of 700 for 0.7) is off.
- `QTableDialog` and `QTextDialog` are exported from `PyQTango.widgets`, as its docstring said.

## 0.3.0

Removed `QArchivedAttributeTree` (tree of the attributes of the old HDB archiving system, no
longer used).

The 0.1 widgets moved into `PyQTango.widgets`, next to the new ones: `QAttribute`
(`widgets/attribute.py`), `QCommandExecuter` (`executer.py`), `QDigitDial` (`digitdial.py`),
`QStatusLed` (`led.py`), `QTangoMainWindow`, `QTangoDialog`, `TangoEvents2Qt` and `WindowScaling`
(`windows.py`), `QDeviceTree` (`devicetree.py`), `QAttributeTree` (`attributetree.py`) and the
tree items (`treeitems.py`). `TangoUtil` moved to `PyQTango.core.tangoutil` and `get_image_path`
to `PyQTango.widgets.icons`. `from PyQTango import ...` works as before, and `PyQTango.TangoUtil`
and `PyQTango.TangoWindows` are still there; the old module paths (`PyQTango.QAttribute`,
`PyQTango.config`, ...) are gone.

Black box and polling profiler for PyJive's Phase 6 (Astor tools):

- `PyQTango.core.blackbox` (no Qt): `parse_black_box()` of `black_box()` lines into date,
  operation, name, source, host and process (Tango 10 formats); `BlackBox` keeps records across
  reads and flags reads that no longer overlap; `top()` counts; `span_text()`.
- `PyQTango.core.pollstatus` (no Qt): `PolledElement` and `parse_poll_status()` of `DevPollStatus`
  (period, ring depth, reading time, time since update, deltas, drifts, Astor's FAULT rule);
  `read_poll_status()`.
- `PyQTango.widgets.blackbox`: `QBlackBoxView` (filter by column, auto-update, Top, raw line),
  `QBlackBoxDialog`, `QTopDialog`.
- `PyQTango.widgets.profiler`: `QPollingProfiler` (Duration, Polling Drift and History charts, table,
  auto-update), `QPollingProfilerDialog`.
- `make_application(argv, name=...)` sets the application name and, on macOS, the name in the
  menu bar and the Dock, which otherwise read "Python" or "python3.12"
  (`PyQTango.core.macos.set_app_name`: PyObjC when installed, else `ctypes`).
- `PYQTANGO_STALL_MS`: `PyQTango.core.stalls.StallWatchdog` reports, with the GUI thread's
  stack, each time the GUI thread is too busy to repaint for longer than that many milliseconds
  (started by `make_application`). A diagnostic for windows that keep showing old content.
- Fixed: a job's progress dialog no longer fails when its window is closed while the job runs.
- `PyQTango.core.proxies.keep_alive(proxy)`: keeps a proxy until the process ends. Destroying a
  DeviceProxy while a failing stateless subscription retries can deadlock (PyTango #302); the
  cache never destroys its proxies, and code that needs a proxy of its own parks it here. The
  test suites keep the proxies they create alive the same way.

Starters, levels and host widgets for PyJive's Phase 5 (Hosts tab):

- `PyQTango.core.starter` (no Qt): `ServerLine` and `parse_servers()` for the Starter's
  `Servers` attribute, `host_state()` / `worst_state()` with the Starter's state rules,
  `parse_starter_log()`, `parse_statistics()`, `split_server_log()`, `starter_device()`,
  `host_of_starter()`.
- `PyQTango.core.levels`: `LevelWalker`, start or stop by startup level on several hosts
  (level order, pause between levels, confirm per level with yes / no / all / cancel, results
  per host and level). `levels_in_use()`.
- `PyQTango.models.starter`: `StarterModel` (State always; Servers and Status only while
  watched, 1 s timeout, 2.5 s polling), Starter commands in the background (`start_server`,
  `stop_server`, `hard_kill`, `start_level`, `stop_level`, `update_servers_info`,
  `reset_statistics`, `read_log`), `starter_model()` registry.
- `SubscriptionLimiter` / `subscription_limiter()`: at most 16 event subscriptions set up at a
  time, with progress, so hundreds of devices load without blocking. Attribute models take a
  `timeout_ms`; `ProxyCache.get(name, timeout_ms=)` keeps a separate proxy per timeout and
  the refresher groups reads by source and timeout.
- `DatabaseService.starters()` (one SQL query for every Starter's `HostCollection` and
  `HostUsage`, else per device) and `host_servers_info(host)`.
- Widgets: `PyQTango.widgets.icons` (`state_icon`, `host_icon`, `ball_icon`),
  `PyQTango.widgets.dialogs` (`QTableDialog` with filter, numeric sort, copy and save;
  `QTextDialog` loading long text in chunks, with find and save) and `PyQTango.widgets.levels`
  (`QStartupLevelDialog`, `ask_levels_policy`, `QServerPickerDialog`, `QLevelWalkerDialog`).
- `state_colors()` accepts state names. `LazyTreeModel.node_changed(node)` repaints one node.
- Tests: `tests/starterserver.py`, a fake Starter (Servers, State, Status, log, DevStart,
  DevStop, start and stop by level, HardKill) and `dbserver.setup_hosts()`, `add_starters()`,
  `start_starter()`.

Charts, trends and viewers for PyJive's Phase 4 (MonitorDevice and Trend):

- `QTangoChart` is now the full ATK JLChart port: second Y axis, time axis with a display
  duration, `DataView` styles (colour, width, 5 line styles, 11 markers, line or bar, fill,
  A0 + A1*y + A2*y² transform), `AxisSettings` (visible, autoscale with margin or fixed range,
  "Autoscale once", log, grid, title), zoom history with Zoom back, rectangle zoom, and the
  JLChart menu (Chart properties, Data View properties, Save/Load data File as CSV, Show table,
  Show statistics over the visible window, Zoom back, Print Chart, Save a snapshot as PNG or
  SVG). `settings()` / `apply_settings()`. The 0.3 API (`set_curve`, `curve_data`, ...) is kept.
- `PyQTango.widgets.chartdialogs`: `QChartPropertiesDialog`, `QDataViewDialog` (applied live),
  `QChartTableDialog`, `QChartStatisticsDialog`, `QColorButton`.
- `PyQTango.widgets.trend`: `TrendBuffer`, `QTrend`, `QBooleanTrend` with ATK's toolbar, menu and
  attribute menu, JSON settings and `parse_atk_settings()` for ATK trend files.
- `PyQTango.widgets.spectrum`: `QSpectrumViewer` and the string, state and boolean list viewers.
- `PyQTango.widgets.image`: `QImageViewer` (moved from `plot`, still importable there) with colour
  maps, fixed or automatic levels, profiles and Save; `QStringImageViewer`; `QRawImageViewer`
  and `decode_encoded()`.
- `QCommandCombo`, `QAttributePropertyDialog`, `QRefresherDiagnostic`, `QNumberComboSetter`,
  `QStringComboSetter` (`create_setter(..., values=)`), property buttons, `setReadOnly()` and
  allowed-values combos in `QScalarListViewer` (DevEncoded scalars are left to image viewers).
- Widgets: `setFrozen()` / `refreshOnce()`, `pauseWhenHidden`, `tango_widgets()`,
  `freeze_widgets()`. Models: `suspend()` / `resume()` (the refresher skips a model whose users
  are all suspended), `set_source()`, counters for the diagnostic (`n_events`, `n_updates`,
  `n_errors`, `last_update`). `ProxyCache.get(name, source=)` gives a proxy reading from another
  source; `proxies_of(name)`.
- Refresher: reads of one device never overlap (a lock per device); a grouped read that times
  out is retried attribute by attribute, and the attributes that time out alone are polled on
  their own afterwards, at most every 10 s (`SOLO_PERIOD_MS`); one that then reads fine alone
  goes back to its device group.
- Fixed: Tango callbacks now go through one long-lived event bridge, so an event that arrives
  after a model was deleted no longer emits on a destroyed QObject (a segmentation fault seen
  with PyQt6).
- Subscriptions use `sub_mode=EventSubMode.Stateless` where PyTango offers it (10.3 deprecates
  `stateless=True`).

- `PyQTango.widgets.confirm`: `QMultiChangeDialog` and `confirm_changes()` (Jive's multiple change
  confirmation); `QConfigPanel` uses it for changes on several devices (`confirm_changes` hook).
- `DatabaseService`: `device_property_selection`, `device_attribute_property_selection` (one SQL
  query, or per device without `DbMySqlSelect`) and `find_usage` (`__SubDevices`).

- Tests can run on MariaDB with the C++ Databaseds: set `TANGO_TEST_MARIADB` (see
  `tests/dbserver.py`); each test module gets its own empty schema, dropped afterwards.

- Removed pipe support: `ArgParser.pipe()` and the pipe blob syntax are gone (Tango 10 removed
  pipes).

- `PyQTango.widgets.plot`: `QTangoChart` (named curves against an index or x values, legend,
  autoscale) and `QImageViewer` (2D arrays with a colour bar and the value under the cursor),
  on pyqtgraph (`pip install PyQTango[plot]`), following the binding PyQTango selected.
- `PyQTango.qt.fixed_font()`: a fixed-pitch font even where `QFontDatabase`'s fixed font is
  proportional (offscreen platform, minimal desktops); used by `QConsole` and the editors.
- `DatabaseService`: `add_device`, `delete_device`, `add_server`, `delete_server`,
  `rename_server`, `unexport_server`, `unexport_device`, `put_device_alias`,
  `delete_device_alias` (refused when read-only). `LazyTreeModel.insert_child`.

- `DatabaseService`: class, class attribute, device attribute and free property writes and
  deletes; `*_property_history` returning `PropertyHistory` entries (deletions included).
- `PropertyTableModel` compares each value with the loaded one: a value edited back is no
  longer "modified"; modified values are bold and tinted with the stored value as tooltip;
  `revert()`, `set_value()`, `row_of()`, `names()`, `stored()`; read-only refuses edits;
  `row_editable(name)` limits editing per row.
- Finished `QConfigPanel` jobs refresh only when the panel still shows the same devices.

- `QConfigPanel`'s Refresh button has the reload icon and the tooltip "Reload this panel".

- `DatabaseService.device_table()`: (server, class, device) of every device in one SQL query
  (PyJive's search), None without `DbMySqlSelect`.

- `QPropertyTable` recomputes row heights when a column is resized, so a name that wrapped
  while its column was narrow no longer leaves a row twice as tall.

- `QConfigPanel` and `ConfigTableModel` (`PyQTango.widgets.configtables`): tabbed configuration
  tables with pending edits (bold, tinted, tooltip with the stored value), check-box columns,
  Apply on several devices in a progress `Job`, Revert, context-menu actions and a read-only mode.
- `QPollingPanel` (Jive's device polling panel, for PyJive and the Astor polling manager) and
  `PyQTango.core.polling` (polling status parsing, poll/stop poll, `poll_old_factor` and
  `poll_ring_depth`, reset of the stored configuration).
- `DatabaseService`: `put_device_property`, `delete_device_property`,
  `delete_device_attribute_property`, `attribute_alias`, `put_attribute_alias`,
  `delete_attribute_alias` (all writes refused when read-only).

- `PyQTango.core.db.DatabaseService` (moved from the PyJive plan's `pyjive.core.db`): typed
  database access, fully qualified names, `DbMySqlSelect` decoding with a one-time probe and API
  fallbacks, tolerant server info (databases that store blanks), Starter collections, read-only
  guard. Tested against the PyTango SQLite database server.
- `run_async(..., owner=widget)` drops results that arrive after the widget was deleted;
  `LazyTreeModel` uses it, and `ensure_loaded`/`find_path` now finish when a load fails.
- `PyQTango.qt.is_deleted()` and `sip`.
- `python -m PyQTango.qtcheck` and `PyQTango.qtcheck.platform_problems()`: explain why Qt cannot
  open a window on Linux (no display, overridden plugin path, missing xcb libraries with the
  Debian and RHEL package names) before Qt aborts the process.


## 0.2.1

Follows the widget changes of ATK 10.0.6 (ATK 9.4.15 to 10.0.6).

### New widgets
- `QBooleanLabel`: DevBoolean viewer, `displayMode` "label" (ATK `BooleanScalarLabelViewer`:
  label on green/white, red on error) or "tick" (ATK `BooleanScalarTickViewer`); colours and
  true/false texts configurable; optional `hideUntilValid`.
- `QSwitchButton`: painted, animated on/off switch (ATK `SwitchButton`), keyboard accessible,
  optional Yes/No confirmation; `switched(bool)` only for user toggles.
- `QSwitchSetter`: title + switch bound to a DevBoolean attribute (ATK
  `BooleanScalarSwitchButton`): confirmation, true/false titles, quality colour, disabled on
  error, toggle dropped when the value changes while the question is open.

### Changed
- Setters: `setNeedsConfirmation()` / `setConfirmMessage()` ask before writing (ATK
  `BooleanScalarCheckBoxViewer` and `EnumScalarComboEditor`); after a failed write the setter
  shows the device value again (ATK 10 set-error listeners).
- `QStringSetter.setWriteOnEdit()` writes on every keystroke (ATK `updateImmediately`).
- `QErrorDialog`: long or multi-line messages are shown in a capped, scrollable area.


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
