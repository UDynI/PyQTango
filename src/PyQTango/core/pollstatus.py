# -*- coding: utf-8 -*-
"""
Polling status of a device, as the polling profiler sees it (Astor's
DevPollStatus and PolledElement), without Qt.

The admin device's ``DevPollStatus <device>`` returns one block per polled
object::

    Polled attribute name = Servers
    Polling period (mS) = 500
    Polling ring buffer depth = 10
    Time needed for the last attribute reading (mS) = 0.379
    Data not updated since 14 mS
    Delta between last records (in mS) = 499, 499, 499, 500

"Polling externally triggered" replaces the period line for objects filled by
the device itself. An element is FAULT when its last delta exceeds 1.5 times
the period or a reading takes longer than the period (Astor's rule).
"""

import re
from dataclasses import dataclass, field

__all__ = ["PolledElement", "parse_poll_status", "read_poll_status", "drifts"]


@dataclass
class PolledElement:
    device: str
    name: str
    kind: str = "attribute"                 # "attribute" or "command"
    polled: bool = True                     # False: externally triggered
    period: int = -1                        # ms
    depth: int = -1
    duration: float = -1.0                  # ms, last reading
    last_update: int = -1                   # ms since the last update
    last_update_text: str = ""
    deltas: list = field(default_factory=list)   # ms between the last records, newest first
    several: bool = False                   # read with other attributes ("attributes reading")
    text: str = ""

    @property
    def state(self):
        """ "ON" or "FAULT" """
        if not self.polled:
            return "ON" if self.duration >= 0 else "FAULT"
        if self.period < 0 or self.depth < 0 or self.duration < 0 or not self.deltas:
            return "FAULT"
        if self.deltas[0] > 1.5 * self.period or self.duration > self.period:
            return "FAULT"
        return "ON"

    @property
    def full_name(self):
        return "{0}/{1}".format(self.device, self.name)

    def drifts(self):
        """ delta - period for each recorded delta (ms) """
        return drifts(self)


def drifts(element):
    return [d - element.period for d in element.deltas] if element.polled and element.period > 0 else []


def _value(line):
    return line.split("=", 1)[1].strip() if "=" in line else ""


def _int(text, default=-1):
    try:
        return int(text)
    except ValueError:
        return default


def _since_ms(line):
    """ "Data not updated since 1 S and 14 mS" / "since 2 mn, 3 S and 4 mS" -> ms """
    m = re.search(r"since (.*)$", line)
    if not m:
        return -1, ""
    text = m.group(1).strip()
    total = 0
    for value, unit in re.findall(r"(\d+)\s*(mn|mS|ms|S|s|h)\b", text):
        v = int(value)
        total += {"h": 3600000, "mn": 60000, "S": 1000, "s": 1000}.get(unit, 1) * v
    return total, text


def parse_block(device, text):
    lines = [l for l in str(text).split("\n")]
    e = PolledElement(device, _value(lines[0]) if lines else "", text=str(text))
    e.kind = "attribute" if lines and "attribute" in lines[0].split("=")[0] else "command"
    for line in lines[1:]:
        if line.startswith("Polling externally triggered"):
            e.polled = False
        elif line.startswith("Polling period"):
            e.period = _int(_value(line))
        elif line.startswith("Polling ring buffer depth"):
            e.depth = _int(_value(line))
        elif line.startswith("Time needed for the last"):
            e.several = "attributes reading" in line
            try:
                e.duration = float(_value(line))
            except ValueError:
                e.duration = 0.0
        elif "not updated since" in line:
            e.last_update, e.last_update_text = _since_ms(line)
        elif line.startswith("Delta between last records"):
            e.deltas = [_int(x.strip(), 0) for x in _value(line).split(",") if x.strip()]
    return e


def parse_poll_status(device, lines):
    """ DevPollStatus strings -> [PolledElement] (one per object, first block wins) """
    out, seen = [], set()
    for text in lines or ():
        e = parse_block(device, text)
        key = (e.kind, e.name.lower())
        if e.name and key not in seen:
            seen.add(key)
            out.append(e)
    return out


def read_poll_status(admin_proxy, devices):
    """ Blocking: [PolledElement] of each device, through its admin device's DevPollStatus """
    out = []
    for dev in devices:
        out += parse_poll_status(dev, admin_proxy.command_inout("DevPollStatus", dev))
    return out
