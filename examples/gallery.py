# -*- coding: utf-8 -*-
"""
PyQTango 0.2 widget gallery.

    python examples/gallery.py sys/tg_test/1             # any running device
    PYQTANGO_QT_API=pyqt6 python examples/gallery.py sys/tg_test/1

With TangoTest, the scalar list shows every scalar attribute, the setters write
to the device, and the value labels follow change events where the server
pushes them and polling otherwise.
"""

import sys

from PyQTango.qt import QtWidgets, Qt, make_application, API
from PyQTango import widgets as W
from PyQTango import QAttribute, QCommandExecuter
from PyQTango.models import registry


def attr(device, name):
    if "#" in device:
        dev, frag = device.split("#", 1)
        return "{0}/{1}#{2}".format(dev, name, frag)
    return device + "/" + name


class Gallery(QtWidgets.QWidget):

    def __init__(self, device, attributes=None, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.setWindowTitle("PyQTango {0} gallery on {1} - {2}".format(__import__("PyQTango").__version__, API, device))
        layout = QtWidgets.QVBoxLayout(self)

        header = W.QStateStatusViewer(self)
        header.setDevice(device)
        layout.addWidget(header)

        split = QtWidgets.QHBoxLayout()
        box = QtWidgets.QGroupBox("QScalarListViewer", self)
        bl = QtWidgets.QVBoxLayout(box)
        self.scalars = W.QScalarListViewer(box)
        self.scalars.setDevice(device)
        scroll = QtWidgets.QScrollArea(box)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.scalars)
        bl.addWidget(scroll)
        split.addWidget(box, 3)

        right = QtWidgets.QVBoxLayout()
        attrs = attributes or {}
        form_box = QtWidgets.QGroupBox("Single widgets", self)
        form = QtWidgets.QFormLayout(form_box)
        if "value" in attrs:
            v = W.QValueLabel(form_box)
            v.setModel(attr(device, attrs["value"]))
            form.addRow("QValueLabel", v)
        if "wheel" in attrs:
            wh = W.QAttributeWheelEditor(form_box)
            wh.setModel(attr(device, attrs["wheel"]))
            form.addRow("QAttributeWheelEditor", wh)
        if "qattribute" in attrs:
            qa = QAttribute(form_box)
            qa.setTangoAttribute(attr(device, attrs["qattribute"]))
            form.addRow("QAttribute (0.1 API)", qa)
        if "alarm" in attrs:
            al = W.QValueLabel(form_box)
            al.setModel(attr(device, attrs["alarm"]))
            form.addRow("Value in alarm", al)
        if "missing" in attrs:
            er = W.QValueLabel(form_box)
            er.setModel(attr(device, attrs["missing"]))
            form.addRow("Missing attribute", er)
        right.addWidget(form_box)

        cmd_box = QtWidgets.QGroupBox("QCommandExecuter", self)
        cl = QtWidgets.QVBoxLayout(cmd_box)
        self.cmd = QCommandExecuter(cmd_box)
        self.cmd.setDevice(device)
        cl.addWidget(self.cmd)
        right.addWidget(cmd_box)
        split.addLayout(right, 2)
        layout.addLayout(split, 1)

        console = W.QConsole(self)
        console.separator()
        console.print("Command: {0}/Ping\nDuration: 1 msec\n\nDevice is alive\n".format(device))
        console.setMaximumHeight(110)
        layout.addWidget(console)

    def closeEvent(self, event):
        registry().shutdown()
        QtWidgets.QWidget.closeEvent(self, event)


def main():
    app = make_application(sys.argv)
    device = sys.argv[1] if len(sys.argv) > 1 else "sys/tg_test/1"
    attrs = {"value": "double_scalar", "wheel": "double_scalar_w", "qattribute": "long_scalar_w"}
    g = Gallery(device, attrs)
    g.resize(1100, 700)
    g.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
