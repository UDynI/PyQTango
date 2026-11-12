# -*- coding: utf-8 -*-
"""
DatabaseService: one Tango database, typed results, SQL with fallbacks.

Every method blocks on the network: call them from a worker thread
(:func:`PyQTango.models.run_async`), never from the GUI thread.

* Several Tango hosts can be open at once; device names returned by
  :meth:`DatabaseService.fq` are fully qualified (``tango://host:port/dom/fam/mem``)
  so proxies never depend on the process-wide ``TANGO_HOST``.
* :meth:`select` decodes ``DbMySqlSelect`` (null flags, row and field counts).
  The command is probed once; when it is missing or refused, the helpers that
  use SQL fall back to the regular database API.
* With ``read_only=True`` every write raises :class:`ReadOnlyError` before any
  Tango call, so a missing menu rule cannot write.
"""

import logging
import threading
from collections import namedtuple, OrderedDict

import tango

from .names import wildcard_to_regex, wildcard_to_sql_like

log = logging.getLogger(__name__)

DEFAULT_PORT = 10000

#: Server startup information (``controlled`` is the Starter "mode")
ServerInfo = namedtuple("ServerInfo", "name host controlled level")

#: Device information from the database (dates are the database strings)
DeviceInfo = namedtuple("DeviceInfo", "name server klass exported host pid version started stopped ior")

#: One entry of a property's history: ``values`` is None when the entry is a deletion;
#: ``attribute`` is "" for device, class and free properties
PropertyHistory = namedtuple("PropertyHistory", "date name values deleted attribute")


class ReadOnlyError(RuntimeError):
    """ A write was attempted on a read-only DatabaseService """


def parse_tango_host(text):
    """ ``"host:port"`` (or ``"host"``) -> ``(host, port)``; also accepts ``tango://host:port`` """
    text = (text or "").strip()
    if text.startswith("tango://"):
        text = text[len("tango://"):].split("/", 1)[0]
    if not text:
        raise ValueError("empty TANGO_HOST")
    if ":" in text:
        host, port = text.rsplit(":", 1)
        return host, int(port)
    return text, DEFAULT_PORT


def split_tango_hosts(text):
    """ A ``TANGO_HOST`` value may hold several comma-separated databases """
    return [h.strip() for h in (text or "").split(",") if h.strip()]


def _strings(value):
    """ DbDatum, sequence or None -> list of str """
    if value is None:
        return []
    if hasattr(value, "value_string"):
        return list(value.value_string)
    return [str(v) for v in value]


def _matches(names, pattern):
    if not pattern or pattern == "*":
        return list(names)
    rx = wildcard_to_regex(pattern)
    return [n for n in names if rx.match(n)]


