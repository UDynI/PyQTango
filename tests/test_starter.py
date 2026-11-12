# -*- coding: utf-8 -*-
""" Starter helpers, LevelWalker and StarterModel on fake Starters (plan 7.6) """

import datetime
import time

import pytest
import tango

from PyQTango.core.starter import (parse_servers, host_state, worst_state, parse_starter_log, parse_statistics,
                                   split_server_log, starter_device, host_of_starter, ServerLine)
from PyQTango.core.levels import LevelWalker, levels_in_use, START, STOP
from PyQTango.core.proxies import ProxyCache
from dbserver import start_database, stop_database, populate, setup_hosts, start_starter
from conftest import wait

pytestmark = pytest.mark.usefixtures("no_tango_in_gui_thread")


def test_servers_and_states():
    lines = ["PowerSupply/lab\tON\t1\t1\t1", "Motion/axis\tFAULT\t1\t2\t0", "X/y\tMOVING\t0\t0\t2", ""]
    s = parse_servers(lines)
    assert [x.name for x in s] == ["PowerSupply/lab", "Motion/axis", "X/y"]
    assert s[0].running and s[0].controlled and s[0].level == 1 and not s[1].running
    assert s[2].twice and s[2].effective_level == 0 and s[1].effective_level == 2
    assert parse_servers("\n".join(lines))[1] == s[1] and s[0].to_line() == lines[0]
    assert host_state(tango.DevState.ON) == "running" and host_state("MOVING") == "moving"
    assert host_state(tango.DevState.STANDBY) == "blocked" and host_state("OFF") == "off"
    assert host_state(None) == "unknown" and host_state("ON", reachable=False) == "unreachable"
    assert worst_state(["running", "off", "alarm"]) == "alarm" and worst_state([]) == "unknown"
    assert worst_state(["running", "unreachable"]) == "unreachable"
    assert starter_device("hosta.lab.org") == "tango/admin/hosta" and host_of_starter("tango/admin/hosta") == "hosta"
    assert levels_in_use({"a": s, "b": [ServerLine("z", controlled=True, level=4)]}) == [1, 2, 4]


def test_log_parsers():
    log = parse_starter_log("10/11/26   23:30:01\tMotion/axis started\n10/11/26   23:29:59\tStarter startup\n")
    assert [l.message for l in log] == ["Motion/axis started", "Starter startup"]
    assert log[0].time == datetime.datetime(2026, 11, 10, 23, 30, 1)
    stats = parse_statistics("A/1\tON\t1700000000\t0\t1\nB/2\tFAULT\t1700000100\t1700000200\t0\n")
    assert stats[1].server == "B/2" and stats[1].failed == 1700000200 and stats[0].auto
    name, date, body = split_server_log("/tmp/A_1.log\n10/11/26   10:00:00\n\nhello\nworld\n")
    assert (name, date, body.strip()) == ("/tmp/A_1.log", "10/11/26   10:00:00", "hello\nworld")


def test_level_walker():
    calls, asked, slept = [], [], []

    def command(host, level):
        calls.append((host, level))
        if host == "b" and level == 2:
            raise RuntimeError("boom")

    hosts = {"a": [1, 2], "b": [2, 3]}
    answers = iter(["yes", "no", "all"])
    w = LevelWalker(START, hosts, command, decide=lambda a, lv: asked.append(lv) or next(answers),
                    sleep=slept.append)
    res = w.run()
    assert asked == [1, 2, 3] and calls == [("a", 1), ("b", 3)]
    assert [(r.host, r.level, r.ok, r.skipped) for r in res] == [
        ("a", 1, True, False), ("a", 2, True, True), ("b", 2, True, True), ("b", 3, True, False)]
    assert slept == [0.5, 0.5]
    calls.clear()
    w = LevelWalker(STOP, hosts, command, decide=lambda a, lv: "all", sleep=lambda s: None)
    w.run()
    assert calls == [("b", 3), ("a", 2), ("b", 2), ("a", 1)]
    assert [(f.host, f.level, f.message) for f in w.failures()] == [("b", 2, "boom")]
    w = LevelWalker(START, hosts, command, decide=lambda a, lv: "cancel")
    assert w.run() == [] and w.was_cancelled
    with pytest.raises(ValueError):
        LevelWalker("restart", hosts, command)


def test_proxy_cache_keys():
    c = ProxyCache(timeout_ms=3000)
    # Same key for the default timeout, separate keys otherwise (no proxy is created here)
    import PyQTango.core.proxies as P
    created = []

    class FakeProxy(object):
        def __init__(self, name):
            created.append(name)

        def set_timeout_millis(self, ms):
            self.ms = ms

        def set_source(self, s):
            self.src = s

    from concurrent.futures import ThreadPoolExecutor

    def check():
        a = c.get("a/b/c")
        assert c.get("a/b/c", timeout_ms=3000) is a
        b = c.get("a/b/c", timeout_ms=1000)
        assert b is not a and b.ms == 1000 and c.get("a/b/c", timeout_ms=1000) is b
        assert len(c.proxies_of("a/b/c")) == 2
        c.invalidate("a/b/c")                       # dropped proxies are parked, never destroyed
        assert c.proxies_of("a/b/c") == [] and a in P._kept and b in P._kept
        d = c.get("x/y/z")
        c.clear()
        assert d in P._kept
    old = P.tango.DeviceProxy
    P.tango.DeviceProxy = FakeProxy
    try:
        with ThreadPoolExecutor(1) as ex:
            ex.submit(check).result()
    finally:
        P.tango.DeviceProxy = old


