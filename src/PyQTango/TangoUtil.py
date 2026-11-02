# -*- coding: utf-8 -*-
"""
Tango database helpers (blocking: call them from a worker thread in GUIs).

@author: Michele Devetta <michele.devetta@cnr.it>
"""

import logging
import concurrent.futures

import tango as PT

log = logging.getLogger(__name__)


def _database(dbhost=None, port=10000):
    if dbhost is not None:
        return PT.Database(dbhost, port)
    return PT.Database()


def getAllRegisteredDevices(dbhost=None, port=10000):
    """ Get all registered devices
        For each device return a dict with ('device': <Device>, 'server': <Server>, 'class': <Class>)
    """
    db = _database(dbhost, port)

    # Fast path: one SQL query (not available on every database server)
    try:
        reply = db.command_inout("DbMySqlSelect", "select name,server,class from device order by name")
        values = list(reply[1])
        return [{'device': values[i], 'server': values[i + 1], 'class': values[i + 2]}
                for i in range(0, len(values) - 2, 3)]
    except PT.DevFailed:
        log.debug("DbMySqlSelect not available, falling back to one query per server")

    # Fallback: scan all registered servers
    dev = []
    for s in db.get_server_list():
        devices = db.get_device_class_list(s)
        for i in range(0, len(devices) - 1, 2):
            dev.append({'device': devices[i], 'server': s, 'class': devices[i + 1]})
    return dev


def _check_alive(dev):
    try:
        d = PT.DeviceProxy(dev['device'])
        d.set_timeout_millis(1000)
        d.ping()
        dev['alive'] = True
    except PT.DevFailed:
        dev['alive'] = False
    return dev


def checkDevicesAreLive(dev_list, max_workers=16):
    """ Check if the devices specified in the list of dict are live. Add an alive field to the dicts.
    """
    out = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_check_alive, d) for d in dev_list]
        for future in concurrent.futures.as_completed(futures):
            try:
                out.append(future.result())
            except Exception:  # noqa: BLE001 - skip failed device
                pass
    return out


def getAllLiveDevices(dbhost=None, port=10000):
    """ Get all live devices
        For each device return a dict with ('device': <Device>, 'server': <Server>, 'class': <Class>)
    """
    alive = []
    for d in checkDevicesAreLive(getAllRegisteredDevices(dbhost, port)):
        if d.pop('alive', False):
            alive.append(d)
    return alive


def getAllLiveAttributes(dbhost=None, port=10000):
    """ Get all attributes from live devices
    """
    attr_list = []
    for d in getAllLiveDevices(dbhost, port):
        try:
            dev = PT.DeviceProxy(d['device'])
            for conf in dev.attribute_list_query_ex():
                attr_list.append({'attribute': d['device'] + "/" + conf.name,
                                  'data_format': conf.data_format, 'data_type': conf.data_type})
        except PT.DevFailed:
            pass
    return attr_list


def getAllLiveDevicesByClass(class_list, dbhost=None, port=10000):
    """ Get all live devices for the classes given in class_list
    """
    db = _database(dbhost, port)
    devs = []
    for cl in class_list:
        datum = db.get_device_exported_for_class(cl)
        for d in datum.value_string:
            devs.append({'device': d})
    return checkDevicesAreLive(devs)
