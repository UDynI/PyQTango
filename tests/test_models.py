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
    modes = []
    a.modeChanged.connect(modes.append)
    a.attach()
    b.attach()
    wait(qtbot, lambda: a.last_value() is not None, timeout=5000)
    a.release()
    qtbot.wait(300)
    assert a.mode() != "idle"           # still used once
    b.release()
    wait(qtbot, lambda: a.mode() == "idle", timeout=3000)
    assert not refresher().is_registered(a)
    assert modes and modes[-1] == "idle"
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


def test_device_state_model_after_forget(qtbot, device_name):
    d = device_model(device_name)
    m = d.state_model
    m.attach()
    wait(qtbot, lambda: m.last_value() is not None, timeout=5000)
    m.release()
    wait(qtbot, lambda: m.mode() == "idle", timeout=3000)
    wait(qtbot, lambda: attribute_model(attr(device_name, "State")) is not m, timeout=3000)
    assert d.state_model is attribute_model(attr(device_name, "State"))


def test_write_uses_model_timeout(qtbot, device_name, monkeypatch):
    from PyQTango.core.proxies import proxy_cache
    m = attribute_model(attr(device_name, "rw_double"))
    m.timeout_ms = 1500
    used = []
    real_get = proxy_cache.get

    def get(name, timeout_ms=None, source=None):
        used.append(timeout_ms)
        return real_get(name, timeout_ms=timeout_ms, source=source)
    monkeypatch.setattr(proxy_cache, "get", get)
    try:
        with qtbot.waitSignal(m.writeDone, timeout=5000) as blocker:
            m.write(12.5)
        assert blocker.args == [None]
        assert used[0] == 1500     # the write itself, not the refresh after it
    finally:
        m.timeout_ms = None


# -- Model life cycle (review round 2) ---------------------------------------------------------------

def test_limiter_skips_released_models_without_recursion(qtbot):
    from PyQTango.models.attribute import SubscriptionLimiter

    class M(object):
        def __init__(self, i, refs):
            self.name = "m%d" % i
            self._refs = refs
            self._starting = True
            self.started = self.stopped = False

        def _setup(self):
            self.started = True

        def _stop_if_unused(self):
            self.stopped = True

    lim = SubscriptionLimiter(max_active=1)
    first = M(0, 1)
    lim.request(first)
    released = [M(i, 0) for i in range(1, 3001)]     # a closed window: 3000 queued, all released
    for m in released:
        lim.request(m)
    idle = []
    lim.idle.connect(lambda: idle.append(True))
    lim.finished(first, True)                         # used to recurse once per queued model
    assert all(m.stopped and not m.started and not m._starting for m in released)
    assert not lim.busy() and idle == [True]


def test_model_dropped_during_setup_frees_its_limiter_slot(qtbot, device_name, monkeypatch):
    import gc
    import time as _time
    from PyQTango.core.proxies import proxy_cache
    from PyQTango.models.attribute import subscription_limiter
    real_get = proxy_cache.get

    def slow_get(name, timeout_ms=None, source=None):
        _time.sleep(0.5)                              # a slow device: the release timer fires first
        return real_get(name, timeout_ms=timeout_ms, source=source)
    monkeypatch.setattr(proxy_cache, "get", slow_get)
    name = attr(device_name, "alarm_double")
    m = attribute_model(name)
    m.release_delay_ms = 10
    m.attach()
    m.release()
    del m
    gc.collect()
    wait(qtbot, lambda: not subscription_limiter().busy(), timeout=5000)
    wait(qtbot, lambda: registry().lookup(name) is None, timeout=3000)   # then stopped and forgotten


def test_unsubscribe_uses_the_subscribing_proxy(qtbot, device_name, monkeypatch):
    from PyQTango.core.proxies import proxy_cache
    seen = []
    real_get = proxy_cache.get

    def get(name, timeout_ms=None, source=None):
        p = real_get(name, timeout_ms=timeout_ms, source=source)
        seen.append((name, timeout_ms, p))
        return p
    monkeypatch.setattr(proxy_cache, "get", get)
    m = attribute_model(attr(device_name, "ev_double"))
    m.attach()
    wait(qtbot, lambda: m._ids, timeout=5000)
    ids = list(m._ids)
    proxy = [p for n, t, p in seen if n == m.device_name and t is None][0]
    m.timeout_ms = 1000                               # as StarterModel does on a shared model
    m.release()
    wait(qtbot, lambda: m.mode() == "idle", timeout=3000)
    results = []

    def try_again():
        out = []
        for i in ids:
            try:
                proxy.unsubscribe_event(i)
                out.append("was still subscribed")
            except Exception as e:                    # noqa: BLE001
                out.append(type(e).__name__)
        return out
    qtbot.wait(300)                                   # the unsubscription runs in a worker
    run_async(try_again, on_done=results.append)
    wait(qtbot, lambda: results, timeout=5000)
    assert "was still subscribed" not in results[0]


