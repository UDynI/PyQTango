# -*- coding: utf-8 -*-
"""
Diagnose why a Qt application cannot open a window on Linux.

    python -m PyQTango.qtcheck

Qt aborts the process (no Python exception) when its platform plugin cannot
start, so applications call :func:`platform_problems` before creating the
QApplication and print the report instead of dumping core.

Nothing here creates a QApplication.
"""

import os
import shutil
import subprocess
import sys

# Libraries the xcb plugin of the PyQt wheels loads, with the packages that provide them
_PACKAGES = {
    "libxcb-cursor.so.0": ("libxcb-cursor0", "xcb-util-cursor"),
    "libxcb-icccm.so.4": ("libxcb-icccm4", "xcb-util-wm"),
    "libxcb-image.so.0": ("libxcb-image0", "xcb-util-image"),
    "libxcb-keysyms.so.1": ("libxcb-keysyms1", "xcb-util-keysyms"),
    "libxcb-render-util.so.0": ("libxcb-render-util0", "xcb-util-renderutil"),
    "libxcb-xinerama.so.0": ("libxcb-xinerama0", "libxcb"),
    "libxcb-randr.so.0": ("libxcb-randr0", "libxcb"),
    "libxcb-shape.so.0": ("libxcb-shape0", "libxcb"),
    "libxcb-xkb.so.1": ("libxcb-xkb1", "libxcb"),
    "libxkbcommon-x11.so.0": ("libxkbcommon-x11-0", "libxkbcommon-x11"),
    "libxkbcommon.so.0": ("libxkbcommon0", "libxkbcommon"),
    "libEGL.so.1": ("libegl1", "libglvnd-egl"),
    "libGL.so.1": ("libgl1", "libglvnd-glx"),
    "libfontconfig.so.1": ("libfontconfig1", "fontconfig"),
    "libdbus-1.so.3": ("libdbus-1-3", "dbus-libs"),
}

_ENV = ("DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE", "QT_QPA_PLATFORM", "QT_PLUGIN_PATH",
        "QT_QPA_PLATFORM_PLUGIN_PATH", "PYQTANGO_QT_API", "LD_LIBRARY_PATH")


def _plugins_dir(QtCore):
    try:
        return QtCore.QLibraryInfo.location(QtCore.QLibraryInfo.PluginsPath)          # Qt5
    except AttributeError:
        return QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.LibraryPath.PluginsPath)  # Qt6


def _missing_libraries(path):
    """ Libraries ``ldd`` cannot resolve for ``path``; None when ldd is unavailable """
    if shutil.which("ldd") is None:
        return None
    try:
        out = subprocess.run(["ldd", path], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return sorted({line.split("=>")[0].strip() for line in out.splitlines() if "not found" in line})


def platform_report():
    """ dict with the binding, Qt version, plugin directory, environment and problems found """
    from .qt import QtCore, API
    report = {"binding": API, "qt": QtCore.QT_VERSION_STR, "python": sys.version.split()[0],
              "env": {k: os.environ.get(k) for k in _ENV}, "problems": [], "hints": []}
    plugins = _plugins_dir(QtCore)
    report["plugins_dir"] = plugins
    platforms = os.path.join(plugins, "platforms") if plugins else ""
    report["platforms"] = sorted(os.listdir(platforms)) if os.path.isdir(platforms) else []
    if not sys.platform.startswith("linux"):
        return report

    env = report["env"]
    wanted = (env.get("QT_QPA_PLATFORM") or "").split(":")[0].split(";")[0].strip().lower()
    if wanted in ("offscreen", "minimal", "vnc", "eglfs", "linuxfb"):
        return report
    for var in ("QT_QPA_PLATFORM_PLUGIN_PATH", "QT_PLUGIN_PATH"):
        if env.get(var):
            report["problems"].append("{0} is set to '{1}': Qt looks for its platform plugins there "
                                      "instead of (or before) the {2} wheel.".format(var, env[var], API))
            report["hints"].append("Unset it for this application: env -u {0} pyjive ...".format(var))
    use_wayland = wanted.startswith("wayland") or (not wanted and API == "PyQt6" and env.get("WAYLAND_DISPLAY"))
    if use_wayland:
        return report
    if not env.get("DISPLAY"):
        report["problems"].append("DISPLAY is not set: there is no X server to open windows on "
                                  "(an SSH session without -X/-Y, or a service without a desktop).")
        report["hints"].append("Run from a desktop session, use 'ssh -X' (or -Y), or a VNC/X2Go session.")
    xcb = os.path.join(platforms, "libqxcb.so")
    if not os.path.isfile(xcb):
        report["problems"].append("The xcb platform plugin is missing from {0}.".format(platforms or "the wheel"))
        report["hints"].append("Reinstall the binding: pip install --force-reinstall {0} {0}-Qt{1}".format(
            API, API[-1]))
        return report
    missing = _missing_libraries(xcb)
    if missing:
        report["problems"].append("The xcb plugin cannot load: missing system libraries " + ", ".join(missing))
        deb = sorted({_PACKAGES.get(m, (m, m))[0] for m in missing})
        rpm = sorted({_PACKAGES.get(m, (m, m))[1] for m in missing})
        report["hints"].append("Debian/Ubuntu: sudo apt install " + " ".join(deb))
        report["hints"].append("RHEL/Alma/Rocky/Fedora: sudo dnf install " + " ".join(rpm))
    return report


def platform_problems():
    """ List of problem strings (empty when Qt should be able to open a window) """
    try:
        return platform_report()["problems"]
    except Exception:  # noqa: BLE001 (the check must never stop a working setup)
        return []


def format_report(report):
    lines = ["Qt binding      : {binding} (Qt {qt}), Python {python}".format(**report),
             "Plugins dir     : {0}".format(report.get("plugins_dir")),
             "Platform plugins: {0}".format(", ".join(report.get("platforms", [])) or "none")]
    for k, v in report["env"].items():
        lines.append("{0:<16}: {1}".format(k, v if v is not None else "(not set)"))
    if report["problems"]:
        lines.append("")
        lines.append("Problems:")
        lines += ["  - " + p for p in report["problems"]]
        lines.append("")
        lines.append("What to do:")
        lines += ["  - " + h for h in report["hints"]]
        lines.append("  - For Qt's own diagnosis: QT_DEBUG_PLUGINS=1 <command>")
    else:
        lines.append("")
        lines.append("No problem found.")
    return "\n".join(lines)


def main():
    report = platform_report()
    print(format_report(report))
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
