# -*- coding: utf-8 -*-
"""
macOS: the application's name in the menu bar and the Dock.

macOS takes that name from the main bundle's ``CFBundleName``. A script run
by Python has Python's bundle (or none), so the menu bar says "Python" or
"python3.12" whatever ``QApplication.setApplicationName`` says.
:func:`set_app_name` writes ``CFBundleName`` into the main bundle's info
dictionary, and renames the process, before Qt starts Cocoa: it must be
called before the ``QApplication`` is made (:func:`PyQTango.qt.make_application`
does it when given ``name``). PyObjC is used when installed, else ``ctypes``
on the Objective-C runtime. It does nothing on other systems and never raises.
"""

import ctypes
import ctypes.util
import logging
import sys

__all__ = ["set_app_name"]

log = logging.getLogger(__name__)
_KEYS = ("CFBundleName", "CFBundleDisplayName")


def _with_pyobjc(name):
    from Foundation import NSBundle, NSProcessInfo     # noqa: PLC0415 (PyObjC is optional)
    bundle = NSBundle.mainBundle()
    info = bundle.infoDictionary()
    if info is not None:
        for key in _KEYS:
            info[key] = name
    try:
        # a translated name, if Python's bundle has one, wins over CFBundleName (may be read-only)
        localized = bundle.localizedInfoDictionary()
        if localized is not None and "CFBundleName" in localized:
            localized["CFBundleName"] = name
    except Exception:  # noqa: BLE001
        pass
    NSProcessInfo.processInfo().setProcessName_(name)


def _with_ctypes(name):
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    ctypes.cdll.LoadLibrary(ctypes.util.find_library("Foundation"))
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value

    def send(obj, selector, *args, restype=ctypes.c_void_p):
        # objc_msgSend is called through a prototype of the exact types (required on arm64)
        proto = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *[ctypes.c_void_p] * len(args))
        return proto(address)(obj, objc.sel_registerName(selector.encode()), *args)

    def cls(n):
        return objc.objc_getClass(n.encode())

    def string(text):
        # alloc/init, not stringWithUTF8String: there is no autorelease pool yet
        proto = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)
        obj = send(cls("NSString"), "alloc")
        return proto(address)(obj, objc.sel_registerName(b"initWithUTF8String:"), text.encode("utf-8"))

    value = string(name)
    bundle = send(cls("NSBundle"), "mainBundle")
    if bundle:
        info = send(bundle, "infoDictionary")
        if info:
            for key in _KEYS:
                send(info, "setObject:forKey:", value, string(key), restype=None)
    process = send(cls("NSProcessInfo"), "processInfo")
    if process:
        send(process, "setProcessName:", value, restype=None)


def set_app_name(name, platform=None):
    """ Show ``name`` in the macOS menu bar and Dock; True when it was set """
    if (platform or sys.platform) != "darwin" or not name:
        return False
    for how in (_with_pyobjc, _with_ctypes):
        try:
            how(name)
            return True
        except Exception as exc:  # noqa: BLE001 - a cosmetic setting must never stop the application
            log.debug("set_app_name via %s: %s", how.__name__, exc)
    return False
