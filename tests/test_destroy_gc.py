# -*- coding: utf-8 -*-
"""
Destroy handlers must survive the cyclic garbage collector.

A widget whose wrapper is collected while its C++ object lives on (owned by a C++ parent, deleted
later) used to crash when Qt destroyed it: the collector had cleared the Python ``destroyed``
handler, which the slot proxy still called. Each case runs in a subprocess because the failure is
a segmentation fault.
"""

import os
import subprocess
import sys

import pytest

pytest.importorskip("pyqtgraph")

import PyQTango  # noqa: E402
from PyQTango.qt import API  # noqa: E402

SCRIPT = r"""
import gc, os, sys
from PyQTango.qt import QtCore, QtWidgets, sip
from PyQTango.models import attribute_model
from PyQTango.widgets.spectrum import QSpectrumViewer
from PyQTango.widgets.trend import QTrend
from PyQTango.widgets.image import QImageViewer

case, device = sys.argv[1], sys.argv[2]
dev, frag = device.split("#", 1)
attr = lambda name: "{0}/{1}#{2}".format(dev, name, frag)

app = QtWidgets.QApplication([])
top = QtWidgets.QWidget()
inner = QtWidgets.QWidget(top)
names = []
if case == "spectrum":          # QSpectrumViewer's own handler (no model)
    QSpectrumViewer(inner)
elif case == "attribute":       # TangoAttributeWidget's handler
    names = [attr("spectrum")]
    QSpectrumViewer(inner).setModel(names[0])
elif case == "image":           # pyqtgraph's ImageView registers named ViewBoxes
    QImageViewer(inner)
elif case == "trend":           # QTrend's handler (an attribute's connections keep a trend alive)
    QTrend(inner)
models = [attribute_model(n) for n in names]
assert all(m.ref_count() == 1 for m in models)
top.cycle = top                 # only the collector can free the window wrapper
sip.transferto(top, None)       # C++ owns the window: freeing the wrapper does not delete it
top.deleteLater()
del top, inner
gc.collect()
QtCore.QTimer.singleShot(0, app.quit)
app.exec() if hasattr(app, "exec") else app.exec_()
print("refs", [m.ref_count() for m in models], flush=True)
os._exit(0 if all(m.ref_count() == 0 for m in models) else 1)
"""


@pytest.mark.parametrize("case", ["spectrum", "attribute", "image", "trend"])
def test_destroy_handler_after_wrapper_collected(case, device_name):
    env = dict(os.environ, PYQTANGO_QT_API=API.lower(), QT_QPA_PLATFORM="offscreen",
               PYTHONPATH=os.path.dirname(os.path.dirname(PyQTango.__file__)))
    proc = subprocess.run([sys.executable, "-c", SCRIPT, case, device_name], env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, "exit {0}\n{1}\n{2}".format(proc.returncode, proc.stdout, proc.stderr)
