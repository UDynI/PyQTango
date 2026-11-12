# -*- coding: utf-8 -*-
"""
Tabbed configuration tables (Jive's polling, event and attribute-config panels).

A :class:`QConfigPanel` shows one table per tab. The first column names a row
(an attribute, a command, a setting); the other columns are values the user
edits in place, with check boxes for boolean columns. Edits stay pending,
shown in bold on a tinted background, until **Apply** writes them, on every
selected device, in a background :class:`~PyQTango.models.Job` with progress.
**Revert** drops them, **Refresh** reads the device again.

Subclasses implement two worker-thread methods:

* ``load(dbs, device)`` returns ``{tab_key: [row dict, ...]}``; each row dict
  has ``"name"`` plus one entry per column key. Other keys of the returned
  dict are kept in ``self.data``.
* ``write(job, dbs, devices, pending, rows)`` applies ``pending``,
  ``{tab_key: [(row name, column key, new value), ...]}``; ``rows`` is a copy of
  every tab's rows, ``{tab_key: {row name: row dict}}``, taken when Apply was
  pressed (the worker must not read the Qt models).

``validate(pending)`` (GUI thread) may return an error text that stops Apply.
Right-click actions are declared per tab with :class:`ConfigAction`.
"""

from ..qt import QtCore, QtGui, QtWidgets, Qt, Signal
from ..models.worker import run_async, Job
from .progress import QJobProgressDialog

MODIFIED_BACKGROUND = "#fff1b8"
MODIFIED_FOREGROUND = "#000000"


class ConfigColumn(object):
    """ ``kind`` is "text" or "bool" (check box) """

    def __init__(self, key, header, kind="text", editable=True):
        self.key = key
        self.header = header
        self.kind = kind
        self.editable = editable


class ConfigAction(object):
    """ Context-menu entry: ``callback(tab_key, row_names)``.
    ``write`` actions are hidden when the panel is read-only; ``visible(panel, tab_key)``
    may hide the entry; ``text=None`` is a separator. """

    def __init__(self, text, callback=None, write=True, visible=None):
        self.text = text
        self.callback = callback
        self.write = write
        self.visible = visible


class ConfigTab(object):

    def __init__(self, key, title, columns, name_header="Attribute name", actions=()):
        self.key = key
        self.title = title
        self.columns = list(columns)
        self.name_header = name_header
        self.actions = list(actions)


