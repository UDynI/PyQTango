# -*- coding: utf-8 -*-
"""
Start a throw-away Tango database server for tests and demos.

By default: PyTango's database server on a fresh SQLite file. ``TANGO_TEST_DB_PYTHON`` names
the Python that runs it (default: the one running the tests). PyTango 9.5's server does not
start, so test a PyTango 9.5 client against the server of a PyTango 10 environment.

With ``TANGO_TEST_MARIADB=mysql://user:password@host:port`` set: the C++
``Databaseds`` on a fresh MariaDB/MySQL schema (``tango_test_<pid>_<n>``), created
from the Tango schema scripts and dropped again by :func:`stop_database`, so each
test module still gets an empty database and the ``tango`` schema is never touched.
The user needs the right to create and drop schemas. Optional settings:

``TANGO_TEST_DATABASEDS``
    the ``Databaseds`` executable (default: on PATH, else /usr/lib/tango/Databaseds)
``TANGO_TEST_DB_SQL``
    the schema install script, as shipped by TangoDatabase (default: the Debian
    tango-db package's /usr/share/dbconfig-common/data/tango-db/install/mysql);
    its ``source`` lines are inlined, and the ``tango.`` schema prefix replaced
``TANGO_TEST_MYSQL_CLI``
    the SQL client command line, e.g. ``docker exec -i tango-db mariadb -uroot -psecret``
    (default: ``mariadb`` or ``mysql`` with the URL's credentials)
"""

import itertools
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import urlparse, unquote

import tango

MARIADB_ENV = "TANGO_TEST_MARIADB"
DB_PYTHON_ENV = "TANGO_TEST_DB_PYTHON"
DEBIAN_SQL = "/usr/share/dbconfig-common/data/tango-db/install/mysql"
_schemas = itertools.count(1)


def backend():
    """ "mariadb" when TANGO_TEST_MARIADB is set, else "sqlite" """
    return "mariadb" if os.environ.get(MARIADB_ENV) else "sqlite"


def start_database(workdir, timeout=30.0):
    """ Start a database server on a free port with an empty database.
    Returns ``(process, "host:port")``. """
    if backend() == "mariadb":
        return _start_mariadb(workdir, timeout)
    return _start_sqlite(workdir, timeout)


