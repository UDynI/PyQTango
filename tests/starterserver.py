# -*- coding: utf-8 -*-
"""
Fake Starter for the tests (plan 8.2): the Starter 9.1 interface over an
in-memory server table, without starting any process.

* The table comes from the database (``DbGetHostServersInfo`` of the host the
  device is named after, ``<domain>/admin/<host>``); a server whose admin
  device answers starts as running.
* ``DevStart`` marks a server MOVING for ``StartDelay`` seconds, then ON;
  ``DevStop`` stops it at once. Both log as the real Starter does
  (``dd/mm/yy   hh:mm:ss<TAB><server> started|stopped``, newest first) and raise
  its errors ("is already running !", "is NOT running !", "Unknown Server !").
* ``DevStartAll`` / ``DevStopAll`` act on the controlled servers of a level.
* State and Status follow the Starter rules (ON, MOVING, STANDBY, ALARM, OFF).
* ``Servers``, ``RunningServers``, ``StoppedServers`` and ``HostState``.
* ``DevReadLog("Starter" | "Statistics" | <server>)`` in the verified formats.

Run: ``python starterserver.py <instance>`` with TANGO_HOST set.
"""

import sys
import time
import threading

import tango
from tango import DevState, AttrWriteType
from tango.server import Device, attribute, command, device_property, run


def _strtime(t):
    return time.strftime("%d/%m/%y   %H:%M:%S", time.localtime(t))


