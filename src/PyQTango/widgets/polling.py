# -*- coding: utf-8 -*-
"""
QPollingPanel: Jive's device polling panel (DevicePollingPanel), shared with
Astor's polling manager.

Tabs:

* **Command** - commands without argument: name, Polled, Period (ms)
* **Attribute** - every attribute: name, Polled, Period (ms)
* **Settings** - ``poll_old_factor`` and ``poll_ring_depth`` (database properties)

Editing a period ticks "Polled", as in Jive. Right-click offers Enable
polling, Disable polling and Set period for the selected rows. **Reset**
deletes the stored polling configuration of the device(s); the server applies
it at its next restart.
"""

from ..core import polling
from ..core.proxies import ProxyCache
from .configtables import ConfigColumn, ConfigAction, ConfigTab, QConfigPanel

SETTINGS = (("poll_old_factor", "Poll old factor"), ("poll_ring_depth", "Poll ring depth"))


class QPollingPanel(QConfigPanel):

    base_title = "Device polling"

    def __init__(self, parent=None, proxies=None):
        self.proxies = proxies or ProxyCache(timeout_ms=3000)
        row_actions = [ConfigAction("Enable polling", self._enable),
                       ConfigAction("Disable polling", self._disable),
                       ConfigAction("Set period", self._set_period)]
        columns = [ConfigColumn("polled", "Polled", "bool"), ConfigColumn("period", "Period (ms)")]
        tabs = [ConfigTab("command", "Command", columns, "Command name", row_actions),
                ConfigTab("attribute", "Attribute", columns, "Attribute name", row_actions),
                ConfigTab("settings", "Settings", [ConfigColumn("value", "Value")], "Parameters name")]
        QConfigPanel.__init__(self, tabs, parent)
        for key in ("command", "attribute"):
            self.models[key].edit_hook = self._period_ticks_polled
        self.reset_button = self.add_button("Reset", self.reset_config,
                                            tooltip="Delete the stored polling configuration "
                                                    "(applied at the next server restart)")

    @staticmethod
    def _period_ticks_polled(model, row, key, value):
        if key == "period" and value != model.stored(row, "period"):
            model.set_value(row, "polled", True, hook=False)

    # -- Worker side ------------------------------------------------------------------
    def load(self, dbs, device):
        proxy = self.proxies.get(dbs.fq(device))
        commands, attributes = polling.read_polling(proxy)
        old_factor, ring_depth = polling.read_polling_settings(dbs, device)
        settings = dict(zip([k for k, _ in SETTINGS], (old_factor, ring_depth)))

        def rows(entries):
            return [{"name": e.name, "polled": e.polled, "period": e.period} for e in entries]
        return {"command": rows(commands), "attribute": rows(attributes),
                "settings": [{"name": label, "key": key, "value": settings[key]} for key, label in SETTINGS]}

    def write(self, job, dbs, devices, pending, rows):
        dbs.check_write("polling")
        settings = {name: r["key"] for name, r in rows["settings"].items()}
        steps = [(d, tab, change) for d in devices for tab, changes in pending.items() for change in changes]
        done = set()
        for i, (device, tab, (name, key, value)) in enumerate(steps):
            if job.cancelled:
                break
            job.set_progress(100 * i // max(1, len(steps)), "Updating {0}/{1}".format(device, name))
            try:
                if tab == "settings":
                    polling.write_polling_setting(dbs, device, settings[name], value)
                    continue
                if (device, tab, name) in done:      # polled and period of a row: one call
                    continue
                done.add((device, tab, name))
                row = rows[tab][name]
                proxy = self.proxies.get(dbs.fq(device))
                polling.set_polling(proxy, tab, name, row["polled"], row["period"])
            except Exception as e:  # noqa: BLE001 (collected and shown at the end)
                job.add_error(e, "{0}/{1}".format(device, name))

    # -- GUI side ---------------------------------------------------------------------------
    def validate(self, pending):
        for tab in ("command", "attribute"):
            model = self.models[tab]
            for name in {n for n, _, _ in pending.get(tab, [])}:
                row = model.rows()[model.row_of(name)]
                if row["polled"]:
                    try:
                        polling.parse_period(row["period"])
                    except ValueError:
                        return "Invalid polling period '{0}' for {1} {2}.".format(row["period"], tab, name)
        for name, key, value in pending.get("settings", []):
            if not str(value).strip().isdigit() or int(value) <= 0:
                return "{0} must be a positive integer.".format(name)
        return None

    def _enable(self, tab, names):
        model = self.models[tab]
        for n in names:
            r = model.row_of(n)
            model.set_value(r, "polled", True)
            if not model.value(r, "period"):
                model.set_value(r, "period", str(polling.DEFAULT_PERIOD_MS))

    def _disable(self, tab, names):
        self.set_pending(tab, names, "polled", False)

    def _set_period(self, tab, names):
        period = self.prompt("Set period", "Enter polling period (ms)", str(polling.DEFAULT_PERIOD_MS))
        if period is None:
            return
        try:
            polling.parse_period(period)
        except ValueError:
            self._set_status("Invalid polling period '{0}'.".format(period), error=True)
            return
        self.set_pending(tab, names, "period", period.strip())

    def reset_config(self):
        if self.read_only or not self.devices:
            return None
        if not self.confirm("This will reset the polling configuration of all attributes and commands "
                            "of {0}.\nReset configuration?".format(
                                self.devices[0] if len(self.devices) == 1
                                else "{0} devices".format(len(self.devices)))):
            return None

        def reset(job, dbs, devices):
            for i, d in enumerate(devices):
                job.set_progress(100 * i // len(devices), "Resetting " + d)
                try:
                    polling.reset_polling(dbs, d)
                except Exception as e:  # noqa: BLE001
                    job.add_error(e, d)
        job = self.run_job("Resetting polling configuration", reset, self.dbs, list(self.devices))
        job.finished.connect(lambda: self.inform(
            "The polling configuration has been reset.\n"
            "The server needs to be restarted to take the change into account.")
            if not job.errors and self.show_job_errors else None)
        return job


__all__ = ["QPollingPanel"]
