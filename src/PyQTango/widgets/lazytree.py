# -*- coding: utf-8 -*-
"""
Lazy, asynchronous tree model (base of Jive's TangoNode trees).

Subclass :class:`TreeNode` and implement :meth:`TreeNode.populate`, which runs
in a worker thread and returns the child nodes. The model shows a temporary
"Loading..." row while it runs, and an error row if it fails.
"""

import logging

from ..qt import QtCore, QtGui, Qt, Signal
from ..models.worker import run_async

log = logging.getLogger(__name__)


class TreeNode(object):
    """ One node of a :class:`LazyTreeModel` (plain Python, no Qt) """

    #: icon name or QIcon returned by :meth:`icon`
    icon_name = None

    def __init__(self, label, parent=None, leaf=False, data=None):
        self.label = label
        self.parent = parent
        self.leaf = leaf
        self.data = data
        self.children = []
        self.loaded = leaf
        self.loading = False
        self.error = None

    # -- To override ---------------------------------------------------------------
    def populate(self, context):
        """ Return the list of child nodes. Runs in a worker thread: no Qt here. """
        return []

    def display(self):
        return self.label

    def icon(self):
        return None

    def tooltip(self):
        return None

    # -- Helpers -------------------------------------------------------------------
    def row(self):
        return self.parent.children.index(self) if self.parent is not None else 0

    def path(self):
        names = []
        node = self
        while node is not None and node.parent is not None:
            names.append(node.label)
            node = node.parent
        return list(reversed(names))

    def child_by_label(self, label, case_sensitive=False):
        for c in self.children:
            if c.label == label or (not case_sensitive and c.label.lower() == label.lower()):
                return c
        return None


class _PlaceholderNode(TreeNode):

    def __init__(self, label, parent):
        TreeNode.__init__(self, label, parent, leaf=True)


