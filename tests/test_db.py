# -*- coding: utf-8 -*-
""" DatabaseService against a real (PyTango SQLite) database server """

import pytest

from PyQTango.core.db import (DatabaseService, ReadOnlyError, ServerInfo, parse_tango_host,
                              split_tango_hosts)
from dbserver import start_database, stop_database, populate


@pytest.fixture(scope="module")
def tango_host(tmp_path_factory):
    proc, th = start_database(tmp_path_factory.mktemp("db"))
    populate(th)
    yield th
    stop_database(proc)


@pytest.fixture
def dbs(tango_host):
    return DatabaseService(tango_host)


def test_parse():
    assert parse_tango_host("host:10001") == ("host", 10001)
    assert parse_tango_host("host") == ("host", 10000)
    assert parse_tango_host("tango://h:2/a/b/c") == ("h", 2)
    assert split_tango_hosts("a:1, b:2") == ["a:1", "b:2"]


def test_names_and_lists(dbs, tango_host):
    assert dbs.fq("lab/power/ps1") == "tango://{0}/lab/power/ps1".format(tango_host)
    assert "PowerSupply" in dbs.server_names()
    assert dbs.server_names("Power*") == ["PowerSupply"]
    assert dbs.instances("PowerSupply") == ["lab"]
    assert dbs.server_classes("PowerSupply/lab") == ["PowerSupply", "VacGauge"]
    assert dbs.server_devices("PowerSupply/lab", "PowerSupply") == ["lab/power/ps1", "lab/power/ps2"]
    assert ("lab/vac/gauge1", "VacGauge") in dbs.device_class_list("PowerSupply/lab")
    assert "lab" in dbs.domains()
    assert dbs.families("lab") == ["motor", "power", "vac"]
    assert dbs.members("lab", "power") == ["ps1", "ps2"]
    assert dbs.devices_matching("*power*") == ["dserver/PowerSupply/lab", "lab/power/ps1", "lab/power/ps2"]
    assert dbs.device_aliases() == ["m1", "ps1"]
    assert dbs.alias_device("m1") == "lab/motor/m1"
    assert dbs.attribute_aliases() == ["ps1_current"]
    assert dbs.alias_attribute("ps1_current") == "lab/power/ps1/current"
    assert dbs.device_alias("lab/power/ps1") == "ps1"
    assert dbs.device_alias("lab/power/ps2") == ""
    assert {"Astor", "CtrlSystem"} <= set(dbs.objects())


def test_properties(dbs):
    props = dbs.device_properties("lab/power/ps1")
    assert list(props) == ["Current_max", "Description", "polled_attr"]
    assert props["Description"] == ["Main supply", "line 2"]
    assert dbs.class_properties("PowerSupply") == {"Vendor": ["ACME"]}
    assert dbs.object_properties("Astor")["LastCollections"] == ["Beamline"]
    assert dbs.device_attribute_list("lab/power/ps1") == ["current"]
    assert dbs.device_attribute_properties("lab/power/ps1", "current") == {"format": ["%6.2f"], "unit": ["A"]}
    assert dbs.class_attributes("PowerSupply") == ["voltage"]
    assert dbs.class_attribute_properties("PowerSupply", "voltage") == {"unit": ["V"]}


def test_infos(dbs):
    info = dbs.device_info("lab/power/ps1")
    assert info.server == "PowerSupply/lab" and info.klass == "PowerSupply" and not info.exported
    assert info.host == "nada"      # never exported (PyTango 9.5 reads it with DbGetDeviceInfo)
    # The SQLite database stores blanks for unset startup info: no exception
    assert dbs.server_info("PowerSupply/lab") == ServerInfo("PowerSupply/lab", "", False, 0)
    assert "Device" in dbs.info() or "TANGO" in dbs.info()


@pytest.mark.parametrize("sql", [True, False])
def test_sql_and_fallbacks(dbs, sql):
    if not sql:
        dbs.disable_sql()
    else:
        assert dbs.has_sql()
        rows = dbs.select("select name, alias from device where class='Motor'")
        assert rows == [("lab/motor/m1", "m1")]
    assert dbs.class_devices("PowerSupply") == ["lab/power/ps1", "lab/power/ps2"]
    table = dbs.device_table()
    if sql:
        assert ("PowerSupply/lab", "PowerSupply", "lab/power/ps1") in table
        assert ("PowerSupply/lab", "DServer", "dserver/PowerSupply/lab") in table
    else:
        assert table is None
    assert dbs.host_collections() == {"tango/admin/hosta": "Lab", "tango/admin/hostb": "Beamline"}