class ConfigTableModel(QtCore.QAbstractTableModel):
    """ Rows of one tab with pending-edit tracking.

    ``edit_hook(model, row, key, value)`` runs after an edit, e.g. editing a
    polling period also ticks "Polled".
    """

    modifiedChanged = Signal(bool)

    def __init__(self, tab, parent=None):
        QtCore.QAbstractTableModel.__init__(self, parent)
        self.tab = tab
        self.columns = tab.columns
        self.editable = True
        self.edit_hook = None
        self._rows = []
        self._orig = []

    # -- Content ---------------------------------------------------------------------
    def set_rows(self, rows):
        self.beginResetModel()
        self._rows = [dict(r) for r in rows]
        self._orig = [dict(r) for r in rows]
        self.endResetModel()
        self.modifiedChanged.emit(False)

    def rows(self):
        return [dict(r) for r in self._rows]

    def names(self):
        return [r["name"] for r in self._rows]

    def row_of(self, name):
        for i, r in enumerate(self._rows):
            if r["name"] == name:
                return i
        return -1

    def value(self, row, key):
        return self._rows[row].get(key)

    def stored(self, row, key):
        return self._orig[row].get(key)

    def is_cell_modified(self, row, key):
        return self._rows[row].get(key) != self._orig[row].get(key)

    def set_value(self, row, key, value, hook=True):
        """ Change a cell (pending until Apply); returns True when it changed """
        if self._rows[row].get(key) == value:
            return False
        was = self.is_modified()
        self._rows[row][key] = value
        col = 1 + [c.key for c in self.columns].index(key)
        idx = self.index(row, col)
        self.dataChanged.emit(self.index(row, 0), idx)
        if hook and self.edit_hook is not None:
            self.edit_hook(self, row, key, value)
        if was != self.is_modified():
            self.modifiedChanged.emit(self.is_modified())
        return True

    def changes(self):
        """ [(row name, column key, new value)] in table order """
        out = []
        for r, o in zip(self._rows, self._orig):
            for c in self.columns:
                if r.get(c.key) != o.get(c.key):
                    out.append((r["name"], c.key, r.get(c.key)))
        return out

    def is_modified(self):
        return any(r != o for r, o in zip(self._rows, self._orig))

    def revert(self):
        self.set_rows(self._orig)

    # -- Qt model ----------------------------------------------------------------------
    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else 1 + len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.tab.name_header if section == 0 else self.columns[section - 1].header
        return None

    def _column(self, index):
        return self.columns[index.column() - 1] if index.column() > 0 else None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        col = self._column(index)
        if col is not None and col.editable and self.editable:
            f |= Qt.ItemFlag.ItemIsUserCheckable if col.kind == "bool" else Qt.ItemFlag.ItemIsEditable
        return f

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = self._column(index)
        if col is None:
            if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
                return row["name"]
            return None
        value = row.get(col.key)
        modified = self.is_cell_modified(index.row(), col.key)
        if col.kind == "bool":
            if role == Qt.ItemDataRole.CheckStateRole:
                return Qt.CheckState.Checked if value else Qt.CheckState.Unchecked
        elif role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return "" if value is None else str(value)
        if modified:
            if role == Qt.ItemDataRole.FontRole:
                f = QtGui.QFont()
                f.setBold(True)
                return f
            if role == Qt.ItemDataRole.BackgroundRole:
                return QtGui.QBrush(QtGui.QColor(MODIFIED_BACKGROUND))
            if role == Qt.ItemDataRole.ForegroundRole:
                return QtGui.QBrush(QtGui.QColor(MODIFIED_FOREGROUND))
            if role == Qt.ItemDataRole.ToolTipRole:
                stored = self.stored(index.row(), col.key)
                if col.kind == "bool":
                    stored = "yes" if stored else "no"
                return "Not applied yet (stored value: {0})".format(stored)
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        col = self._column(index)
        if col is None or not (col.editable and self.editable):
            return False
        if col.kind == "bool":
            if role != Qt.ItemDataRole.CheckStateRole:
                return False
            checked = value == Qt.CheckState.Checked or value == getattr(Qt.CheckState.Checked, "value", 2) \
                or value is True
            self.set_value(index.row(), col.key, bool(checked))
            return True
        if role != Qt.ItemDataRole.EditRole:
            return False
        self.set_value(index.row(), col.key, str(value).strip())
        return True


