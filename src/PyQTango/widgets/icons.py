# -*- coding: utf-8 -*-
"""
Painted icons: ATK state balls and Astor host-state icons.

Drawn at any size and device pixel ratio from the ATK colours, cached, no image
files.

* :func:`state_icon` - a ball in the ATK colour of a DevState (or its name).
* :func:`host_icon` - a host-state icon (core.starter states): a computer
  screen whose light shows the state; "unreachable" is crossed out.
* :func:`ball_icon` - a ball of any colour.
* :func:`get_image_path` - path of an image file shipped with PyQTango (legacy widgets).

@author: Michele Devetta <michele.devetta@cnr.it>
"""

import sys
import os.path as osp

from ..qt import QtCore, QtGui, Qt
from ..core.formatting import state_colors

__all__ = ["state_icon", "host_icon", "ball_icon", "HOST_COLORS", "get_image_path"]


def get_image_path(image, module="PyQTango"):
    """ Absolute path of ``image`` in the ``images`` folder of ``module``, or "" if missing """
    path = osp.join(osp.dirname(osp.abspath(sys.modules[module].__file__)), "images", image)
    return osp.abspath(path) if osp.isfile(path) else ""

#: Host state -> colour (ATK: ON green, MOVING blue, STANDBY yellow, ALARM orange, OFF white)
HOST_COLORS = {"running": "#00ff00", "moving": "#80a0ff", "blocked": "#ffff00", "alarm": "#ff8c00",
               "off": "#ffffff", "unreachable": "#ff0000", "unknown": "#9b9b9b"}

_cache = {}


def _pixmaps(key, painter_fn, sizes=(16, 24, 32)):
    ic = _cache.get(key)
    if ic is not None:
        return ic
    ic = QtGui.QIcon()
    for size in sizes:
        pm = QtGui.QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter_fn(p, size)
        p.end()
        ic.addPixmap(pm)
    _cache[key] = ic
    return ic


def _ball(p, size, colour):
    r = QtCore.QRectF(size * 0.12, size * 0.12, size * 0.76, size * 0.76)
    g = QtGui.QRadialGradient(r.center() - QtCore.QPointF(size * 0.12, size * 0.12), size * 0.5)
    c = QtGui.QColor(colour)
    g.setColorAt(0.0, c.lighter(170))
    g.setColorAt(1.0, c.darker(115))
    p.setBrush(QtGui.QBrush(g))
    p.setPen(QtGui.QPen(QtGui.QColor("#404040"), max(1.0, size / 16.0)))
    p.drawEllipse(r)


def ball_icon(colour):
    return _pixmaps(("ball", colour), lambda p, s: _ball(p, s, colour))


def state_icon(state):
    """ Ball in the ATK colour of a DevState (or its name) """
    bg, _ = state_colors(state)
    return ball_icon(bg)


def host_icon(state):
    """ Astor-like host icon for a host state ("running", "alarm", ...) """
    colour = HOST_COLORS.get(state, HOST_COLORS["unknown"])

    def paint(p, s):
        pen = QtGui.QPen(QtGui.QColor("#303030"), max(1.0, s / 16.0))
        p.setPen(pen)
        p.setBrush(QtGui.QColor("#d8dce4"))
        screen = QtCore.QRectF(s * 0.06, s * 0.1, s * 0.88, s * 0.62)
        p.drawRoundedRect(screen, s * 0.08, s * 0.08)
        p.setBrush(QtGui.QColor(colour))
        inner = screen.adjusted(s * 0.1, s * 0.1, -s * 0.1, -s * 0.1)
        p.drawRect(inner)
        p.setBrush(QtGui.QColor("#606060"))
        p.drawRect(QtCore.QRectF(s * 0.38, s * 0.72, s * 0.24, s * 0.1))
        p.drawRect(QtCore.QRectF(s * 0.22, s * 0.82, s * 0.56, s * 0.08))
        if state == "unreachable":
            p.setPen(QtGui.QPen(QtGui.QColor("#c00000"), max(2.0, s / 8.0)))
            p.drawLine(QtCore.QPointF(s * 0.15, s * 0.15), QtCore.QPointF(s * 0.85, s * 0.85))
    return _pixmaps(("host", state), paint)
