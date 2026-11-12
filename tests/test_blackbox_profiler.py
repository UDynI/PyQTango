# -*- coding: utf-8 -*-
""" Black box and polling profiler: parsers (real Tango 10 lines) and widgets on a live device """

import pytest
import tango

from PyQTango.core.blackbox import parse_black_box, parse_line, BlackBox, top, span_seconds, span_text
from PyQTango.core.pollstatus import parse_poll_status
from conftest import wait

pytestmark = pytest.mark.usefixtures("no_tango_in_gui_thread")

LINES = [
    "11/11/2026 08:06:07:36 : Operation read_attributes_5 (State, Status) from cache_device requested from "
    "vm (CPP/Python client with PID 195)",
    "11/11/2026 08:06:07:30 : Operation command_inout_4 (cmd = State) from device requested from "
    "vm.esrf.fr (CPP/Python client with PID 195)",
    "11/11/2026 08:06:07:20 : Operation command_list_query_2 requested from vm",
    "11/11/2026 08:06:06:10 : Operation blackbox requested from vm",
    "11/11/2026 08:06:05:00 : Attribute state requested from pc1 (Java client with main class jive3.MainPanel)",
    "11/11/2026 08:06:04:00 : Operation read_attributes_5 (Servers) from device requested from polling",
    "garbage",
]


def test_black_box_parser():
    recs = parse_black_box(LINES)
    assert [r.values() for r in recs] == [
        ("11/11/2026 08:06:07:36", "read_attributes_5", "State, Status", "cache_device", "vm", "PID=195"),
        ("11/11/2026 08:06:07:30", "command_inout_4", "State", "device", "vm", "PID=195"),
        ("11/11/2026 08:06:07:20", "command_list_query_2", "", "device", "vm", ""),
        ("11/11/2026 08:06:05:00", "CORBA Attribute", "state", "device", "pc1", "jive3.MainPanel"),
        ("11/11/2026 08:06:04:00", "read_attributes_5", "Servers", "device", "polling", ""),
    ]
    assert parse_line("garbage") is None
    assert span_seconds(recs) == pytest.approx(3.36)
    assert span_text(3.36) == "03.360 sec." and span_text(125.5) == "02:05.500"
    assert span_text(3605) == "01:00:05.000"
    assert top(recs, "Host") == [("vm", 3), ("pc1", 1), ("polling", 1)]
    assert top(recs, "Operation")[0] == ("read_attributes_5", 2)


def test_black_box_merge():
    box = BlackBox()
    assert box.update(LINES[2:]) == 3
    # next read: two new records on top, overlapping the newest one we had
    assert box.update(LINES[:4]) == 2 and box.contiguous
    assert [r.name for r in box.records][:3] == ["State, Status", "State", ""]
    assert len(box.records) == 5
    # a read that no longer overlaps: everything is added and the gap is flagged
    new = ["11/11/2026 09:00:00:00 : Operation ping requested from vm"]
    assert box.update(new) == 1 and not box.contiguous


POLL = [
    "Polled command name = State\nPolling period (mS) = 1000\nPolling ring buffer depth = 10\n"
    "Time needed for the last command reading (mS) = 0.163\nData not updated since 509 mS\n"
    "Delta between last records (in mS) = 999, 999",
    "Polled attribute name = Servers\nPolling period (mS) = 500\nPolling ring buffer depth = 10\n"
    "Time needed for the last attribute reading (mS) = 0.379\nData not updated since 1 S and 14 mS\n"
    "Delta between last records (in mS) = 800, 499, 499, 500",
    "Polled attribute name = Slow\nPolling externally triggered\nPolling ring buffer depth = 10\n"
    "Time needed for the last attribute reading (mS) = 2\nData not updated since 2 mn, 3 S and 4 mS",
    "Polled attribute name = servers\nPolling period (mS) = 3000",
]


def test_poll_status_parser():
    els = parse_poll_status("a/b/c", POLL)
    assert [(e.kind, e.name, e.polled, e.period, e.depth, e.duration, e.last_update, e.deltas, e.state)
            for e in els] == [
        ("command", "State", True, 1000, 10, 0.163, 509, [999, 999], "ON"),
        ("attribute", "Servers", True, 500, 10, 0.379, 1014, [800, 499, 499, 500], "FAULT"),
        ("attribute", "Slow", False, -1, 10, 2.0, 123004, [], "ON"),
    ]
    assert els[0].drifts() == [-1, -1] and els[1].drifts()[0] == 300 and els[2].drifts() == []
    assert els[1].full_name == "a/b/c/Servers"


def in_thread(fn, *args):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(1) as ex:
        return ex.submit(fn, *args).result()


def test_black_box_view(qtbot, device_name):
    from PyQTango.widgets.blackbox import QBlackBoxDialog
    p = in_thread(tango.DeviceProxy, device_name)
    in_thread(lambda: [p.read_attribute("Status"), p.command_inout("State"), p.ping()])
    d = QBlackBoxDialog(device_name, depth=50)
    qtbot.addWidget(d)
    v = d.view
    wait(qtbot, lambda: v.records(), 10000)
    ops = {r.operation for r in v.records()}
    assert "read_attributes_5" in ops or "read_attributes_4" in ops
    assert all(r.operation != "blackbox" for r in v.records())
    # filter on one column
    v.column.setCurrentIndex(2)          # Operation
    v.filter.setText("command_inout")
    assert v.visible_rows() and all("command_inout" in r[1] for r in v.visible_rows())
    assert "shown" in v.info.text()
    top = v.show_top()
    assert dict(top.counts()["Operation"]).get(v.visible_rows()[0][1], 0) >= 1
    v.filter.clear()
    # auto update picks up new calls
    n = len(v.records())
    v.auto.setChecked(True)
    in_thread(lambda: [p.command_inout("State") for _ in range(3)])
    wait(qtbot, lambda: len(v.records()) >= n + 3, 10000)
    v.auto.setChecked(False)
    lines = []
    v.show_line = lines.append
    v._show_line(v.proxy.index(0, 0))
    assert lines and lines[0].startswith(v.records()[0].date)
    v.clear()
    assert v.records() == [] and v.visible_rows() == []


def test_polling_profiler(qtbot, device_name):
    from PyQTango.widgets.profiler import QPollingProfilerDialog
    p = in_thread(tango.DeviceProxy, device_name)
    in_thread(lambda: p.poll_attribute("Status", 200))
    try:
        qtbot.wait(1200)
        d = QPollingProfilerDialog([device_name])
        qtbot.addWidget(d)
        prof = d.profiler
        wait(qtbot, lambda: any(e.name.lower() == "status" for e in prof.elements), 10000)
        e = [e for e in prof.elements if e.name.lower() == "status"][0]
        assert e.period == 200 and e.deltas and e.polled
        assert any(r[1].lower() == "status" for r in prof.rows())
        for i in range(3):
            prof.mode.setCurrentIndex(i)            # every chart draws
        assert "Polling on:" in prof.title.text()
        failed = []
        prof.reader = lambda devs: (_ for _ in ()).throw(tango.DevFailed())
        prof.failed.connect(failed.append)
        prof.update_now()
        wait(qtbot, lambda: failed, 5000)
    finally:
        in_thread(lambda: p.stop_poll_attribute("Status"))
