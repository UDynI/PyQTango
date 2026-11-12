# -*- coding: utf-8 -*-
"""
Device polling: read the live polling state, change it, and edit the polling
settings kept in the database (port of Jive's TaskPollingNode).

Every function blocks on Tango: call them from a worker thread.

* Commands that take an argument cannot be polled and are not listed.
* Changing the period of a polled object calls ``poll_*`` again, which the
  device server treats as a period update.
* ``poll_old_factor`` and ``poll_ring_depth`` are device properties (defaults 4
  and 10); the device server reads them at startup.
"""

from collections import namedtuple

import tango

#: Period used when an object is polled without one (Jive's default)
DEFAULT_PERIOD_MS = 3000
DEFAULT_OLD_FACTOR = "4"
DEFAULT_RING_DEPTH = "10"
#: Database properties holding the polling configuration (deleted by :func:`reset_polling`)
POLLING_CONFIG_PROPERTIES = ("polled_attr", "polled_cmd", "non_auto_polled_cmd", "non_auto_polled_attr")

PollEntry = namedtuple("PollEntry", "kind name polled period external", defaults=(False,))
PollEntry.__doc__ = """ kind is "command" or "attribute"; period is a str, "" when not polled or
externally triggered (``external``: polled with no period, by the server's trigger_polling) """


def parse_polling_status(lines):
    """ ``polling_status()`` strings -> {(kind, lower name): period str}; the period is ""
    for externally triggered objects (polled, but with no period) """
    out = {}
    for text in lines or ():
        rows = str(text).split("\n")
        if len(rows) < 2:
            continue
        kind = "attribute" if rows[0].startswith("Polled attribute") else "command"
        name = rows[0].split("=", 1)[-1].strip()
        if "externally triggered" in rows[1].lower():
            period = ""
        else:
            period = rows[1].split("=", 1)[-1].strip()
        out[(kind, name.lower())] = period
    return out


def read_polling(proxy):
    """ (commands, attributes): lists of :class:`PollEntry` for a live device """
    status = parse_polling_status(proxy.polling_status())
    commands = [c.cmd_name for c in proxy.command_list_query() if c.in_type == tango.CmdArgType.DevVoid]
    attributes = sorted(proxy.get_attribute_list(), key=str.lower)

    def entries(kind, names):
        out = []
        for n in names:
            key = (kind, n.lower())
            period = status.get(key, "")
            out.append(PollEntry(kind, n, key in status, period, key in status and period == ""))
        return out
    return entries("command", commands), entries("attribute", attributes)


def parse_period(text):
    """ Period in ms from user text; "" gives the default. Raises ValueError """
    text = str(text).strip()
    if not text:
        return DEFAULT_PERIOD_MS
    value = int(text)
    if value <= 0:
        raise ValueError("the polling period must be a positive number of ms, not {0}".format(text))
    return value


def set_polling(proxy, kind, name, polled, period=""):
    """ Start (or change the period of) or stop the polling of one command or attribute """
    if polled:
        ms = parse_period(period)
        if kind == "command":
            proxy.poll_command(name, ms)
        else:
            proxy.poll_attribute(name, ms)
    elif kind == "command":
        proxy.stop_poll_command(name)
    else:
        proxy.stop_poll_attribute(name)


def read_polling_settings(dbs, device):
    """ (poll_old_factor, poll_ring_depth) as strings, defaults when not set """
    props = {k.lower(): v for k, v in dbs.device_properties(device).items()}

    def first(name, default):
        values = props.get(name)
        return values[0] if values else default
    return first("poll_old_factor", DEFAULT_OLD_FACTOR), first("poll_ring_depth", DEFAULT_RING_DEPTH)


def write_polling_setting(dbs, device, name, value):
    """ ``name`` is "poll_old_factor" or "poll_ring_depth" """
    if name not in ("poll_old_factor", "poll_ring_depth"):
        raise ValueError("unknown polling setting " + name)
    value = str(value).strip()
    if not value.isdigit() or int(value) <= 0:
        raise ValueError("{0} must be a positive integer, not '{1}'".format(name, value))
    dbs.put_device_property(device, {name: value})


def reset_polling(dbs, device):
    """ Remove the stored polling configuration (effective at the next server restart) """
    dbs.delete_device_property(device, POLLING_CONFIG_PROPERTIES)


__all__ = ["PollEntry", "DEFAULT_PERIOD_MS", "DEFAULT_OLD_FACTOR", "DEFAULT_RING_DEPTH",
           "POLLING_CONFIG_PROPERTIES", "parse_polling_status", "read_polling", "parse_period",
           "set_polling", "read_polling_settings", "write_polling_setting", "reset_polling"]
