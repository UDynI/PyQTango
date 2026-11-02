# -*- coding: utf-8 -*-
"""
Value formatting and the ATK colour conventions (no Qt dependency).

Colours are ``#rrggbb`` strings so they can be used in style sheets or passed to
``QColor``.
"""

import re
import numpy as np
import tango

#: ATK state colours (background, foreground), see ATKConstant.java
STATE_COLORS = {
    tango.DevState.ON: ("#00ff00", "#000000"),
    tango.DevState.OFF: ("#ffffff", "#000000"),
    tango.DevState.CLOSE: ("#ffffff", "#000000"),
    tango.DevState.OPEN: ("#00ff00", "#000000"),
    tango.DevState.INSERT: ("#ffffff", "#000000"),
    tango.DevState.EXTRACT: ("#00ff00", "#000000"),
    tango.DevState.MOVING: ("#80a0ff", "#000000"),
    tango.DevState.STANDBY: ("#ffff00", "#000000"),
    tango.DevState.FAULT: ("#ff0000", "#000000"),
    tango.DevState.INIT: ("#cccc7a", "#000000"),
    tango.DevState.RUNNING: ("#007d00", "#ffffff"),
    tango.DevState.ALARM: ("#ff8c00", "#000000"),
    tango.DevState.DISABLE: ("#ff00ff", "#000000"),
    tango.DevState.UNKNOWN: ("#9b9b9b", "#000000"),
}

#: ATK quality colours
QUALITY_COLORS = {
    tango.AttrQuality.ATTR_VALID: "#00ff00",
    tango.AttrQuality.ATTR_INVALID: "#808080",
    tango.AttrQuality.ATTR_ALARM: "#ffc800",
    tango.AttrQuality.ATTR_WARNING: "#ffc800",
    tango.AttrQuality.ATTR_CHANGING: "#80a0ff",
}

_FMT_RE = re.compile(r"%[-+ #0]*\d*(\.\d+)?[diouxXeEfFgGs]")

_INT_TYPES = (tango.CmdArgType.DevShort, tango.CmdArgType.DevLong, tango.CmdArgType.DevLong64,
              tango.CmdArgType.DevUShort, tango.CmdArgType.DevULong, tango.CmdArgType.DevULong64,
              tango.CmdArgType.DevUChar)
_FLOAT_TYPES = (tango.CmdArgType.DevFloat, tango.CmdArgType.DevDouble)


def is_int_type(data_type):
    return data_type in _INT_TYPES


def is_float_type(data_type):
    return data_type in _FLOAT_TYPES


def is_numeric_type(data_type):
    return data_type in _INT_TYPES or data_type in _FLOAT_TYPES


def state_name(state):
    try:
        return str(tango.DevState(state))
    except Exception:
        return str(state)


def quality_name(quality):
    try:
        return str(tango.AttrQuality(quality))
    except Exception:
        return str(quality)


def state_colors(state):
    """ (background, foreground) for a DevState """
    try:
        return STATE_COLORS[tango.DevState(state)]
    except Exception:
        return STATE_COLORS[tango.DevState.UNKNOWN]


def quality_color(quality):
    try:
        return QUALITY_COLORS[tango.AttrQuality(quality)]
    except Exception:
        return QUALITY_COLORS[tango.AttrQuality.ATTR_INVALID]


def _valid_format(fmt):
    return bool(fmt) and fmt.lower() not in ("not specified", "") and _FMT_RE.search(fmt) is not None


def format_scalar(value, fmt="", data_type=None, enum_labels=None, unit=""):
    """ Format one scalar value with a Tango (C printf) format string.

    Falls back to ``str()`` when the format does not apply to the value.
    """
    if value is None:
        text = "-"
    elif data_type == tango.CmdArgType.DevState or isinstance(value, tango.DevState):
        text = state_name(value)
    elif data_type == tango.CmdArgType.DevEnum and enum_labels:
        try:
            text = enum_labels[int(value)]
        except (IndexError, ValueError, TypeError):
            text = str(value)
    elif isinstance(value, (bool, np.bool_)):
        text = str(bool(value))
    elif isinstance(value, (str, bytes)):
        text = value.decode(errors="replace") if isinstance(value, bytes) else value
    elif _valid_format(fmt):
        try:
            text = fmt % value
        except (TypeError, ValueError):
            try:
                text = fmt % float(value)
            except (TypeError, ValueError):
                text = str(value)
    else:
        text = str(value)
    if unit and unit.lower() not in ("not specified", "no unit"):
        text = text + " " + unit
    return text


def format_value(value, fmt="", data_type=None, enum_labels=None, unit="", max_items=None):
    """ Format a scalar, spectrum or image value as text """
    if isinstance(value, np.ndarray) or isinstance(value, (list, tuple)):
        arr = np.asarray(value, dtype=object) if not isinstance(value, np.ndarray) else value
        flat = list(arr.ravel())
        if max_items is not None and len(flat) > max_items:
            flat = flat[:max_items]
            suffix = ", ..."
        else:
            suffix = ""
        items = [format_scalar(v, fmt, data_type, enum_labels) for v in flat]
        text = "[" + ", ".join(items) + suffix + "]"
        if unit and unit.lower() not in ("not specified", "no unit"):
            text += " " + unit
        return text
    return format_scalar(value, fmt, data_type, enum_labels, unit)


def format_digits(fmt, default=(4, 2)):
    """ (integer digits, decimals) suggested by a ``%w.pf`` / ``%wd`` format, for wheel editors """
    if not _valid_format(fmt):
        return default
    m = re.search(r"%[-+ #0]*(\d*)(?:\.(\d+))?([diouxXeEfFgG])", fmt)
    if m is None:
        return default
    width = int(m.group(1)) if m.group(1) else 0
    prec = int(m.group(2)) if m.group(2) else 0
    conv = m.group(3).lower()
    if conv in ("d", "i", "u", "o", "x"):
        return (width if width else default[0], 0)
    if conv == "f":
        ints = width - prec - 1 if width else default[0]
        return (max(ints, 1), prec)
    return default