def test_period_and_source_requests(qtbot, device_name):
    m = attribute_model(attr(device_name, "tab_a"))
    base = m.polling_period
    m.attach()                                        # a plain widget
    m.attach()
    m.request_period("trend", 60000)                  # a slow trend
    assert m.polling_period == base
    m.request_period("fast", 100)
    assert m.polling_period == 100
    m.request_period("fast", None)
    assert m.polling_period == base
    m.release()                                       # the plain widget goes: only the trend is left
    assert m.polling_period == 60000
    m.request_source("trend", tango.DevSource.DEV)
    assert m.source == tango.DevSource.DEV
    m.request_period("trend", None)
    m.request_source("trend", None)
    assert m.polling_period == base and m.source is None
    m.release()


# -- Dead devices and the worker pool (review round 2) ------------------------------------------------

def _timeout():
    tango.Except.throw_exception("API_DeviceTimedOut", "Device timed out", "test")


class _DeadProxy(object):
    def __init__(self):
        self.reads = self.singles = 0

    def read_attributes(self, names):
        self.reads += 1
        _timeout()

    def read_attribute(self, name):
        self.singles += 1
        _timeout()


class _PolledModel(object):
    def __init__(self, i):
        self.device_name = "dead/device/1"
        self.attr_name = "a%d" % i
        self.name = self.device_name + "/" + self.attr_name
        self.polling_period = 1000
        self.source = self.timeout_ms = None
        self.errors = []

    def is_suspended(self):
        return False

    def _apply_error(self, err):
        self.errors.append(err)

    def _apply_value(self, da):
        pass


def test_dead_device_does_not_hold_workers(qtbot, monkeypatch):
    from PyQTango.core.proxies import proxy_cache
    from PyQTango.models.refresher import AttributeRefresher
    proxy = _DeadProxy()
    monkeypatch.setattr(proxy_cache, "get", lambda *a, **k: proxy)
    r = AttributeRefresher()
    models = [_PolledModel(i) for i in range(5)]
    for m in models:
        r.register(m)
    wait(qtbot, lambda: all(m.errors for m in models), 5000)
    group = next(iter(r._groups.values()))
    wait(qtbot, lambda: not group.busy, 5000)
    assert proxy.singles == 2                         # the probe gave up after two timeouts, not five
    group.errors = 3
    reads = proxy.reads
    r._on_timer(1000)                                 # backing off: no read now
    qtbot.wait(100)
    assert proxy.reads == reads and group.skipped >= 1
    lock = r._lock("dead/device/1")
    lock.acquire()                                    # another read of the device is running
    try:
        group.errors = 0
        skipped = group.skipped
        r._read_group(group, force=True)
        wait(qtbot, lambda: not group.busy, 3000)     # gave up its tick instead of waiting
        assert proxy.reads == reads and group.skipped == skipped + 1
    finally:
        lock.release()
    for m in models:
        r.unregister(m)


def test_setup_retries_back_off(qtbot, device_name, monkeypatch):
    from PyQTango.core.proxies import proxy_cache

    def dead(*a, **k):
        _timeout()
    monkeypatch.setattr(proxy_cache, "get", dead)
    m = attribute_model(attr(device_name, "no_such_attribute"))
    m.retry_delay_ms = 20
    m.attach()
    try:
        wait(qtbot, lambda: m._start_failures >= 4, 5000)
        assert m._retry_timer.interval() == 20 * 2 ** (m._start_failures - 1)
        m.max_retry_delay_ms = 50
        n = m._start_failures
        wait(qtbot, lambda: m._start_failures > n, 5000)
        assert m._retry_timer.interval() == 50
    finally:
        m.release()
