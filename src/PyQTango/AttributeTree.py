# -*- coding: utf-8 -*-
"""
@author: Michele Devetta <michele.devetta@cnr.it>
"""

import logging

from .qt import QtCore, QtGui, QtWidgets

from .CommonTree import TreeItem, DeviceItem, AttributeItem
import tango as PT
from .DeviceTree import DeviceTreeModel
from .TangoUtil import getAllLiveAttributes
from .config import get_image_path

log = logging.getLogger(__name__)


class AttributeTreeModel(DeviceTreeModel):

    def __init__(self, attr_list, label="", parent=None):
        # Parent constructor
        QtCore.QAbstractItemModel.__init__(self, parent)
        self.rootItem = TreeItem(label)

        attr_dict = {}
        for d in attr_list:
            # Split device names
            (sys, sub, dev, attr) = d['attribute'].split("/")

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

    def __init__(self, dbhost=None, port=10000, resize=False, label="", parent=None):
        """ Constructor
        """
        # Get attribute list)
        attr_list = getAllLiveAttributes()

        # Common parent constructor
        QBaseAttributeTree.__init__(self, attr_list, resize=resize, label=label, parent=parent)


class QArchivedAttributeTree(QBaseAttributeTree):

    def __init__(self, extractor, resize=False, label="", parent=None):
        """ Constructor
        """
        # Get attribute list
        attrs = extractor.GetAttNameAll()
        attr_list = []

        if parent is not None:
            app = QtWidgets.QApplication.instance()
            progress = QtWidgets.QProgressDialog(parent)
            progress.setLabelText("Scanning attributes for configuration...")
            progress.setMinimum(0)
            progress.setMaximum(len(attrs))
            progress.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
            progress.setAutoClose(True)
            progress.setValue(0)
            progress.show()
            app.processEvents()

        for i, a in enumerate(attrs):
            if parent is not None:
                progress.setValue(i)
                app.processEvents()

            try:
                if parent is not None and progress.wasCanceled():
                    log.debug("Attribute scanning canceled")
                    break
                ap = PT.AttributeProxy(a)
                conf = ap.get_config()
                attr_list.append({'attribute': a, 'data_format': conf.data_format, 'data_type': conf.data_type})
                log.debug("configured attribute %s", a)
            except PT.DevFailed:
                attr_list.append({'attribute': a})

        log.debug("Attribute scanning done")
        if parent is not None:
            progress.close()

        # Common parent constructor
        QBaseAttributeTree.__init__(self, attr_list, resize=resize, label=label, parent=parent)