class Starter(Device):

    StartDelay = device_property(dtype=float, default_value=0.4)
    MovingMaxDuration = device_property(dtype=float, default_value=120.0)

    def init_device(self):
        super().init_device()
        self._lock = threading.Lock()
        self.host = self.get_name().split("/")[-1]
        self._servers = {}        # name -> dict(controlled, level, state, moving_since, instances)
        self._log = []
        self._stats = []
        self._load()
        self._write_log("Starter startup")

    # -- Table -------------------------------------------------------------------
    def _db(self):
        return tango.Database()

    def _load(self):
        db = self._db()
        try:
            flat = list(db.command_inout("DbGetHostServersInfo", self.host))
        except tango.DevFailed:
            flat = []
        with self._lock:
            old = self._servers
            self._servers = {}
            for i in range(0, len(flat) - 2, 3):
                name, controlled, level = flat[i], flat[i + 1], flat[i + 2]
                prev = old.get(name)
                if prev is not None:
                    state = prev["state"]
                    instances = prev["instances"]
                else:
                    exported = self._alive(name)
                    state = "ON" if exported else "FAULT"
                    instances = 1 if exported else 0
                self._servers[name] = {"controlled": str(controlled).strip() == "1",
                                       "level": int(str(level).strip() or 0), "state": state,
                                       "moving_since": prev["moving_since"] if prev else 0.0,
                                       "instances": instances}

    @staticmethod
    def _alive(name):
        """ True when the server's admin device answers (fake servers never do) """
        try:
            p = tango.DeviceProxy("dserver/" + name)
            p.set_timeout_millis(300)
            p.ping()
            return True
        except tango.DevFailed:
            return False

    def _tick(self):
        now = time.time()
        with self._lock:
            for name, s in self._servers.items():
                if s["state"] == "MOVING" and now - s["moving_since"] >= self.StartDelay:
                    s["state"] = "ON"
                    s["instances"] = 1

    def _write_log(self, message):
        self._log.insert(0, "{0}\t{1}".format(_strtime(time.time()), message))
        del self._log[400:]

    # -- State -------------------------------------------------------------------
    def dev_state(self):
        self._tick()
        with self._lock:
            controlled = [s for s in self._servers.values() if s["controlled"]]
        if not controlled:
            self.set_status("All controlled servers are running")
            return DevState.ON
        now = time.time()
        moving = [s for s in controlled if s["state"] == "MOVING"]
        long_moving = [s for s in moving if now - s["moving_since"] > self.MovingMaxDuration]
        running = [s for s in controlled if s["state"] == "ON"]
        twice = [s for s in running if s["instances"] > 1]
        if moving and not long_moving:
            self.set_status("At least one of the  controlled servers is running but not responding")
            return DevState.MOVING
        if long_moving:
            self.set_status("At least one of the  controlled servers is running but not responding since a while")
            return DevState.STANDBY
        if len(running) == len(controlled):
            if twice:
                self.set_status("At least one server is running twice")
                return DevState.ALARM
            self.set_status("All controlled servers are running")
            return DevState.ON
        if not running:
            self.set_status("All controlled servers are not running")
            return DevState.OFF
        self.set_status("At least one of the  controlled servers is not running")
        return DevState.ALARM

    def dev_status(self):
        self.dev_state()
        return self.get_status()

    # -- Attributes --------------------------------------------------------------
    @attribute(dtype=(str,), max_dim_x=4096)
    def Servers(self):
        self._tick()
        with self._lock:
            return ["{0}\t{1}\t{2}\t{3}\t{4}".format(n, s["state"], int(s["controlled"]), s["level"], s["instances"])
                    for n, s in sorted(self._servers.items())]

    @attribute(dtype=(str,), max_dim_x=4096)
    def RunningServers(self):
        self._tick()
        with self._lock:
            return sorted(n for n, s in self._servers.items() if s["state"] == "ON")

    @attribute(dtype=(str,), max_dim_x=4096)
    def StoppedServers(self):
        self._tick()
        with self._lock:
            return sorted(n for n, s in self._servers.items() if s["state"] != "ON")

    @attribute(dtype=int)
    def HostState(self):
        return int(self.dev_state())

    @attribute(dtype=int, access=AttrWriteType.READ_WRITE)
    def NbInstancesHack(self):
        return 0

    @NbInstancesHack.write
    def NbInstancesHack(self, v):
        """ Test helper: the first running server appears to run ``v`` times """
        with self._lock:
            for s in self._servers.values():
                if s["state"] == "ON":
                    s["instances"] = int(v)
                    break

    # -- Commands ----------------------------------------------------------------
    def _get(self, name):
        s = self._servers.get(name)
        if s is None:
            raise tango.DevFailed(tango.DevError())
        return s

    @command(dtype_in=str)
    def DevStart(self, name):
        self._tick()
        with self._lock:
            s = self._servers.get(name)
            if s is None:
                # Not in the table yet (Start New): known to the database?
                info = self._db().command_inout("DbGetServerInfo", name)
                s = {"controlled": False, "level": 0, "state": "FAULT", "moving_since": 0.0, "instances": 0}
                if not info or not info[0]:
                    tango.Except.throw_exception(name + ": Unknown Server !", name + ": Unknown Server !",
                                                 "Starter::dev_start()")
                self._servers[name] = s
            if s["state"] in ("ON", "MOVING"):
                tango.Except.throw_exception("ALREADY_RUNNING", name + " is already running !",
                                             "Starter::processCouldStart()")
            s["state"] = "MOVING"
            s["moving_since"] = time.time()
        self._write_log(name + " started")
        self._stats.insert(0, "{0}\tON\t{1}\t0\t0".format(name, int(time.time())))

    @command(dtype_in=str)
    def DevStop(self, name):
        self._tick()
        with self._lock:
            s = self._servers.get(name)
            if s is None:
                tango.Except.throw_exception(name + ": Unknown Server !", name + ": Unknown Server !",
                                             "Starter::dev_stop()")
            if s["state"] == "MOVING":
                tango.Except.throw_exception("SERVER_NOT_RESPONDING", name + " is running but not responding !",
                                             "Starter::dev_stop()")
            if s["state"] != "ON":
                tango.Except.throw_exception("SERVER_NOT_RUNNING", name + " is NOT running !",
                                             "Starter::dev_stop()")
            s["state"] = "FAULT"
            s["instances"] = 0
        self._write_log(name + " stopped")

    @command(dtype_in=str)
    def HardKillServer(self, name):
        with self._lock:
            s = self._servers.get(name)
            if s is None or s["state"] == "FAULT":
                tango.Except.throw_exception("SERVER_NOT_RUNNING", "Server " + name + " is not running !",
                                             "Starter::hard_kill_server()")
            s["state"] = "FAULT"
            s["instances"] = 0

    def _level(self, level):
        with self._lock:
            return sorted(n for n, s in self._servers.items() if s["controlled"] and s["level"] == level)

    @command(dtype_in=tango.DevShort)
    def DevStartAll(self, level):
        if not self._servers:
            tango.Except.throw_exception("NO Server  controlled !", "NO Server  controlled !",
                                         "Starter::dev_start_all()")
        for name in self._level(level):
            if self._servers[name]["state"] == "FAULT":
                self.DevStart(name)

    @command(dtype_in=tango.DevShort)
    def DevStopAll(self, level):
        if not self._servers:
            tango.Except.throw_exception("NO Server  controlled !", "NO Server  controlled !",
                                         "Starter::dev_stop_all()")
        for name in self._level(level):
            if self._servers[name]["state"] == "ON":
                self.DevStop(name)

    @command(dtype_in=bool, dtype_out=(str,))
    def DevGetRunningServers(self, all_servers):
        self._tick()
        with self._lock:
            return sorted(n for n, s in self._servers.items() if s["state"] == "ON" and (all_servers or s["controlled"]))

    @command(dtype_in=bool, dtype_out=(str,))
    def DevGetStopServers(self, all_servers):
        self._tick()
        with self._lock:
            return sorted(n for n, s in self._servers.items() if s["state"] != "ON" and (all_servers or s["controlled"]))

    @command(dtype_in=str, dtype_out=str)
    def DevReadLog(self, name):
        if name == "Starter":
            return "\n".join(self._log) + "\n"
        if name == "Statistics":
            return "\n".join(self._stats) + ("\n" if self._stats else "")
        if name not in self._servers:
            tango.Except.throw_exception("Cannot open /tmp/" + name.replace("/", "_") + ".log",
                                         "No such file or directory", "Starter::dev_read_log")
        return "/tmp/{0}.log\n{1}\n\n{0} standard output\nline 2\n".format(name.replace("/", "_"),
                                                                             _strtime(time.time()))

    @command
    def UpdateServersInfo(self):
        self._load()

    @command
    def ResetStatistics(self):
        self._stats = []


if __name__ == "__main__":
    run((Starter,), args=["Starter"] + sys.argv[1:])