class LazyTreeModel(QtCore.QAbstractItemModel):
    """ Tree model that loads children on demand in a worker thread.

    Signals:
        nodeLoaded(QModelIndex):  children of that index are now available
        loadFailed(QModelIndex, object): populate() raised (ErrorRecord)
    """

    nodeLoaded = Signal(object)
    loadFailed = Signal(object, object)

    LOADING_TEXT = "Loading..."

    def __init__(self, root, context=None, parent=None):
        QtCore.QAbstractItemModel.__init__(self, parent)
        self.root = root
        self.context = context
        self._icons = {}

    # -- Index plumbing --------------------------------------------------------------
    def node(self, index):
        return index.internalPointer() if index.isValid() else self.root

    def index_of(self, node):
        if node is None or node is self.root or node.parent is None:
            return QtCore.QModelIndex()
        return self.createIndex(node.row(), 0, node)

    def index(self, row, column, parent=QtCore.QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QtCore.QModelIndex()
        p = self.node(parent)
        if row >= len(p.children):
            return QtCore.QModelIndex()
        return self.createIndex(row, column, p.children[row])

    def parent(self, index=QtCore.QModelIndex()):
        if not index.isValid():
            return QtCore.QModelIndex()
        return self.index_of(index.internalPointer().parent)

    def rowCount(self, parent=QtCore.QModelIndex()):
        if parent.column() > 0:
            return 0
        return len(self.node(parent).children)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 1

    def hasChildren(self, parent=QtCore.QModelIndex()):
        n = self.node(parent)
        if n.leaf:
            return False
        return bool(n.children) or not n.loaded

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        if isinstance(index.internalPointer(), _PlaceholderNode):
            return Qt.ItemFlag.ItemIsEnabled
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        n = index.internalPointer()
        if role == Qt.ItemDataRole.DisplayRole:
            return n.display()
        if role == Qt.ItemDataRole.DecorationRole:
            icon = n.icon()
            if isinstance(icon, str):
                if icon not in self._icons:
                    self._icons[icon] = QtGui.QIcon(icon)
                return self._icons[icon]
            return icon
        if role == Qt.ItemDataRole.ToolTipRole:
            return n.tooltip()
        if role == Qt.ItemDataRole.ForegroundRole and isinstance(n, _PlaceholderNode) and n.error is not None:
            return QtGui.QBrush(QtGui.QColor("red"))
        return None

    def mimeTypes(self):
        return ["text/plain"]

    def mimeData(self, indexes):
        mime = QtCore.QMimeData()
        mime.setText("\n".join("/".join(self.node(i).path()) for i in indexes if i.isValid()))
        return mime

    # -- Lazy loading ------------------------------------------------------------------
    def canFetchMore(self, parent=QtCore.QModelIndex()):
        n = self.node(parent)
        return not n.leaf and not n.loaded and not n.loading

    def fetchMore(self, parent=QtCore.QModelIndex()):
        n = self.node(parent)
        if n.leaf or n.loaded or n.loading:
            return
        n.loading = True
        # Each load has a generation: a result of an older load, or of a node removed
        # from the tree meanwhile, is dropped
        gen = n._load_gen = getattr(n, "_load_gen", 0) + 1
        self.beginInsertRows(parent, 0, 0)
        n.children = [_PlaceholderNode(self.LOADING_TEXT, n)]
        self.endInsertRows()
        ctx = self.context
        run_async(n.populate, ctx, on_done=lambda kids, node=n, g=gen: self._loaded(node, kids, g),
                  on_error=lambda err, node=n, g=gen: self._failed(node, err, g), source=n.label, owner=self)

    def _current(self, n, gen):
        """ True when ``gen`` is the last load of ``n`` and ``n`` is still in the tree """
        if gen is not None and gen != getattr(n, "_load_gen", 0):
            return False
        while n is not self.root:
            p = n.parent
            if p is None or not any(c is n for c in p.children):
                return False
            n = p
        return True

    def _replace_children(self, n, kids):
        parent = self.index_of(n)
        if n.children:
            self.beginRemoveRows(parent, 0, len(n.children) - 1)
            n.children = []
            self.endRemoveRows()
        if kids:
            self.beginInsertRows(parent, 0, len(kids) - 1)
            for k in kids:
                k.parent = n
            n.children = list(kids)
            self.endInsertRows()

    def _loaded(self, n, kids, gen=None):
        if not self._current(n, gen):
            return
        n.loading = False
        n.loaded = True
        n.error = None
        self._replace_children(n, kids or [])
        self.nodeLoaded.emit(self.index_of(n))

    def _failed(self, n, err, gen=None):
        if not self._current(n, gen):
            return
        n.loading = False
        n.loaded = True
        n.error = err
        ph = _PlaceholderNode("Error: " + err.message, n)
        ph.error = err
        self._replace_children(n, [ph])
        self.loadFailed.emit(self.index_of(n), err)

    def insert_child(self, index, node, row=0):
        """ Add ``node`` under the node at ``index``; returns its index.
        For nodes that exist only in the view until something is written
        (Jive's "Add attribute", "Create free property"). The parent's children
        must be loaded (use :meth:`ensure_loaded`): a later load replaces them. """
        parent = self.node(index)
        if not parent.loaded:
            raise RuntimeError("insert_child: the children of {0} are not loaded".format(parent.label))
        row = max(0, min(row, len(parent.children)))
        self.beginInsertRows(index, row, row)
        node.parent = parent
        parent.children.insert(row, node)
        self.endInsertRows()
        return self.index_of(node)

    def node_changed(self, node):
        """ Repaint ``node`` (its icon, text or tooltip changed) """
        idx = self.index_of(node)
        if idx.isValid():
            self.dataChanged.emit(idx, idx)

    def refresh(self, index=QtCore.QModelIndex()):
        """ Forget the children of ``index`` and load them again """
        n = self.node(index)
        if n.leaf:
            return
        self._replace_children(n, [])
        n.loaded = False
        n.loading = False
        if n is self.root or index.isValid():
            self.fetchMore(index)

    def ensure_loaded(self, index, callback):
        """ Call ``callback(index)`` once the children of ``index`` are loaded """
        n = self.node(index)
        if n.loaded and not n.loading:
            callback(index)
            return

        def on_loaded(idx, *_):
            if self.node(idx) is n:
                for sig in (self.nodeLoaded, self.loadFailed):
                    try:
                        sig.disconnect(on_loaded)
                    except (TypeError, RuntimeError):
                        pass
                callback(idx)
        self.nodeLoaded.connect(on_loaded)
        self.loadFailed.connect(on_loaded)     # a failed load ends the wait too
        self.fetchMore(index)

    def find_path(self, labels, callback, case_sensitive=False):
        """ Load the tree along ``labels`` and call ``callback(index or None)`` """
        labels = list(labels)

        def step(index, rest):
            if not rest:
                callback(index)
                return

            def loaded(idx):
                child = self.node(idx).child_by_label(rest[0], case_sensitive)
                if child is None:
                    callback(None)
                else:
                    step(self.index_of(child), rest[1:])
            self.ensure_loaded(index, loaded)

        step(QtCore.QModelIndex(), labels)
