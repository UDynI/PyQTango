# -*- coding: utf-8 -*-
"""
Readable error records built from tango.DevFailed (or any exception).
"""

import time
from dataclasses import dataclass, field
from html import escape

try:
    import tango
except ImportError:  # pragma: no cover - PyTango is a hard dependency at runtime
    tango = None


@dataclass
class ErrorItem:
    reason: str
    desc: str
    origin: str = ""
    severity: str = ""


@dataclass
class ErrorRecord:
    """ One error with its full Tango stack """
    source: str
    items: list
    timestamp: float = field(default_factory=time.time)
    exception: object = None

    @property
    def reason(self):
        return self.items[0].reason if self.items else ""

    @property
    def message(self):
        """ Most useful one-line description (the first desc of the stack) """
        return self.items[0].desc.strip() if self.items else ""

    def text(self):
        lines = []
        if self.source:
            lines.append(self.source)
        for i, it in enumerate(self.items):
            lines.append("[{0}] {1}".format(i, it.reason))
            lines.append("    desc:     " + it.desc.strip().replace("\n", "\n              "))
            if it.origin:
                lines.append("    origin:   " + it.origin.strip())
            if it.severity:
                lines.append("    severity: " + it.severity)
        return "\n".join(lines)

    def html(self):
        rows = []
        for it in self.items:
            rows.append("<tr><td><b>{0}</b></td><td>{1}</td><td><small>{2}</small></td><td>{3}</td></tr>".format(
                escape(it.reason), escape(it.desc.strip()).replace("\n", "<br/>"), escape(it.origin.strip()),
                escape(it.severity)))
        return ("<p><b>{0}</b></p><table border='1' cellspacing='0' cellpadding='3'>"
                "<tr><th>Reason</th><th>Description</th><th>Origin</th><th>Severity</th></tr>{1}</table>").format(
            escape(self.source), "".join(rows))

    def __str__(self):
        return "{0}: {1}".format(self.reason, self.message) if self.items else self.source


def _severity_name(sev):
    try:
        return str(sev).split(".")[-1]
    except Exception:
        return ""


def error_from_exception(exc, source=""):
    """ Build an ErrorRecord from tango.DevFailed, a DevError sequence or any exception """
    items = []
    errs = None
    if tango is not None and isinstance(exc, tango.DevFailed):
        errs = exc.args
    elif isinstance(exc, (list, tuple)):
        errs = exc
    if errs:
        for e in errs:
            if hasattr(e, "reason"):
                items.append(ErrorItem(str(e.reason), str(e.desc), str(e.origin), _severity_name(e.severity)))
            else:
                items.append(ErrorItem(type(e).__name__, str(e)))
    elif exc is not None:
        items.append(ErrorItem(type(exc).__name__, str(exc)))
    return ErrorRecord(source=source, items=items, exception=exc)
