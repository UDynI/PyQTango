# -*- coding: utf-8 -*-
"""
QValueLabel: generic read-only viewer for any attribute (ATK SimpleScalarViewer).
"""

import tango

from ..qt import QtWidgets, Qt, Property
from ..core.formatting import format_value, quality_color, state_colors
from .base import TangoAttributeWidget, model_name_property

_NO_UNIT = ("", "No unit", "Not specified")


class QValueLabel(TangoAttributeWidget, QtWidgets.QLabel):
    """ Formatted value with unit and a quality marker.

    * numbers use the attribute's Tango ``format``; ``formatOverride`` replaces it
    * enums show their label, states their name on the state colour
    * spectra and images show the first ``maxItems`` values
    * quality: a coloured left border (``qualityStyle="border"``, default) or an
      ATK-like background (``qualityStyle="background"``); ``showQuality=False``
      disables it
    * the read value is shown; ``showSetPoint=True`` appends the set point
    """

    modelName = model_name_property()

    def __init__(self, parent=None):
        QtWidgets.QLabel.__init__(self, parent)
        TangoAttributeWidget.__init__(self)
        self._show_unit = True
        self._show_quality = True
        self._show_setpoint = False
        self._quality_style = "border"
        self._format = ""
        self._max_items = 20
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setText("-")

    # -- Properties -------------------------------------------------------------
    def getShowUnit(self):
        return self._show_unit

    def setShowUnit(self, v):
        self._show_unit = bool(v)
        self._refresh()

    showUnit = Property(bool, getShowUnit, setShowUnit)

    def getShowQuality(self):
        return self._show_quality

    def setShowQuality(self, v):
        self._show_quality = bool(v)
        self._refresh()

    showQuality = Property(bool, getShowQuality, setShowQuality)

    def getShowSetPoint(self):
        return self._show_setpoint

    def setShowSetPoint(self, v):
        self._show_setpoint = bool(v)
        self._refresh()

    showSetPoint = Property(bool, getShowSetPoint, setShowSetPoint)

    def getQualityStyle(self):
        return self._quality_style

    def setQualityStyle(self, v):
        self._quality_style = "background" if v == "background" else "border"
        self._refresh()

    qualityStyle = Property(str, getQualityStyle, setQualityStyle)

    def getFormatOverride(self):
        return self._format

    def setFormatOverride(self, fmt):
        self._format = fmt or ""
        self._refresh()

    formatOverride = Property(str, getFormatOverride, setFormatOverride)

    def getMaxItems(self):
        return self._max_items

    def setMaxItems(self, n):
        self._max_items = int(n)
        self._refresh()

    maxItems = Property(int, getMaxItems, setMaxItems)

    # -- Rendering ----------------------------------------------------------------
    def text_for(self, raw):
        cfg = self.attributeConfig()
        if cfg is None:
            return format_value(raw, self._format, max_items=self._max_items)
        unit = cfg.unit if (self._show_unit and cfg.unit not in _NO_UNIT) else ""
        fmt = self._format or cfg.format
        return format_value(raw, fmt, cfg.data_type, list(cfg.enum_labels or []), unit, max_items=self._max_items)

    def _refresh(self):
        value = self.attributeValue()
        if value is not None:
            self.on_value(value)

    def on_config(self, cfg):
        self.setToolTip(self.tooltip_text())
        self._refresh()

    def on_value(self, value):
        text = self.text_for(value.value)
        if self._show_setpoint and value.w_value is not None:
            text += "  (set: {0})".format(self.text_for(value.w_value))
        self.setText(text)
        self.setStyleSheet(self._style(value))
        self.setToolTip(self.tooltip_text())

    def _style(self, value):
        cfg = self.attributeConfig()
        if cfg is not None and cfg.data_type == tango.CmdArgType.DevState and cfg.data_format == tango.AttrDataFormat.SCALAR:
            bg, fg = state_colors(value.value)
            return "background-color: {0}; color: {1}; padding: 1px 4px;".format(bg, fg)
        if not self._show_quality:
            return "padding: 1px 4px;"
        color = quality_color(value.quality)
        if self._quality_style == "background":
            return "background-color: {0}; padding: 1px 4px;".format(color)
        if value.quality == tango.AttrQuality.ATTR_VALID:
            # (Qt only paints a QLabel border when the style also sets a background)
            return "border-left: 4px solid {0}; background-color: transparent; padding: 1px 4px;".format(color)
        # Non-valid: border plus a light tint so it stands out
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        return "border-left: 4px solid {0}; background-color: rgba({1},{2},{3},64); padding: 1px 4px;".format(
            color, r, g, b)

    def on_error(self, err):
        if err is not None:
            self.setText("#Err")
            self.setStyleSheet("border-left: 4px solid #808080; color: #808080; padding: 1px 4px;")
        self.setToolTip(self.tooltip_text())

    def on_model_cleared(self):
        self.setText("-")
        self.setStyleSheet("")
        self.setToolTip("")