@pytest.fixture(scope="module")
def hosts_db(tmp_path_factory):
    proc, th = start_database(tmp_path_factory.mktemp("hostsdb"))
    starters = []
    try:
        populate(th)
        setup_hosts(th)
        starters.append(start_starter(th, "hosta", ["tango/admin/hosta"]))
        yield th
    finally:
        for p in starters:
            p.terminate()
            p.wait(10)
        stop_database(proc)


def test_starter_model(qtbot, hosts_db):
    from PyQTango.models import starter_model
    from PyQTango.models.starter import is_stop_error_not_running, STARTER_TIMEOUT_MS
    th = hosts_db
    m = starter_model("tango://{0}/tango/admin/hosta".format(th))
    assert m.host == "hosta" and m.state_model.timeout_ms == STARTER_TIMEOUT_MS
    m.attach()
    m.watch_servers()
    wait(qtbot, lambda: len(m.servers()) == 3, 10000)
    wait(qtbot, lambda: m.state() == "off", 10000)       # nothing runs on the fake host
    assert {s.name: (s.controlled, s.level) for s in m.servers()} == {
        "PowerSupply/lab": (True, 1), "Motion/axis": (True, 2), "TangoTest/test2": (False, 0)}
    assert m.levels() == [1, 2]
    with qtbot.waitSignal(m.commandDone, timeout=10000) as blocker:
        m.start_level(1)
    assert blocker.args == ["DevStartAll(1)", None]
    wait(qtbot, lambda: m.state() == "alarm", 10000)
    wait(qtbot, lambda: {s.name for s in m.servers() if s.running} == {"PowerSupply/lab"}, 10000)
    with qtbot.waitSignal(m.commandDone, timeout=10000):
        m.start_server("Motion/axis")
    wait(qtbot, lambda: m.state() == "running", 10000)
    errors = []
    with qtbot.waitSignal(m.commandDone, timeout=10000):
        m.start_server("Motion/axis", on_error=errors.append)
    assert "already running" in errors[0].message
    with qtbot.waitSignal(m.commandDone, timeout=10000):
        m.stop_server("TangoTest/test2", on_error=errors.append)
    assert is_stop_error_not_running(errors[1])
    logs = []
    with qtbot.waitSignal(m.commandDone, timeout=10000):
        m.read_log("Starter", on_done=logs.append)
    msgs = [l.message for l in parse_starter_log(logs[0])]
    assert msgs[:3] == ["Motion/axis started", "PowerSupply/lab started", "Starter startup"]
    with qtbot.waitSignal(m.commandDone, timeout=10000):
        m.stop_level(2)
    with qtbot.waitSignal(m.commandDone, timeout=10000):
        m.stop_level(1)
    wait(qtbot, lambda: m.state() == "off", 10000)
    assert m.status() != ""
    m.unwatch_servers()
    m.release()


def test_unreachable_host(qtbot, hosts_db):
    from PyQTango.models import starter_model
    m = starter_model("tango://{0}/tango/admin/hostb".format(hosts_db))   # registered, not running
    m.attach()
    wait(qtbot, lambda: m.state() == "unreachable", 10000)
    m.release()


def test_subscription_limiter(qtbot):
    from PyQTango.models.attribute import SubscriptionLimiter

    class M(object):
        def __init__(self, i):
            self.name = "m%d" % i
            self.started = False
            self._refs = 1

        def _setup(self):
            self.started = True

    lim = SubscriptionLimiter(max_active=2)
    ms = [M(i) for i in range(5)]
    seen = []
    lim.progress.connect(lambda d, t: seen.append((d, t)))
    for m in ms:
        lim.request(m)
    assert [m.started for m in ms] == [True, True, False, False, False] and lim.busy()
    lim.finished(ms[0], True)
    assert ms[2].started and seen == [(1, 5)]
    lim.finished(ms[1], False, "err")
    assert lim.failures == [("m1", "err")]
    for m in ms[2:]:
        lim.finished(m, True)
    assert not lim.busy() and lim.total == 0 and seen[-1] == (5, 5)
    time.sleep(0)


def test_release_after_qt_deleted_the_models():
    """ Closing a window at exit can delete the attribute models first: releasing them is then a
    no-op (a stand-in, since deleting the shared models would break later tests) """
    from PyQTango.models.starter import _detach

    class Deleted:
        def __getattr__(self, name):
            raise RuntimeError("wrapped C/C++ object of type TangoAttributeModel has been deleted")
    _detach(Deleted(), (("valueChanged", print),))

    class Alive:
        released = False

        class valueChanged:                     # noqa: N801
            @staticmethod
            def disconnect(slot):
                raise TypeError("not connected")

        def release(self):
            self.released = True
    a = Alive()
    _detach(a, (("valueChanged", print),))
    assert a.released


def test_starter_model_reattach(qtbot, hosts_db):
    from PyQTango.models import starter_model, attribute_model
    from PyQTango.models.starter import STARTER_TIMEOUT_MS
    m = starter_model("tango://{0}/tango/admin/hosta".format(hosts_db))
    m.attach()
    first = m.state_model
    wait(qtbot, lambda: first.last_value() is not None, 10000)
    m.release()
    wait(qtbot, lambda: first.mode() == "idle", 5000)
    m.attach()
    try:
        assert m.state_model is attribute_model(m.device + "/State")
        assert m.state_model.timeout_ms == STARTER_TIMEOUT_MS
    finally:
        m.release()


def test_starter_model_replays_a_known_error(qtbot, hosts_db):
    from PyQTango.models import starter_model, attribute_model
    name = "tango://{0}/tango/admin/hostz".format(hosts_db)     # not defined: State fails
    other = attribute_model(name + "/State")                     # another user follows it already
    other.attach()
    try:
        wait(qtbot, lambda: other.last_error() is not None, 10000)
        m = starter_model(name)
        m.attach()
        assert m.state() == "unreachable"            # at once, not when the error text changes
        m.release()
    finally:
        other.release()
