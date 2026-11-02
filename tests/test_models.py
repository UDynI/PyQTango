# -*- coding: utf-8 -*-
""" Event-aware models against a live device server """

import pytest
import tango

from PyQTango.models import attribute_model, device_model, registry, refresher, error_history, run_async, Job
from PyQTango.models import MODE_EVENTS, MODE_POLLING
from conftest import attr, wait

pytestmark = pytest.mark.usefixtures("no_tango_in_gui_thread")


def test_events_mode(qtbot, device_name):
    m = attribute_model(attr(device_name, "ev_double"))
    values = []
    m.valueChanged.connect(lambda v: values.append(v.value))
    m.attach()
    wait(qtbot, lambda: m.mode() == MODE_EVENTS and values, timeout=5000)
    assert m.config().unit == "V"
    first = values[-1]
    device_model(device_name).execute("Push")
    wait(qtbot, lambda: values and values[-1] == first + 1.0, timeout=5000)
    assert not refresher().is_registered(m)
    m.release()


def test_polling_fallback_and_write(qtbot, device_name):
    m = attribute_model(attr(device_name, "rw_double"))
    values, writes = [], []
    m.valueChanged.connect(lambda v: values.append(v.value))
    m.writeDone.connect(writes.append)
    m.attach()
    wait(qtbot, lambda: m.mode() == MODE_POLLING and values, timeout=5000)
    assert refresher().is_registered(m)
    assert m.is_writable() and m.label() == "RW double"
    m.write(42.5)
    wait(qtbot, lambda: writes and values[-1] == 42.5, timeout=5000)
    assert writes[-1] is None
    m.write(1000.0)   # above max_value
    wait(qtbot, lambda: len(writes) == 2, timeout=5000)
    assert writes[-1] is not None and "range" in writes[-1].message.lower() or writes[-1].reason
    m.release()


def test_shared_model_and_release(qtbot, device_name):
    name = attr(device_name, "rw_long")
    a, b = attribute_model(name), attribute_model(name.upper().replace("TANGO://", "tango://"))
    assert a is b
    a.attach()
    b.attach()
    wait(qtbot, lambda: a.last_value() is not None, timeout=5000)
    a.release()
    qtbot.wait(300)
    assert a.mode() != "idle"           # still used once
    b.release()
    wait(qtbot, lambda: a.mode() == "idle", timeout=3000)
    assert not refresher().is_registered(a)
    assert attribute_model(name) is not a   # forgotten by the registry


def test_config_event(qtbot, device_name):
    m = attribute_model(attr(device_name, "rw_long"))
    labels = []
    m.configChanged.connect(lambda c: labels.append(c.label))
    m.attach()
    wait(qtbot, lambda: m.config() is not None, timeout=5000)

    def change_label():
        p = tango.DeviceProxy(device_name)
        cfg = p.get_attribute_config_ex(["rw_long"])[0]
        cfg.label = "Renamed"
        p.set_attribute_config([cfg])
    run_async(change_label)
    wait(qtbot, lambda: "Renamed" in labels, timeout=8000)
    m.release()


def test_errors(qtbot, device_name):
    m = attribute_model(attr(device_name, "does_not_exist"))
    errors = []
    m.errorChanged.connect(errors.append)
    m.attach()
    wait(qtbot, lambda: errors, timeout=5000)
    assert errors[0] is not None and errors[0].reason
    assert any(r.source.endswith("does_not_exist#dbase=no") or "does_not_exist" in r.source
               for r in error_history().records())
    m.shutdown()


def test_device_model_commands(qtbot, device_name):
    d = device_model(device_name)
    cmds, done, failed = [], [], []
    d.commandsChanged.connect(cmds.append)
    d.load_commands()
    wait(qtbot, lambda: cmds, timeout=5000)
    assert {"Echo", "Sum", "Push", "Fail"} <= {c.cmd_name for c in cmds[0]}
    t = d.execute("Sum", [1.0, 2.0, 3.5])
    t.done.connect(done.append)
    wait(qtbot, lambda: done, timeout=5000)
    assert done[0][0] == 6.5 and done[0][1] >= 0
    t = d.execute("Fail")
    t.failed.connect(failed.append)
    wait(qtbot, lambda: failed, timeout=5000)
    assert "Fail on purpose" in failed[0].text()


def test_state_model(qtbot, device_name):
    d = device_model(device_name)
    d.state_model.attach()
    wait(qtbot, lambda: d.state_model.last_value() is not None, timeout=5000)
    # alarm_double is in alarm, so Tango reports ALARM
    assert d.state_model.last_value().value == tango.DevState.ALARM
    d.state_model.release()


def test_job_progress(qtbot):
    progress = []

    def work(job, n):
        for i in range(n):
            job.set_progress(100 * (i + 1) // n, "step %d" % i)
        job.add_error(ValueError("minor"), "item 2")
        return n

    job = Job(work, 4, title="Test job")
    job.progress.connect(lambda p, t: progress.append(p))
    with qtbot.waitSignal(job.done, timeout=5000) as blocker:
        job.start()
    assert blocker.args == [4]
    wait(qtbot, lambda: progress and progress[-1] == 100, timeout=2000)
    assert job.errors and job.errors[0].message == "minor"
