# -*- coding: utf-8 -*-
"""
Starter helpers without Qt: the Servers attribute, host states, Starter logs.

Formats follow the Starter 9.1 sources (plan section 3.6):

* ``Servers``: one line per server, tab separated: name, DevStateName (ON,
  MOVING or FAULT), controlled (0/1), startup level, number of instances.
* Starter ``State``: ON all controlled servers running; MOVING one starting;
  STANDBY moving longer than MovingMaxDuration; ALARM some stopped or one
  running twice; OFF all stopped. The Starter never reports FAULT: a host is
  "unreachable" when its Starter does not answer.
* ``DevReadLog("Starter")``: newest first, ``dd/mm/yy   hh:mm:ss<TAB>message``.
* ``DevReadLog("Statistics")``: newest first,
  ``server<TAB>ON|FAULT<TAB>started<TAB>failed<TAB>auto``.
* ``DevReadLog(<server>)``: two header lines (file name, modification date), a
  blank line, then the server's standard output and error.

@author: Michele Devetta <michele.devetta@cnr.it>
"""

import datetime
from dataclasses import dataclass

__all__ = ["ServerLine", "parse_servers", "HOST_STATES", "host_state", "worst_state", "state_text",
           "LogLine", "parse_starter_log", "StatLine", "parse_statistics", "split_server_log",
           "starter_device", "host_of_starter", "STARTER_CLASS", "NOT_CONTROLLED"]

STARTER_CLASS = "Starter"

#: Level used for servers that are not controlled (shown last)
NOT_CONTROLLED = 0


@dataclass
class ServerLine:
    """ One line of the Starter ``Servers`` attribute """
    name: str
    state: str = "FAULT"          # ON, MOVING or FAULT
    controlled: bool = False
    level: int = 0
    instances: int = 0

    @property
    def running(self):
        return self.state == "ON"

    @property
    def twice(self):
        return self.instances > 1

    @property
    def effective_level(self):
        """ Startup level, or NOT_CONTROLLED (0) when the server is not controlled """
        return self.level if self.controlled and self.level > 0 else NOT_CONTROLLED

    def to_line(self):
        return "{0}\t{1}\t{2}\t{3}\t{4}".format(self.name, self.state, int(self.controlled), self.level,
                                                self.instances)


def _int(text, default=0):
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return default


def parse_servers(lines):
    """ [ServerLine] from the ``Servers`` attribute value (lines or one string) """
    if lines is None:
        return []
    if isinstance(lines, str):
        lines = lines.splitlines()
    out = []
    for line in lines:
        f = str(line).split("\t")
        if not f or not f[0].strip():
            continue
        f += [""] * (5 - len(f))
        out.append(ServerLine(f[0].strip(), f[1].strip() or "FAULT", _int(f[2]) != 0, _int(f[3]),
                              _int(f[4])))
    return out


#: Host states, from best to worst (index = severity)
HOST_STATES = ("running", "unknown", "off", "moving", "blocked", "alarm", "unreachable")

_STATE_TEXT = {
    "running": "All controlled servers are running",
    "moving": "A server is starting (MOVING)",
    "blocked": "A server has been starting for too long (STANDBY)",
    "alarm": "Some controlled servers are stopped, or one runs twice (ALARM)",
    "off": "All controlled servers are stopped (OFF)",
    "unreachable": "The Starter does not answer",
    "unknown": "State not read yet",
}


def host_state(starter_state, reachable=True):
    """ Host state from the Starter State (tango.DevState or its name) """
    if not reachable:
        return "unreachable"
    if starter_state is None:
        return "unknown"
    name = str(starter_state).split(".")[-1].upper()
    return {"ON": "running", "MOVING": "moving", "STANDBY": "blocked", "ALARM": "alarm",
            "OFF": "off"}.get(name, "unknown")


def worst_state(states):
    """ The worst of several host states (a branch shows its worst host); "unknown" when empty """
    states = list(states)
    if not states:
        return "unknown"
    return max(states, key=lambda s: HOST_STATES.index(s) if s in HOST_STATES else 1)


def state_text(state):
    return _STATE_TEXT.get(state, state)


@dataclass
class LogLine:
    time: datetime.datetime
    message: str
    text: str


def _parse_time(text):
    text = " ".join(text.split())
    for fmt in ("%d/%m/%y %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def parse_starter_log(text):
    """ [LogLine] (newest first, as the Starter writes them) from DevReadLog("Starter") """
    out = []
    for line in (text or "").replace("\x00", "").splitlines():
        if not line.strip():
            continue
        stamp, _, msg = line.partition("\t")
        out.append(LogLine(_parse_time(stamp), msg.strip(), line))
    return out


@dataclass
class StatLine:
    server: str
    state: str
    started: float
    failed: float
    auto: bool


def parse_statistics(text):
    """ [StatLine] from DevReadLog("Statistics") (times as seconds since the epoch, 0 when absent) """
    out = []
    for line in (text or "").replace("\x00", "").splitlines():
        f = line.split("\t")
        if len(f) < 2 or not f[0].strip():
            continue
        f += ["0"] * (5 - len(f))

        def num(x):
            try:
                return float(x)
            except ValueError:
                return 0.0
        out.append(StatLine(f[0].strip(), f[1].strip(), num(f[2]), num(f[3]), str(f[4]).strip() in ("1", "true")))
    return out


def split_server_log(text):
    """ (file name, modification date, body) of DevReadLog(<server>) """
    lines = (text or "").replace("\x00", "").split("\n")
    name = lines[0] if lines else ""
    date = lines[1] if len(lines) > 1 else ""
    body = "\n".join(lines[3:] if len(lines) > 2 and not lines[2].strip() else lines[2:])
    return name, date, body


def starter_device(host, domain="tango"):
    """ Starter device of a host: ``<domain>/admin/<short host name>`` """
    return "{0}/admin/{1}".format(domain, host.split(".")[0])


def host_of_starter(device):
    """ Host name of a Starter device (its member) """
    return device.rstrip("/").split("/")[-1]
