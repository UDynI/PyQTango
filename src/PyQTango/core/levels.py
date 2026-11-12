# -*- coding: utf-8 -*-
"""
LevelWalker: start or stop servers level by level on one or more hosts
(Astor's ServerCmdThread), without Qt.

Start walks the levels upward, stop downward, skipping levels no host uses.
Before each level ``decide(action, level)`` returns "yes", "no", "all" (yes
for this and every following level) or "cancel". For each host using the level
``command(host, level)`` runs (DevStartAll or DevStopAll), then the walker
pauses (500 ms after a start, 50 ms after a stop by default). Errors do not
stop the walk: every (host, level) gets a :class:`LevelResult`.

The walker runs in a worker thread; ``progress(done, total, text)`` reports
and ``cancelled()`` is polled between hosts.

@author: Michele Devetta <michele.devetta@cnr.it>
"""

import time
from dataclasses import dataclass

__all__ = ["LevelWalker", "LevelResult", "levels_in_use", "START", "STOP"]

START = "start"
STOP = "stop"


@dataclass
class LevelResult:
    host: str
    level: int
    ok: bool
    message: str = ""
    skipped: bool = False


def levels_in_use(servers_by_host, controlled_only=True):
    """ Sorted levels (> 0) used by any host; ``servers_by_host`` maps host -> [ServerLine] """
    levels = set()
    for servers in servers_by_host.values():
        for s in servers:
            if (s.controlled or not controlled_only) and s.level > 0:
                levels.add(s.level)
    return sorted(levels)


class LevelWalker(object):
    """ Start or stop by level.

    ``hosts_levels`` maps host -> the levels it uses; ``command(host, level)``
    does the work (raise to report a failure).
    """

    def __init__(self, action, hosts_levels, command, decide=None, progress=None, cancelled=None,
                 pause_start=0.5, pause_stop=0.05, sleep=time.sleep):
        if action not in (START, STOP):
            raise ValueError("action must be 'start' or 'stop'")
        self.action = action
        self.hosts_levels = {h: sorted(set(lv)) for h, lv in hosts_levels.items()}
        self.command = command
        self.decide = decide or (lambda action, level: "yes")
        self.progress = progress or (lambda done, total, text: None)
        self.cancelled = cancelled or (lambda: False)
        self.pause = pause_start if action == START else pause_stop
        self.sleep = sleep
        self.results = []
        self.was_cancelled = False

    def levels(self):
        all_levels = sorted({lv for levels in self.hosts_levels.values() for lv in levels if lv > 0})
        return all_levels if self.action == START else list(reversed(all_levels))

    def run(self):
        levels = self.levels()
        total = sum(1 for lv in levels for h in self.hosts_levels if lv in self.hosts_levels[h])
        done = 0
        for_all = False
        for lv in levels:
            hosts = sorted(h for h in self.hosts_levels if lv in self.hosts_levels[h])
            if not for_all:
                answer = self.decide(self.action, lv)
                if answer == "cancel":
                    self.was_cancelled = True
                    break
                if answer == "all":
                    for_all = True
                elif answer != "yes":
                    for h in hosts:
                        self.results.append(LevelResult(h, lv, True, "skipped", skipped=True))
                        done += 1
                    self.progress(done, total, "Level {0} skipped".format(lv))
                    continue
            for h in hosts:
                if self.cancelled():
                    self.was_cancelled = True
                    return self.results
                self.progress(done, total, "{0} level {1} on {2}".format(
                    "Starting" if self.action == START else "Stopping", lv, h))
                try:
                    self.command(h, lv)
                    self.results.append(LevelResult(h, lv, True))
                except Exception as e:  # noqa: BLE001 (reported per host)
                    self.results.append(LevelResult(h, lv, False, _message(e)))
                done += 1
                self.progress(done, total, "")
                if self.pause:
                    self.sleep(self.pause)
        return self.results

    def failures(self):
        return [r for r in self.results if not r.ok]


def _message(e):
    args = getattr(e, "args", None)
    if args and hasattr(args[0], "desc"):
        return args[0].desc.strip()
    return str(e)
