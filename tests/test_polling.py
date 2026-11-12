# -*- coding: utf-8 -*-
""" Polling core, configuration tables and QPollingPanel on a registered device server """

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import tango

from PyQTango.core import polling
from PyQTango.core.db import DatabaseService, ReadOnlyError
from dbserver import start_database, stop_database, populate

HERE = os.path.dirname(os.path.abspath(__file__))
DEV = "test/pqt/1"


def in_thread(fn, *args):
    with ThreadPoolExecutor(1) as ex:
        return ex.submit(fn, *args).result()


@pytest.fixture(scope="module")
def tango_host(tmp_path_factory):
    proc, th = start_database(tmp_path_factory.mktemp("db"))
    populate(th)
    host, port = th.split(":")
    db = tango.Database(host, int(port))
    info = tango.DbDevInfo()
    info.name, info._class, info.server = DEV, "PQTPoll", "PQTPoll/1"
    db.add_device(info)
    server = subprocess.Popen([sys.executable, os.path.join(HERE, "pqtserver.py"), "1"],
                              env=dict(os.environ, TANGO_HOST=th),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proxy = tango.DeviceProxy("tango://{0}/{1}".format(th, DEV))
    deadline = time.time() + 30
    while True:
        try:
            proxy.ping()
            break
        except tango.DevFailed:
            if time.time() > deadline:
                server.kill()
                raise
            time.sleep(0.3)
    yield th
    server.terminate()
    server.wait(10)
    stop_database(proc)


@pytest.fixture
def dbs(tango_host):
    return in_thread(DatabaseService, tango_host)


@pytest.fixture
def proxy(tango_host):
    return tango.DeviceProxy("tango://{0}/{1}".format(tango_host, DEV))


def test_parse_polling_status():
    lines = ["Polled command name = State\nPolling period (mS) = 2000\nPolling ring buffer depth = 10",
             "Polled attribute name = current\nPolling period (mS) = 1500\nNo data recorded yet", "junk"]
    assert polling.parse_polling_status(lines) == {("command", "state"): "2000",
                                                   ("attribute", "current"): "1500"}
    assert polling.parse_period("") == polling.DEFAULT_PERIOD_MS
    assert polling.parse_period(" 250 ") == 250
    for bad in ("abc", "0", "-5"):
        with pytest.raises(ValueError):
            polling.parse_period(bad)


def test_read_and_set_polling(dbs, proxy):
    in_thread(polling.set_polling, proxy, "attribute", "voltage", True, "1200")
    try:
        commands, attributes = in_thread(polling.read_polling, proxy)
        assert "Echo" not in [c.name for c in commands]          # takes an argument
        assert {"Init", "Reset", "State", "Status"} <= {c.name for c in commands}
        volt = next(a for a in attributes if a.name == "voltage")
        assert volt.polled and volt.period == "1200"
        assert not next(a for a in attributes if a.name == "current").polled
    finally:
        in_thread(polling.set_polling, proxy, "attribute", "voltage", False)
    assert not any(a.polled for a in in_thread(polling.read_polling, proxy)[1] if a.name == "voltage")
    assert in_thread(polling.read_polling_settings, dbs, DEV) == ("4", "10")


def test_settings_and_reset(dbs, tango_host):
    in_thread(polling.write_polling_setting, dbs, DEV, "poll_ring_depth", "20")
    assert in_thread(polling.read_polling_settings, dbs, DEV) == ("4", "20")
    with pytest.raises(ValueError):
        polling.write_polling_setting(dbs, DEV, "poll_ring_depth", "x")
    in_thread(dbs.put_device_property, DEV, {"polled_attr": ["voltage", "1000"]})
    in_thread(polling.reset_polling, dbs, DEV)
    assert "polled_attr" not in in_thread(dbs.device_properties, DEV)
    in_thread(dbs.delete_device_property, DEV, ["poll_ring_depth"])
    ro = in_thread(DatabaseService, tango_host, True)
    with pytest.raises(ReadOnlyError):
        ro.put_device_property(DEV, {"x": "1"})
    with pytest.raises(ReadOnlyError):
        ro.delete_device_attribute_property(DEV, "current", ["unit"])


def test_config_table_model(qtbot):
    from PyQTango.widgets.configtables import ConfigColumn, ConfigTab, ConfigTableModel
    from PyQTango.qt import Qt
    tab = ConfigTab("t", "T", [ConfigColumn("on", "On", "bool"), ConfigColumn("v", "V")])
    model = ConfigTableModel(tab)
    model.set_rows([{"name": "a", "on": False, "v": "1"}, {"name": "b", "on": True, "v": "2"}])
    assert not model.is_modified() and model.headerData(0, Qt.Orientation.Horizontal) == "Attribute name"
    assert model.setData(model.index(0, 2), " 5 ")
    assert model.setData(model.index(1, 1), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert model.changes() == [("a", "v", "5"), ("b", "on", False)]
    assert model.data(model.index(0, 2), Qt.ItemDataRole.FontRole).bold()
    assert "stored value: 1" in model.data(model.index(0, 2), Qt.ItemDataRole.ToolTipRole)
    model.set_value(0, "v", "1")                 # back to the stored value: not a change
    assert model.changes() == [("b", "on", False)]
    model.editable = False
    assert not model.setData(model.index(0, 2), "9")
    model.revert()
    assert not model.is_modified()


def _panel(qtbot, dbs, read_only=False):
    from PyQTango.widgets.polling import QPollingPanel
    panel = QPollingPanel()
    qtbot.addWidget(panel)
    panel.show_job_errors = False
    panel.confirm = lambda *a, **k: True
    panel.confirm_changes = lambda *a, **k: True
    panel.inform = lambda *a, **k: None
    panel.set_read_only(read_only)
    with qtbot.waitSignal(panel.loaded, timeout=10000):
        panel.show_devices(dbs, [DEV])
    return panel


def _apply(qtbot, panel):
    with qtbot.waitSignal(panel.loaded, timeout=20000):
        job = panel.apply()
        assert job is not None
    return job


def test_polling_panel_apply(qtbot, dbs, proxy):
    panel = _panel(qtbot, dbs)
    assert [t.title for t in panel.tabs] == ["Command", "Attribute", "Settings"]
    assert panel.title.text() == "Device polling [{0}]".format(DEV)
    att = panel.models["attribute"]
    assert "voltage" in att.names() and "Echo" not in panel.models["command"].names()
    assert panel.menu_texts("attribute", ["voltage"]) == ["Enable polling", "Disable polling", "Set period"]
    # Editing the period ticks "Polled"; nothing is written before Apply
    r = att.row_of("voltage")
    att.setData(att.index(r, 2), "1100")
    assert att.value(r, "polled") is True and panel.apply_button.isEnabled()
    assert not any(a.polled for a in polling.read_polling(proxy)[1] if a.name == "voltage")
    job = _apply(qtbot, panel)
    assert not job.errors
    assert next(a for a in polling.read_polling(proxy)[1] if a.name == "voltage").period == "1100"
    assert att.value(att.row_of("voltage"), "polled") and not panel.has_pending()
    # Context menu: set period on two rows, then disable one
    panel.prompt = lambda *a, **k: "900"
    assert panel.trigger_menu("attribute", ["voltage", "current"], "Set period")
    _apply(qtbot, panel)
    status = polling.parse_polling_status(proxy.polling_status())
    assert status[("attribute", "voltage")] == "900" and status[("attribute", "current")] == "900"
    panel.trigger_menu("attribute", ["voltage", "current"], "Disable polling")
    _apply(qtbot, panel)
    assert not polling.parse_polling_status(proxy.polling_status())
    # Settings tab writes the database property
    settings = panel.models["settings"]
    settings.setData(settings.index(settings.row_of("Poll ring depth"), 1), "15")
    _apply(qtbot, panel)
    assert dbs.device_properties(DEV)["poll_ring_depth"] == ["15"]
    dbs.delete_device_property(DEV, ["poll_ring_depth"])


def test_polling_panel_validation_and_reset(qtbot, dbs):
    panel = _panel(qtbot, dbs)
    att = panel.models["attribute"]
    att.setData(att.index(att.row_of("voltage"), 2), "fast")
    assert panel.apply() is None and "Invalid polling period" in panel.status.text()
    panel.revert()
    assert not panel.has_pending()
    dbs.put_device_property(DEV, {"polled_attr": ["voltage", "1000"]})
    with qtbot.waitSignal(panel.loaded, timeout=20000):
        panel.reset_config()
    assert "polled_attr" not in dbs.device_properties(DEV)


def test_polling_panel_read_only(qtbot, tango_host):
    ro = in_thread(DatabaseService, tango_host, True)
    panel = _panel(qtbot, ro, read_only=True)
    att = panel.models["attribute"]
    assert not att.setData(att.index(0, 2), "1000")
    assert panel.menu_texts("attribute", att.names()[:1]) == []
    assert not panel.apply_button.isEnabled() and not panel.reset_button.isEnabled()


def test_polling_panel_dead_device(qtbot, dbs):
    from PyQTango.widgets.polling import QPollingPanel
    panel = QPollingPanel()
    qtbot.addWidget(panel)
    with qtbot.waitSignal(panel.loaded, timeout=20000):
        panel.show_devices(dbs, ["lab/power/ps1"])
    assert "Cannot read lab/power/ps1" in panel.status.text()
    assert panel.models["attribute"].rowCount() == 0


def test_property_table_rows_shrink_when_column_widens(qtbot):
    from PyQTango.widgets.tables import QPropertyTable
    table = QPropertyTable()
    qtbot.addWidget(table)
    table.resize(500, 300)
    table.show()
    table.setColumnWidth(0, 40)
    table.model().set_properties([("Current logging target", "x"), ("a", "y")])
    tall = table.rowHeight(0)
    table.resizeColumnToContents(0)
    qtbot.waitUntil(lambda: table.rowHeight(0) < tall)
    assert table.rowHeight(0) == table.rowHeight(1)


def test_polling_panel_status_follows_edits(qtbot, dbs):
    panel = _panel(qtbot, dbs)
    att = panel.models["attribute"]
    att.setData(att.index(att.row_of("voltage"), 2), "1100")
    n1 = panel.pending_count()
    assert "{0} value(s)".format(n1) in panel.status.text()
    att.setData(att.index(att.row_of("current"), 2), "1200")
    n2 = panel.pending_count()
    assert n2 > n1 and "{0} value(s)".format(n2) in panel.status.text()
    for name, key, _ in att.changes():                # undone by hand
        row = att.row_of(name)
        att.set_value(row, key, att.stored(row, key), hook=False)
    assert not panel.has_pending() and panel.status.text() == panel.loaded_text()


def test_externally_triggered_polling():
    status = polling.parse_polling_status([
        "Polled attribute name = voltage\nPolling externally triggered\nPolling ring buffer depth = 10",
        "Polled attribute name = current\nPolling period (mS) = 1000\nPolling ring buffer depth = 10"])
    assert status == {("attribute", "voltage"): "", ("attribute", "current"): "1000"}

    class Proxy(object):
        def polling_status(self):
            return ["Polled attribute name = voltage\nPolling externally triggered"]

        def command_list_query(self):
            return []

        def get_attribute_list(self):
            return ["voltage", "current"]
    _, attrs = polling.read_polling(Proxy())
    v, c = [a for a in attrs if a.name == "voltage"][0], [a for a in attrs if a.name == "current"][0]
    assert v.polled and v.external and v.period == "" and not c.polled and not c.external