def _start_sqlite(workdir, timeout):
    env = dict(os.environ)
    env["PYTANGO_DATABASE_NAME"] = os.path.join(str(workdir), "tango_test.db")
    env.pop("TANGO_HOST", None)
    proc = subprocess.Popen(
        [os.environ.get(DB_PYTHON_ENV, sys.executable), "-m", "tango.databaseds.database",
         "--port", "0", "--host", "127.0.0.1",
         "--print-host-port", "2"],
        cwd=str(workdir), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    deadline = time.time() + timeout
    port = None
    while time.time() < deadline:
        line = proc.stderr.readline()
        if not line:
            if proc.poll() is not None:
                raise RuntimeError("database server exited with code {0}".format(proc.returncode))
            continue
        m = re.search(r"port=(\d+)", line)
        if m:
            port = int(m.group(1))
            break
    if port is None:
        proc.kill()
        raise RuntimeError("database server did not start")
    tango_host = "127.0.0.1:{0}".format(port)
    # Wait until it answers
    while time.time() < deadline:
        try:
            tango.Database("127.0.0.1", port).get_info()
            return proc, tango_host
        except tango.DevFailed:
            time.sleep(0.2)
    proc.kill()
    raise RuntimeError("database server not answering")


def stop_database(proc):
    proc.terminate()
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        proc.kill()
    schema = getattr(proc, "tango_schema", None)
    if schema:
        _sql("DROP DATABASE IF EXISTS `{0}`;".format(schema))


# -- MariaDB / MySQL with the C++ Databaseds ---------------------------------------------------
def _url():
    u = urlparse(os.environ[MARIADB_ENV])
    if u.scheme not in ("mysql", "mariadb") or not u.hostname:
        raise RuntimeError("{0} must look like mysql://user:password@host:3306".format(MARIADB_ENV))
    return u


def _cli():
    custom = os.environ.get("TANGO_TEST_MYSQL_CLI")
    if custom:
        return shlex.split(custom)
    u = _url()
    exe = shutil.which("mariadb") or shutil.which("mysql")
    if exe is None:
        raise RuntimeError("no mariadb/mysql client: install one or set TANGO_TEST_MYSQL_CLI")
    cmd = [exe, "-h", u.hostname, "-P", str(u.port or 3306), "-u", unquote(u.username or "root")]
    if u.password:
        cmd.append("-p" + unquote(u.password))
    return cmd


def _sql(text):
    r = subprocess.run(_cli(), input=text, text=True, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("SQL failed: {0}".format(r.stderr.strip()))
    return r.stdout


def _schema_script(schema):
    path = os.environ.get("TANGO_TEST_DB_SQL", DEBIAN_SQL)
    if not os.path.exists(path):
        raise RuntimeError("Tango schema script not found: {0} (set TANGO_TEST_DB_SQL)".format(path))

    def expand(p):
        out = []
        for line in open(p, encoding="utf-8", errors="replace"):
            m = re.match(r"\s*source\s+(\S+)", line, re.I)
            if m:
                inner = m.group(1).rstrip(";")
                if not os.path.isabs(inner):
                    inner = os.path.join(os.path.dirname(p), inner)
                out.append(expand(inner))
            elif not re.match(r"\s*(USE|CREATE DATABASE)\b", line, re.I):
                out.append(line)
        return "".join(out)
    text = re.sub(r"\btango\.", "`{0}`.".format(schema), expand(path))
    return "CREATE DATABASE `{0}`;\nUSE `{0}`;\n{1}".format(schema, text)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start_mariadb(workdir, timeout):
    u = _url()
    schema = "tango_test_{0}_{1}".format(os.getpid(), next(_schemas))
    _sql("DROP DATABASE IF EXISTS `{0}`;".format(schema))
    _sql(_schema_script(schema))
    exe = os.environ.get("TANGO_TEST_DATABASEDS") or shutil.which("Databaseds") or "/usr/lib/tango/Databaseds"
    port = _free_port()
    env = dict(os.environ, MYSQL_HOST="{0}:{1}".format(u.hostname, u.port or 3306),
               MYSQL_USER=unquote(u.username or "root"), MYSQL_PASSWORD=unquote(u.password or ""),
               MYSQL_DATABASE=schema, TANGO_HOST="127.0.0.1:{0}".format(port))
    log = open(os.path.join(str(workdir), "databaseds.log"), "w")
    proc = subprocess.Popen([exe, "2", "-ORBendPoint", "giop:tcp:127.0.0.1:{0}".format(port)],
                            cwd=str(workdir), env=env, stdout=log, stderr=subprocess.STDOUT)
    proc.tango_schema = schema
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            _sql("DROP DATABASE IF EXISTS `{0}`;".format(schema))
            raise RuntimeError("Databaseds exited (see {0})".format(log.name))
        try:
            tango.Database("127.0.0.1", port).get_info()
            return proc, "127.0.0.1:{0}".format(port)
        except tango.DevFailed:
            time.sleep(0.3)
    stop_database(proc)
    raise RuntimeError("Databaseds did not answer")


def populate(tango_host):
    """ A small control system: servers, classes, devices, properties, aliases,
    free properties and Starters, used by tests and the demo """
    host, port = tango_host.split(":")
    db = tango.Database(host, int(port))

    def add(dev, cls, srv):
        info = tango.DbDevInfo()
        info.name, info._class, info.server = dev, cls, srv
        db.add_device(info)

    for i in (1, 2, 3):
        add("sys/tg_test/{0}".format(i), "TangoTest", "TangoTest/test{0}".format(i))
    add("lab/power/ps1", "PowerSupply", "PowerSupply/lab")
    add("lab/power/ps2", "PowerSupply", "PowerSupply/lab")
    add("lab/vac/gauge1", "VacGauge", "PowerSupply/lab")
    add("lab/motor/m1", "Motor", "Motion/axis")
    add("tango/admin/hosta", "Starter", "Starter/hosta")
    add("tango/admin/hostb", "Starter", "Starter/hostb")
    db.put_device_property("tango/admin/hosta", {"HostCollection": ["Lab"], "HostUsage": ["Power supplies"],
                                                 "StartDsPath": ["/usr/local/bin"]})
    db.put_device_property("tango/admin/hostb", {"HostCollection": ["Beamline"]})
    db.put_device_property("lab/power/ps1", {"Current_max": ["10.5"], "Description": ["Main supply", "line 2"],
                                             "polled_attr": ["current", "3000"]})
    db.put_device_property("lab/power/ps2", {"Current_max": ["8"]})
    db.put_class_property("PowerSupply", {"Vendor": ["ACME"]})
    db.put_device_attribute_property("lab/power/ps1", {"current": {"unit": ["A"], "format": ["%6.2f"]}})
    db.put_class_attribute_property("PowerSupply", {"voltage": {"unit": ["V"]}})
    db.put_device_alias("lab/power/ps1", "ps1")
    db.put_device_alias("lab/motor/m1", "m1")
    db.put_attribute_alias("lab/power/ps1/current", "ps1_current")
    db.put_property("Astor", {"LastCollections": ["Beamline"]})
    db.put_property("CtrlSystem", {"Name": ["Test system"]})
    return db


# -- Hosts (fake Starters) ----------------------------------------------------------------------
#: server -> (host, controlled, level) written by setup_hosts()
HOST_SERVERS = {
    "PowerSupply/lab": ("hosta", True, 1),
    "Motion/axis": ("hosta", True, 2),
    "TangoTest/test2": ("hosta", False, 0),
    "TangoTest/test1": ("hostb", True, 1),
    "TangoTest/test3": ("hostb", True, 3),
}


def setup_hosts(tango_host, servers=None):
    """ Put the server info (host, controlled, level) of ``servers`` (default HOST_SERVERS) """
    host, port = tango_host.split(":")
    db = tango.Database(host, int(port))
    for name, (h, controlled, level) in (servers or HOST_SERVERS).items():
        info = tango.DbServerInfo()
        info.name, info.host, info.mode, info.level = name, h, 1 if controlled else 0, level
        db.put_server_info(info)
        # The databases list a host's servers from where their admin device was last
        # exported: export it once on that host, then unexport it (it ran there before)
        exp = tango.DbDevExportInfo()
        exp.name, exp.ior, exp.host, exp.version, exp.pid = "dserver/" + name, "IOR:00", h, "6", 0
        db.export_device(exp)
        db.unexport_device("dserver/" + name)
    return db


def add_starters(tango_host, hosts, instance, collection=None):
    """ Register ``tango/admin/<host>`` Starter devices of the server Starter/<instance> """
    host, port = tango_host.split(":")
    db = tango.Database(host, int(port))
    infos = []
    for h in hosts:
        info = tango.DbDevInfo()
        info.name, info._class, info.server = "tango/admin/" + h, "Starter", "Starter/" + instance
        infos.append(info)
    if hasattr(db, "add_server") and len(infos) > 1:
        db.add_server(infos[0].server, infos, with_dserver=True)
    else:
        for info in infos:
            db.add_device(info)
    if collection is not None:
        for h in hosts:
            db.put_device_property("tango/admin/" + h, {"HostCollection": [collection]})
    return db


def start_starter(tango_host, instance, devices, timeout=60.0):
    """ Run tests/starterserver.py as Starter/<instance>; returns the process once ``devices`` answer """
    here = os.path.dirname(os.path.abspath(__file__))
    env = dict(os.environ, TANGO_HOST=tango_host)
    proc = subprocess.Popen([sys.executable, os.path.join(here, "starterserver.py"), instance], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + timeout
    for dev in devices:
        p = tango.DeviceProxy("tango://{0}/{1}".format(tango_host, dev))
        while True:
            try:
                p.ping()
                break
            except tango.DevFailed:
                if time.time() > deadline or proc.poll() is not None:
                    proc.kill()
                    raise RuntimeError("fake Starter {0} did not start".format(instance))
                time.sleep(0.3)
    return proc