class DatabaseService(object):
    """ Typed access to one Tango database.

    Construction connects (blocking). Use :meth:`connect` from a worker.
    """

    def __init__(self, tango_host=None, read_only=False, timeout_ms=3000):
        if tango_host is None:
            tango_host = tango.ApiUtil.get_env_var("TANGO_HOST")
        hosts = split_tango_hosts(tango_host)
        if not hosts:
            raise ValueError("TANGO_HOST is not set")
        self.host, self.port = parse_tango_host(hosts[0])
        self.tango_host = "{0}:{1}".format(self.host, self.port)
        self.read_only = bool(read_only)
        self.db = tango.Database(self.host, self.port)
        self.db.set_timeout_millis(timeout_ms)
        self._lock = threading.Lock()
        self._sql = None          # None = not probed, True/False after the probe

    @classmethod
    def connect(cls, tango_host=None, read_only=False):
        return cls(tango_host, read_only)

    # -- Names --------------------------------------------------------------------
    def fq(self, name):
        """ Fully qualified device or attribute name on this database """
        if name.startswith("tango://"):
            return name
        return "tango://{0}/{1}".format(self.tango_host, name)

    def device_name(self):
        """ Name of the database device itself """
        return self.db.dev_name()

    # -- Guard -------------------------------------------------------------------
    def check_write(self, what="write"):
        if self.read_only:
            raise ReadOnlyError("{0}: the database is open read-only".format(what))

    # -- SQL ---------------------------------------------------------------------
    def has_sql(self):
        """ True when ``DbMySqlSelect`` works on this database (probed once) """
        with self._lock:
            if self._sql is None:
                try:
                    self.db.command_inout("DbMySqlSelect", "select count(*) from device")
                    self._sql = True
                except tango.DevFailed as e:
                    log.info("DbMySqlSelect not available on %s: %s", self.tango_host, e.args[0].desc)
                    self._sql = False
                except Exception:  # noqa: BLE001 (any transport problem)
                    self._sql = False
            return self._sql

    def disable_sql(self):
        """ Force the API fallbacks (tests, or a database whose SQL is wrong) """
        with self._lock:
            self._sql = False

    def select(self, query):
        """ Run a SELECT; returns a list of row tuples (None for SQL nulls) """
        lvalue, svalue = self.db.command_inout("DbMySqlSelect", query)
        lvalue = list(lvalue)
        if len(lvalue) < 2:
            return []
        nrows, nfields = int(lvalue[-2]), int(lvalue[-1])
        rows = []
        for r in range(nrows):
            row = []
            for f in range(nfields):
                i = r * nfields + f
                row.append(svalue[i] if i < len(svalue) and lvalue[i] else None)
            rows.append(tuple(row))
        return rows

    @staticmethod
    def like(pattern):
        """ Escaped SQL LIKE pattern from a Jive wildcard (quotes doubled) """
        return wildcard_to_sql_like(pattern)

    # -- Info ---------------------------------------------------------------------
    def info(self):
        return self.db.get_info()

    # -- Servers -----------------------------------------------------------------
    def server_names(self, pattern="*"):
        return sorted(_matches(_strings(self.db.get_server_name_list()), pattern), key=str.lower)

    def instances(self, server, pattern="*"):
        return sorted(_matches(_strings(self.db.get_instance_name_list(server)), pattern), key=str.lower)

    def server_list(self, pattern="*"):
        return sorted(_strings(self.db.get_server_list(pattern)), key=str.lower)

    def server_classes(self, server):
        """ Classes of ``server/instance`` (DServer excluded) """
        return [c for c in _strings(self.db.get_server_class_list(server)) if c != "DServer"]

    def server_devices(self, server, klass):
        return sorted(_strings(self.db.get_device_name(server, klass)), key=str.lower)

    def device_class_list(self, server):
        """ [(device, class), ...] of a server, admin device excluded """
        flat = _strings(self.db.get_device_class_list(server))
        pairs = list(zip(flat[0::2], flat[1::2]))
        return [(d, c) for d, c in pairs if c != "DServer"]

    def server_info(self, server):
        """ :class:`ServerInfo`; tolerant of databases that store blanks """
        raw = list(self.db.command_inout("DbGetServerInfo", server))
        raw += [""] * (4 - len(raw))

        def num(s):
            try:
                return int(str(s).strip())
            except ValueError:
                return 0
        host = raw[1].strip()
        return ServerInfo(raw[0] or server, host, num(raw[2]) != 0, num(raw[3]))

    def put_server_info(self, info):
        self.check_write("put_server_info")
        si = tango.DbServerInfo()
        si.name, si.host, si.mode, si.level = info.name, info.host, int(bool(info.controlled)), int(info.level)
        self.db.put_server_info(si)

    # -- Devices -------------------------------------------------------------------
    def domains(self, pattern="*", family_pattern="*", member_pattern="*"):
        """ Domains having at least one device matching ``pattern/family_pattern/member_pattern``
        (the database matches whole device names) """
        name = "{0}/{1}/{2}".format(pattern or "*", family_pattern or "*", member_pattern or "*")
        return sorted(_strings(self.db.get_device_domain(name)), key=str.lower)

    def families(self, domain, pattern="*", member_pattern="*"):
        name = "{0}/{1}/{2}".format(domain, pattern or "*", member_pattern or "*")
        return sorted(_strings(self.db.get_device_family(name)), key=str.lower)

    def members(self, domain, family, pattern="*"):
        return sorted(_strings(self.db.get_device_member("{0}/{1}/{2}".format(domain, family, pattern))),
                      key=str.lower)

    def devices_matching(self, pattern):
        """ Device names matching a wildcard anywhere (search) """
        return sorted(_strings(self.db.command_inout("DbGetDeviceWideList", pattern)), key=str.lower)

    def device_table(self):
        """ [(server/instance, class, device)] for every device, in one SQL query;
        None when ``DbMySqlSelect`` is not available (search falls back to names) """
        if not self.has_sql():
            return None
        try:
            rows = self.select("select server, class, name from device order by server, class, name")
        except tango.DevFailed as e:
            log.info("SQL device table failed: %s", e.args[0].desc)
            return None
        return [(r[0], r[1], r[2]) for r in rows if r[0] and r[1] and r[2]]

    def device_info(self, device):
        i = self.db.get_device_info(device)
        return DeviceInfo(i.name, i.ds_full_name, i.class_name, bool(i.exported), i.host, i.pid,
                          i.version, i.started_date, i.stopped_date, i.ior)

    def device_alias(self, device):
        """ Alias of a device or "" """
        try:
            return self.db.get_alias_from_device(device)
        except tango.DevFailed:
            return ""

    # -- Classes -------------------------------------------------------------------
    def classes(self, pattern="*"):
        return sorted(_strings(self.db.get_class_list(pattern)), key=str.lower)

    def class_devices(self, klass):
        """ All devices of a class (Jive's Class tree) """
        if self.has_sql():
            try:
                rows = self.select("select name from device where class='{0}' order by name".format(
                    klass.replace("'", "''")))
                return [r[0] for r in rows if r[0]]
            except tango.DevFailed as e:
                log.info("SQL class device list failed, using the API: %s", e.args[0].desc)
        return sorted(_strings(self.db.get_device_name("*", klass)), key=str.lower)

    def class_attributes(self, klass):
        return sorted(_strings(self.db.get_class_attribute_list(klass, "*")), key=str.lower)

    # -- Aliases -------------------------------------------------------------------
    def device_aliases(self, pattern="*"):
        return sorted(_strings(self.db.get_device_alias_list(pattern)), key=str.lower)

    def alias_device(self, alias):
        return self.db.get_device_from_alias(alias)

    def attribute_aliases(self, pattern="*"):
        return sorted(_strings(self.db.get_attribute_alias_list(pattern)), key=str.lower)

    def alias_attribute(self, alias):
        return self.db.get_attribute_from_alias(alias)

    def attribute_alias(self, attribute):
        """ Alias of a ``device/attribute`` or "" """
        try:
            return self.db.get_alias_from_attribute(attribute)
        except tango.DevFailed:
            return ""

    def put_attribute_alias(self, attribute, alias):
        self.check_write("put_attribute_alias")
        self.db.put_attribute_alias(attribute, alias)

    def delete_attribute_alias(self, alias):
        self.check_write("delete_attribute_alias")
        self.db.delete_attribute_alias(alias)

    # -- Free properties ---------------------------------------------------------------
    def objects(self, pattern="*"):
        return sorted(_strings(self.db.get_object_list(pattern)), key=str.lower)

    # -- Properties (ordered dict name -> list of str) ------------------------------
    def _props(self, names, getter):
        if not names:
            return OrderedDict()
        data = getter(list(names))
        return OrderedDict((n, list(data.get(n, []))) for n in sorted(names, key=str.lower))

    def device_properties(self, device):
        names = _strings(self.db.get_device_property_list(device, "*"))
        return self._props(names, lambda n: self.db.get_device_property(device, n))

    def class_properties(self, klass):
        names = _strings(self.db.get_class_property_list(klass))
        return self._props(names, lambda n: self.db.get_class_property(klass, n))

    def object_properties(self, obj):
        names = _strings(self.db.get_object_property_list(obj, "*"))
        return self._props(names, lambda n: self.db.get_property(obj, n))

    def device_attribute_list(self, device):
        """ Attributes that have properties in the database for this device """
        return sorted(_strings(self.db.command_inout("DbGetDeviceAttributeList", [device, "*"])), key=str.lower)

    def device_attribute_properties(self, device, attribute):
        data = self.db.get_device_attribute_property(device, [attribute])
        return OrderedDict(sorted(((k, list(v)) for k, v in data.get(attribute, {}).items()),
                                  key=lambda kv: kv[0].lower()))

    def class_attribute_properties(self, klass, attribute):
        data = self.db.get_class_attribute_property(klass, [attribute])
        return OrderedDict(sorted(((k, list(v)) for k, v in data.get(attribute, {}).items()),
                                  key=lambda kv: kv[0].lower()))

    def find_usage(self, device):
        """ Devices whose ``__SubDevices`` property names ``device`` (Jive's Find usage), sorted;
        one SQL query when ``DbMySqlSelect`` works, else the admin devices are read one by one """
        target = device.strip().lower()
        if self.has_sql():
            try:
                rows = self.select("select distinct device from property_device where name='__SubDevices' "
                                   "and lower(value)='{0}' order by device".format(target.replace("'", "''")))
                return sorted({r[0] for r in rows if r[0]}, key=str.lower)
            except tango.DevFailed as e:
                log.info("SQL find usage failed: %s", e.args[0].desc)
        out = []
        for admin in self.devices_matching("dserver/*"):
            values = self.db.get_device_property(admin, ["__SubDevices"]).get("__SubDevices", [])
            if any(str(v).strip().lower() == target for v in values):
                out.append(admin)
        return sorted(out, key=str.lower)

    # -- Property selections (Jive's Multiple property selection) --------------------------------
    def device_property_selection(self, device_pattern, name_pattern="*"):
        """ [(device, None, property, values)] for device properties matching the wildcards """
        out = []
        match = wildcard_to_regex(name_pattern)
        for dev in self.devices_matching(device_pattern):
            names = [n for n in _strings(self.db.get_device_property_list(dev, name_pattern)) if match.match(n)]
            if names:
                data = self.db.get_device_property(dev, names)
                out += [(dev, None, n, list(data.get(n, []))) for n in sorted(names, key=str.lower)]
        return out

    def device_attribute_property_selection(self, device_pattern, attribute_pattern="*", name_pattern="*"):
        """ [(device, attribute, property, values)] for device attribute properties matching the
        wildcards: one SQL query when ``DbMySqlSelect`` works, else per device """
        dmatch, amatch, nmatch = (wildcard_to_regex(p) for p in (device_pattern, attribute_pattern, name_pattern))

        def like(p):
            return p.replace("'", "''").replace("*", "%")
        if self.has_sql():
            try:
                rows = self.select(
                    "select device, attribute, name, count, value from property_attribute_device "
                    "where device like '{0}' and attribute like '{1}' and name like '{2}' "
                    "order by device, attribute, name, count".format(
                        like(device_pattern), like(attribute_pattern), like(name_pattern)))
            except tango.DevFailed as e:
                log.info("SQL attribute property selection failed: %s", e.args[0].desc)
                rows = None
            if rows is not None:
                out, index = [], {}
                for dev, att, name, count, value in rows:
                    if not (dev and att and name) or not (dmatch.match(dev) and amatch.match(att)
                                                          and nmatch.match(name)):
                        continue
                    key = (dev.lower(), att.lower(), name.lower())
                    if key not in index:
                        index[key] = len(out)
                        out.append((dev, att, name, []))
                    out[index[key]][3].append(value if value is not None else "")
                return sorted(out, key=lambda r: (r[0].lower(), r[1].lower(), r[2].lower()))
        out = []
        for dev in self.devices_matching(device_pattern):
            atts = [a for a in _strings(self.db.command_inout("DbGetDeviceAttributeList", [dev, attribute_pattern]))
                    if amatch.match(a)]
            if not atts:
                continue
            data = self.db.get_device_attribute_property(dev, atts)
            for att in sorted(atts, key=str.lower):
                for name, values in sorted(data.get(att, {}).items(), key=lambda kv: kv[0].lower()):
                    if nmatch.match(name):
                        out.append((dev, att, name, list(values)))
        return out

    # -- Property writes (refused when read-only) ---------------------------------------
    @staticmethod
    def _datum(props):
        """ {name: str or list of str} -> {name: [str]} """
        return {k: [v] if isinstance(v, str) else [str(x) for x in v] for k, v in props.items()}

    def put_device_property(self, device, props):
        self.check_write("put_device_property")
        self.db.put_device_property(device, self._datum(props))

    def delete_device_property(self, device, names):
        self.check_write("delete_device_property")
        self.db.delete_device_property(device, list(names))

    def delete_device_attribute_property(self, device, attribute, names):
        """ Remove attribute properties (config fields) from the database """
        self.check_write("delete_device_attribute_property")
        self.db.delete_device_attribute_property(device, {attribute: list(names)})

    def put_device_attribute_property(self, device, attribute, props):
        self.check_write("put_device_attribute_property")
        self.db.put_device_attribute_property(device, {attribute: self._datum(props)})

    def put_class_property(self, klass, props):
        self.check_write("put_class_property")
        self.db.put_class_property(klass, self._datum(props))

    def delete_class_property(self, klass, names):
        self.check_write("delete_class_property")
        self.db.delete_class_property(klass, list(names))

    def put_class_attribute_property(self, klass, attribute, props):
        self.check_write("put_class_attribute_property")
        self.db.put_class_attribute_property(klass, {attribute: self._datum(props)})

    def delete_class_attribute_property(self, klass, attribute, names):
        self.check_write("delete_class_attribute_property")
        self.db.delete_class_attribute_property(klass, {attribute: list(names)})

    def put_object_property(self, obj, props):
        """ Free property of an object (Jive's Property tab) """
        self.check_write("put_property")
        self.db.put_property(obj, self._datum(props))

    def delete_object_property(self, obj, names):
        self.check_write("delete_property")
        self.db.delete_property(obj, list(names))

    # -- Servers, devices and aliases (refused when read-only) --------------------------
    def add_device(self, device, klass, server):
        """ Register ``device`` of ``klass`` in ``server`` ("Server/instance") """
        self.check_write("add_device")
        info = tango.DbDevInfo()
        info.name, info._class, info.server = device, klass, server
        self.db.add_device(info)

    def delete_device(self, device):
        self.check_write("delete_device")
        self.db.delete_device(device)

    def add_server(self, server, klass, devices):
        """ Register a server instance with ``devices`` of ``klass`` (and its admin device) """
        self.check_write("add_server")
        infos = []
        for d in devices:
            info = tango.DbDevInfo()
            info.name, info._class, info.server = d, klass, server
            infos.append(info)
        self.db.add_server(server, infos)

    def delete_server(self, server):
        """ Remove a server instance and every device in it """
        self.check_write("delete_server")
        self.db.delete_server(server)

    def rename_server(self, old, new):
        """ ``DbRenameServer``: same devices, new "Server/instance" name """
        self.check_write("rename_server")
        self.db.rename_server(old, new)

    def unexport_server(self, server):
        """ Mark every device of a server as not exported (after a crash) """
        self.check_write("unexport_server")
        self.db.unexport_server(server)

    def unexport_device(self, device):
        self.check_write("unexport_device")
        self.db.unexport_device(device)

    def put_device_alias(self, device, alias):
        self.check_write("put_device_alias")
        self.db.put_device_alias(device, alias)

    def delete_device_alias(self, alias):
        self.check_write("delete_device_alias")
        self.db.delete_device_alias(alias)

    # -- Property history ----------------------------------------------------------------
    @staticmethod
    def _history(entries, with_attribute=False):
        out = []
        for h in entries or ():
            values = list(h.get_value().value_string) if hasattr(h.get_value(), "value_string") \
                else list(h.get_value())
            # Some database servers mark a deletion only by the value "DELETED"
            deleted = bool(h.is_deleted()) or values == ["DELETED"]
            att = h.get_attribute_name() if with_attribute and hasattr(h, "get_attribute_name") else ""
            out.append(PropertyHistory(h.get_date(), h.get_name(), None if deleted else values, deleted, att))
        return out

    def device_property_history(self, device, pattern="*"):
        return self._history(self.db.get_device_property_history(device, pattern))

    def class_property_history(self, klass, pattern="*"):
        return self._history(self.db.get_class_property_history(klass, pattern))

    def object_property_history(self, obj, pattern="*"):
        return self._history(self.db.get_property_history(obj, pattern))

    def device_attribute_property_history(self, device, attribute="*", pattern="*"):
        return self._history(self.db.get_device_attribute_property_history(device, attribute, pattern), True)

    def class_attribute_property_history(self, klass, attribute="*", pattern="*"):
        return self._history(self.db.get_class_attribute_property_history(klass, attribute, pattern), True)

    # -- Hosts and Starters ---------------------------------------------------------------
    def host_servers(self, host):
        return sorted(_strings(self.db.get_host_server_list(host)), key=str.lower)

    def starter_domain(self):
        prop = self.db.get_class_property("Starter", ["Domain"]).get("Domain", [])
        return (list(prop) or ["tango"])[0]

    def starters(self):
        """ [(starter device, collection, usage)] of every Starter device, sorted by device
        (one SQL query for the properties, else per device) """
        devices = self.class_devices("Starter")
        props = {}
        if devices and self.has_sql():
            try:
                header = self.starter_domain() + "/admin/"
                rows = self.select("select device, name, value from property_device where device like '{0}%' and "
                                   "(name='HostCollection' or name='HostUsage') order by device, count"
                                   .format(self.like(header)))
                for dev, name, value in rows:
                    if dev and name in ("HostCollection", "HostUsage"):
                        props.setdefault(dev.lower(), {}).setdefault(name, value or "")
            except tango.DevFailed as e:
                log.info("SQL Starter properties failed, using the API: %s", e.args[0].desc)
                props = None
        if not devices:
            return []
        if not self.has_sql() or props is None:
            props = {}
            for dev in devices:
                data = self.db.get_device_property(dev, ["HostCollection", "HostUsage"])
                props[dev.lower()] = {k: (list(v) or [""])[0] for k, v in data.items() if len(v)}
        out = []
        for dev in devices:
            p = props.get(dev.lower(), {})
            out.append((dev, p.get("HostCollection", ""), p.get("HostUsage", "")))
        return sorted(out, key=lambda t: t[0].lower())

    def host_servers_info(self, host):
        """ [(server, controlled, level)] of the servers that ran on ``host`` (DbGetHostServersInfo) """
        flat = _strings(self.db.command_inout("DbGetHostServersInfo", host))
        out = []
        for i in range(0, len(flat) - 2, 3):
            try:
                level = int(str(flat[i + 2]).strip() or 0)
            except ValueError:
                level = 0
            out.append((flat[i], str(flat[i + 1]).strip() == "1", level))
        return out

    def host_collections(self):
        """ {starter_device: collection} for every Starter (SQL, else per device) """
        header = self.starter_domain() + "/admin/"
        if self.has_sql():
            try:
                rows = self.select("select device, value from property_device where device like '{0}%' "
                                   "and name='HostCollection'".format(self.like(header)))
                return {r[0].lower(): r[1] for r in rows if r[0]}
            except tango.DevFailed as e:
                log.info("SQL collection query failed, using the API: %s", e.args[0].desc)
        result = {}
        for dev in _strings(self.db.get_device_name("*", "Starter")):
            value = self.db.get_device_property(dev, ["HostCollection"]).get("HostCollection", [])
            if len(value):
                result[dev.lower()] = value[0]
        return result


__all__ = ["DatabaseService", "PropertyHistory", "ServerInfo", "DeviceInfo", "ReadOnlyError", "parse_tango_host",
           "split_tango_hosts"]
