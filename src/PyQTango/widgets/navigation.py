# -*- coding: utf-8 -*-
"""
QNavigationBar and NavigationHistory (Jive's NavigationBar / NavManager).
"""

from ..qt import QtCore, QtWidgets, Signal


class NavigationHistory(object):
    """ Back/forward history of opaque locations (e.g. tree paths) """

    def __init__(self, max_size=100):
        self._items = []
        self._pos = -1
        self.max_size = max_size

    def record(self, location):
        if self._pos >= 0 and self._items[self._pos] == location:
            return
        del self._items[self._pos + 1:]
        self._items.append(location)
        if len(self._items) > self.max_size:
            del self._items[0]
        self._pos = len(self._items) - 1

    def can_go_back(self):
        return self._pos > 0

    def can_go_forward(self):
        return self._pos < len(self._items) - 1

    def back(self):
        if self.can_go_back():
            self._pos -= 1
        return self.current()

    def forward(self):
        if self.can_go_forward():
            self._pos += 1
        return self.current()

    def current(self):
        return self._items[self._pos] if self._pos >= 0 else None

    def reset(self):
        self._items = []
        self._pos = -1


class QNavigationBar(QtWidgets.QToolBar):
    """ Back, forward, search combo (with link history), search, next/previous
    occurrence and refresh.

    Signals: backRequested, forwardRequested, refreshRequested, nextRequested,
    previousRequested, searchRequested(str), linkActivated(object).
    """

    backRequested = Signal()
    forwardRequested = Signal()
    refreshRequested = Signal()
    nextRequested = Signal()
    previousRequested = Signal()
    searchRequested = Signal(str)
    linkActivated = Signal(object)

    def __init__(self, parent=None, max_links=30):
        QtWidgets.QToolBar.__init__(self, parent)
        self.setMovable(False)
        style = self.style()
        sp = QtWidgets.QStyle.StandardPixmap
        self.back_action = self.addAction(style.standardIcon(sp.SP_ArrowBack), "Back")
        self.back_action.triggered.connect(self.backRequested.emit)
        self.forward_action = self.addAction(style.standardIcon(sp.SP_ArrowForward), "Forward")
        self.forward_action.triggered.connect(self.forwardRequested.emit)
        self.search = QtWidgets.QComboBox(self)
        self.search.setEditable(True)
        self.search.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.search.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.search.lineEdit().setPlaceholderText("Search (e.g. sys/tg_test/1, Server/instance, Device:...)")
        # An editable combo reports one Enter twice (line edit, then combo): merge them
        self._enter = QtCore.QTimer(self)
        self._enter.setSingleShot(True)
        self._enter.setInterval(0)
        self._enter.timeout.connect(self._on_search)
        self.search.lineEdit().returnPressed.connect(self._enter.start)
        self.search.activated.connect(self._on_activated)
        self.addWidget(self.search)
        self.search_action = self.addAction(style.standardIcon(sp.SP_FileDialogContentsView), "Search")
        self.search_action.triggered.connect(self._on_search)
        self.previous_action = self.addAction(style.standardIcon(sp.SP_ArrowUp), "Previous occurrence")
        self.previous_action.triggered.connect(self.previousRequested.emit)
        self.next_action = self.addAction(style.standardIcon(sp.SP_ArrowDown), "Next occurrence")
        self.next_action.triggered.connect(self.nextRequested.emit)
        self.refresh_action = self.addAction(style.standardIcon(sp.SP_BrowserReload), "Refresh")
        self.refresh_action.triggered.connect(self.refreshRequested.emit)
        self.max_links = max_links
        for a in (self.back_action, self.forward_action, self.previous_action, self.next_action):
            a.setEnabled(False)

    def enableBack(self, on):
        self.back_action.setEnabled(bool(on))

    def enableForward(self, on):
        self.forward_action.setEnabled(bool(on))

    def enableNextOcc(self, on):
        self.next_action.setEnabled(bool(on))

    def enablePreviousOcc(self, on):
        self.previous_action.setEnabled(bool(on))

    def searchText(self):
        return self.search.currentText().strip()

    def addLink(self, text, data=None):
        """ Add a location to the combo history (most recent first) """
        idx = self.search.findText(text)
        if idx >= 0:
            self.search.removeItem(idx)
        self.search.insertItem(0, text, data)
        while self.search.count() > self.max_links:
            self.search.removeItem(self.search.count() - 1)
        self.search.setCurrentIndex(0)

    def _on_search(self):
        text = self.searchText()
        if text:
            idx = self.search.findText(text)
            if idx >= 0 and self.search.itemData(idx) is not None:
                self.linkActivated.emit(self.search.itemData(idx))
            else:
                self.searchRequested.emit(text)

    def _on_activated(self, index):
        data = self.search.itemData(index)
        if data is not None:
            self.linkActivated.emit(data)