class QConfigPanel(QtWidgets.QWidget):
    """ Tabs of :class:`ConfigTableModel` tables with Refresh, Apply, Revert.

    Signals: ``loaded()`` after a read, ``applied()`` after a write job ended.
    """

    loaded = Signal()
    applied = Signal()

    #: Title shown above the tabs; the device (or device count) is appended
    base_title = "Configuration"

    def __init__(self, tabs, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.tabs = list(tabs)
        self.dbs = None
        self.devices = []
        self.data = {}
        self.read_only = False
        self.show_job_errors = True
        self.last_job = None
        self._token = 0
        self._write_buttons = []

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.title = QtWidgets.QLabel(self)
        f = self.title.font()
        f.setBold(True)
        self.title.setFont(f)
        layout.addWidget(self.title)
        self.tab_widget = QtWidgets.QTabWidget(self)
        layout.addWidget(self.tab_widget, 1)
        self.models = {}
        self.views = {}
        for tab in self.tabs:
            model = ConfigTableModel(tab, self)
            model.modifiedChanged.connect(self._update_buttons)
            model.dataChanged.connect(self._update_buttons)     # the count of changes too
            view = QtWidgets.QTableView(self)
            view.setModel(model)
            view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            view.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
            view.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
                                 | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed
                                 | QtWidgets.QAbstractItemView.EditTrigger.AnyKeyPressed)
            view.verticalHeader().setVisible(False)
            view.horizontalHeader().setStretchLastSection(True)
            view.setAlternatingRowColors(True)
            view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            view.customContextMenuRequested.connect(lambda pos, k=tab.key: self._context_menu(k, pos))
            self.models[tab.key] = model
            self.views[tab.key] = view
            self.tab_widget.addTab(view, tab.title)

        buttons = QtWidgets.QHBoxLayout()
        self.refresh_button = QtWidgets.QPushButton("Refresh", self)
        self.refresh_button.setIcon(self.refresh_button.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserReload))
        self.refresh_button.setToolTip("Reload this panel")
        self.refresh_button.clicked.connect(self._refresh_clicked)
        self.apply_button = QtWidgets.QPushButton("Apply", self)
        self.apply_button.clicked.connect(self.apply)
        self.revert_button = QtWidgets.QPushButton("Revert", self)
        self.revert_button.setToolTip("Drop the changes not applied yet")
        self.revert_button.clicked.connect(self.revert)
        for b in (self.refresh_button, self.apply_button, self.revert_button):
            buttons.addWidget(b)
        self._buttons = buttons
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.status = QtWidgets.QLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self._update_buttons()

    # -- Set-up --------------------------------------------------------------------------
    def add_button(self, text, slot, write=True, tooltip=None):
        """ Extra button before the stretch; ``write`` buttons are disabled when read-only """
        b = QtWidgets.QPushButton(text, self)
        b.clicked.connect(slot)
        if tooltip:
            b.setToolTip(tooltip)
        self._buttons.insertWidget(self._buttons.count() - 1, b)
        if write:
            self._write_buttons.append(b)
        self._update_buttons()
        return b

    def set_read_only(self, on):
        self.read_only = bool(on)
        for m in self.models.values():
            m.editable = not self.read_only and self.tab_editable(m.tab.key)
        self._update_buttons()

    def tab_editable(self, tab_key):
        """ Override to lock a tab (e.g. aliases with several devices) """
        return True

    def show_devices(self, dbs, devices):
        """ Show the configuration of ``devices`` (names on ``dbs``); the first one is read """
        self.dbs = dbs
        self.devices = list(devices)
        for m in self.models.values():
            m.editable = not self.read_only and self.tab_editable(m.tab.key)
        self.title.setText(self.title_text())
        self.refresh()

    def title_text(self):
        if len(self.devices) == 1:
            return "{0} [{1}]".format(self.base_title, self.devices[0])
        return "{0} [{1} devices selected]".format(self.base_title, len(self.devices))

    # -- Reading -----------------------------------------------------------------------------
    def load(self, dbs, device):
        raise NotImplementedError

    def refresh(self):
        if not self.devices:
            return
        self._token += 1
        token = self._token
        self._set_status("Loading...")
        run_async(self.load, self.dbs, self.devices[0],
                  on_done=lambda data, t=token: self._loaded(t, data),
                  on_error=lambda err, t=token: self._load_failed(t, err),
                  source=type(self).__name__, owner=self)

    def _refresh_clicked(self):
        if self.has_pending() and not self.confirm(
                "Refresh discards the {0} change(s) not applied yet. Refresh?".format(self.pending_count())):
            return
        self.refresh()

    def _loaded(self, token, data):
        if token != self._token:
            return
        self.data = data
        for key, model in self.models.items():
            model.set_rows(data.get(key, []))
        for view in self.views.values():
            view.resizeColumnsToContents()
            view.setColumnWidth(0, min(320, max(160, view.columnWidth(0) + 16)))
            for c in range(1, view.model().columnCount() - 1):
                view.setColumnWidth(c, max(90, view.columnWidth(c) + 12))
        self._set_status(self.loaded_text())
        self._update_buttons()
        self.loaded.emit()

    def loaded_text(self):
        key = self.current_tab_key()
        return "{0} rows".format(self.models[key].rowCount()) if key else ""

    def _load_failed(self, token, err):
        if token != self._token:
            return
        self.data = {}
        for model in self.models.values():
            model.set_rows([])
        text = err.text() if hasattr(err, "text") else str(err)
        self._set_status("Cannot read {0}: {1}".format(self.devices[0], text), error=True)
        self._update_buttons()
        self.loaded.emit()

    # -- Pending changes ------------------------------------------------------------------
    def pending(self):
        return {k: m.changes() for k, m in self.models.items() if m.changes()}

    def has_pending(self):
        return any(m.is_modified() for m in self.models.values())

    def pending_count(self):
        return sum(len(c) for c in self.pending().values())

    def revert(self):
        for m in self.models.values():
            m.revert()
        self._set_status(self.loaded_text())

    def set_pending(self, tab_key, names, key, value):
        """ Set one column of several rows (the "Set ..." menu entries) """
        model = self.models[tab_key]
        for n in names:
            r = model.row_of(n)
            if r >= 0:
                model.set_value(r, key, value)
        self._update_buttons()

    def validate(self, pending):
        return None

    # -- Writing ---------------------------------------------------------------------------
    def write(self, job, dbs, devices, pending, rows):
        raise NotImplementedError

    def snapshot(self):
        """ {tab_key: {row name: row dict}} copied from the tables """
        return {k: {r["name"]: r for r in m.rows()} for k, m in self.models.items()}

    def apply(self):
        """ Write the pending changes on every shown device """
        if self.read_only:
            return None
        pending = self.pending()
        if not pending:
            self._set_status("Nothing to apply.")
            return None
        error = self.validate(pending)
        if error:
            self._set_status(error, error=True)
            return None
        if len(self.devices) > 1:
            rows = [("{0}: {1}".format(self._tab_title(k), n), self._shown(k, key, v))
                    for k, changes in pending.items() for n, key, v in changes]
            if not self.confirm_changes(rows, len(self.devices)):
                return None
        return self.run_job("Applying " + self.base_title.lower(), self.write, self.dbs,
                            list(self.devices), pending, self.snapshot())

    def run_job(self, title, fn, *args):
        """ Run ``fn(job, *args)`` with a progress dialog, then refresh """
        job = Job(fn, *args, title=title)
        self.last_job = job
        job.finished.connect(lambda j=job, devices=list(self.devices): self._job_finished(j, devices))
        self._set_status(title + "...")
        QJobProgressDialog.run(job, self, show_errors=self.show_job_errors)
        return job

    def _job_finished(self, job, devices):
        self.applied.emit()
        if devices == self.devices:     # else the panel moved on and already loaded the new devices
            self.refresh()

    # -- Dialog hooks (tests replace them) -------------------------------------------------
    def confirm_changes(self, rows, n_devices, extra="", item="property"):
        """ Jive's multiple change confirmation; True to proceed """
        from .confirm import confirm_changes
        return confirm_changes(self, rows, n_devices, extra, item)

    def confirm(self, text, details=""):
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Icon.Question, self.base_title, text,
                                    QtWidgets.QMessageBox.StandardButton.Yes
                                    | QtWidgets.QMessageBox.StandardButton.No, self)
        if details:
            box.setDetailedText(details)
        return box.exec() == QtWidgets.QMessageBox.StandardButton.Yes

    def prompt(self, title, label, default=""):
        """ Text from the user or None """
        text, ok = QtWidgets.QInputDialog.getText(self, title, label, text=default)
        return text if ok else None

    def inform(self, text):
        QtWidgets.QMessageBox.information(self, self.base_title, text)

    # -- Helpers -----------------------------------------------------------------------------
    def current_tab_key(self):
        i = self.tab_widget.currentIndex()
        return self.tabs[i].key if 0 <= i < len(self.tabs) else None

    def select_tab(self, key):
        for i, t in enumerate(self.tabs):
            if t.key == key:
                self.tab_widget.setCurrentIndex(i)

    def selected_names(self, tab_key=None):
        key = tab_key or self.current_tab_key()
        view, model = self.views[key], self.models[key]
        rows = sorted({i.row() for i in view.selectionModel().selectedRows()})
        return [model.names()[r] for r in rows]

    def select_names(self, tab_key, names):
        view, model = self.views[tab_key], self.models[tab_key]
        sel = view.selectionModel()
        sel.clearSelection()
        flags = QtCore.QItemSelectionModel.SelectionFlag.Select | QtCore.QItemSelectionModel.SelectionFlag.Rows
        for n in names:
            r = model.row_of(n)
            if r >= 0:
                sel.select(model.index(r, 0), flags)

    def _tab_title(self, key):
        return next((t.title for t in self.tabs if t.key == key), key)

    def _shown(self, tab_key, col_key, value):
        model = self.models[tab_key]
        col = next((c for c in model.columns if c.key == col_key), None)
        if col is not None and col.kind == "bool":
            return "yes" if value else "no"
        return value

    def _set_status(self, text, error=False):
        self.status.setText(text)
        self.status.setStyleSheet("color: #c00000" if error else "")

    def _update_buttons(self, *args):
        pending = self.has_pending()
        writable = not self.read_only and bool(self.devices)
        self.apply_button.setEnabled(writable and pending)
        self.revert_button.setEnabled(pending)
        for b in self._write_buttons:
            b.setEnabled(writable)
        if pending:
            n = self.pending_count()
            self._set_status("{0} value(s) changed, not applied yet: Apply writes them{1}.".format(
                n, " on {0} devices".format(len(self.devices)) if len(self.devices) > 1 else ""))
            self._pending_shown = True
        elif getattr(self, "_pending_shown", False):
            # Every change was undone by hand: the pending text no longer applies
            self._pending_shown = False
            self._set_status(self.loaded_text())

    def _context_menu(self, tab_key, pos):
        view = self.views[tab_key]
        index = view.indexAt(pos)
        if index.isValid() and index.row() not in {i.row() for i in view.selectionModel().selectedRows()}:
            self.select_names(tab_key, [self.models[tab_key].names()[index.row()]])
        names = self.selected_names(tab_key)
        menu = self.build_menu(tab_key, names)
        if menu is not None and not menu.isEmpty():
            menu.exec(view.viewport().mapToGlobal(pos))
        if menu is not None:
            menu.deleteLater()

    def build_menu(self, tab_key, names):
        """ QMenu for the selected rows of a tab (None when nothing applies) """
        if not names:
            return None
        tab = next(t for t in self.tabs if t.key == tab_key)
        menu = QtWidgets.QMenu(self)
        for action in tab.actions:
            if action.text is None:
                menu.addSeparator()
                continue
            if action.write and (self.read_only or not self.tab_editable(tab_key)):
                continue
            if action.visible is not None and not action.visible(self, tab_key):
                continue
            a = menu.addAction(action.text)
            a.triggered.connect(lambda checked=False, cb=action.callback, k=tab_key, n=list(names): cb(k, n))
        return menu

    def menu_texts(self, tab_key, names):
        """ Visible entries of the context menu (tests) """
        menu = self.build_menu(tab_key, names)
        return [a.text() for a in menu.actions() if not a.isSeparator()] if menu else []

    def trigger_menu(self, tab_key, names, text):
        """ Run a context-menu entry by its text (tests, scripting) """
        menu = self.build_menu(tab_key, names)
        for a in (menu.actions() if menu else []):
            if a.text() == text:
                a.trigger()
                return True
        return False


__all__ = ["ConfigColumn", "ConfigAction", "ConfigTab", "ConfigTableModel", "QConfigPanel"]
