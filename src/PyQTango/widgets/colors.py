# -*- coding: utf-8 -*-
"""
Qt helpers for the ATK state and quality colours.
"""

from ..qt import QtGui
from ..core.formatting import state_colors, quality_color

STATE_STYLE_COMMON = "border-radius:3px;border: 1px solid black;"


def state_style(state):
    """ Style sheet for a label showing a DevState (same look as QAttribute 0.1) """
    bg, fg = state_colors(state)
    return "{0}background-color: {1};color: {2};".format(STATE_STYLE_COMMON, bg, fg)


def state_qcolors(state):
    bg, fg = state_colors(state)
    return QtGui.QColor(bg), QtGui.QColor(fg)


def quality_qcolor(quality):
    return QtGui.QColor(quality_color(quality))
