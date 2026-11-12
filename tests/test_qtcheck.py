# -*- coding: utf-8 -*-
""" PyQTango.qtcheck: explain why Qt cannot open a window (Linux) """

import sys

import pytest

from PyQTango import qtcheck

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux checks")


def test_offscreen_is_fine(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert qtcheck.platform_problems() == []


def test_no_display(monkeypatch):
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    problems = qtcheck.platform_problems()
    assert any("DISPLAY is not set" in p for p in problems)
    text = qtcheck.format_report(qtcheck.platform_report())
    assert "ssh -X" in text and "QT_DEBUG_PLUGINS" in text


def test_plugin_path_override_and_missing_libraries(monkeypatch):
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("QT_QPA_PLATFORM_PLUGIN_PATH", "/opt/other/plugins")
    monkeypatch.setattr(qtcheck, "_missing_libraries", lambda path: ["libxcb-cursor.so.0"])
    report = qtcheck.platform_report()
    assert any("QT_QPA_PLATFORM_PLUGIN_PATH" in p for p in report["problems"])
    assert any("libxcb-cursor.so.0" in p for p in report["problems"])
    assert "Debian/Ubuntu: sudo apt install libxcb-cursor0" in report["hints"]
    assert "RHEL/Alma/Rocky/Fedora: sudo dnf install xcb-util-cursor" in report["hints"]
