# -*- coding: utf-8 -*-
"""
@author: Michele Devetta <michele.devetta@cnr.it>
"""

import logging

from ..qt import QtCore, QtGui, QtWidgets, Signal

from .treeitems import TreeItem, DeviceItem, AttributeItem
import tango as PT
from .devicetree import DeviceTreeModel
from ..core.tangoutil import getAllLiveAttributes
from .icons import get_image_path
from ..models.worker import run_async


def _name_parts(name):
    """ "tango://host:port/a/b/c/d#dbase=no" -> ["a", "b", "c", "d"] (labels of the tree levels) """
    path = name.split("#", 1)[0]
    if "://" in path:
        path = path.split("://", 1)[1].split("/", 1)[-1]
    return path.split("/")

log = logging.getLogger(__name__)


class AttributeTreeModel(DeviceTreeModel):

    def __init__(self, attr_list, label="", parent=None):
        # Parent constructor
        QtCore.QAbstractItemModel.__init__(self, parent)
        self.rootItem = TreeItem(label)

        attr_dict = {}
        for d in attr_list:
            # Split device names (the full name stays in d)
            parts = _name_parts(d['attribute'])
            if len(parts) != 4 or not all(parts):
                log.warning("Skipping invalid attribute name %s", d['attribute'])
                continue
            (sys, sub, dev, attr) = parts

            if sys in attr_dict:
                if sub in attr_dict[sys]:
                    if dev in attr_dict[sys][sub]:
                        if attr in attr_dict[sys][sub][dev]:
                            # Duplicate attribute
                            log.warning("Skipping duplicate attribute %s", d['attribute'])
                        else:
                            attr_dict[sys][sub][dev][attr] = d
                    else:
                        attr_dict[sys][sub][dev] = {}
                        attr_dict[sys][sub][dev][attr] = d
                else:
                    attr_dict[sys][sub] = {}
                    attr_dict[sys][sub][dev] = {}
                    attr_dict[sys][sub][dev][attr] = d
            else:
                attr_dict[sys] = {}
                attr_dict[sys][sub] = {}
                attr_dict[sys][sub][dev] = {}
                attr_dict[sys][sub][dev][attr] = d

        # Now we have a list of devices, we can populate the tree
        sys = list(attr_dict.keys())
        sys.sort()

        for k1 in sys:
            # Create sys obj
            sysobj = TreeItem(k1, self.rootItem)

            # Get subsystems keys
            subsys = list(attr_dict[k1].keys())
            subsys.sort()
            for k2 in subsys:
                # Create sub-sys obj
                subobj = TreeItem(k2, sysobj)

                # Scan list of devices
                devices = list(attr_dict[k1][k2].keys())
                devices.sort()
                for d in devices:
                    devobj = DeviceItem(d, {}, subobj)

                    # Scan list of attributes
                    attributes = list(attr_dict[k1][k2][d].keys())
                    attributes.sort()
                    for a in attributes:
                        devobj.appendChild(AttributeItem(a, attr_dict[k1][k2][d][a], devobj))

                    # Append child to parent
                    subobj.appendChild(devobj)

                # Add child to parent
                sysobj.appendChild(subobj)

            # Add child to parent
            self.rootItem.appendChild(sysobj)

    def data(self, index, role):
        if not index.isValid():
            return None

        if role == QtCore.Qt.ItemDataRole.DecorationRole:
            item = index.internalPointer()
            if type(item) == AttributeItem:
                if item.getDataFormat() == PT.AttrDataFormat.SCALAR:
                    return QtGui.QIcon(QtGui.QPixmap(get_image_path("scalar.svg")))
                elif item.getDataFormat() == PT.AttrDataFormat.SPECTRUM:
                    return QtGui.QIcon(QtGui.QPixmap(get_image_path("spectrum.png")))
                elif item.getDataFormat() == PT.AttrDataFormat.IMAGE:
                    return QtGui.QIcon(QtGui.QPixmap(get_image_path("image.png")))
                else:
                    # Unknown format (device not reachable): generic attribute icon
                    return QtGui.QIcon(QtGui.QPixmap(get_image_path("scalar.svg")))

        return super().data(index, role)


class QBaseAttributeTree(QtWidgets.QTreeView):
    def __init__(self, attr_list, resize=False, label="", parent=None):
        """ Constructor
        """
        # Parent constructor
        QtWidgets.QTreeView.__init__(self, parent)

        # Model
        self.model = AttributeTreeModel(attr_list, label=label, parent=self)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(True)

        # Initialize model
        self.setModel(self.model)

        # Auto-resize
        if resize and parent is not None:
            self.resize(parent.size())

        style = """
QTreeView::branch:has-siblings:!adjoins-item {{
    border-image: url({0:s}) 0;
}}

QTreeView::branch:has-siblings:adjoins-item {{
    border-image: url({1:s}) 0;
}}

QTreeView::branch:!has-children:!has-siblings:adjoins-item {{
    border-image: url({2:s}) 0;
}}

QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:closed:has-children:has-siblings {{
    border-image: none;
    image: url({3:s});
}}

QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings  {{
    border-image: none;
    image: url({4:s});
}}
"""
        style = style.format(
            get_image_path("vline.png"),
            get_image_path("branch-more.png"),
            get_image_path("branch-end.png"),
            get_image_path("branch-closed.png"),
            get_image_path("branch-open.png"),
        )
        self.setStyleSheet(style)


class QAttributeTree(QBaseAttributeTree):

    #: The attribute list is shown (``load_async=True``)
    loaded = Signal()

    def __init__(self, dbhost=None, port=10000, resize=False, label="", parent=None, load_async=False):
        """ Constructor.

        ``load_async``: show the tree at once, empty, and fill it from a worker
        thread (listing the live attributes pings every device, which takes
        seconds when some are dead); :attr:`loaded` is emitted when it is filled.
        """
        if load_async:
            QBaseAttributeTree.__init__(self, [], resize=resize, label=label, parent=parent)
            self._label = label
            run_async(getAllLiveAttributes, dbhost, port, on_done=self._set_attributes,
                      on_error=lambda e: log.warning("Cannot list the attributes: %s", e.message),
                      source="Attribute tree", owner=self)
            return
        # Get attribute list
        attr_list = getAllLiveAttributes(dbhost, port)

        # Common parent constructor
        QBaseAttributeTree.__init__(self, attr_list, resize=resize, label=label, parent=parent)

    def _set_attributes(self, attr_list):
        old = self.model
        self.model = AttributeTreeModel(attr_list, label=self._label, parent=self)
        self.setModel(self.model)
        old.deleteLater()
        self.loaded.emit()
