# -*- coding: utf-8 -*-
"""
Tango name helpers.

Accepted attribute name forms::

    dom/fam/mem/attr
    tango://host:port/dom/fam/mem/attr
    tango://host:port/dom/fam/mem/attr#dbase=no
    //host:port/dom/fam/mem/attr
"""

import re

_PREFIX_RE = re.compile(r"^(?P<scheme>tango:)?(?P<host>//[^/]+/)?(?P<path>[^#]*)(?P<frag>#.*)?$", re.IGNORECASE)

_DEV_FIELD = r"[A-Za-z0-9_.\-]+"
_DEVICE_RE = re.compile(r"^(tango:)?(//[A-Za-z0-9_.\-]+:[0-9]+/)?{0}/{0}/{0}$".format(_DEV_FIELD))
_SERVER_RE = re.compile(r"^{0}/{0}$".format(_DEV_FIELD))


def split_attribute_name(name):
    """ Split a full attribute name into (device_name, attribute_name).

    The device part keeps the host prefix and the ``#dbase=no`` fragment so it
    can be passed to ``tango.DeviceProxy`` as is.
    """
    name = name.strip()
    m = _PREFIX_RE.match(name)
    if m is None:
        raise ValueError("Invalid attribute name '{0}'".format(name))
    path = m.group("path")
    parts = path.split("/")
    if len(parts) != 4 or not all(parts):
        raise ValueError("Attribute name '{0}' must be <domain>/<family>/<member>/<attribute>".format(name))
    prefix = (m.group("scheme") or "") + (m.group("host") or "")
    frag = m.group("frag") or ""
    device = prefix + "/".join(parts[:3]) + frag
    return device, parts[3]


def device_of(attribute_name):
    """ Device name part of a full attribute name """
    return split_attribute_name(attribute_name)[0]


def normalize_name(name):
    """ Case-insensitive key for a device or attribute name """
    name = name.strip().lower()
    if name.startswith("tango:"):
        name = name[6:]
    return name


def is_device_name(name):
    """ Port of JiveUtils.isDeviceName(): dom/fam/mem with optional //host:port/ prefix """
    if len(name) < 5 or " " in name:
        return False
    return _DEVICE_RE.match(name) is not None


def is_full_server_name(name):
    """ Port of JiveUtils.isFullServerName(): Server/instance """
    return _SERVER_RE.match(name) is not None


def wildcard_to_regex(pattern, case_sensitive=False):
    """ Convert a ``*`` wildcard pattern into a compiled full-match regex """
    if pattern in ("", "*"):
        return re.compile(r".*", re.DOTALL)
    rx = "".join(".*" if c == "*" else re.escape(c) for c in pattern)
    return re.compile("^" + rx + "$", 0 if case_sensitive else re.IGNORECASE)


def wildcard_to_sql_like(pattern):
    """ Convert a ``*`` wildcard pattern into an escaped SQL LIKE pattern.

    ``'`` is doubled, ``%``, ``_`` and ``\\`` are escaped, ``*`` becomes ``%``.
    Use with ``LIKE '<result>'`` (MySQL's default escape character is ``\\``).
    """
    out = []
    for c in pattern:
        if c == "*":
            out.append("%")
        elif c in ("%", "_", "\\"):
            out.append("\\" + c)
        elif c == "'":
            out.append("''")
        else:
            out.append(c)
    return "".join(out)