def test_read_only(tango_host):
    ro = DatabaseService(tango_host, read_only=True)
    with pytest.raises(ReadOnlyError):
        ro.put_server_info(ServerInfo("PowerSupply/lab", "h", True, 1))


def test_property_writes_and_history(tango_host):
    dbs = DatabaseService(tango_host)
    dbs.put_class_property("Motor", {"Speed": ["1", "2"]})
    assert dbs.class_properties("Motor")["Speed"] == ["1", "2"]
    dbs.delete_class_property("Motor", ["Speed"])
    assert "Speed" not in dbs.class_properties("Motor")
    dbs.put_class_attribute_property("Motor", "position", {"unit": "mm"})
    assert dbs.class_attribute_properties("Motor", "position") == {"unit": ["mm"]}
    dbs.delete_class_attribute_property("Motor", "position", ["unit"])
    dbs.put_device_attribute_property("lab/motor/m1", "position", {"unit": "um"})
    assert dbs.device_attribute_properties("lab/motor/m1", "position")["unit"] == ["um"]
    dbs.delete_device_attribute_property("lab/motor/m1", "position", ["unit"])
    dbs.put_object_property("CtrlSystem", {"Note": "x"})
    assert dbs.object_properties("CtrlSystem")["Note"] == ["x"]
    dbs.delete_object_property("CtrlSystem", ["Note"])
    # History: values, then a deletion
    dbs.put_device_property("lab/motor/m1", {"Acc": "1"})
    dbs.put_device_property("lab/motor/m1", {"Acc": ["2", "3"]})
    dbs.delete_device_property("lab/motor/m1", ["Acc"])
    hist = dbs.device_property_history("lab/motor/m1", "Acc")
    assert [h.values for h in hist][:2] == [["1"], ["2", "3"]] and hist[-1].deleted and hist[-1].values is None
    assert dbs.object_property_history("CtrlSystem", "Note")[0].values == ["x"]
    att = dbs.device_attribute_property_history("lab/motor/m1", "position", "unit")
    assert att and att[0].attribute == "position"
    ro = DatabaseService(tango_host, read_only=True)
    for call in (lambda: ro.put_class_property("Motor", {"a": "1"}), lambda: ro.delete_object_property("x", ["a"]),
                 lambda: ro.put_device_attribute_property("a/b/c", "x", {"u": "1"})):
        with pytest.raises(ReadOnlyError):
            call()


@pytest.mark.parametrize("sql", [True, False])
def test_property_selections(tango_host, sql):
    dbs = DatabaseService(tango_host)
    if not sql:
        dbs.disable_sql()
    assert dbs.device_property_selection("lab/power/*", "Current_max") == [
        ("lab/power/ps1", None, "Current_max", ["10.5"]), ("lab/power/ps2", None, "Current_max", ["8"])]
    assert dbs.device_property_selection("lab/power/ps1", "desc*") == [
        ("lab/power/ps1", None, "Description", ["Main supply", "line 2"])]
    assert dbs.device_property_selection("nothing/*/*", "*") == []
    assert dbs.device_attribute_property_selection("lab/*/*", "cur*", "*") == [
        ("lab/power/ps1", "current", "format", ["%6.2f"]), ("lab/power/ps1", "current", "unit", ["A"])]
    assert dbs.device_attribute_property_selection("lab/power/ps1", "current", "UNIT") == [
        ("lab/power/ps1", "current", "unit", ["A"])]


@pytest.mark.parametrize("sql", [True, False])
def test_find_usage(tango_host, sql):
    import tango
    db = tango.Database(*tango_host.split(":"))
    db.put_device_property("dserver/PowerSupply/lab", {"__SubDevices": ["lab/motor/m1", "LAB/VAC/GAUGE1"]})
    db.put_device_property("dserver/Motion/axis", {"__SubDevices": ["lab/vac/gauge1"]})
    try:
        dbs = DatabaseService(tango_host)
        if not sql:
            dbs.disable_sql()
        assert dbs.find_usage("lab/vac/gauge1") == ["dserver/Motion/axis", "dserver/PowerSupply/lab"]
        assert dbs.find_usage("Lab/Motor/M1") == ["dserver/PowerSupply/lab"]
        assert dbs.find_usage("lab/power/ps1") == []
    finally:
        db.delete_device_property("dserver/PowerSupply/lab", ["__SubDevices"])
        db.delete_device_property("dserver/Motion/axis", ["__SubDevices"])
