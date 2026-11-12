# -*- coding: utf-8 -*-
"""
Device black box, parsed (Astor's BlackBoxTable and TopDialog), without Qt.

A black box line (newest first) reads::

    11/11/2026 08:06:07:36 : Operation read_attributes_5 (State, Status) from cache_device
        requested from vm (CPP/Python client with PID 195)
    11/11/2026 08:06:07:36 : Operation command_inout_4 (cmd = State) from device requested from ...
    11/11/2026 08:06:07:36 : Attribute state requested from vm
    11/11/2026 08:06:07:36 : Operation command_list_query_2 requested from vm

and becomes a :class:`BlackBoxRecord` (date, operation, name, source, host,
process). Calls to ``black_box`` itself are dropped, as Astor does.
"""

import re
from collections import Counter
from dataclasses import dataclass

__all__ = ["BlackBoxRecord", "parse_black_box", "BlackBox", "COLUMNS", "top", "span_seconds", "span_text"]

COLUMNS = ("Date", "Operation", "Name", "Source", "Host", "Process")

_NO_PARAM = ("command_list_query", "get_attribute_config", "ping", "adm_name")
_DATE = re.compile(r"^\s*(\d+/\d+/\d+ \d+:\d+:\d+:\d+)\s*:\s*")


@dataclass(frozen=True)
class BlackBoxRecord:
    date: str
    operation: str
    name: str
    source: str
    host: str
    process: str
    line: str = ""

    def values(self):
        return (self.date, self.operation, self.name, self.source, self.host, self.process)

    def key(self):
        """ What identifies a record when merging two reads (the text line) """
        return self.line or "\t".join(self.values())


def _word(text):
    """ First word of ``text``, without the parentheses Astor strips """
    parts = text.split()
    if not parts:
        return ""
    w = parts[0]
    if w.startswith("("):
        w = w[1:]
    i = w.find(")")
    return w[:i] if i > 0 else w


def parse_line(line):
    """ One black box line -> BlackBoxRecord, or None (unparsable, or a black_box call) """
    m = _DATE.match(line)
    if not m:
        return None
    date = m.group(1)
    rest = line[m.end():]
    kind = _word(rest)
    rest = rest[len(rest) - len(rest.lstrip()) + len(kind):].lstrip()
    if kind == "Operation":
        operation = _word(rest)
        rest = rest[len(operation):].lstrip()
    elif kind == "Attribute":
        operation = "CORBA Attribute"
    else:
        operation = kind
    if operation.startswith("blackbox"):
        return None
    name = ""
    if not operation.startswith(_NO_PARAM):
        m2 = re.match(r"\(([^)]*)\)", rest)
        if m2:
            name = m2.group(1).strip()
            if name.startswith("cmd ="):
                name = name[5:].strip()
            elif name.startswith("attributes ="):
                name = name[12:].strip()
        elif kind == "Attribute":
            name = _word(rest)
    if "from cache_device" in line:
        source = "cache_device"
    elif "from cache" in line:
        source = "cache"
    else:
        source = "device"
    host = ""
    if "requested from polling" in line or "requested form polling" in line:
        host = "polling"
    else:
        i = line.find("requested from ")
        if i > 0:
            host = _word(line[i + len("requested from "):]).split(".")[0]
    process = ""
    low = line.lower()
    j = low.find("java client with main class")
    if j > 0:
        process = line[j + len("java client with main class"):].split(")")[0].strip()
    else:
        j = low.find("cpp/python client with pid")
        if j > 0:
            process = "PID=" + _word(line[j + len("cpp/python client with pid"):])
    return BlackBoxRecord(date, operation, name, source, host, process, line)


def parse_black_box(lines):
    """ black_box() strings (newest first) -> [BlackBoxRecord] (newest first) """
    out = []
    for line in lines or ():
        r = parse_line(str(line))
        if r is not None:
            out.append(r)
    return out


def _seconds(date):
    """ "dd/mm/yyyy hh:mm:ss:cc" -> seconds of the day (0 when unreadable) """
    t = date.split(" ")[-1].split(":")
    try:
        h, m, s, c = (int(x) for x in t[:4])
    except ValueError:
        return 0.0
    return 3600 * h + 60 * m + s + c / 100.0


def span_seconds(records):
    """ Time between the oldest and the newest record (records newest first) """
    if not records:
        return 0.0
    start, stop = _seconds(records[-1].date), _seconds(records[0].date)
    while stop < start:
        stop += 24 * 3600
    return stop - start


def span_text(seconds):
    """ Astor's duration text: "12.340 sec.", "02:05.000", "01:00:05.000" """
    whole = int(seconds)
    millis = int(round(1000 * (seconds - whole)))
    if millis == 1000:
        whole, millis = whole + 1, 0
    h, rest = divmod(whole, 3600)
    m, s = divmod(rest, 60)
    if h:
        return "{0:02d}:{1:02d}:{2:02d}.{3:03d}".format(h, m, s, millis)
    if m:
        return "{0:02d}:{1:02d}.{2:03d}".format(m, s, millis)
    return "{0:02d}.{1:03d} sec.".format(s, millis)


def top(records, column):
    """ [(value, count)] of one column ("Operation", "Name", "Source", "Host" or "Process"),
    most frequent first (Astor's Top) """
    idx = COLUMNS.index(column)
    counts = Counter(r.values()[idx] for r in records if r.values()[idx])
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))


class BlackBox:
    """ Records accumulated over successive reads (auto-update): each read is merged on top
    of what is already there, so records the device dropped from its ring stay visible """

    def __init__(self, limit=10000):
        self.records = []
        self.limit = limit
        #: False when the last read did not overlap the previous one (records were lost)
        self.contiguous = True

    def update(self, lines):
        new = parse_black_box(lines)
        if not self.records:
            self.records = new[:self.limit]
            self.contiguous = True
            return len(self.records)
        # Find where the known records start in the new read: match the newest few in a
        # row, not only the newest one (identical lines in the same centisecond would
        # otherwise be taken as already seen). Near the end of the read the black box may
        # have dropped the older ones: a shorter match at the tail is accepted.
        anchor = [r.key() for r in self.records[:5]]
        keys = [r.key() for r in new]
        pos = None
        for i in range(len(keys)):
            n = min(len(anchor), len(keys) - i)
            if keys[i:i + n] == anchor[:n]:
                pos = i
                break
        if pos is not None:
            fresh = new[:pos]
            self.contiguous = True
        else:
            fresh = new
            self.contiguous = False
        self.records = (fresh + self.records)[:self.limit]
        return len(fresh)

    def clear(self):
        self.records = []
        self.contiguous = True
