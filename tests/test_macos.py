# -*- coding: utf-8 -*-
""" The macOS menu bar name (set_app_name); the Cocoa calls themselves only run on a Mac """

from PyQTango.core import macos


def test_only_on_macos(monkeypatch):
    called = []
    monkeypatch.setattr(macos, "_with_pyobjc", lambda n: called.append(n))
    assert macos.set_app_name("PyJive", platform="linux") is False
    assert macos.set_app_name("", platform="darwin") is False
    assert called == []
    assert macos.set_app_name("PyJive", platform="darwin") is True
    assert called == ["PyJive"]


def test_falls_back_to_ctypes_and_never_raises(monkeypatch):
    called = []

    def no_pyobjc(_n):
        raise ImportError("No module named 'Foundation'")

    monkeypatch.setattr(macos, "_with_pyobjc", no_pyobjc)
    monkeypatch.setattr(macos, "_with_ctypes", lambda n: called.append(n))
    assert macos.set_app_name("PyJive", platform="darwin") is True
    assert called == ["PyJive"]

    def broken(_n):
        raise OSError("no libobjc")

    monkeypatch.setattr(macos, "_with_ctypes", broken)
    assert macos.set_app_name("PyJive", platform="darwin") is False


def test_make_application_names_the_running_app(qapp):
    from PyQTango.qt import make_application
    old = qapp.applicationName()
    try:
        assert make_application([], name="PyJive Test") is qapp
        assert qapp.applicationName() == "PyJive Test"
    finally:
        qapp.setApplicationName(old)
